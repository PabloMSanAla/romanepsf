"""
Roman Extended PSF (ePSF) Pipeline Architecture & Execution Runner.

Provides orchestration for:
1. Single-detector execution (run_single_detector):
   - Fast spatial bounding filtering of master catalog
   - Forward roundtrip astrometric projection (WCS error < 0.5 arcsec)
   - Background-subtracted centroid refinement
   - Moffat isolation clearance filtering
   - 3-tier stellar classification (Bright, Medium, Faint)
   - Postage stamp extraction, subpixel bicubic centering, and spike-protected contaminant masking
   - Explicit memory disposal in finally block (peak RSS << 4 GB)
   - PyTorch-accelerated 2D composite ePSF assembly with multi-tier fallback (handling 0 bright stars)
   - FITS export with standard <= 8 char astropy.io.fits header cards
2. End-to-end multi-detector execution across all 18 WFI SCAs (run_pipeline):
   - Detector discovery via pattern matching
   - Sequential processing of each SCA with immediate memory deallocation
   - Cross-SCA stamp pooling into global Bright, Medium, and Faint collections
   - Composite canvas assembly with cross-tier scaling and annular blending
   - 4-HDU multi-extension FITS serialization (PRIMARY, COVERAGE, RADIAL_PROFILES, DETECTOR_SUMMARY)
"""

from __future__ import annotations

import gc
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from astropy.io import fits

from romanepsf import __version__
from romanepsf.config import PipelineConfig, Config, load_config, resolve_device
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
from romanepsf.assembly import (
    assemble_composite_extended_psf,
    serialize_composite_epsf_fits,
)

logger = logging.getLogger("romanepsf.pipeline")

# Alias for specification compatibility
RomanPSFConfig = PipelineConfig


@dataclass
class SingleDetectorResult:
    """Complete results and metadata from single-detector ePSF synthesis."""
    detector_id: str                              # Sensor Chip Assembly identifier (e.g. 'wfi01')
    asdf_path: Path                               # Path to input Level 2 ASDF file
    fits_path: Path                               # Path to exported single-detector ePSF FITS model
    epsf_model: np.ndarray                        # 2D normalized ePSF canvas (float32, sum=1.0)
    canvas_size: int                              # Square canvas dimension (e.g. 1025)
    star_counts: Dict[str, int]                   # Star counts per tier: {'bright': int, 'medium': int, 'faint': int, 'total': int}
    scale_factors: Dict[str, Optional[float]]     # Overlap flux scale factors: {'k_fm': float, 'k_mb': Optional[float]}
    pixel_scale: float                            # Detector pixel scale in arcsec/pixel (~0.11)
    pa_aperture: float                            # Aperture position angle in degrees
    diagnostics: Dict[str, Any]                   # Detailed assembly diagnostics
    stamps_by_tier: Dict[str, List[StellarStamp]] # Extracted stamps grouped by tier
    catalog_df: pd.DataFrame                      # Final verified, tiered star catalog
    execution_time_s: float                       # Processing duration in seconds
    success: bool = True                          # Status indicator

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
    """Output container for end-to-end multi-detector pipeline execution."""
    composite_epsf: np.ndarray
    fits_path: Path
    diagnostics: Dict[str, Any]
    detector_results: Dict[str, SingleDetectorResult] = field(default_factory=dict)
    detector_summaries: List[Dict[str, Any]] = field(default_factory=list)
    pooled_stamps: Optional[Dict[str, List[StellarStamp]]] = None
    stamps_by_tier: Optional[Dict[str, List[StellarStamp]]] = None

    def __post_init__(self):
        if self.stamps_by_tier is None and self.pooled_stamps is not None:
            self.stamps_by_tier = self.pooled_stamps
        elif self.pooled_stamps is None and self.stamps_by_tier is not None:
            self.pooled_stamps = self.stamps_by_tier


def discover_detectors(
    detectors_dir: Union[str, Path],
    requested: Optional[Sequence[str]] = None,
) -> Dict[str, Path]:
    """
    Discover all calibrated ASDF detector files in the input directory.

    Matches patterns like 'r0108301001001001001_0001_wfi01_f146_cal.asdf'.
    Returns a sorted dictionary mapping detector name ('wfi01'..'wfi18') to file Path.
    """
    p_dir = Path(detectors_dir)
    pattern = re.compile(r"_wfi(\d{2})_", re.IGNORECASE)
    det_map: Dict[str, Path] = {}

    if p_dir.is_dir():
        for f in p_dir.glob("*_cal.asdf"):
            m = pattern.search(f.name)
            if m:
                det_id = f"wfi{m.group(1).lower()}"
                det_map[det_id] = f

    sorted_keys = sorted(det_map.keys())
    if requested is None:
        return {d: det_map[d] for d in sorted_keys}

    req_lower = [str(r).lower().strip() for r in requested]
    if "all" in req_lower:
        return {d: det_map[d] for d in sorted_keys}

    req_set = set(req_lower)
    return {d: det_map[d] for d in sorted_keys if d in req_set}


def process_single_detector_stamps(
    asdf_path: Path,
    catalog_df: pd.DataFrame,
    cfg: Config,
) -> Tuple[str, Dict[str, List[StellarStamp]], Dict[str, Any]]:
    """
    Load an ASDF image, extract verified stamps, and immediately free memory.

    Encapsulated inside a single stack frame with prompt 'del' and 'gc.collect()'
    in a finally block to guarantee peak RSS stays strictly below 4 GB (Requirement R3).

    Returns
    -------
    (detector_name, stamps_dict, stats) : Tuple[str, Dict[str, List[StellarStamp]], Dict[str, Any]]
    """
    t0 = time.perf_counter()
    l2_data: Optional[RomanL2Data] = None

    try:
        l2_data = load_l2_image(asdf_path, calibrate=True)
        det_name = l2_data.detector.lower()
        t_load = time.perf_counter() - t0

        t_proj_start = time.perf_counter()
        ra_c, dec_c, rad, ra_min, ra_max, dec_min, dec_max = get_detector_sky_bounds(l2_data, margin_deg=0.02)
        cand = catalog_df[
            (catalog_df["ra"] >= ra_min)
            & (catalog_df["ra"] <= ra_max)
            & (catalog_df["dec"] >= dec_min)
            & (catalog_df["dec"] <= dec_max)
        ].copy()

        empty_stamps: Dict[str, List[StellarStamp]] = {"bright": [], "medium": [], "faint": []}

        if cand.empty:
            return det_name, empty_stamps, {
                "detector": det_name.upper(),
                "faint": 0, "medium": 0, "bright": 0, "total": 0,
                "status": "NO_STARS",
                "pa_aperture": float(l2_data.pa_aperture),
                "pixel_scale": float(l2_data.pixel_scale),
                "time_s": time.perf_counter() - t0,
            }

        proj = project_catalog_to_pixels(
            l2_data=l2_data,
            catalog_df=cand,
            margin_px=cfg.catalog.edge_margin_px,
            tolerance_arcsec=cfg.catalog.roundtrip_tolerance_arcsec,
        )
        if proj.empty:
            return det_name, empty_stamps, {
                "detector": det_name.upper(),
                "faint": 0, "medium": 0, "bright": 0, "total": 0,
                "status": "NO_PROJECTED_STARS",
                "pa_aperture": float(l2_data.pa_aperture),
                "pixel_scale": float(l2_data.pixel_scale),
                "time_s": time.perf_counter() - t0,
            }

        refined = refine_stellar_centroids(
            l2_data=l2_data,
            df=proj,
            box_radius=cfg.catalog.centroid_refine_box_px,
        )
        isolated = filter_isolated_stars(
            df=refined,
            pixel_scale=float(l2_data.pixel_scale),
            isolation_safety_factor=cfg.catalog.isolation_safety_factor,
            min_dist_arcsec=cfg.catalog.min_dist_arcsec,
            mag_col=cfg.catalog.mag_col,
        )
        if isolated.empty:
            return det_name, empty_stamps, {
                "detector": det_name.upper(),
                "faint": 0, "medium": 0, "bright": 0, "total": 0,
                "status": "NO_ISOLATED_STARS",
                "pa_aperture": float(l2_data.pa_aperture),
                "pixel_scale": float(l2_data.pixel_scale),
                "time_s": time.perf_counter() - t0,
            }

        tiered = assign_stellar_tiers(
            df=isolated,
            bright_limit=cfg.tiers.bright_limit,
            faint_limit=cfg.tiers.faint_limit,
            mag_col=cfg.catalog.mag_col,
        )
        t_proj = time.perf_counter() - t_proj_start

        t_stamps_start = time.perf_counter()
        stamps_dict = process_star_stamps(
            l2_data=l2_data,
            catalog_df=tiered,
            spikes_cfg=cfg.spikes,
            stamps_cfg=cfg.stamps,
        )
        t_stamps = time.perf_counter() - t_stamps_start

        n_b = len(stamps_dict.get("bright", []))
        n_m = len(stamps_dict.get("medium", []))
        n_f = len(stamps_dict.get("faint", []))
        n_tot = n_b + n_m + n_f

        stats = {
            "detector": det_name.upper(),
            "faint": n_f,
            "medium": n_m,
            "bright": n_b,
            "total": n_tot,
            "status": "SUCCESS" if n_tot > 0 else "NO_VALID_STAMPS",
            "pa_aperture": float(l2_data.pa_aperture),
            "pixel_scale": float(l2_data.pixel_scale),
            "load_time_s": t_load,
            "projection_time_s": t_proj,
            "stamps_time_s": t_stamps,
            "time_s": time.perf_counter() - t0,
            "star_counts": {"bright": n_b, "medium": n_m, "faint": n_f, "total": n_tot},
        }
        return det_name, stamps_dict, stats

    finally:
        # Strict explicit resource lifecycle cleanup to keep RSS << 4 GB
        if l2_data is not None:
            del l2_data
        gc.collect()


def export_single_detector_fits(
    result_or_model: Union[SingleDetectorResult, np.ndarray, None] = None,
    output_path_or_fits: Optional[Union[str, Path]] = None,
    filter_name: str = "F146",
    pixel_scale: float = 0.11,
    *,
    result: Optional[SingleDetectorResult] = None,
    epsf_model: Optional[np.ndarray] = None,
    output_path: Optional[Union[str, Path]] = None,
    fits_path: Optional[Union[str, Path]] = None,
    detector_id: Optional[str] = None,
    pixel_area: float = 2.800978e-13,
    zp_ab: float = 26.836,
    pa_aperture: float = 0.0,
    star_counts: Optional[Dict[str, int]] = None,
    scale_factors: Optional[Dict[str, Optional[float]]] = None,
    overwrite: bool = True,
    **kwargs,
) -> Path:
    """
    Export single-detector synthesized ePSF canvas to FITS format with standard header cards.

    Supports:
    - export_single_detector_fits(result, output_path, ...)
    - export_single_detector_fits(result=res, output_path=...)
    - export_single_detector_fits(epsf_model=canvas, fits_path=..., detector_id=..., ...)
    - export_single_detector_fits(canvas, fits_path, detector_id=..., ...)
    """
    res_or_m = result if result is not None else result_or_model
    if res_or_m is None and epsf_model is not None:
        res_or_m = epsf_model

    if isinstance(res_or_m, SingleDetectorResult):
        res = res_or_m
        model = res.epsf_model
        resolved_path = output_path or output_path_or_fits or fits_path or res.fits_path
        target_path = Path(resolved_path)
        det_id = detector_id or res.detector_id
        pixel_scale = pixel_scale if pixel_scale != 0.11 else res.pixel_scale
        pa_aperture = pa_aperture if pa_aperture != 0.0 else res.pa_aperture
        counts = star_counts or res.star_counts
        scales = scale_factors or res.scale_factors
        total_flux_val = kwargs.get("total_flux_raw", float(np.sum(model)))
    elif isinstance(res_or_m, np.ndarray):
        model = res_or_m
        resolved_path = output_path or output_path_or_fits or fits_path
        if resolved_path is None:
            raise ValueError("Must specify output path or fits_path.")
        target_path = Path(resolved_path)
        det_id = detector_id or "wfi01"
        counts = star_counts or {}
        scales = scale_factors or {}
        total_flux_val = kwargs.get("total_flux_raw", float(np.sum(model)))
    else:
        raise ValueError(
            "Must provide either SingleDetectorResult or 2D numpy array to export_single_detector_fits."
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    canvas_size = int(model.shape[0])
    center_pix = (canvas_size + 1.0) / 2.0

    hdu = fits.PrimaryHDU(model.astype(np.float32))
    h = hdu.header

    h["EXTNAME"] = ("EPSF", "Extended PSF model")
    h["TELESCOP"] = ("ROMAN", "Telescope name")
    h["INSTRUME"] = ("WFI", "Instrument name")
    h["DETECTOR"] = (det_id.upper(), "Sensor Chip Assembly identifier")
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
    h["CTYPE1"] = ("LINEAR", "Linear coordinate system")
    h["CTYPE2"] = ("LINEAR", "Linear coordinate system")
    h["CUNIT1"] = ("deg", "Units of CRVAL1, CDELT1")
    h["CUNIT2"] = ("deg", "Units of CRVAL2, CDELT2")
    h["NORM"] = ("UNIT_FLUX", "Canvas flux normalization mode")
    h["SUM_FLUX"] = (float(np.sum(model)), "Integrated canvas flux")
    h["PEAKFLUX"] = (float(np.max(model)), "Peak pixel flux in normalized canvas")
    h["TOTALFLX"] = (float(total_flux_val), "Pre-normalization integrated flux")
    h["N_BRIGHT"] = (int(counts.get("bright", 0)), "Count of bright stars used")
    h["N_MEDIUM"] = (int(counts.get("medium", 0)), "Count of medium stars used")
    h["N_FAINT"] = (int(counts.get("faint", 0)), "Count of faint stars used")
    h["N_TOTAL"] = (int(counts.get("total", 0)), "Total count of stars used")
    h["K_FM"] = (
        float(scales["k_fm"]) if scales.get("k_fm") is not None else -1.0,
        "Faint-to-medium scale factor",
    )
    h["K_MB"] = (
        float(scales["k_mb"]) if scales.get("k_mb") is not None else -1.0,
        "Medium-to-bright scale factor",
    )
    iso_date = datetime.now(timezone.utc).isoformat()
    h["DATE_UTC"] = (iso_date, "FITS file creation UTC timestamp")
    h["DATE"] = (iso_date, "FITS file creation UTC timestamp")
    h["PROV_VER"] = (str(__version__), "Roman ePSF pipeline version")
    h["ORIGIN"] = ("Roman Extended PSF Pipeline", "Authoring package")

    hdu.writeto(target_path, overwrite=overwrite)
    return target_path


def run_single_detector(
    detector_id_or_config: Union[str, Path, Config, None] = None,
    asdf_path: Optional[Union[str, Path]] = None,
    catalog_path: Optional[Union[str, Path]] = None,
    config: Optional[Union[Config, str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    canvas_size: Optional[int] = None,
    detector: Optional[str] = None,
    device: Optional[str] = None,
    **kwargs,
) -> SingleDetectorResult:
    """
    Execute full single-detector ePSF synthesis pipeline on a designated WFI SCA.

    Supports polymorphic caller signatures:
    - Standard: run_single_detector("wfi01", asdf_path, catalog_path, config, output_dir)
    - Keyword-only: run_single_detector(detector_id="wfi01", asdf_path=..., config=...)
    - Config-first (CLI): run_single_detector(cfg, detector="wfi01")
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

    if device is not None:
        cfg.environment.device = device.lower()

    logger.info(f"Initializing single-detector ePSF pipeline for SCA: {resolved_detector.upper()}")

    # 2. Resolve Output Directory
    resolved_output_dir = Path(output_dir) if output_dir is not None else Path(cfg.data.output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    # 3. Resolve Canvas Dimension (promote even to odd integer)
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
        matches = list(det_dir.glob(pattern)) if det_dir.is_dir() else []
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

    try:
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

    finally:
        # Strict explicit resource lifecycle cleanup
        del l2_data
        gc.collect()

    # 13. 2D Composite ePSF Assembly with Multi-Tier Fallback
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

    # 14. Export Intermediate ePSF Model to FITS
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

    # 15. Save Processed Tiered Catalog CSV
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
    cfg: Union[Config, Path, str, None] = None,
    detectors_dir: Optional[Union[str, Path]] = None,
    catalog_path: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    canvas_size: Optional[int] = None,
    device: Optional[str] = None,
    detectors: Optional[Union[Sequence[str], str]] = None,
    num_workers: Optional[int] = None,
    **kwargs,
) -> PipelineOutputs:
    """
    Execute full multi-detector pipeline across all designated WFI SCAs:
    1. Ingest and sanitize catalog once.
    2. Sequentially process designated SCAs, isolating stars and extracting stamps.
    3. Explicitly free memory after each detector (peak RSS << 4 GB).
    4. Pool stamps across all SCAs into global collections.
    5. Assemble 2D composite extended PSF with cross-tier scaling and annular blending.
    6. Serialize 4-HDU FITS output (PRIMARY, COVERAGE, RADIAL_PROFILES, DETECTOR_SUMMARY).
    """
    if cfg is None or isinstance(cfg, (str, Path)):
        cfg = load_config(cfg) if cfg is not None else load_config()

    # Apply runtime parameter overrides
    if detectors_dir is not None:
        cfg.data.detectors_dir = Path(detectors_dir)
    if catalog_path is not None:
        cfg.data.catalog_path = Path(catalog_path)
    if output_dir is not None:
        cfg.data.output_dir = Path(output_dir)
    if canvas_size is not None:
        cfg.assembly.canvas_size = int(canvas_size)
    if device is not None:
        cfg.environment.device = str(device).lower()
    if num_workers is not None:
        cfg.environment.num_workers = int(num_workers)

    if detectors is not None:
        if isinstance(detectors, str):
            if detectors.strip().lower() == "all":
                cfg.data.detectors = [f"wfi{i:02d}" for i in range(1, 19)]
            else:
                cfg.data.detectors = [d.strip().lower() for d in detectors.split(",") if d.strip()]
        else:
            det_l = [str(d).strip().lower() for d in detectors]
            if "all" in det_l:
                cfg.data.detectors = [f"wfi{i:02d}" for i in range(1, 19)]
            else:
                cfg.data.detectors = det_l
    elif "all" in [str(d).lower() for d in cfg.data.detectors]:
        cfg.data.detectors = [f"wfi{i:02d}" for i in range(1, 19)]

    # Canvas dimension oddness check
    if cfg.assembly.canvas_size % 2 == 0:
        logger.warning(
            f"Even canvas size {cfg.assembly.canvas_size} provided; promoting to odd {cfg.assembly.canvas_size + 1}"
        )
        cfg.assembly.canvas_size += 1

    cfg.validate()
    cfg.data.output_dir.mkdir(parents=True, exist_ok=True)
    torch_dev = cfg.get_torch_device()

    t_start = time.perf_counter()

    # 1. Discover target detectors
    det_map = discover_detectors(cfg.data.detectors_dir, requested=cfg.data.detectors)
    if not det_map:
        raise FileNotFoundError(
            f"No valid detectors found in {cfg.data.detectors_dir} for requested {cfg.data.detectors}"
        )

    logger.info(
        f"Starting pipeline execution across {len(det_map)} detector(s): {list(det_map.keys())}"
    )

    # 2. Ingest Master Catalog once
    logger.info(f"Loading master source catalog from: {cfg.data.catalog_path}")
    raw_df = pd.read_csv(cfg.data.catalog_path, low_memory=False)
    cat_df = sanitize_source_catalog(raw_df, mag_col=cfg.catalog.mag_col)
    del raw_df
    gc.collect()

    # 3. Sequential Extraction Loop with Strict Per-Detector Garbage Collection
    pooled_stamps: Dict[str, List[StellarStamp]] = {"bright": [], "medium": [], "faint": []}
    detector_summaries: List[Dict[str, Any]] = []
    detector_results: Dict[str, SingleDetectorResult] = {}
    failed_detectors: Dict[str, str] = {}

    for det_id, asdf_file in det_map.items():
        try:
            det_name, stamps_dict, stats = process_single_detector_stamps(asdf_file, cat_df, cfg)
            detector_summaries.append(stats)

            for tier in ["bright", "medium", "faint"]:
                pooled_stamps[tier].extend(stamps_dict.get(tier, []))

            logger.info(
                f"[{stats['detector']}] Status={stats['status']} in {stats['time_s']:.2f}s | "
                f"Stars: B={stats['bright']}, M={stats['medium']}, F={stats['faint']} (Total={stats['total']})"
            )
        except Exception as e:
            logger.error(f"Detector {det_id.upper()} extraction failed: {e}", exc_info=True)
            failed_detectors[det_id] = str(e)
            detector_summaries.append({
                "detector": det_id.upper(),
                "faint": 0, "medium": 0, "bright": 0, "total": 0,
                "status": f"FAILED: {str(e)[:40]}",
                "time_s": 0.0,
            })
            if len(det_map) == 1:
                raise

    total_pooled_count = sum(len(v) for v in pooled_stamps.values())
    if total_pooled_count == 0:
        raise RuntimeError(
            f"No valid stars extracted across any of the {len(det_map)} detectors."
        )

    logger.info(
        f"Pooled stars across {len(det_map)} SCAs: "
        f"Bright={len(pooled_stamps['bright'])}, "
        f"Medium={len(pooled_stamps['medium'])}, "
        f"Faint={len(pooled_stamps['faint'])} (Total={total_pooled_count})"
    )

    # 4. Global Composite Canvas Assembly
    t_asm_start = time.perf_counter()
    composite_epsf, diagnostics = assemble_composite_extended_psf(
        tier_stamps=pooled_stamps,
        output_size=cfg.assembly.canvas_size,
        cfg=cfg.assembly,
        device=torch_dev,
    )
    t_assemble = time.perf_counter() - t_asm_start

    # 5. Serialize Standard 4-HDU FITS Output
    fits_path = cfg.data.output_dir / "roman_epsf_composite.fits"
    serialize_composite_epsf_fits(
        composite_epsf=composite_epsf,
        diagnostics=diagnostics,
        detector_summaries=detector_summaries,
        output_fits_path=fits_path,
        filter_name=cfg.data.filter_name,
        pixel_scale=0.11,
    )
    logger.info(f"Composite extended PSF FITS successfully written to: {fits_path}")

    total_time = time.perf_counter() - t_start
    diagnostics.update({
        "detector_summaries": detector_summaries,
        "failed_detectors": failed_detectors,
        "assembly_time_s": t_assemble,
        "total_pipeline_time_s": total_time,
        "fits_path": fits_path,
    })

    return PipelineOutputs(
        composite_epsf=composite_epsf,
        fits_path=fits_path,
        diagnostics=diagnostics,
        detector_results=detector_results,
        detector_summaries=detector_summaries,
        pooled_stamps=pooled_stamps,
        stamps_by_tier=pooled_stamps,
    )


__all__ = [
    "SingleDetectorResult",
    "PipelineOutputs",
    "RomanPSFConfig",
    "discover_detectors",
    "process_single_detector_stamps",
    "export_single_detector_fits",
    "run_single_detector",
    "run_pipeline",
]
