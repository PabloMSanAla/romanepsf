# Handoff Report: Multi-Detector Cross-SCA Stamp Pooling & Composite Extended PSF Canvas Assembly

**Author**: Explorer 3 (Milestone 3: Single-Detector Validation & 18-Detector Pipeline Execution)  
**Date**: 2026-11-07T00:28:00Z  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_3`  
**Target Modules**: `src/romanepsf/pipeline.py`, `src/romanepsf/cli.py`, `src/romanepsf/assembly.py`

---

## 1. Observation

### 1.1 Commissioning Dataset and Detector Census
- **ASDF Datasets**: All 18 Roman WFI detector files are present in `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/`:
  `r0108301001001001001_0001_wfi01_f146_cal.asdf` through `...wfi18_f146_cal.asdf`.
  Each file is ~214 MB on disk with active science shape `(4088, 4088)` float32.
- **Source Catalog**: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv` contains 198,802 raw sources (198,564 after duplicate sanitization).
- **Per-Detector Star Counts & Tier Sparsity**:
  Direct empirical execution of `load_l2_image`, `project_catalog_to_pixels`, `refine_stellar_centroids`, `filter_isolated_stars`, and `assign_stellar_tiers` yielded the following per-SCA census:
  * `wfi01`: Faint=2, Medium=2, Bright=1 (Total: 5)
  * `wfi02`: Faint=4, Medium=2, Bright=0 (Total: 6) — **Zero Bright Stars**
  * `wfi03`: Faint=2, Medium=3, Bright=0 (Total: 5) — **Zero Bright Stars**
  * `wfi04`: Faint=3, Medium=1, Bright=1 (Total: 5)
  * `wfi05`: Faint=9, Medium=1, Bright=1 (Total: 11) [Includes brightest star in field, $m \approx 7.371$]
  * `wfi06`: Faint=3, Medium=3, Bright=1 (Total: 7)
  * `wfi07`: Faint=7, Medium=1, Bright=1 (Total: 9)
  * `wfi08`: Faint=4, Medium=2, Bright=0 (Total: 6) — **Zero Bright Stars**
  * `wfi09`: Faint=6, Medium=2, Bright=1 (Total: 9)
  * `wfi10`: Faint=6, Medium=3, Bright=1 (Total: 10)
  * `wfi11`: Faint=4, Medium=2, Bright=1 (Total: 7)
  * `wfi12`: Faint=1, Medium=3, Bright=1 (Total: 5)
  * `wfi13`: Faint=7, Medium=3, Bright=0 (Total: 10) — **Zero Bright Stars**
  * `wfi14`: Faint=5, Medium=2, Bright=1 (Total: 8)
  * `wfi15`: Faint=4, Medium=3, Bright=1 (Total: 8)
  * `wfi16`: Faint=7, Medium=2, Bright=1 (Total: 10)
  * `wfi17`: Faint=7, Medium=1, Bright=0 (Total: 8) — **Zero Bright Stars**
  * `wfi18`: Faint=8, Medium=3, Bright=0 (Total: 11) — **Zero Bright Stars**
  
  **Direct Empirical Fact**: Exactly 6 detectors (`wfi02`, `wfi03`, `wfi08`, `wfi13`, `wfi17`, `wfi18`) contain zero bright stars ($m_{\text{F146}} < 11.0$).
  **Pooled Census Across All 18 Detectors**:
  * Bright stars ($m < 11.0$): **12**
  * Medium stars ($11.0 \le m < 13.0$): **39**
  * Faint stars ($m \ge 13.0$): **89**
  * Total verified, isolated, centroid-refined stars: **140**

### 1.2 Pipeline Performance Benchmarks
- Sequential 18-detector stamp extraction benchmark executed via `process_star_stamps`:
  * Elapsed time: **9.78 seconds** total (~0.54s per detector).
  * Peak memory footprint remained strictly bounded (< 300 MB) when calling `del l2_data; gc.collect()` after each detector.
- Composite canvas assembly via `assemble_composite_extended_psf`:
  * 1025x1025 canvas assembly: **0.31 seconds**, unit sum = $1.000000$.
  * 2049x2049 canvas assembly: **0.33 seconds**, unit sum = $1.000000$.
  * Derived scale factors across pooled stamps:
    $$k_{\text{FM}} = 0.193659$$
    $$k_{\text{MB}} = 0.025527$$

### 1.3 Optical Geometry & Diffraction Spike Priors
- Across all 18 detectors, aperture position angle $\theta_{\text{PA}}$ has a mean of $-110.007^\circ$ ($\min -110.13^\circ$, $\max -109.87^\circ$).
- Pixel scale ranges from $0.1058$ to $0.1092$ arcsec/pixel (mean $0.1075$, nominal $0.11$).
- Theoretical base pupil spider angles (`ROMAN_BASE_SPIKE_ANGLES_DEG` in `masking.py:32`):
  `[23.55, 55.29, 80.25, 118.65, 142.88, 178.07]` degrees.
- Nominal detector alignment clocking offset: $-9.70^\circ$.
- Net orientation angle in detector pixel frame:
  $$\theta_{\text{net}} = \bar{\theta}_{\text{PA}} + \Delta\theta_{\text{det}} = -110.007^\circ - 9.70^\circ = -119.707^\circ \equiv 240.293^\circ$$
- 12 resulting radial spike ray directions:
  `[23.17, 58.36, 83.84, 115.58, 140.54, 178.94, 203.17, 238.36, 263.84, 295.58, 320.54, 358.94]` degrees.

---

## 2. Logic Chain

1. **Why Cross-SCA Stamp Pooling is Scientifically Necessary**:
   - *Premise 1*: Single-detector modeling on 6 detectors (`wfi02`, `wfi03`, `wfi08`, `wfi13`, `wfi17`, `wfi18`) lacks bright stars, forcing fallback to 2-tier synthesis ($r_{\text{max}} \le 100$ px), omitting extended wings and 6-fold diffraction spikes ($r > 100$ px).
   - *Premise 2*: Roman's optical telescope assembly (OTA) and secondary mirror spider geometry are common to all 18 WFI detectors; the extended diffraction spikes and optical PSF wings are fixed in the telescope frame and rotate together onto the focal plane array.
   - *Deduction*: By extracting subpixel-aligned, background-subtracted postage stamps independently per SCA and pooling them into global tier collections (`pooled_stamps['bright']`, `'medium'`, `'faint'`), all 3 tiers are populated with 12 bright, 39 medium, and 89 faint stars. This enables synthesizing a global, high-signal-to-noise composite extended PSF canvas spanning the entire Roman WFI field.

2. **Determination of Robust Cross-Tier Scale Factors ($k_{\text{FM}}$, $k_{\text{MB}}$)**:
   - *Premise 1*: Faint stars provide unsaturated cores ($r < 10$ px). Medium stars provide unsaturated transition overlap ($8 < r < 45$ px). Bright stars provide high SNR in the distant wings and diffraction spikes ($r > 30$ px).
   - *Premise 2*: Using pooled stacks, the 1D radial profiles measured via `measure_radial_profile_1d` (masked by zero-coverage pixels) have substantial statistical weight (89 faint stars, 39 medium stars, 12 bright stars).
   - *Deduction*: Determining $k_{\text{FM}} = \text{median}(f_{\text{F}} / f_{\text{M}})$ across overlap annulus $r \in [8.0, 16.0]$ px yields $k_{\text{FM}} \approx 0.193659$. Scaling the medium tier and determining $k_{\text{MB}} = \text{median}(f_{\text{M,scaled}} / f_{\text{B}})$ across overlap annulus $r \in [22.0, 45.0]$ px yields $k_{\text{MB}} \approx 0.025527$. The monotonicity $0 < k_{\text{MB}} < k_{\text{FM}} < 1$ is physically consistent with the relative brightness tiers ($m_{\text{faint}} \ge 13 > m_{\text{medium}} \ge 11 > m_{\text{bright}}$).

3. **Composite Canvas Sizing (1025x1025 vs 2049x2049)**:
   - *Premise 1*: Pixel grids must have an exact, unambiguous integer center pixel at $((S-1)/2, (S-1)/2)$ to preserve subpixel centroid alignment and radial profile symmetry without fractional resampling.
   - *Premise 2*: Even dimensions (1024, 2048) have a half-pixel center (511.5, 1023.5), whereas odd dimensions (1025, 2049) have exact integer centers at (512, 512) and (1024, 1024).
   - *Premise 3*: The maximum bright star cutout size is $1001 \times 1001$ pixels ($r \le 500$ px, $\pm 55$ arcsec). On a 1025x1025 canvas, this leaves a 12-pixel margin. On a 2049x2049 canvas, this provides extensive zero-padding ($\pm 112.6$ arcsec) suitable for wide-angle FFT convolution without edge wrap-around.
   - *Deduction*: The pipeline must support both 1025 and 2049 as configurable odd canvas dimensions (default 1025 for memory and speed, 2049 for wide-field convolution).

4. **FITS Serialization Architecture**:
   - *Premise 1*: Astronomical software and pipelines require FITS standards with standard <= 8-character keyword names to avoid `HIERARCH` compatibility warnings.
   - *Premise 2*: Analysis of composite ePSFs requires:
     1. The primary 2D ePSF model (normalized to unit flux).
     2. A spatial coverage map indicating the density of contributing stars across the field.
     3. The 1D radial profiles used for tier scaling.
     4. A tabular summary of the 18 contributing detectors.
   - *Deduction*: The output must be structured as a 4-HDU FITS file:
     - HDU 0: `PRIMARY` (float32, 2D composite ePSF, full optical & tier headers).
     - HDU 1: `COVERAGE` (int32 ImageHDU, valid star count per pixel).
     - HDU 2: `RADIAL_PROFILES` (BinTableHDU, 1D profiles for Faint, Medium, Bright, and Composite).
     - HDU 3: `DETECTOR_SUMMARY` (BinTableHDU, per-SCA star breakdown, pointing, and status).

5. **CLI Subcommand `romanepsf run`**:
   - *Premise 1*: Users and automated scripts need to execute the full pipeline via `romanepsf run` with flexible arguments (`--input-dir`, `--catalog`, `--config`, `--output-dir`, `--canvas-size`, `--device`, `--detectors`, `--num-workers`).
   - *Deduction*: Enhancing `run_command` in `src/romanepsf/cli.py` to accept these options directly (and fallback to Click context / config YAML) provides full compliance with R1, R3, and test requirements.

---

## 3. Caveats

1. **Orientation Alignment Across SCAs**:
   The 18 detectors have aperture position angles differing by up to $\pm 0.13^\circ$ (from $-109.87^\circ$ to $-110.13^\circ$). This slight relative clocking ($\le 0.26^\circ$) across the focal plane is negligible for diffraction spike widths ($\approx 4^\circ$ angular wedge, $4$ px corridor width). For the composite model, the mean aperture PA ($\bar{\theta}_{\text{PA}} = -110.01^\circ$) and detector clocking offset ($-9.70^\circ$) define the net orientation.
2. **Local Background Subtraction**:
   Postage stamps have background subtracted per stamp during extraction in `stamps.py`. Outer pixels in bright star stamps ($r \approx 500$ px) approach the sky background. Global background estimation across SCAs is assumed to be handled during Level 2 pipeline calibration.
3. **Execution Mode**:
   While sequential extraction with memory cleanup took only ~9.8s on Apple Silicon, multiprocessing via `num_workers > 1` can be enabled. However, when using PyTorch MPS acceleration, multiprocessing requires `spawn` or separate processes to avoid MPS context conflicts. Sequential execution on CPU/MPS is recommended as the default given the fast 10-second runtime.

---

## 4. Conclusion & Implementation Blueprint

### 4.1 FITS Serialization Function (`serialize_composite_epsf_fits`)
To be placed in `src/romanepsf/assembly.py` or `src/romanepsf/pipeline.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
import numpy as np
from astropy.io import fits
from astropy.table import Table

from romanepsf import __version__
from romanepsf.masking import ROMAN_BASE_SPIKE_ANGLES_DEG, NOMINAL_DETECTOR_OFFSET_DEG
from romanepsf.assembly import _embed_or_crop_canvas, measure_radial_profile_1d


def serialize_composite_epsf_fits(
    composite_epsf: np.ndarray,
    diagnostics: Dict[str, Any],
    detector_summaries: List[Dict[str, Any]],
    output_fits_path: Path,
    filter_name: str = "F146",
    pixel_scale: float = 0.11,
) -> Path:
    """
    Serialize 2D composite ePSF and diagnostics into standard multi-extension FITS format.

    Extensions:
    - Primary HDU: 2D composite extended PSF canvas (float32, unit sum = 1.0).
    - HDU 1 ('COVERAGE'): 2D integer map of valid unmasked stellar coverage per pixel.
    - HDU 2 ('RADIAL_PROFILES'): 1D radial surface brightness profiles per tier and composite.
    - HDU 3 ('DETECTOR_SUMMARY'): Tabular summary of contributing detectors and star counts.
    """
    target_path = Path(output_fits_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    S = composite_epsf.shape[0]

    # 1. Primary HDU
    primary_hdu = fits.PrimaryHDU(data=composite_epsf.astype(np.float32))
    hdr = primary_hdu.header
    hdr["EXTNAME"] = ("EPSF", "Composite 2D Extended Point Spread Function")
    hdr["TELESCOP"] = ("ROMAN", "Roman Space Telescope")
    hdr["INSTRUME"] = ("WFI", "Wide Field Instrument")
    hdr["FILTER"] = (filter_name, "WFI filter passband")
    hdr["PIXSCALE"] = (float(pixel_scale), "Pixel scale in arcsec/pixel")
    hdr["PIXUNIT"] = ("FLUX_FRACTION", "Unit-normalized integrated surface flux")
    hdr["CANVAS_S"] = (int(S), "Canvas dimension (SxS pixels)")

    # WCS Coordinate metadata (Linear detector frame relative to center)
    cx = (S - 1) / 2.0 + 1.0  # 1-indexed FITS convention
    cy = (S - 1) / 2.0 + 1.0
    hdr["CRPIX1"] = (cx, "X pixel coordinate of center")
    hdr["CRPIX2"] = (cy, "Y pixel coordinate of center")
    hdr["CRVAL1"] = (0.0, "Center X offset (arcsec)")
    hdr["CRVAL2"] = (0.0, "Center Y offset (arcsec)")
    hdr["CDELT1"] = (float(pixel_scale), "Pixel scale X (arcsec/pixel)")
    hdr["CDELT2"] = (float(pixel_scale), "Pixel scale Y (arcsec/pixel)")
    hdr["CTYPE1"] = ("LINEAR", "Linear coordinate system")
    hdr["CTYPE2"] = ("LINEAR", "Linear coordinate system")
    hdr["CUNIT1"] = ("arcsec", "Coordinate units")
    hdr["CUNIT2"] = ("arcsec", "Coordinate units")

    # Contributing detectors and star counts
    n_det = len(detector_summaries)
    hdr["NDET"] = (n_det, "Number of contributing detectors")
    det_list_str = ",".join([d["detector"] for d in detector_summaries])
    if len(det_list_str) > 68:
        det_list_str = f"{detector_summaries[0]['detector']}..{detector_summaries[-1]['detector']}"
    hdr["DETLIST"] = (det_list_str, "Contributing detectors")

    n_f = sum(d.get("faint", 0) for d in detector_summaries)
    n_m = sum(d.get("medium", 0) for d in detector_summaries)
    n_b = sum(d.get("bright", 0) for d in detector_summaries)
    n_tot = n_f + n_m + n_b
    hdr["NSTARS"] = (int(n_tot), "Total stars pooled across all tiers")
    hdr["NSTAR_F"] = (int(n_f), "Stars in faint tier")
    hdr["NSTAR_M"] = (int(n_m), "Stars in medium tier")
    hdr["NSTAR_B"] = (int(n_b), "Stars in bright tier")

    # Scale factors
    k_fm = diagnostics.get("k_fm", 1.0)
    k_mb = diagnostics.get("k_mb", 1.0)
    hdr["SCALE_FM"] = (float(k_fm) if k_fm is not None else 1.0, "Faint-to-Medium scale factor k_FM")
    hdr["SCALE_MB"] = (float(k_mb) if k_mb is not None else 1.0, "Medium-to-Bright scale factor k_MB")

    # Spike angles and orientation
    base_ang_str = ",".join(f"{a:.2f}" for a in ROMAN_BASE_SPIKE_ANGLES_DEG)
    hdr["BASE_ANG"] = (base_ang_str, "Base spike angles (deg)")
    hdr["DET_OFF"] = (float(NOMINAL_DETECTOR_OFFSET_DEG), "Detector alignment clocking offset (deg)")

    mean_pa = float(np.mean([d.get("pa_aperture", -110.0) for d in detector_summaries])) if detector_summaries else -110.0
    hdr["PA_APER"] = (mean_pa, "Mean aperture position angle (deg)")
    net_rot = (mean_pa + NOMINAL_DETECTOR_OFFSET_DEG) % 360.0
    hdr["NET_ROT"] = (float(net_rot), "Net spike rotation angle (deg)")

    # Diagnostics & Provenance
    tot_flux = diagnostics.get("total_flux_raw", 1.0)
    hdr["TOTALFLX"] = (float(tot_flux), "Pre-normalization integrated total flux")
    hdr["NORM"] = ("UNIT_FLUX", "Flux normalization status")
    hdr["PROV_VER"] = (str(__version__), "Roman ePSF pipeline version")
    hdr["DATE_UTC"] = (datetime.now(timezone.utc).isoformat(), "FITS creation UTC timestamp")

    # 2. Secondary HDU: COVERAGE Map
    cf = diagnostics.get("cov_faint")
    cm = diagnostics.get("cov_medium")
    cb = diagnostics.get("cov_bright")
    cov_canvas = np.zeros((S, S), dtype=np.int32)
    if cf is not None:
        cov_canvas += _embed_or_crop_canvas(cf, S).astype(np.int32)
    if cm is not None:
        cov_canvas += _embed_or_crop_canvas(cm, S).astype(np.int32)
    if cb is not None:
        cov_canvas += _embed_or_crop_canvas(cb, S).astype(np.int32)

    cov_hdu = fits.ImageHDU(data=cov_canvas, name="COVERAGE")
    cov_hdu.header["BUNIT"] = ("STAR_COUNT", "Number of valid stars per pixel")

    # 3. Secondary HDU: RADIAL_PROFILES
    r_max = int((S - 1) // 2)
    radii = np.arange(1.0, min(r_max, 500) + 1.0, 1.0)
    r_c, prof_c = measure_radial_profile_1d(composite_epsf, rmax=int(radii[-1]))[:2]

    prof_dict = {
        "RADIUS_PX": radii,
        "RADIUS_ARCSEC": radii * pixel_scale,
        "FLUX_COMPOSITE": np.interp(radii, r_c, prof_c, right=0.0),
    }
    if diagnostics.get("r_f") is not None and diagnostics.get("prof_f") is not None:
        prof_dict["FLUX_FAINT"] = np.interp(radii, diagnostics["r_f"], diagnostics["prof_f"], right=np.nan)
    if diagnostics.get("r_m") is not None and diagnostics.get("prof_m_scaled") is not None:
        prof_dict["FLUX_MED_SCALED"] = np.interp(radii, diagnostics["r_m"], diagnostics["prof_m_scaled"], right=np.nan)
    if diagnostics.get("r_b") is not None and diagnostics.get("prof_b") is not None:
        b_scaled = diagnostics["prof_b"] * (k_mb if k_mb is not None else 1.0)
        prof_dict["FLUX_BRIGHT_SCALED"] = np.interp(radii, diagnostics["r_b"], b_scaled, right=np.nan)

    prof_table = Table(prof_dict)
    prof_hdu = fits.BinTableHDU(prof_table, name="RADIAL_PROFILES")

    # 4. Secondary HDU: DETECTOR_SUMMARY
    det_rows = {
        "DETECTOR": [str(d["detector"]) for d in detector_summaries],
        "N_FAINT": [int(d.get("faint", 0)) for d in detector_summaries],
        "N_MEDIUM": [int(d.get("medium", 0)) for d in detector_summaries],
        "N_BRIGHT": [int(d.get("bright", 0)) for d in detector_summaries],
        "N_TOTAL": [int(d.get("total", 0)) for d in detector_summaries],
        "PA_APER_DEG": [float(d.get("pa_aperture", 0.0)) for d in detector_summaries],
        "PIXSCALE": [float(d.get("pixel_scale", pixel_scale)) for d in detector_summaries],
        "TIME_SEC": [float(d.get("time_s", 0.0)) for d in detector_summaries],
        "STATUS": [str(d.get("status", "SUCCESS")) for d in detector_summaries],
    }
    det_table = Table(det_rows)
    det_hdu = fits.BinTableHDU(det_table, name="DETECTOR_SUMMARY")

    hdul = fits.HDUList([primary_hdu, cov_hdu, prof_hdu, det_hdu])
    hdul.writeto(target_path, overwrite=True)
    return target_path
```

### 4.2 Multi-Detector Stamp Pooling & Execution Runner (`run_pipeline`)
To be defined in `src/romanepsf/pipeline.py`:

```python
import gc
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd

from romanepsf.config import Config, load_config, resolve_device
from romanepsf.loader import load_l2_image
from romanepsf.catalog import (
    sanitize_source_catalog,
    project_catalog_to_pixels,
    refine_stellar_centroids,
    filter_isolated_stars,
    assign_stellar_tiers,
)
from romanepsf.stamps import process_star_stamps, StellarStamp
from romanepsf.assembly import assemble_composite_extended_psf

logger = logging.getLogger("romanepsf.pipeline")


@dataclass
class PipelineOutputs:
    """Output container for end-to-end 18-detector pipeline execution."""
    composite_epsf: np.ndarray
    fits_path: Path
    diagnostics: Dict[str, Any]
    detector_summaries: List[Dict[str, Any]]
    pooled_stamps: Dict[str, List[StellarStamp]]


def run_pipeline(
    cfg: Union[Config, Path, str, None] = None,
    detectors_dir: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    canvas_size: Optional[int] = None,
    device: Optional[str] = None,
    detectors: Optional[List[str]] = None,
) -> PipelineOutputs:
    """
    Execute full end-to-end 18-detector pipeline:
    1. Ingest and sanitize catalog once.
    2. Sequentially process all 18 SCAs, isolating stars and extracting stamps.
    3. Pool stamps globally across all 18 SCAs into Faint, Medium, and Bright tiers.
    4. Assemble 2D composite extended PSF with cross-tier scaling and cosine blending.
    5. Serialize 4-HDU FITS output with metadata and diagnostic tables.
    """
    if cfg is None or isinstance(cfg, (str, Path)):
        cfg = load_config(cfg)

    # Apply runtime parameter overrides
    if detectors_dir is not None:
        cfg.data.detectors_dir = Path(detectors_dir)
    if catalog_path is not None:
        cfg.data.catalog_path = Path(catalog_path)
    if output_dir is not None:
        cfg.data.output_dir = Path(output_dir)
    if canvas_size is not None:
        cfg.assembly.canvas_size = canvas_size
    if device is not None:
        cfg.environment.device = device
    if detectors is not None:
        cfg.data.detectors = detectors

    cfg.validate()
    cfg.data.output_dir.mkdir(parents=True, exist_ok=True)
    torch_dev = cfg.get_torch_device()

    # Determine detector list
    det_list = cfg.data.detectors
    if len(det_list) == 1 and det_list[0].lower() == "all":
        det_list = [f"wfi{i:02d}" for i in range(1, 19)]

    logger.info(f"Starting 18-detector pipeline execution across {len(det_list)} detectors.")

    # 1. Catalog ingestion & sanitization
    logger.info(f"Loading source catalog from {cfg.data.catalog_path}")
    raw_df = pd.read_csv(cfg.data.catalog_path, low_memory=False)
    clean_df = sanitize_source_catalog(raw_df, mag_col=cfg.catalog.mag_col)
    del raw_df

    # 2. Multi-detector extraction loop
    pooled_stamps: Dict[str, List[StellarStamp]] = {"bright": [], "medium": [], "faint": []}
    detector_summaries: List[Dict[str, Any]] = []

    for det in det_list:
        t0 = time.time()
        det_lower = det.lower()
        asdf_matches = list(cfg.data.detectors_dir.glob(f"*{det_lower}*f146_cal.asdf"))
        if not asdf_matches:
            logger.warning(f"No ASDF file found for detector {det_lower} in {cfg.data.detectors_dir}")
            detector_summaries.append({
                "detector": det_lower, "faint": 0, "medium": 0, "bright": 0,
                "total": 0, "status": "FILE_NOT_FOUND"
            })
            continue

        asdf_file = asdf_matches[0]
        try:
            # Lazy load ASDF
            l2_data = load_l2_image(str(asdf_file), calibrate=True)
            proj_df = project_catalog_to_pixels(
                l2_data=l2_data, catalog_df=clean_df,
                margin_px=cfg.catalog.edge_margin_px,
                tolerance_arcsec=cfg.catalog.roundtrip_tolerance_arcsec,
            )
            ref_df = refine_stellar_centroids(l2_data, proj_df, box_radius=cfg.catalog.centroid_refine_box_px)
            iso_df = filter_isolated_stars(
                ref_df, pixel_scale=l2_data.pixel_scale,
                safety_factor=cfg.catalog.isolation_safety_factor,
            )
            tiered_df = assign_stellar_tiers(
                iso_df, bright_limit=cfg.tiers.bright_limit,
                faint_limit=cfg.tiers.faint_limit, mag_col=cfg.catalog.mag_col,
            )

            # Extract stamps with dual-prior spike protection
            stamps = process_star_stamps(l2_data, tiered_df, cfg.spikes, cfg.stamps)

            n_f = len(stamps["faint"])
            n_m = len(stamps["medium"])
            n_b = len(stamps["bright"])

            for tier in ["bright", "medium", "faint"]:
                pooled_stamps[tier].extend(stamps[tier])

            dt = time.time() - t0
            detector_summaries.append({
                "detector": det_lower,
                "faint": n_f,
                "medium": n_m,
                "bright": n_b,
                "total": n_f + n_m + n_b,
                "pa_aperture": l2_data.pa_aperture,
                "pixel_scale": l2_data.pixel_scale,
                "time_s": dt,
                "status": "SUCCESS" if n_b > 0 else "NO_BRIGHT",
            })
            logger.info(f"{det_lower.upper()}: Extracted F={n_f}, M={n_m}, B={n_b} in {dt:.2f}s")

            # Prompt memory cleanup
            del l2_data, proj_df, ref_df, iso_df, tiered_df, stamps
            gc.collect()

        except Exception as e:
            logger.error(f"Error processing detector {det_lower}: {e}")
            detector_summaries.append({
                "detector": det_lower, "faint": 0, "medium": 0, "bright": 0,
                "total": 0, "status": f"FAILED: {str(e)[:30]}"
            })

    # 3. Global composite canvas assembly
    logger.info(
        f"Assembling composite extended PSF from pooled stamps: "
        f"Bright={len(pooled_stamps['bright'])}, Medium={len(pooled_stamps['medium'])}, Faint={len(pooled_stamps['faint'])}"
    )
    composite_epsf, diagnostics = assemble_composite_extended_psf(
        tier_stamps=pooled_stamps,
        output_size=cfg.assembly.canvas_size,
        cfg=cfg.assembly,
        device=torch_dev,
    )

    # 4. Serialize FITS output
    out_fits = cfg.data.output_dir / "roman_epsf_composite.fits"
    from romanepsf.assembly import serialize_composite_epsf_fits
    serialize_composite_epsf_fits(
        composite_epsf=composite_epsf,
        diagnostics=diagnostics,
        detector_summaries=detector_summaries,
        output_fits_path=out_fits,
        filter_name=cfg.data.filter_name,
        pixel_scale=0.11,
    )
    logger.info(f"Composite extended PSF FITS successfully written to {out_fits}")

    return PipelineOutputs(
        composite_epsf=composite_epsf,
        fits_path=out_fits,
        diagnostics=diagnostics,
        detector_summaries=detector_summaries,
        pooled_stamps=pooled_stamps,
    )
```

### 4.3 Proposed CLI Changes in `src/romanepsf/cli.py`
Replace `run_command` in `src/romanepsf/cli.py` with:

```python
@cli.command("run", help="Execute complete end-to-end ePSF measurement pipeline across all 18 detectors.")
@click.option(
    "--input-dir",
    "-i",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory containing Level 2 ASDF detector files.",
)
@click.option(
    "--catalog",
    "-cat",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to precomputed source catalog CSV.",
)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to YAML configuration file.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to store synthesized models, FITS outputs, and reports.",
)
@click.option(
    "--canvas-size",
    "-s",
    type=int,
    default=None,
    help="Composite ePSF canvas dimension (e.g. 1025 or 2049). Default: 1025.",
)
@click.option(
    "--device",
    "-d",
    type=click.Choice(["auto", "mps", "cuda", "cpu"], case_sensitive=False),
    default=None,
    help="Compute device for PyTorch operations ('auto', 'mps', 'cuda', 'cpu').",
)
@click.option(
    "--detectors",
    default=None,
    help="Comma-separated detectors list (e.g. 'wfi01,wfi02') or 'all'.",
)
@click.option(
    "--num-workers",
    "-w",
    type=int,
    default=None,
    help="Number of parallel worker processes.",
)
@click.pass_context
def run_command(
    ctx: click.Context,
    input_dir: Optional[Path],
    catalog: Optional[Path],
    config: Optional[Path],
    output_dir: Optional[Path],
    canvas_size: Optional[int],
    device: Optional[str],
    detectors: Optional[str],
    num_workers: Optional[int],
):
    """Execute complete end-to-end ePSF pipeline across all designated detectors."""
    logger: logging.Logger = ctx.obj["logger"]
    if config is not None:
        cfg = load_config(config)
        ctx.obj["config"] = cfg
    else:
        cfg: Config = ctx.obj["config"]

    if input_dir is not None:
        cfg.data.detectors_dir = input_dir
    if catalog is not None:
        cfg.data.catalog_path = catalog
    if output_dir is not None:
        cfg.data.output_dir = output_dir
    if canvas_size is not None:
        cfg.assembly.canvas_size = canvas_size
    if device is not None:
        cfg.environment.device = device.lower()
        ctx.obj["device"] = resolve_device(cfg.environment.device)
    if num_workers is not None:
        cfg.environment.num_workers = num_workers
    if detectors is not None:
        if detectors.lower().strip() == "all":
            cfg.data.detectors = [f"wfi{i:02d}" for i in range(1, 19)]
        else:
            cfg.data.detectors = [d.strip().lower() for d in detectors.split(",") if d.strip()]

    try:
        cfg.validate()
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        sys.exit(1)

    logger.info(f"Starting pipeline execution across detectors: {cfg.data.detectors}")
    try:
        from romanepsf.pipeline import run_pipeline

        outputs = run_pipeline(cfg)
        logger.info(f"Pipeline completed successfully. FITS model saved to: {outputs.fits_path}")
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)
```

---

## 5. Verification Method

### 5.1 Unit Tests Specification (`tests/unit/test_assembly_m3.py` & `test_cli_m3.py`)

```python
import pytest
import numpy as np
from pathlib import Path
from astropy.io import fits
from click.testing import CliRunner

from romanepsf.cli import cli
from romanepsf.assembly import assemble_composite_extended_psf, serialize_composite_epsf_fits
from romanepsf.stamps import StellarStamp


def test_fits_output_serialization_structure(tmp_path):
    """Verify serialized FITS contains 4 HDUs with required header keywords."""
    S = 1025
    epsf = np.zeros((S, S), dtype=np.float32)
    epsf[512, 512] = 1.0
    diag = {
        "k_fm": 0.1936,
        "k_mb": 0.0255,
        "total_flux_raw": 100.0,
        "cov_faint": np.ones((81, 81), dtype=np.int32),
        "cov_medium": np.ones((201, 201), dtype=np.int32),
        "cov_bright": np.ones((1001, 1001), dtype=np.int32),
    }
    summaries = [
        {"detector": f"wfi{i:02d}", "faint": 4, "medium": 2, "bright": 1 if i not in [2, 3, 8, 13, 17, 18] else 0, "total": 7, "pa_aperture": -110.0, "pixel_scale": 0.11}
        for i in range(1, 19)
    ]
    out_fits = tmp_path / "test_epsf.fits"
    serialize_composite_epsf_fits(epsf, diag, summaries, out_fits)

    with fits.open(out_fits) as hdul:
        assert len(hdul) == 4
        assert hdul[0].name == "EPSF"
        assert hdul[1].name == "COVERAGE"
        assert hdul[2].name == "RADIAL_PROFILES"
        assert hdul[3].name == "DETECTOR_SUMMARY"

        # Check required primary header keywords
        hdr = hdul[0].header
        assert hdr["FILTER"] == "F146"
        assert hdr["PIXSCALE"] == 0.11
        assert hdr["NDET"] == 18
        assert hdr["NSTARS"] == sum(d["total"] for d in summaries)
        assert np.isclose(hdr["SCALE_FM"], 0.1936, atol=1e-3)
        assert np.isclose(hdr["SCALE_MB"], 0.0255, atol=1e-3)
        assert "BASE_ANG" in hdr
        assert "NET_ROT" in hdr
        assert "DATE_UTC" in hdr


def test_cli_run_options_parsing():
    """Verify CLI 'run' parses all options without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "--input-dir" in result.output
    assert "--catalog" in result.output
    assert "--canvas-size" in result.output
    assert "--device" in result.output
    assert "--output-dir" in result.output
```

### 5.2 Independent Terminal Verification Commands
Execute the following commands with `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:

1. **Verify Unit & E2E Tests**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/pytest tests/unit/test_cli.py tests/e2e/test_tier1_features.py -k "Feature08 or Feature21 or Feature20"
   ```

2. **Verify 18-Detector Sequential Pooling & Assembly Script**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   from romanepsf.config import load_config
   from romanepsf.pipeline import run_pipeline
   cfg = load_config('configs/default.yaml')
   cfg.data.detectors = ['all']
   outputs = run_pipeline(cfg)
   print('Generated FITS:', outputs.fits_path)
   assert outputs.fits_path.is_file()
   "
   ```

3. **Verify FITS HDU Structure via Astropy**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   from astropy.io import fits
   with fits.open('output/roman_epsf_composite.fits') as h:
       h.info()
       assert h[0].header['NDET'] == 18
       assert h[0].header['FILTER'] == 'F146'
   "
   ```

### 5.3 Invalidation Conditions
- If any FITS header keyword causes `HIERARCH` card warnings because it exceeds 8 characters.
- If $k_{\text{FM}}$ or $k_{\text{MB}}$ evaluates to $\le 0$, NaN, or infinity.
- If `assemble_composite_extended_psf` crashes when pooled across 18 detectors.
- If peak RSS memory during 18-detector execution exceeds 4 GB.
- If `romanepsf run` CLI rejects valid `--input-dir` or `--catalog` arguments.
