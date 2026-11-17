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
import os
import re
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import asdf
import numpy as np
import pandas as pd
from astropy.io import fits
import torch

# Suppress harmless ASDF package version warnings when reading newer extension schemas
try:
    from asdf.exceptions import AsdfPackageVersionWarning
    warnings.filterwarnings("ignore", category=AsdfPackageVersionWarning)
except ImportError:
    pass
warnings.filterwarnings("ignore", message=r".*was created with extension URI.*")
warnings.filterwarnings("ignore", message=r".*AsdfPackageVersionWarning.*")

from romanepsf import __version__
from romanepsf.config import PipelineConfig, Config, load_config, resolve_device
from romanepsf.loader import load_l2_image, RomanL2Data
from romanepsf.gaia_spatial import GaiaSpatialManager
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
from romanepsf.plot_utils import save_radial_profiles_data, generate_diagnostic_plots
from romanepsf.debug_plots import generate_all_debug_plots

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


def allocate_debug_stars_per_tier(
    total_stars: int,
    available_counts: Dict[str, int],
) -> Dict[str, int]:
    """
    Evenly partition X debug stars across bright, medium, and faint tiers,
    rebalancing overflow/shortfall to maximize tier diversity up to total_stars.
    """
    tiers = ["bright", "medium", "faint"]
    total_avail = sum(available_counts.get(t, 0) for t in tiers)
    target = min(total_stars, total_avail)
    if target <= 0:
        return {t: 0 for t in tiers}

    base = target // 3
    rem = target % 3
    targets = {
        "bright": min(available_counts.get("bright", 0), base + (1 if rem > 0 else 0)),
        "medium": min(available_counts.get("medium", 0), base + (1 if rem > 1 else 0)),
        "faint": min(available_counts.get("faint", 0), base),
    }

    curr_total = sum(targets.values())
    shortfall = target - curr_total

    while shortfall > 0:
        allocated = False
        for t in ["medium", "faint", "bright"]:
            if targets[t] < available_counts.get(t, 0):
                targets[t] += 1
                shortfall -= 1
                allocated = True
                if shortfall == 0:
                    break
        if not allocated:
            break

    return targets


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

        # Run NoiseChisel once for this detector
        l2_data.measure_sky_noisechisel(device=getattr(getattr(cfg, "environment", None), "device", "auto"))

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
            cand = query_gaia_for_detector(
                l2_data=l2_data,
                mag_limit=20.0,
                cache_dir=cfg.data.cache_dir,
                precomputed_catalog=None,
                mag_col=cfg.catalog.mag_col,
            )

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
            box_fraction=cfg.catalog.centroid_box_fraction,
            cfg=cfg,
        )
        isolated = filter_isolated_stars(
            df=refined,
            pixel_scale=float(l2_data.pixel_scale),
            isolation_safety_factor=cfg.catalog.isolation_safety_factor,
            min_dist_arcsec=cfg.catalog.min_dist_arcsec,
            mag_col=cfg.catalog.mag_col,
            cfg=cfg,
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

        # Always obtain full detector Gaia catalog for companion star masking
        full_companions = refined
        try:
            full_gaia = query_gaia_for_detector(
                l2_data=l2_data,
                mag_limit=20.0,
                cache_dir=cfg.data.cache_dir,
                precomputed_catalog=None,
                mag_col=cfg.catalog.mag_col,
            )
            if not full_gaia.empty:
                full_companions = project_catalog_to_pixels(
                    l2_data=l2_data,
                    catalog_df=full_gaia,
                    margin_px=100.0,
                    tolerance_arcsec=cfg.catalog.roundtrip_tolerance_arcsec,
                )
        except Exception as e:
            logger.warning(f"Could not load full Gaia companions for masking ({e}); falling back to target catalog.")

        t_stamps_start = time.perf_counter()
        stamps_dict = process_star_stamps(
            l2_data=l2_data,
            catalog_df=tiered,
            spikes_cfg=cfg.spikes,
            stamps_cfg=cfg.stamps,
            companion_stars=full_companions,
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
    elif cfg.data.catalog_path is not None:
        resolved_catalog_path = Path(cfg.data.catalog_path)
    else:
        resolved_catalog_path = None

    # 6. Lazy Load and Calibrate L2 ASDF Image
    logger.info(f"Loading Level 2 ASDF image: {resolved_asdf_path}")
    l2_data: RomanL2Data = load_l2_image(resolved_asdf_path, calibrate=True)
    l2_data.measure_sky_noisechisel(device=getattr(getattr(cfg, "environment", None), "device", "auto"))

    try:
        pa_aperture = float(l2_data.pa_aperture)
        pixel_scale = float(l2_data.pixel_scale)
        pixel_area = float(l2_data.pixel_area)
        zp_ab = float(l2_data.zp_ab)
        filter_name = str(l2_data.filter_name)

        # 7. Spatial Catalog Pre-Filtering using Detector Sky Bounds
        if resolved_catalog_path is not None and resolved_catalog_path.is_file():
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
                f"No precomputed catalog provided or found. "
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
            box_fraction=cfg.catalog.centroid_box_fraction,
            cfg=cfg,
        )

        # 10. Pairwise Moffat Isolation Clearance Filtering
        isolated_df = filter_isolated_stars(
            df=refined_df,
            pixel_scale=pixel_scale,
            isolation_safety_factor=cfg.catalog.isolation_safety_factor,
            min_dist_arcsec=cfg.catalog.min_dist_arcsec,
            mag_col=cfg.catalog.mag_col,
            cfg=cfg,
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

        # Always obtain full detector Gaia catalog for companion star masking
        full_companions_df = refined_df
        try:
            full_gaia_df = query_gaia_for_detector(
                l2_data=l2_data,
                mag_limit=20.0,
                cache_dir=cfg.data.cache_dir,
                precomputed_catalog=None,
                mag_col=cfg.catalog.mag_col,
            )
            if not full_gaia_df.empty:
                full_companions_df = project_catalog_to_pixels(
                    l2_data=l2_data,
                    catalog_df=full_gaia_df,
                    margin_px=100.0,
                    tolerance_arcsec=cfg.catalog.roundtrip_tolerance_arcsec,
                )
        except Exception as e:
            logger.warning(f"Could not load full Gaia companions for masking ({e}); falling back to target catalog.")

        # 12. Extract Stamps, Bicubic Subpixel Align, and Mask Contaminants (with Spike Protection)
        logger.info(f"Extracting postage stamps for detector {resolved_detector.upper()}...")
        stamps_by_tier = process_star_stamps(
            l2_data=l2_data,
            catalog_df=tiered_df,
            spikes_cfg=cfg.spikes,
            stamps_cfg=cfg.stamps,
            companion_stars=full_companions_df,
        )

    finally:
        # Strict explicit resource lifecycle cleanup
        del l2_data
        gc.collect()

    if cfg.pipeline.debug is not None:
        debug_x = int(cfg.pipeline.debug)
        tier_alloc = allocate_debug_stars_per_tier(
            debug_x,
            {t: len(stamps_by_tier.get(t, [])) for t in ["bright", "medium", "faint"]},
        )
        for tier in ["bright", "medium", "faint"]:
            n_keep = tier_alloc[tier]
            stamps_by_tier[tier].sort(
                key=lambda s: float(np.max(s.data) / max(s.bkg_rms, 1e-4)),
                reverse=True,
            )
            stamps_by_tier[tier] = stamps_by_tier[tier][:n_keep]
        logger.info(
            f"DEBUG MODE (--debug {debug_x}): Selected {sum(len(v) for v in stamps_by_tier.values())} "
            f"stars across tiers: B={len(stamps_by_tier['bright'])}, M={len(stamps_by_tier['medium'])}, F={len(stamps_by_tier['faint'])}"
        )

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

    # 16. Persist Radial Profiles Data (.npz) and Generate Default Diagnostic Plots 1 & 2
    npz_path = resolved_output_dir / f"roman_epsf_{resolved_detector.lower()}_radial_profiles.npz"
    try:
        save_radial_profiles_data(
            output_npz_path=npz_path,
            composite_epsf=epsf_model,
            pooled_stamps=stamps_by_tier,
            diagnostics=diagnostics,
            pixel_scale=pixel_scale,
        )
        plots_dir = resolved_output_dir / "plots"
        generate_diagnostic_plots(
            profiles_data_or_path=npz_path,
            composite_epsf=epsf_model,
            output_dir=plots_dir,
            sca_name=resolved_detector,
            pixel_scale=pixel_scale,
            dpi=getattr(cfg.reporting, "dpi", 300),
        )
        if cfg.pipeline.debug is not None:
            debug_dir = resolved_output_dir / "debug"
            generate_all_debug_plots(
                pooled_stamps=stamps_by_tier,
                composite_epsf=epsf_model,
                diagnostics=diagnostics,
                output_dir=debug_dir,
                sca_name=resolved_detector,
                pixel_scale=pixel_scale,
                growth_rate=getattr(cfg.profile, "growth_rate", 1.03),
            )
    except Exception as e:
        logger.warning(f"Plot generation failed on {resolved_detector}: {e}", exc_info=True)

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

    # 2. Ingest Master Catalog if available
    has_master = (
        cfg.data.catalog_path is not None
        and Path(cfg.data.catalog_path).is_file()
    )
    if has_master:
        logger.info(f"Loading master source catalog from: {cfg.data.catalog_path}")
        raw_df = pd.read_csv(cfg.data.catalog_path, low_memory=False)
        cat_df = sanitize_source_catalog(raw_df, mag_col=cfg.catalog.mag_col)
        del raw_df
        gc.collect()
    else:
        logger.info("No master catalog provided (catalog_path is None). Querying Gaia DR3 dynamically...")
        cat_df = pd.DataFrame()

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

    if cfg.pipeline.debug is not None:
        debug_x = int(cfg.pipeline.debug)
        tier_alloc = allocate_debug_stars_per_tier(
            debug_x,
            {t: len(pooled_stamps[t]) for t in ["bright", "medium", "faint"]},
        )
        for tier in ["bright", "medium", "faint"]:
            n_keep = tier_alloc[tier]
            pooled_stamps[tier].sort(
                key=lambda s: float(np.max(s.data) / max(s.bkg_rms, 1e-4)),
                reverse=True,
            )
            pooled_stamps[tier] = pooled_stamps[tier][:n_keep]
        logger.info(
            f"DEBUG MODE (--debug {debug_x}): Selected {sum(len(v) for v in pooled_stamps.values())} "
            f"stars across tiers: B={len(pooled_stamps['bright'])}, M={len(pooled_stamps['medium'])}, F={len(pooled_stamps['faint'])}"
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

    # 6. Persist Radial Profiles Data (.npz) and Generate Default Diagnostic Plots 1 & 2
    npz_path = cfg.data.output_dir / "roman_epsf_radial_profiles.npz"
    try:
        save_radial_profiles_data(
            output_npz_path=npz_path,
            composite_epsf=composite_epsf,
            pooled_stamps=pooled_stamps,
            diagnostics=diagnostics,
            pixel_scale=0.11,
            growth_rate=getattr(cfg.profile, "growth_rate", 1.03),
        )
        plots_dir = cfg.data.output_dir / "plots"
        generate_diagnostic_plots(
            profiles_data_or_path=npz_path,
            composite_epsf=composite_epsf,
            output_dir=plots_dir,
            sca_name="Composite",
            pixel_scale=0.11,
            dpi=getattr(cfg.reporting, "dpi", 300),
        )
        if cfg.pipeline.debug is not None:
            debug_dir = cfg.data.output_dir / "debug"
            generate_all_debug_plots(
                pooled_stamps=pooled_stamps,
                composite_epsf=composite_epsf,
                diagnostics=diagnostics,
                output_dir=debug_dir,
                sca_name="Composite",
                pixel_scale=0.11,
                growth_rate=getattr(cfg.profile, "growth_rate", 1.03),
            )
    except Exception as e:
        logger.warning(f"Plot generation failed: {e}", exc_info=True)

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


def fast_scan_asdf_footprint(
    asdf_path: Union[str, Path],
    margin_deg: float = 0.02,
) -> Tuple[str, Tuple[float, float, float, float, float, float, float]]:
    """
    Rapidly extract detector identifier and celestial bounding box from L2 ASDF header
    without allocating 2D pixel image arrays (memory mapped, ~20ms execution).

    Returns
    -------
    (detector_id, (ra_cen, dec_cen, radius_deg, ra_min, ra_max, dec_min, dec_max))
    """
    p = Path(asdf_path)
    try:
        with asdf.open(p, memmap=True) as af:
            det = str(af.tree["roman"]["meta"]["instrument"]["detector"]).lower()
            wcs = af.tree["roman"]["meta"]["wcs"]
            pts = [(0.0, 0.0), (4087.0, 0.0), (4087.0, 4087.0), (0.0, 4087.0), (2044.0, 2044.0)]
            ras, decs = [], []
            for x, y in pts:
                r, d = wcs(x, y)
                if np.isfinite(r) and np.isfinite(d):
                    ras.append(float(r))
                    decs.append(float(d))
            if not ras or not decs:
                raise ValueError("WCS evaluation returned non-finite coordinates.")
            cen_r, cen_d = wcs(2044.0, 2044.0)
            ra_cen = float(cen_r) if np.isfinite(cen_r) else 0.5 * (min(ras) + max(ras))
            dec_cen = float(cen_d) if np.isfinite(cen_d) else 0.5 * (min(decs) + max(decs))
            diag = np.hypot(max(ras) - min(ras), max(decs) - min(decs))
            radius = (diag / 2.0) + margin_deg
            bounds = (
                ra_cen,
                dec_cen,
                radius,
                min(ras) - margin_deg,
                max(ras) + margin_deg,
                min(decs) - margin_deg,
                max(decs) + margin_deg,
            )
            return det, bounds
    except Exception as e:
        logger.debug(f"Fast header scan failed for {p.name}: {e}. Falling back to load_l2_image.")
        l2 = load_l2_image(p, calibrate=False)
        det = l2.detector.lower()
        bounds = get_detector_sky_bounds(l2, margin_deg=margin_deg)
        del l2
        gc.collect()
        return det, bounds


def _sca_file_worker_task(
    task_args: Tuple[str, Optional[str], Optional[str], Optional[str], Config, Optional[Dict[str, int]]],
) -> Tuple[str, Dict[str, List[StellarStamp]], Dict[str, Any]]:
    """
    Multiprocessing worker task for single L2 ASDF stamp extraction.
    Ensures prompt deallocation of full image arrays to keep worker RSS << 4 GB.
    """
    # Prevent CPU thread oversubscription during parallel execution:
    # 1 thread per worker process prevents N_workers x N_cores thread contention
    try:
        import torch
        if torch.get_num_threads() > 1:
            torch.set_num_threads(1)
    except Exception:
        pass

    asdf_path_str, target_sca, hpx_cache_dir, master_catalog_path, cfg, max_stars_per_file = task_args
    asdf_path = Path(asdf_path_str)
    t0 = time.perf_counter()
    l2_data: Optional[RomanL2Data] = None
    empty_stamps: Dict[str, List[StellarStamp]] = {"bright": [], "medium": [], "faint": []}

    try:
        l2_data = load_l2_image(asdf_path, calibrate=True)
        det_name = l2_data.detector.lower()

        if target_sca is not None and det_name != target_sca.lower():
            return det_name, empty_stamps, {
                "file": asdf_path.name,
                "detector": det_name.upper(),
                "status": "SKIPPED_WRONG_SCA",
                "time_s": time.perf_counter() - t0,
                "total": 0, "bright": 0, "medium": 0, "faint": 0,
            }

        # Run NoiseChisel once for this detector
        l2_data.measure_sky_noisechisel(device=getattr(getattr(cfg, "environment", None), "device", "auto"))

        ra_c, dec_c, rad, ra_min, ra_max, dec_min, dec_max = get_detector_sky_bounds(l2_data, margin_deg=0.02)

        # Sub-millisecond slice from local HEALPix cache
        mgr = GaiaSpatialManager(
            cache_dir=hpx_cache_dir or "cache/gaia_healpix",
            precomputed_catalog=master_catalog_path,
            mag_col=cfg.catalog.mag_col,
        )
        cand = mgr.get_catalog_for_bounds(ra_min, ra_max, dec_min, dec_max, mag_limit=20.0)

        if cand.empty:
            # Fallback to general detector query if HEALPix cache miss
            cand = query_gaia_for_detector(
                l2_data=l2_data,
                mag_limit=20.0,
                cache_dir=cfg.data.cache_dir,
                precomputed_catalog=master_catalog_path,
                mag_col=cfg.catalog.mag_col,
            )

        if cand.empty:
            return det_name, empty_stamps, {
                "file": asdf_path.name,
                "detector": det_name.upper(),
                "status": "NO_STARS",
                "time_s": time.perf_counter() - t0,
                "total": 0, "bright": 0, "medium": 0, "faint": 0,
            }

        proj = project_catalog_to_pixels(
            l2_data=l2_data,
            catalog_df=cand,
            margin_px=cfg.catalog.edge_margin_px,
            tolerance_arcsec=cfg.catalog.roundtrip_tolerance_arcsec,
        )
        if proj.empty:
            return det_name, empty_stamps, {
                "file": asdf_path.name,
                "detector": det_name.upper(),
                "status": "NO_PROJECTED_STARS",
                "time_s": time.perf_counter() - t0,
                "total": 0, "bright": 0, "medium": 0, "faint": 0,
            }

        refined = refine_stellar_centroids(
            l2_data=l2_data,
            df=proj,
            box_radius=cfg.catalog.centroid_refine_box_px,
            box_fraction=cfg.catalog.centroid_box_fraction,
            cfg=cfg,
        )
        isolated = filter_isolated_stars(
            df=refined,
            pixel_scale=float(l2_data.pixel_scale),
            isolation_safety_factor=cfg.catalog.isolation_safety_factor,
            min_dist_arcsec=cfg.catalog.min_dist_arcsec,
            mag_col=cfg.catalog.mag_col,
            cfg=cfg,
        )
        if isolated.empty:
            return det_name, empty_stamps, {
                "file": asdf_path.name,
                "detector": det_name.upper(),
                "status": "NO_ISOLATED_STARS",
                "time_s": time.perf_counter() - t0,
                "total": 0, "bright": 0, "medium": 0, "faint": 0,
            }

        tiered = assign_stellar_tiers(
            df=isolated,
            bright_limit=cfg.tiers.bright_limit,
            faint_limit=cfg.tiers.faint_limit,
            mag_col=cfg.catalog.mag_col,
        )

        stamps_dict = process_star_stamps(
            l2_data=l2_data,
            catalog_df=tiered,
            spikes_cfg=cfg.spikes,
            stamps_cfg=cfg.stamps,
            companion_stars=refined,
        )

        n_b = len(stamps_dict.get("bright", []))
        n_m = len(stamps_dict.get("medium", []))
        n_f = len(stamps_dict.get("faint", []))
        n_tot = n_b + n_m + n_f

        stats = {
            "file": asdf_path.name,
            "detector": det_name.upper(),
            "bright": n_b,
            "medium": n_m,
            "faint": n_f,
            "total": n_tot,
            "status": "SUCCESS" if n_tot > 0 else "NO_VALID_STAMPS",
            "time_s": time.perf_counter() - t0,
            "pixel_scale": float(l2_data.pixel_scale),
            "pa_aperture": float(l2_data.pa_aperture),
        }
        return det_name, stamps_dict, stats

    except Exception as exc:
        logger.warning(f"Worker failed on {asdf_path.name}: {exc}", exc_info=True)
        return "unknown", empty_stamps, {
            "file": asdf_path.name,
            "detector": (target_sca or "unknown").upper(),
            "status": f"ERROR: {str(exc)[:60]}",
            "time_s": time.perf_counter() - t0,
            "total": 0, "bright": 0, "medium": 0, "faint": 0,
        }
    finally:
        if l2_data is not None:
            del l2_data
        gc.collect()


def run_sca_batch_pipeline(
    files: Union[Sequence[Union[str, Path]], str, Path],
    sca_id: Optional[str] = None,
    cfg: Optional[Union[Config, str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    canvas_size: Optional[int] = None,
    num_workers: Optional[int] = None,
    gaia_cache_dir: Optional[Union[str, Path]] = None,
    master_catalog_path: Optional[Union[str, Path]] = None,
    device: Optional[str] = None,
    max_stamps_per_tier: Optional[Dict[str, int]] = None,
) -> PipelineOutputs:
    """
    High-throughput batch pipeline for synthesizing a composite extended PSF model
    for a single Roman Sensor Chip Assembly (SCA) across hundreds/thousands of L2 images.

    Architectural optimizations:
    1. Pre-flight spatial harvesting: Aggregates all HEALPix tiles across input footprints
       and fetches missing tiles in a single-threaded polite rate-limited phase to completely
       prevent ESA Gaia TAP rate limits (HTTP 429).
    2. Parallel multi-core multiprocessing via ProcessPoolExecutor: Full utilization of
       large multi-core servers (e.g. 56-60 CPUs).
    3. Strict per-image RAM reclamation (peak RSS << 4 GB per core, safe for 500 GB RAM).
    4. Overlap flux scaling and annular blending into 1 composite model per SCA.
    """
    t_start = time.perf_counter()

    # 1. Resolve Configuration
    if cfg is None or isinstance(cfg, (str, Path)):
        resolved_cfg = load_config(cfg) if cfg is not None else load_config()
    else:
        resolved_cfg = cfg

    if output_dir is not None:
        resolved_cfg.data.output_dir = Path(output_dir)
    if canvas_size is not None:
        resolved_cfg.assembly.canvas_size = int(canvas_size)
    if device is not None:
        resolved_cfg.environment.device = str(device).lower()
    if num_workers is not None:
        resolved_cfg.environment.num_workers = int(num_workers)
    if master_catalog_path is not None:
        resolved_cfg.data.catalog_path = Path(master_catalog_path)
    if gaia_cache_dir is not None:
        resolved_cfg.data.gaia_cache_dir = Path(gaia_cache_dir)

    resolved_cfg.validate()
    resolved_cfg.data.output_dir.mkdir(parents=True, exist_ok=True)
    resolved_hpx_dir = resolved_cfg.data.gaia_cache_dir
    resolved_hpx_dir.mkdir(parents=True, exist_ok=True)

    # 2. Parse and Expand Input File List
    raw_files: List[Path] = []
    if isinstance(files, (str, Path)):
        p_files = Path(files)
        if p_files.is_file() and p_files.suffix.lower() in [".txt", ".lst", ".list", ".csv"]:
            with open(p_files, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        raw_files.append(Path(stripped))
        elif p_files.is_file():
            raw_files.append(p_files)
        elif p_files.is_dir():
            raw_files.extend(sorted(p_files.glob("*_cal.asdf")))
        else:
            raise FileNotFoundError(f"Specified input path does not exist: {p_files}")
    else:
        for f in files:
            p = Path(f)
            if p.is_file():
                raw_files.append(p)

    if not raw_files:
        raise ValueError("No valid input L2 ASDF files found to process.")

    logger.info(f"Loaded {len(raw_files)} total input file path(s).")

    # 3. Detect or Filter Target SCA
    from romanepsf.config import normalize_sca_id
    target_sca = normalize_sca_id(sca_id) if sca_id else None
    if target_sca is None:
        # Auto-detect from first file
        det_found, _ = fast_scan_asdf_footprint(raw_files[0])
        target_sca = normalize_sca_id(det_found)
        logger.info(f"Auto-detected target SCA: {target_sca.upper()} from {raw_files[0].name}")

    # Filter files belonging to target_sca
    matching_files: List[Path] = []
    pattern = re.compile(rf"_{target_sca}_", re.IGNORECASE)
    for f in raw_files:
        if pattern.search(f.name):
            matching_files.append(f)

    if not matching_files:
        # Fallback to header inspection if filename doesn't contain standard SCA token
        logger.info(f"Filename pattern didn't match '{target_sca}'; verifying via ASDF headers...")
        for f in raw_files:
            det, _ = fast_scan_asdf_footprint(f)
            if det == target_sca:
                matching_files.append(f)

    if not matching_files:
        raise ValueError(f"No files matched target SCA '{target_sca.upper()}' out of {len(raw_files)} inputs.")

    logger.info(
        f"Selected {len(matching_files)} file(s) for target SCA: {target_sca.upper()}"
    )

    # 4. Pre-Flight Spatial Harvesting (Zero Gaia API Overload)
    logger.info("Starting Pre-Flight celestial coverage scan...")
    mgr = GaiaSpatialManager(
        cache_dir=resolved_hpx_dir,
        precomputed_catalog=resolved_cfg.data.catalog_path,
        mag_col=resolved_cfg.catalog.mag_col,
    )

    all_required_tiles: set[int] = set()
    for f in matching_files:
        _, (ra_c, dec_c, rad, _, _, _, _) = fast_scan_asdf_footprint(f)
        tiles = mgr.query_disc_tiles(ra_c, dec_c, rad)
        all_required_tiles.update(tiles)

    missing_tiles = mgr.get_missing_tiles(sorted(all_required_tiles))
    logger.info(
        f"Pre-Flight scan: {len(all_required_tiles)} HEALPix tiles cover all footprints. "
        f"Missing from local cache: {len(missing_tiles)}."
    )

    if missing_tiles:
        if resolved_cfg.data.catalog_path and resolved_cfg.data.catalog_path.is_file():
            logger.info("Partitioning missing tiles from local master catalog...")
            mgr.partition_from_master_catalog(target_tiles=missing_tiles)
            missing_tiles = mgr.get_missing_tiles(missing_tiles)

        if missing_tiles:
            logger.info(
                f"Fetching {len(missing_tiles)} missing tiles via rate-limited TAP (polite single-threaded)..."
            )
            mgr.fetch_missing_tiles_polite(missing_tiles, delay_seconds=1.5)

    # 5. Multiprocessing Parallel Stamp Extraction
    n_cpus = os.cpu_count() or 4
    default_workers = max(1, min(len(matching_files), n_cpus - 2, 56))
    effective_workers = (
        resolved_cfg.environment.num_workers
        if resolved_cfg.environment.num_workers > 0
        else default_workers
    )

    logger.info(
        f"Launching parallel extraction across {effective_workers} worker processes "
        f"for {len(matching_files)} image(s)..."
    )

    pooled_stamps: Dict[str, List[StellarStamp]] = {"bright": [], "medium": [], "faint": []}
    detector_summaries: List[Dict[str, Any]] = []

    tasks = [
        (
            str(f),
            target_sca,
            str(resolved_hpx_dir),
            str(resolved_cfg.data.catalog_path) if (resolved_cfg.data.catalog_path and resolved_cfg.data.catalog_path.is_file()) else None,
            resolved_cfg,
            None,
        )
        for f in matching_files
    ]

    debug_x = int(resolved_cfg.pipeline.debug) if resolved_cfg.pipeline.debug is not None else None

    if effective_workers <= 1:
        for task in tasks:
            det_name, stamps_dict, stats = _sca_file_worker_task(task)
            detector_summaries.append(stats)
            for tier in ["bright", "medium", "faint"]:
                pooled_stamps[tier].extend(stamps_dict.get(tier, []))
            if debug_x is not None:
                needed = max(1, debug_x // 3)
                if (
                    len(pooled_stamps["bright"]) >= needed
                    and len(pooled_stamps["medium"]) >= needed
                    and len(pooled_stamps["faint"]) >= needed
                ):
                    logger.info(f"DEBUG MODE: Reached star threshold ({needed} per tier); stopping file ingestion.")
                    break
    else:
        with ProcessPoolExecutor(max_workers=effective_workers) as executor:
            futures = [executor.submit(_sca_file_worker_task, t) for t in tasks]
            completed_count = 0
            for fut in as_completed(futures):
                completed_count += 1
                det_name, stamps_dict, stats = fut.result()
                detector_summaries.append(stats)
                for tier in ["bright", "medium", "faint"]:
                    pooled_stamps[tier].extend(stamps_dict.get(tier, []))

                if completed_count % 10 == 0 or completed_count == len(matching_files):
                    logger.info(
                        f"Processed {completed_count}/{len(matching_files)} files | "
                        f"Pooled: B={len(pooled_stamps['bright'])}, "
                        f"M={len(pooled_stamps['medium'])}, "
                        f"F={len(pooled_stamps['faint'])}"
                    )
                if debug_x is not None:
                    needed = max(1, debug_x // 3)
                    if (
                        len(pooled_stamps["bright"]) >= needed
                        and len(pooled_stamps["medium"]) >= needed
                        and len(pooled_stamps["faint"]) >= needed
                    ):
                        logger.info(f"DEBUG MODE: Reached star threshold ({needed} per tier); cancelling remaining worker tasks.")
                        for f_rem in futures:
                            f_rem.cancel()
                        break

    total_pooled = sum(len(v) for v in pooled_stamps.values())
    if total_pooled == 0:
        raise RuntimeError(
            f"No valid stars extracted across {len(matching_files)} files for SCA {target_sca.upper()}."
        )

    # 6. Reservoir Sampling / Tier Capacity Capping (or Debug X Allocation)
    if debug_x is not None:
        tier_alloc = allocate_debug_stars_per_tier(
            debug_x,
            {t: len(pooled_stamps[t]) for t in ["bright", "medium", "faint"]},
        )
        for tier in ["bright", "medium", "faint"]:
            n_keep = tier_alloc[tier]
            pooled_stamps[tier].sort(
                key=lambda s: float(np.max(s.data) / max(s.bkg_rms, 1e-4)),
                reverse=True,
            )
            pooled_stamps[tier] = pooled_stamps[tier][:n_keep]
        logger.info(
            f"DEBUG MODE (--debug {debug_x}): Selected {sum(len(v) for v in pooled_stamps.values())} "
            f"stars across tiers: B={len(pooled_stamps['bright'])}, M={len(pooled_stamps['medium'])}, F={len(pooled_stamps['faint'])}"
        )
    else:
        caps = max_stamps_per_tier or {}
        for tier in ["bright", "medium", "faint"]:
            cap = caps.get(tier)
            if cap is None and hasattr(resolved_cfg.tiers.max_stars_per_tier, tier):
                cap = getattr(resolved_cfg.tiers.max_stars_per_tier, tier)

            if cap and len(pooled_stamps[tier]) > cap:
                # Keep highest SNR / cleanest stamps
                pooled_stamps[tier].sort(
                    key=lambda s: float(np.max(s.data) / max(s.bkg_rms, 1e-4)),
                    reverse=True,
                )
                pooled_stamps[tier] = pooled_stamps[tier][:cap]
                logger.info(f"Reservoir sampled '{tier}' tier to top {cap} highest SNR stamps.")

    logger.info(
        f"Final stamp pool for {target_sca.upper()}: "
        f"Bright={len(pooled_stamps['bright'])}, "
        f"Medium={len(pooled_stamps['medium'])}, "
        f"Faint={len(pooled_stamps['faint'])} (Total={sum(len(v) for v in pooled_stamps.values())})"
    )

    # 7. Composite Canvas Assembly
    torch_dev = resolved_cfg.get_torch_device()
    if torch_dev.type == "cpu":
        torch.set_num_threads(effective_workers)

    t_asm_start = time.perf_counter()
    composite_epsf, diagnostics = assemble_composite_extended_psf(
        tier_stamps=pooled_stamps,
        output_size=resolved_cfg.assembly.canvas_size,
        cfg=resolved_cfg.assembly,
        device=torch_dev,
    )
    t_asm = time.perf_counter() - t_asm_start

    # 8. Serialize 4-HDU Composite FITS
    fits_path = resolved_cfg.data.output_dir / f"roman_epsf_{target_sca.lower()}_composite.fits"
    serialize_composite_epsf_fits(
        composite_epsf=composite_epsf,
        diagnostics=diagnostics,
        detector_summaries=detector_summaries,
        output_fits_path=fits_path,
        filter_name=resolved_cfg.data.filter_name,
        pixel_scale=0.11,
    )
    logger.info(f"Composite extended PSF for {target_sca.upper()} successfully saved to: {fits_path}")

    # 9. Persist Radial Profiles Data (.npz) and Generate Default Diagnostic Plots 1 & 2
    npz_path = resolved_cfg.data.output_dir / f"roman_epsf_{target_sca.lower()}_radial_profiles.npz"
    try:
        save_radial_profiles_data(
            output_npz_path=npz_path,
            composite_epsf=composite_epsf,
            pooled_stamps=pooled_stamps,
            diagnostics=diagnostics,
            pixel_scale=0.11,
            growth_rate=getattr(resolved_cfg.profile, "growth_rate", 1.03),
        )
        plots_dir = resolved_cfg.data.output_dir / "plots"
        generate_diagnostic_plots(
            profiles_data_or_path=npz_path,
            composite_epsf=composite_epsf,
            output_dir=plots_dir,
            sca_name=target_sca,
            pixel_scale=0.11,
            dpi=getattr(resolved_cfg.reporting, "dpi", 300),
        )
        if resolved_cfg.pipeline.debug is not None:
            debug_dir = resolved_cfg.data.output_dir / "debug"
            generate_all_debug_plots(
                pooled_stamps=pooled_stamps,
                composite_epsf=composite_epsf,
                diagnostics=diagnostics,
                output_dir=debug_dir,
                sca_name=target_sca,
                pixel_scale=0.11,
                growth_rate=getattr(resolved_cfg.profile, "growth_rate", 1.03),
            )
    except Exception as e:
        logger.warning(f"Plot generation failed on {target_sca}: {e}", exc_info=True)

    # 10. Persist Polar Profiles Data (.parquet) containing all spike polar profiles
    parquet_path = resolved_cfg.data.output_dir / f"roman_epsf_{target_sca}_polar_profiles.parquet"
    try:
        from romanepsf.profile import save_spike_polar_profiles_parquet
        save_spike_polar_profiles_parquet(
            pooled_stamps=pooled_stamps,
            output_parquet_path=parquet_path,
            sca_name=target_sca,
        )
        diagnostics["polar_profiles_parquet"] = parquet_path
    except Exception as e:
        logger.warning(f"Spike polar profiles table generation failed on {target_sca}: {e}", exc_info=True)

    total_time = time.perf_counter() - t_start
    diagnostics.update({
        "target_sca": target_sca.upper(),
        "input_files_count": len(matching_files),
        "detector_summaries": detector_summaries,
        "assembly_time_s": t_asm,
        "total_pipeline_time_s": total_time,
        "fits_path": fits_path,
    })

    return PipelineOutputs(
        composite_epsf=composite_epsf,
        fits_path=fits_path,
        diagnostics=diagnostics,
        detector_results={},
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
    "fast_scan_asdf_footprint",
    "run_sca_batch_pipeline",
    "allocate_debug_stars_per_tier",
]
