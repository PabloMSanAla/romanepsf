"""
Roman Extended PSF (ePSF) Single-Detector and Multi-Detector Pipeline.

Architectural module for:
1. Single-detector execution (run_single_detector):
   - Lazy ASDF loading and photometric calibration
   - Fast spatial bounding filtering of master catalog
   - Forward roundtrip astrometric projection (WCS error < 0.5 arcsec)
   - Background-subtracted centroid refinement
   - Analytic Moffat extension isolation clearance filtering
   - 3-tier stellar classification (Bright, Medium, Faint)
   - Postage stamp extraction, subpixel bicubic centering, and spike-protected contaminant masking
   - Memory-efficient array disposal (peak memory < 4 GB)
   - PyTorch-accelerated 2D composite ePSF assembly with multi-tier fallback (handling 0 bright stars)
   - FITS export with standard astropy.io.fits header cards
2. Full multi-detector execution orchestration (run_pipeline).
"""

from __future__ import annotations

import gc
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from astropy.io import fits

from romanepsf.loader import load_l2_image, RomanL2Data
from romanepsf.catalog import (
    sanitize_source_catalog,
    get_detector_sky_bounds,
    query_gaia_for_detector,
    project_catalog_to_pixels,
    refine_stellar_centroids,
    filter_isolated_stars,
    assign_stellar_tiers,
)
from romanepsf.stamps import process_star_stamps, StellarStamp
from romanepsf.assembly import assemble_composite_extended_psf
from romanepsf.config import PipelineConfig, Config, load_config, resolve_device

logger = logging.getLogger("romanepsf.pipeline")

# Alias for specification compatibility
RomanPSFConfig = PipelineConfig


@dataclass
class SingleDetectorResult:
    """Complete results and metadata from single-detector ePSF synthesis."""
    detector_id: str                          # Sensor Chip Assembly identifier (e.g. 'wfi01')
    asdf_path: Path                           # Path to input Level 2 ASDF file
    fits_path: Path                           # Path to exported single-detector ePSF FITS model
    epsf_model: np.ndarray                    # 2D normalized ePSF canvas (float32, sum=1.0)
    canvas_size: int                          # Square canvas dimension (e.g. 1025)
    star_counts: Dict[str, int]               # Star counts per tier: {'bright': int, 'medium': int, 'faint': int, 'total': int}
    scale_factors: Dict[str, Optional[float]] # Overlap flux scale factors: {'k_fm': float, 'k_mb': Optional[float]}
    pixel_scale: float                        # Detector pixel scale in arcsec/pixel (~0.11)
    pa_aperture: float                        # Aperture position angle in degrees
    diagnostics: Dict[str, Any]               # Detailed assembly diagnostics
    stamps_by_tier: Dict[str, List[StellarStamp]] # Extracted stamps grouped by tier
    catalog_df: pd.DataFrame                  # Final verified, tiered star catalog
    execution_time_s: float                   # Processing duration in seconds
    success: bool = True                      # Status indicator

    def to_dict(self) -> Dict[str, Any]:
        """Serialize summary metrics to dictionary."""
        return {
            "detector_id": self.detector_id,
            "asdf_path": str(self.asdf_path),
            "fits_path": str(self.fits_path),
            "canvas_size": self.canvas_size,
            "star_counts": self.star_counts,
            "scale_factors": self.scale_factors,
            "pixel_scale": self.pixel_scale,
            "pa_aperture": self.pa_aperture,
            "execution_time_s": self.execution_time_s,
            "success": self.success,
        }

    def summary(self) -> str:
        """Formatted human-readable summary string."""
        return (
            f"SingleDetectorResult({self.detector_id.upper()}: "
            f"stars={self.star_counts.get('total', 0)} "
            f"[B={self.star_counts.get('bright', 0)}, M={self.star_counts.get('medium', 0)}, F={self.star_counts.get('faint', 0)}], "
            f"k_fm={self.scale_factors.get('k_fm')}, k_mb={self.scale_factors.get('k_mb')}, "
            f"canvas={self.canvas_size}x{self.canvas_size}, time={self.execution_time_s:.2f}s)"
        )


@dataclass
class PipelineOutputs:
    """Output container for end-to-end pipeline execution."""
    composite_epsf: np.ndarray
    fits_path: Path
    diagnostics: Dict[str, Any]
    detector_results: Dict[str, SingleDetectorResult] = field(default_factory=dict)


def export_single_detector_fits(
    epsf_model: np.ndarray,
    fits_path: Union[str, Path],
    detector_id: str,
    filter_name: str = "F146",
    pixel_scale: float = 0.11,
    pixel_area: float = 2.800978e-13,
    zp_ab: float = 26.836,
    pa_aperture: float = 0.0,
    star_counts: Optional[Dict[str, int]] = None,
    scale_factors: Optional[Dict[str, Optional[float]]] = None,
    overwrite: bool = True,
) -> Path:
    """
    Export single-detector synthesized ePSF canvas to FITS format with standard headers.

    Parameters
    ----------
    epsf_model : np.ndarray
        2D unit-normalized extended PSF canvas.
    fits_path : str or Path
        Target destination FITS filepath.
    detector_id : str
        Detector SCA string (e.g. 'wfi01').
    filter_name : str, default 'F146'
        Filter bandpass name.
    pixel_scale : float, default 0.11
        Plate scale in arcsec/pixel.
    pixel_area : float, default 2.800978e-13
        Pixel solid angle in steradians.
    zp_ab : float, default 26.836
        AB magnitude photometric zero-point.
    pa_aperture : float, default 0.0
        Aperture position angle in degrees.
    star_counts : dict, optional
        Counts of stars used per tier.
    scale_factors : dict, optional
        Cross-tier flux scaling factors k_fm and k_mb.
    overwrite : bool, default True
        Whether to overwrite existing destination file.

    Returns
    -------
    Path
        Absolute path to written FITS file.
    """
    out_path = Path(fits_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    counts = star_counts or {}
    scales = scale_factors or {}

    canvas_size = int(epsf_model.shape[0])
    center_pix = (canvas_size + 1.0) / 2.0

    hdu = fits.PrimaryHDU(epsf_model.astype(np.float32))
    h = hdu.header

    h["EXTNAME"] = ("EPSF", "Extended PSF model")
    h["TELESCOP"] = ("ROMAN", "Telescope name")
    h["INSTRUME"] = ("WFI", "Instrument name")
    h["DETECTOR"] = (detector_id.upper(), "Sensor Chip Assembly identifier")
    h["FILTER"] = (str(filter_name), "Optical filter element")
    h["PIXSCALE"] = (float(pixel_scale), "[arcsec/pixel] Plate scale")
    h["PIXAREA"] = (float(pixel_area), "[sr] Pixel solid angle")
    h["ZP_AB"] = (float(zp_ab), "[mag] AB photometric zero-point")
    h["PA_APER"] = (float(pa_aperture), "[deg] Aperture position angle")
    h["CANVAS_S"] = (canvas_size, "Canvas dimension in pixels")
    h["CRPIX1"] = (center_pix, "Reference pixel axis 1")
    h["CRPIX2"] = (center_pix, "Reference pixel axis 2")
    h["CRVAL1"] = (0.0, "Reference world coordinate axis 1")
    h["CRVAL2"] = (0.0, "Reference world coordinate axis 2")
    h["CDELT1"] = (float(pixel_scale) / 3600.0, "[deg/pix] Axis 1 coordinate increment")
    h["CDELT2"] = (float(pixel_scale) / 3600.0, "[deg/pix] Axis 2 coordinate increment")
    h["CUNIT1"] = ("deg", "Units of CRVAL1, CDELT1")
    h["CUNIT2"] = ("deg", "Units of CRVAL2, CDELT2")
    h["NORM"] = ("UNIT_FLUX", "Canvas flux normalization mode")
    h["SUM_FLUX"] = (float(np.sum(epsf_model)), "Integrated canvas flux")
    h["PEAKFLUX"] = (float(np.max(epsf_model)), "Peak pixel flux in normalized canvas")
    h["N_BRIGHT"] = (int(counts.get("bright", 0)), "Count of bright stars used")
    h["N_MEDIUM"] = (int(counts.get("medium", 0)), "Count of medium stars used")
    h["N_FAINT"] = (int(counts.get("faint", 0)), "Count of faint stars used")
    h["N_TOTAL"] = (int(counts.get("total", 0)), "Total count of stars used")
    h["K_FM"] = (
        float(scales["k_fm"]) if scales.get("k_fm") is not None else -1.0,
        "Faint-to-medium flux scale factor (-1 if unused)",
    )
    h["K_MB"] = (
        float(scales["k_mb"]) if scales.get("k_mb") is not None else -1.0,
        "Medium-to-bright flux scale factor (-1 if unused)",
    )
    h["DATE"] = (datetime.now(timezone.utc).isoformat(), "FITS file creation UTC timestamp")
    h["ORIGIN"] = ("Roman Extended PSF Pipeline", "Authoring package")

    hdu.writeto(out_path, overwrite=overwrite)
    return out_path


def run_single_detector(
    detector_id_or_config: Union[str, Path, Config, None] = None,
    asdf_path: Optional[Union[str, Path]] = None,
    catalog_path: Optional[Union[str, Path]] = None,
    config: Optional[Union[Config, str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    canvas_size: Optional[int] = None,
    detector: Optional[str] = None,
    **kwargs,
) -> SingleDetectorResult:
    """
    Execute full single-detector ePSF synthesis pipeline on a designated WFI SCA.

    Supports polymorphic caller signatures:
    - Standard: run_single_detector("wfi01", asdf_path, catalog_path, config, output_dir)
    - Keyword-only: run_single_detector(detector_id="wfi01", asdf_path=..., config=...)
    - Config-first (CLI): run_single_detector(cfg, detector="wfi01")

    Parameters
    ----------
    detector_id_or_config : str, Path, Config, or None
        Either detector identifier string (e.g. 'wfi01') or PipelineConfig instance.
    asdf_path : str or Path, optional
        Explicit path to Level 2 ASDF image file. If omitted, resolved from config.
    catalog_path : str or Path, optional
        Explicit path to source catalog CSV. If omitted, resolved from config.
    config : Config, str, or Path, optional
        Configuration object or path to YAML config file.
    output_dir : str or Path, optional
        Destination directory for output models and diagnostics.
    canvas_size : int, optional
        Square canvas dimension (e.g. 1025). Overrides config.assembly.canvas_size.
    detector : str, optional
        Detector identifier string (alias for detector_id).

    Returns
    -------
    SingleDetectorResult
        Dataclass containing synthesized model, star counts, scale factors, and paths.
    """
    t0 = time.time()

    # 1. Resolve Config and Detector ID across polymorphic argument signatures
    if isinstance(detector_id_or_config, PipelineConfig):
        cfg = detector_id_or_config
        det = detector or kwargs.get("detector_id")
        if det is None and cfg.data.detectors:
            det = cfg.data.detectors[0]
        resolved_detector = (det or "wfi01").lower()
    else:
        det = detector_id_or_config or detector or kwargs.get("detector_id") or "wfi01"
        resolved_detector = str(det).lower()
        if config is None:
            cfg = load_config()
        elif isinstance(config, (str, Path)):
            cfg = load_config(config)
        else:
            cfg = config

    logger.info(f"Initializing single-detector ePSF pipeline for SCA: {resolved_detector.upper()}")

    # 2. Resolve Output Directory
    resolved_output_dir = Path(output_dir) if output_dir is not None else Path(cfg.data.output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    # 3. Resolve Canvas Dimension
    resolved_canvas_size = int(canvas_size) if canvas_size is not None else int(cfg.assembly.canvas_size)
    if resolved_canvas_size % 2 == 0:
        logger.warning(
            f"Even canvas size {resolved_canvas_size} provided; converting to odd {resolved_canvas_size + 1}"
        )
        resolved_canvas_size += 1

    # 4. Resolve ASDF Image Path
    if asdf_path is not None:
        resolved_asdf_path = Path(asdf_path)
    else:
        det_dir = Path(cfg.data.detectors_dir)
        pattern = f"*{resolved_detector}*.asdf"
        matches = list(det_dir.glob(pattern))
        if matches:
            resolved_asdf_path = matches[0]
        else:
            resolved_asdf_path = det_dir / f"r0108301001001001001_0001_{resolved_detector}_f146_cal.asdf"

    if not resolved_asdf_path.is_file():
        raise FileNotFoundError(f"Detector ASDF file not found: {resolved_asdf_path}")

    # 5. Resolve Source Catalog Path
    if catalog_path is not None:
        resolved_catalog_path = Path(catalog_path)
    else:
        resolved_catalog_path = Path(cfg.data.catalog_path)

    # 6. Lazy Load and Calibrate L2 ASDF Image
    logger.info(f"Loading Level 2 ASDF image: {resolved_asdf_path}")
    l2_data: RomanL2Data = load_l2_image(resolved_asdf_path, calibrate=True)

    # Extract required calibration parameters before potential cleanup
    pa_aperture = float(l2_data.pa_aperture)
    pixel_scale = float(l2_data.pixel_scale)
    pixel_area = float(l2_data.pixel_area)
    zp_ab = float(l2_data.zp_ab)
    filter_name = str(l2_data.filter_name)

    # 7. Spatial Catalog Pre-Filtering using Detector Sky Bounds
    if resolved_catalog_path.is_file():
        logger.info(f"Ingesting precomputed master catalog from: {resolved_catalog_path}")
        raw_df = pd.read_csv(resolved_catalog_path, low_memory=False)
        clean_df = sanitize_source_catalog(raw_df, mag_col=cfg.catalog.mag_col)

        ra_cen, dec_cen, radius_deg, ra_min, ra_max, dec_min, dec_max = get_detector_sky_bounds(
            l2_data, margin_deg=0.02
        )
        sub_df = clean_df[
            (clean_df["ra"] >= ra_min)
            & (clean_df["ra"] <= ra_max)
            & (clean_df["dec"] >= dec_min)
            & (clean_df["dec"] <= dec_max)
        ].copy()
    else:
        logger.info(
            f"Precomputed catalog not found at {resolved_catalog_path}. "
            f"Querying Gaia DR3 for {resolved_detector.upper()}..."
        )
        sub_df = query_gaia_for_detector(
            l2_data,
            mag_limit=20.0,
            cache_dir=cfg.data.cache_dir,
            precomputed_catalog=None,
            mag_col=cfg.catalog.mag_col,
        )

    if sub_df.empty:
        raise RuntimeError(
            f"No catalog stars found within celestial footprint of detector {resolved_detector.upper()}."
        )

    # 8. Astrometric Projection with Forward Roundtrip WCS Verification (error < 0.5 arcsec)
    projected_df = project_catalog_to_pixels(
        l2_data=l2_data,
        catalog_df=sub_df,
        margin_px=cfg.catalog.edge_margin_px,
        tolerance_arcsec=cfg.catalog.roundtrip_tolerance_arcsec,
    )
    if projected_df.empty:
        raise RuntimeError(
            f"No catalog stars survived WCS roundtrip projection for detector {resolved_detector.upper()}."
        )

    # 9. Background-Subtracted Centroid Refinement
    refined_df = refine_stellar_centroids(
        l2_data=l2_data,
        df=projected_df,
        box_radius=cfg.catalog.centroid_refine_box_px,
    )

    # 10. Pairwise Moffat Isolation Clearance Filtering
    isolated_df = filter_isolated_stars(
        df=refined_df,
        pixel_scale=pixel_scale,
        isolation_safety_factor=cfg.catalog.isolation_safety_factor,
        min_dist_arcsec=cfg.catalog.min_dist_arcsec,
        mag_col=cfg.catalog.mag_col,
    )
    if isolated_df.empty:
        raise RuntimeError(
            f"No isolated stars remained after neighbor clearance for detector {resolved_detector.upper()}."
        )

    # 11. 3-Tier Stellar Assignment (Bright < 11.0, Medium 11.0-13.0, Faint >= 13.0)
    tiered_df = assign_stellar_tiers(
        df=isolated_df,
        bright_limit=cfg.tiers.bright_limit,
        faint_limit=cfg.tiers.faint_limit,
        mag_col=cfg.catalog.mag_col,
    )

    # 12. Extract Stamps, Bicubic Subpixel Align, and Mask Contaminants (with Spike Protection)
    logger.info(f"Extracting postage stamps for detector {resolved_detector.upper()}...")
    stamps_by_tier = process_star_stamps(
        l2_data=l2_data,
        catalog_df=tiered_df,
        spikes_cfg=cfg.spikes,
        stamps_cfg=cfg.stamps,
    )

    # 13. Memory Management: Free heavy 4088x4088 detector arrays immediately
    del l2_data
    gc.collect()

    # 14. 2D Composite ePSF Assembly with Multi-Tier Fallback
    logger.info(
        f"Synthesizing 2D composite ePSF canvas ({resolved_canvas_size}x{resolved_canvas_size}) with multi-tier fallback..."
    )
    epsf_model, diagnostics = assemble_composite_extended_psf(
        tier_stamps=stamps_by_tier,
        output_size=resolved_canvas_size,
        cfg=cfg.assembly,
        device=cfg.get_torch_device(),
    )

    # Compile Star Counts and Overlap Scale Factors
    star_counts = {
        "bright": len(stamps_by_tier.get("bright", [])),
        "medium": len(stamps_by_tier.get("medium", [])),
        "faint": len(stamps_by_tier.get("faint", [])),
    }
    star_counts["total"] = sum(star_counts.values())

    scale_factors = {
        "k_fm": diagnostics.get("k_fm"),
        "k_mb": diagnostics.get("k_mb"),
    }

    # 15. Export Intermediate ePSF Model to FITS
    fits_path = resolved_output_dir / f"roman_epsf_{resolved_detector.lower()}.fits"
    export_single_detector_fits(
        epsf_model=epsf_model,
        fits_path=fits_path,
        detector_id=resolved_detector,
        filter_name=filter_name,
        pixel_scale=pixel_scale,
        pixel_area=pixel_area,
        zp_ab=zp_ab,
        pa_aperture=pa_aperture,
        star_counts=star_counts,
        scale_factors=scale_factors,
    )

    # 16. Save Processed Tiered Catalog CSV
    csv_path = resolved_output_dir / f"{resolved_detector.lower()}_stars_tiered.csv"
    tiered_df.to_csv(csv_path, index=False)

    execution_time = time.time() - t0
    logger.info(
        f"Single-detector {resolved_detector.upper()} succeeded in {execution_time:.2f}s. "
        f"Model saved: {fits_path}"
    )

    return SingleDetectorResult(
        detector_id=resolved_detector,
        asdf_path=resolved_asdf_path,
        fits_path=fits_path,
        epsf_model=epsf_model,
        canvas_size=resolved_canvas_size,
        star_counts=star_counts,
        scale_factors=scale_factors,
        pixel_scale=pixel_scale,
        pa_aperture=pa_aperture,
        diagnostics=diagnostics,
        stamps_by_tier=stamps_by_tier,
        catalog_df=tiered_df,
        execution_time_s=execution_time,
        success=True,
    )


def run_pipeline(
    config_or_path: Union[PipelineConfig, str, Path, None] = None,
    detectors: Optional[List[str]] = None,
    canvas_size: Optional[int] = None,
    output_dir: Optional[Union[str, Path]] = None,
    **kwargs,
) -> PipelineOutputs:
    """
    Execute full ePSF pipeline orchestration across all designated detectors.

    Parameters
    ----------
    config_or_path : PipelineConfig, str, Path, or None
        Configuration object or YAML path.
    detectors : list of str, optional
        List of detector IDs to process (e.g. ['wfi01', ..., 'wfi18'] or ['wfi01']).
    canvas_size : int, optional
        Canvas dimension.
    output_dir : str or Path, optional
        Output directory.

    Returns
    -------
    PipelineOutputs
        Container with composite ePSF model, fits path, diagnostics, and per-detector results.
    """
    if isinstance(config_or_path, PipelineConfig):
        cfg = config_or_path
    elif isinstance(config_or_path, (str, Path)):
        cfg = load_config(config_or_path)
    else:
        cfg = load_config()

    if detectors is not None:
        cfg.data.detectors = [d.lower() for d in detectors]
    if canvas_size is not None:
        cfg.assembly.canvas_size = canvas_size
    if output_dir is not None:
        cfg.data.output_dir = Path(output_dir)

    out_dir = Path(cfg.data.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    target_detectors = cfg.data.detectors
    if target_detectors == ["all"]:
        target_detectors = [f"wfi{i:02d}" for i in range(1, 19)]

    logger.info(f"Running ePSF pipeline across {len(target_detectors)} detectors: {target_detectors}")

    detector_results: Dict[str, SingleDetectorResult] = {}
    for det in target_detectors:
        try:
            res = run_single_detector(cfg, detector=det, output_dir=out_dir)
            detector_results[det] = res
        except Exception as e:
            logger.error(f"Detector {det} processing failed: {e}")
            if len(target_detectors) == 1:
                raise

    if not detector_results:
        raise RuntimeError("No detectors were successfully processed.")

    # Combine into composite canvas
    if len(detector_results) == 1:
        single_res = list(detector_results.values())[0]
        composite_epsf = single_res.epsf_model
        composite_fits = single_res.fits_path
        diagnostics = single_res.diagnostics
    else:
        # Multi-detector averaging / mosaic across detectors
        models = [res.epsf_model for res in detector_results.values() if res.success]
        composite_epsf = np.mean(models, axis=0)
        norm = np.sum(composite_epsf)
        if norm > 0:
            composite_epsf /= norm

        composite_fits = out_dir / "roman_epsf_composite.fits"
        export_single_detector_fits(
            epsf_model=composite_epsf,
            fits_path=composite_fits,
            detector_id="ALL18",
            filter_name=cfg.data.filter_name,
            pixel_scale=0.11,
            overwrite=True,
        )
        diagnostics = {"detectors_processed": list(detector_results.keys())}

    return PipelineOutputs(
        composite_epsf=composite_epsf,
        fits_path=composite_fits,
        diagnostics=diagnostics,
        detector_results=detector_results,
    )


__all__ = [
    "SingleDetectorResult",
    "PipelineOutputs",
    "RomanPSFConfig",
    "export_single_detector_fits",
    "run_single_detector",
    "run_pipeline",
]
