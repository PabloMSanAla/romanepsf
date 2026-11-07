# Handoff Report: Milestone 2 — Diffraction Spike Protection & Contaminant Masking (`src/romanepsf/masking.py`)

**Agent ID**: `explorer_m2_2`  
**Parent Agent**: `e80d314a-b5a0-43fb-be2e-ceabc982347e`  
**Target Path**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_2/handoff.md`  
**Timestamp**: 2026-11-06T10:26:00Z  

---

## 1. Observation

### 1.1 Existing Codebase Layout & Missing Canonical Module
- In `src/romanepsf/`, `config.py` (15,256 bytes), `loader.py` (12,266 bytes), `catalog.py` (23,130 bytes), and `cli.py` (18,521 bytes) exist.
- Noticeably, `src/romanepsf/masking.py` **does not exist**; an initial implementation file exists directly at `src/masking.py` (9,974 bytes).
- Standard pattern established in Milestone 1:
  - Canonical implementation lives under `src/romanepsf/<module>.py`.
  - Re-export shim lives at top-level `src/<module>.py` (e.g. `src/catalog.py` line 5: `from romanepsf.catalog import ...`, `src/loader.py` line 5: `from romanepsf.loader import ...`).
- In `src/romanepsf/__init__.py`, exports are present for `config`, `loader`, and `catalog`, but `masking` is not yet imported or exported.

### 1.2 Pupil Spider Geometry & Spike Angles
- Secondary mirror support structure of the Roman Space Telescope aperture has 6 struts.
- Base angles relative to WFI aperture frame are:
  `ROMAN_BASE_SPIKE_ANGLES_DEG = [23.55, 55.29, 80.25, 118.65, 142.88, 178.07]` (degrees).
- Each strut generates two opposing rays separated by $180^\circ$:
  $\theta_{\text{opp}} = (\theta_{\text{base}} + 180^\circ) \pmod{360^\circ}$, yielding 12 radial spike directions.
- In `tests/e2e/test_tier1_features.py` (lines 626–675):
  - `test_f12_01_generates_12_rays`: `masking.get_theoretical_spike_angles(0.0)` produces 12 angles.
  - `test_f12_02_detector_offset_minus_9_7_deg`: With detector alignment offset $-9.70^\circ$, rotated angles modulo $180^\circ$ match `[13.85, 45.59, 70.55, 108.95, 133.18, 168.37]` degrees.
  - `test_f12_03_modulo_180_opposing_symmetry`: Every ray $\theta$ has an opposing counterpart at $(\theta + 180^\circ) \pmod{360^\circ}$.
- In `tests/e2e/test_tier2_boundaries.py` (lines 535–554):
  - `test_b10_01_rotation_by_360_degrees`: `get_theoretical_spike_angles(0.0) == get_theoretical_spike_angles(360.0)`.
  - `test_b10_02_negative_angle_wrapping`: All angles wrapped in $[0, 360)$.
  - `test_b10_03_aperture_pa_extremes`: Rotations of $-180^\circ$ and $+180^\circ$ yield identical sorted sets.

### 1.3 Geometric Spike Protection Masks
- In `tests/e2e/test_tier1_features.py` (lines 653–675) & `tests/e2e/test_tier2_boundaries.py` (lines 555–572):
  - `create_geometric_spike_mask(shape, center, angles, angular_half_width_deg=4.0, radial_min=3.0, spike_width_px=4.0)`:
    - Angular cone: $\Delta\theta \le \theta_{\text{half\_width}}$ (default $4.0^\circ$).
    - Linear corridor: $d_\perp = |-\sin(\theta) dx + \cos(\theta) dy| \le w_{\text{spike}}$ (default $4.0$ px).
    - Radial boundary: pixels with $r < r_{\text{min}}$ are **omitted** (reserved for core protection).
    - Pixel at $(cx, cy)$ is never masked by `create_geometric_spike_mask`.
    - Both `spike_width_px` (0.5 vs 8.0) and `angular_half_width_deg` (1.0 vs 10.0) produce monotonic coverage scaling.

### 1.4 High-Aspect-Ratio Directional Morphological Filtering
- In `tests/e2e/test_tier1_features.py` (lines 679–736) & `tests/e2e/test_tier2_boundaries.py` (lines 575–622):
  - `fit_moffat_model(stamp, dq_mask=None, max_radius=None) -> (fitted_image, fitted_model)`:
    - Uses `astropy.modeling.models.Moffat2D` with $\alpha \approx 1.52$, $\gamma \approx 2.5$, bounded center within $\pm 5$ px.
    - Fits stellar core to isolate smooth circularly symmetric profile.
    - Benchmarking test: on $1001 \times 1001$ stamp with `max_radius=200`, LevMarLSQFitter converges in **0.186 seconds**.
  - `detect_morphological_spikes(data, center, threshold_sigma=2.0, min_length_px=15) -> np.ndarray[bool]`:
    - Estimates background noise $bkg\_med, bkg\_std$ from outer ring ($r > \text{80th percentile}$).
    - Flags bright pixels $> bkg\_med + \text{threshold\_sigma} \times bkg\_std$.
    - Clamps inner radius: pixels with $r < 5.0$ px are excluded (`test_b11_05`).
    - Discriminate by aspect ratio: connected components must have radial span $\Delta r = \max(r) - \min(r) \ge \text{min\_length\_px}$ (default 15 px).
    - Rejects compact circular companion stars (e.g. Gaussian/Moffat blobs of FWHM 3 px, `test_f13_02`).
    - Rejects short lines $< 15$ px (`test_b11_01`), detects lines $\ge 15$ px (`test_b11_02`).
    - Handles flat images with $bkg\_std == 0$ without `ZeroDivisionError` (`test_b11_03`).
    - Dilates detected spikes by 2 iterations to ensure full width coverage.

### 1.5 Interface Contract Gap in Existing `src/masking.py`
- Verbatim execution test:
  ```python
  from romanepsf.config import SpikesConfig
  from src.masking import mask_contaminants_with_spikes_protected
  mask_contaminants_with_spikes_protected(data, None, 30.0, SpikesConfig())
  ```
  Result:
  ```
  FAILED: TypeError: '<=' not supported between instances of 'float' and 'SpikesSection'
  ```
- **Direct Cause**:
  `src/masking.py` line 211 defines:
  ```python
  def mask_contaminants_with_spikes_protected(
      stamp: np.ndarray,
      dq_mask: Optional[np.ndarray],
      pa_offset_deg: float = 0.0,
      core_protection_radius_px: float = 6.0,
      detection_sigma: float = 3.0,
  )
  ```
  When invoked according to the authoritative contract:
  `mask_contaminants_with_spikes_protected(stamp, dq_mask, pa_aperture, cfg: SpikesConfig)`
  the 4th positional argument `cfg` maps to `core_protection_radius_px`, triggering a crash on line 258: `(r <= core_protection_radius_px)`.

---

## 2. Logic Chain

### Step 1: Telescope Optics to Angle Transform
1. The secondary mirror struts are fixed at physical angles:
   $$\Theta_{\text{base}} = [23.55^\circ, 55.29^\circ, 80.25^\circ, 118.65^\circ, 142.88^\circ, 178.07^\circ]$$
2. For each base angle, diffraction creates a 2D line through the star centroid, producing two opposite rays: $\theta_k$ and $(\theta_k + 180^\circ) \pmod{360^\circ}$, yielding 12 rays in total.
3. The WFI focal plane detector arrays are mounted at a fixed clocking angle offset $\Delta\theta_{\text{det}} \approx -9.70^\circ$ relative to the aperture reference axis (specified in `config.spikes.detector_alignment_offset_deg = -9.70`).
4. In detector pixel coordinates, the 12 spike rays are rotated by the net rotation:
   $$\theta_{\text{net}} = pa_{\text{aperture}} + \Delta\theta_{\text{det}}$$
   or directly by `pa_offset_deg` if specified in legacy callers.
5. All resulting angles must be normalized via modulo arithmetic to $[0^\circ, 360^\circ)$ and returned in strictly sorted order.

### Step 2: High-Aspect-Ratio Ridge Detection vs. Stellar Profile
1. The extended stellar PSF consists of three spatial components:
   - Symmetric central core and inner wings ($r < 15\text{ px}$), modeled analytically by a 2D Moffat profile $I(r) = I_0 [1 + (r/\gamma)^2]^{-\alpha}$.
   - Linear diffraction spikes stretching radially outward across hundreds of pixels along the 12 pupil rays.
   - Non-star contaminants: neighbor stars, cosmic ray outliers, and bad detector pixels.
2. Subtracting the fitted 2D Moffat model removes the symmetric core, leaving residuals where:
   - Clean sky pixels follow zero-centered Gaussian noise.
   - Diffraction spikes appear as narrow, positive, linear ridges.
   - Neighbor companion stars appear as compact circular 2D Gaussian/Moffat peaks.
3. Morphological discrimination isolates linear ridges:
   - Core pixels ($r < 5.0\text{ px}$) are masked out to avoid Moffat subtraction ringing artifacts.
   - Connected components of pixels $> \text{threshold\_sigma} \times \sigma_{\text{bkg}}$ are extracted.
   - Radial extent $\Delta r = \max(r) - \min(r)$ measures the continuous radial length.
   - Spikes satisfy $\Delta r \ge 15\text{ px}$ with low angular spread ($\sigma_\theta < 20^\circ$), whereas compact neighbor stars have $\Delta r < 10\text{ px}$ and are excluded from spike detection.
   - Binary dilation (radius 2 px) ensures that the flanks of diffraction spikes are fully covered.

### Step 3: Dual-Prior Fusion and Invariant Protection
1. Theoretical prior $M_{\text{geom}}$ provides an immutable geometric safety net even in low signal-to-noise wings.
2. Empirical prior $M_{\text{morph}}$ captures real aberrations, optical distortion, and slight field-dependent alignment shifts.
3. Core protection $M_{\text{core}} = (r \le r_{\text{core\_prot}})$ protects the inner star core from being zeroed or hollowed out.
4. Total protected stellar area:
   $$M_{\text{protected}} = M_{\text{geom}} \cup M_{\text{morph}} \cup M_{\text{core}}$$
5. Contaminant detection evaluates residuals in the clean background ($r \notin M_{\text{protected}}$ and $dq == 0$):
   - Computes robust background statistics via Median and Median Absolute Deviation ($\sigma_{\text{MAD}} = 1.4826 \times \text{MAD}$).
   - Identifies candidate contaminant pixels $> \text{detection\_sigma} \times \sigma_{\text{MAD}}$.
   - Dilates candidate contaminants by 1 iteration to cover stellar wings.
6. **Strict Invariant**:
   $$\text{Contaminants}_{\text{final}} = \text{Contaminants}_{\text{candidate}} \setminus M_{\text{protected}}$$
   $$\text{FinalMask} = \text{Contaminants}_{\text{final}} \cup \text{DQ}_{\text{bad}} \cup \text{NonFinite}$$
   This guarantees that no valid core or spike pixels are ever masked out as contaminants, while extraneous companion stars and bad pixels are rigorously masked.

### Step 4: Interface Contract Harmonization
1. To satisfy both `PROJECT.md` line 82 (`mask_contaminants_with_spikes_protected(stamp, dq_mask, pa_aperture, cfg)`) and the 33 existing tests that invoke keyword or legacy arguments:
2. The function signature must accept:
   ```python
   def mask_contaminants_with_spikes_protected(
       stamp: np.ndarray,
       dq_mask: Optional[np.ndarray] = None,
       pa_aperture: Optional[Union[float, SpikesConfig, SpikesSection]] = None,
       cfg: Optional[Union[SpikesConfig, SpikesSection, float]] = None,
       *,
       pa_offset_deg: Optional[float] = None,
       core_protection_radius_px: Optional[float] = None,
       detection_sigma: Optional[float] = None,
       tier: Optional[str] = None,
   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
   ```
3. Type dispatch resolves:
   - If `isinstance(cfg, (SpikesConfig, SpikesSection))`: extract parameters from config dataclass.
   - If `isinstance(pa_aperture, (SpikesConfig, SpikesSection))`: handle swapped argument call.
   - If `isinstance(cfg, (int, float))`: handle legacy 4th positional argument `core_protection_radius_px`.
   - If `pa_offset_deg` is explicitly passed: use directly.
   - If `pa_aperture` is a float: compute `pa_aperture + cfg.detector_alignment_offset_deg`.
   - If `core_protection_radius_px` is None: resolve dynamically from `cfg.core_protection_radius_px` by `tier` ('bright': 6.0, 'medium': 4.0, 'faint': 3.0, default: 6.0).

---

## 3. Caveats

1. **Top-Level Shim vs. Canonical Package Location**:
   - `src/romanepsf/masking.py` must be the primary canonical implementation file.
   - `src/masking.py` must re-export all symbols to maintain backward compatibility with `tests/e2e/` and `src/stamps.py`.
2. **DQ Mask Bit Interpretation**:
   - In `masking.py`, `dq_mask` is treated as a boolean mask (`True = bad/saturated/do-not-use`).
   - Saturated core pixels in bright stars (where `stamp <= 0` or unphysical negative flags) are preserved in `final_mask` because `dq_mask` is OR-ed into `final_mask`.
   - Faint star finite core protection (`faint_core_protect_finite = True`) is handled in `stamps.py` by clearing DQ Bit 1 before calling `masking.py`, ensuring positive core flux is preserved.
3. **Moffat Fit Runtime on Very Large Bright Cutouts ($1001 \times 1001$)**:
   - Astropy's `LevMarLSQFitter` on $10^6$ pixels would take multiple seconds per star.
   - Restricting `max_radius = min(max(cx * 0.3, 20.0), 50.0)` guarantees the fit evaluates on $\le 8,000$ pixels, completing in $\approx 0.18$ seconds without sacrificing accuracy.

---

## 4. Conclusion & Complete Blueprints

### 4.1 Canonical Module Blueprint: `src/romanepsf/masking.py`

```python
"""
Diffraction Spike Protection and Non-Star Contaminant Masking for Roman Space Telescope WFI.

Implements dual-prior diffraction spike preservation:
1. Theoretical 6-fold pupil geometry angle priors:
   - Base angles: [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] degrees.
   - Rotated into detector pixel frame via aperture PA and detector alignment offset (-9.70 deg).
   - Angular wedge and constant-width corridor protection masks.
2. High-aspect-ratio directional morphological filtering:
   - Sub-pixel centered 2D Moffat profile core fitting.
   - Moffat subtraction to isolate residuals.
   - Aspect ratio and radial span discrimination rejecting compact companion stars.
3. Dual-prior fusion:
   - Fuses geometric cones, empirical ridge detections, and stellar core protection.
   - Identifies non-star contaminants (neighbor stars, cosmic rays) via robust MAD background statistics.
   - Strictly protects diffraction spikes and cores from contaminant masking.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import logging
import numpy as np
from astropy.modeling import fitting, models
from scipy.ndimage import binary_dilation, generate_binary_structure, label

from romanepsf.config import SpikesConfig, SpikesSection

logger = logging.getLogger("romanepsf.masking")

# Roman 6-fold secondary mirror support spider base angles (degrees) relative to WFI aperture frame
ROMAN_BASE_SPIKE_ANGLES_DEG: List[float] = [23.55, 55.29, 80.25, 118.65, 142.88, 178.07]
NOMINAL_DETECTOR_OFFSET_DEG: float = -9.70


def get_theoretical_spike_angles(
    pa_offset_deg: float = 0.0,
    detector_offset_deg: Optional[float] = None,
) -> np.ndarray:
    """
    Generate all 12 radial spike directions (6 struts x 2 opposing directions)
    adjusted for telescope aperture position angle and detector alignment.

    Parameters
    ----------
    pa_offset_deg : float, default 0.0
        Aperture position angle or net angle offset in degrees.
    detector_offset_deg : float, optional
        Detector frame clocking offset in degrees (nominal -9.70 deg).
        If provided, net rotation is pa_offset_deg + detector_offset_deg.

    Returns
    -------
    np.ndarray (float64, shape (12,))
        Array of 12 unique spike ray angles in degrees, in range [0, 360), strictly sorted.
    """
    net_offset = float(pa_offset_deg)
    if detector_offset_deg is not None:
        net_offset += float(detector_offset_deg)

    base = np.array(ROMAN_BASE_SPIKE_ANGLES_DEG, dtype=np.float64) + net_offset
    opposing = (base + 180.0) % 360.0
    all_angles = np.concatenate([base % 360.0, opposing])
    return np.unique(np.round(all_angles, 4))


def create_geometric_spike_mask(
    shape: Tuple[int, int],
    center: Tuple[float, float],
    angles_deg: np.ndarray,
    angular_half_width_deg: float = 4.0,
    radial_min: float = 3.0,
    spike_width_px: float = 4.0,
) -> np.ndarray:
    """
    Create a 2D boolean mask indicating theoretical diffraction spike corridors.

    Combines an angular wedge cone with a constant-width corridor along each ray.
    Excludes the central core (r < radial_min) which is handled by core protection.

    Parameters
    ----------
    shape : (height, width)
        Dimensions of stamp.
    center : (cx, cy)
        Stellar centroid in stamp pixel coordinates.
    angles_deg : np.ndarray
        Array of spike angles in degrees.
    angular_half_width_deg : float, default 4.0
        Angular tolerance cone around each spike direction.
    radial_min : float, default 3.0
        Radius below which spike masking is omitted.
    spike_width_px : float, default 4.0
        Half-width of the linear spike corridor in pixels.

    Returns
    -------
    np.ndarray (bool)
        True for pixels within the geometric spike protection zone.
    """
    height, width = shape
    cx, cy = center
    grid_y, grid_x = np.ogrid[:height, :width]
    dx = grid_x - cx
    dy = grid_y - cy

    r = np.sqrt(dx**2 + dy**2)
    theta = np.degrees(np.arctan2(dy, dx)) % 360.0

    spike_mask = np.zeros(shape, dtype=bool)

    for ang in angles_deg:
        ang_norm = float(ang) % 360.0
        # Angular difference taking periodic boundary into account
        diff = np.abs((theta - ang_norm + 180.0) % 360.0 - 180.0)
        # Distance perpendicular to spike line
        ang_rad = np.radians(ang_norm)
        perp_dist = np.abs(-np.sin(ang_rad) * dx + np.cos(ang_rad) * dy)

        is_spike = (diff <= angular_half_width_deg) | (perp_dist <= spike_width_px)
        spike_mask |= (is_spike & (r >= radial_min))

    return spike_mask


def detect_morphological_spikes(
    data: np.ndarray,
    center: Tuple[float, float],
    threshold_sigma: float = 2.0,
    min_length_px: int = 15,
    dilation_iterations: int = 2,
) -> np.ndarray:
    """
    Detect continuous radial linear features (diffraction spikes) in 2D residual or flux data.

    Discriminates spikes from compact circular companion stars based on radial extent
    and directional alignment.

    Parameters
    ----------
    data : np.ndarray
        2D flux or residual array.
    center : (cx, cy)
        Stellar centroid in stamp pixel coordinates.
    threshold_sigma : float, default 2.0
        Significance threshold above local background.
    min_length_px : int, default 15
        Minimum radial continuous span in pixels to be classified as a spike.
    dilation_iterations : int, default 2
        Morphological dilation iterations applied to detected spikes.

    Returns
    -------
    np.ndarray (bool)
        Boolean mask of detected empirical spike ridges.
    """
    height, width = data.shape
    cx, cy = center
    grid_y, grid_x = np.indices((height, width))
    dx = grid_x - cx
    dy = grid_y - cy
    r = np.sqrt(dx**2 + dy**2)

    # Estimate background noise from outer ring
    outer_pixels = data[r > np.percentile(r, 80)]
    valid = outer_pixels[np.isfinite(outer_pixels)]
    if len(valid) > 10:
        bkg_med = float(np.median(valid))
        bkg_std = float(np.std(valid, ddof=0))
    else:
        bkg_med, bkg_std = 0.0, 1.0

    if bkg_std <= 0.0:
        bkg_std = 1.0

    # High signal features (suppress inner core r < 5.0 px)
    bright_pixels = (data - bkg_med) > (threshold_sigma * bkg_std)
    bright_pixels &= (r >= 5.0) & np.isfinite(data)

    if not np.any(bright_pixels):
        return np.zeros_like(bright_pixels, dtype=bool)

    # Label contiguous components
    s = generate_binary_structure(2, 2)
    labeled, num_features = label(bright_pixels, structure=s)

    spike_mask = np.zeros_like(bright_pixels, dtype=bool)

    for feat_id in range(1, num_features + 1):
        feat_mask = (labeled == feat_id)
        feat_r = r[feat_mask]
        if feat_r.size == 0:
            continue
        radial_span = float(np.ptp(feat_r))
        # Spikes must span at least min_length_px radially
        if radial_span >= min_length_px:
            feat_dy = dy[feat_mask]
            feat_dx = dx[feat_mask]
            feat_angles = np.degrees(np.arctan2(feat_dy, feat_dx)) % 360.0
            ang_spread = float(np.std(feat_angles))
            # True spikes have narrow angular spread or very large radial span
            if ang_spread < 20.0 or radial_span >= 25.0:
                spike_mask |= feat_mask

    if np.any(spike_mask) and dilation_iterations > 0:
        spike_mask = binary_dilation(spike_mask, iterations=dilation_iterations)

    return spike_mask


def fit_moffat_model(
    stamp: np.ndarray,
    dq_mask: Optional[np.ndarray] = None,
    max_radius: Optional[float] = None,
) -> Tuple[np.ndarray, Any]:
    """
    Fit a 2D circularly symmetric Moffat profile to the stellar core.

    Parameters
    ----------
    stamp : np.ndarray
        2D stamp flux array.
    dq_mask : np.ndarray, optional
        Boolean mask of invalid/saturated pixels (True = bad).
    max_radius : float, optional
        Maximum radius from stamp center included in fit (limits computation on large stamps).

    Returns
    -------
    Tuple[np.ndarray, Any]
        (fitted_image, fitted_model)
    """
    ny, nx = stamp.shape
    cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
    grid_y, grid_x = np.mgrid[:ny, :nx]
    r = np.sqrt((grid_x - cx)**2 + (grid_y - cy)**2)

    valid = np.isfinite(stamp)
    if dq_mask is not None:
        valid &= (~dq_mask)
    if max_radius is not None:
        valid &= (r <= max_radius)

    if not np.any(valid):
        return np.zeros_like(stamp, dtype=np.float32), None

    outer = valid & (r > np.percentile(r[valid], 75))
    bkg = float(np.median(stamp[outer])) if np.any(outer) else 0.0

    peak_val = float(np.nanmax(stamp[valid])) - bkg

    init_moffat = models.Moffat2D(
        amplitude=max(peak_val, 1.0),
        x_0=float(cx),
        y_0=float(cy),
        gamma=2.5,
        alpha=1.52,
    )
    init_moffat.x_0.bounds = (cx - 5.0, cx + 5.0)
    init_moffat.y_0.bounds = (cy - 5.0, cy + 5.0)
    init_moffat.amplitude.bounds = (0.0, None)
    init_moffat.gamma.bounds = (0.5, 20.0)
    init_moffat.alpha.bounds = (1.1, 4.0)

    fitter = fitting.LevMarLSQFitter()
    try:
        weights = 1.0 / np.sqrt(np.clip(stamp[valid] + max(bkg, 0.0) + 1.0, 1.0, None))
        fitted = fitter(init_moffat, grid_x[valid], grid_y[valid], stamp[valid] - bkg, weights=weights)
        fitted_image = (fitted(grid_x, grid_y) + bkg).astype(np.float32)
        return fitted_image, fitted
    except Exception:
        fallback_img = (init_moffat(grid_x, grid_y) + bkg).astype(np.float32)
        return fallback_img, init_moffat


def mask_contaminants_with_spikes_protected(
    stamp: np.ndarray,
    dq_mask: Optional[np.ndarray] = None,
    pa_aperture: Optional[Union[float, SpikesConfig, SpikesSection]] = None,
    cfg: Optional[Union[SpikesConfig, SpikesSection, float]] = None,
    *,
    pa_offset_deg: Optional[float] = None,
    core_protection_radius_px: Optional[float] = None,
    detection_sigma: Optional[float] = None,
    tier: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Mask non-stellar contaminants in stamp while strictly protecting Roman diffraction spikes and core.

    Harmonizes both the authoritative pipeline contract:
      `mask_contaminants_with_spikes_protected(stamp, dq_mask, pa_aperture, cfg)`
    and legacy caller signatures:
      `mask_contaminants_with_spikes_protected(stamp, dq_mask, pa_offset_deg, core_protection_radius_px, ...)`

    Parameters
    ----------
    stamp : np.ndarray
        2D stamp flux image.
    dq_mask : np.ndarray, optional
        Pre-existing DQ bad-pixel mask (True = bad).
    pa_aperture : float or SpikesConfig, optional
        Telescope aperture position angle in degrees, or SpikesConfig instance.
    cfg : SpikesConfig or float, optional
        SpikesConfig configuration dataclass, or legacy core_protection_radius_px float.
    pa_offset_deg : float, optional
        Explicit rotation offset in degrees.
    core_protection_radius_px : float, optional
        Inner stellar core radius protected from contaminant masking.
    detection_sigma : float, optional
        Threshold above residual background to flag contaminants.
    tier : str, optional
        Stellar tier ('bright', 'medium', 'faint') for tier-dependent core radii.

    Returns
    -------
    Tuple[np.ndarray, np.ndarray, np.ndarray]
        (final_mask: bool[H, W], protected_area: bool[H, W], residual: float32[H, W])
    """
    # 1. Resolve configuration and parameter dispatch
    spikes_cfg: Optional[Union[SpikesConfig, SpikesSection]] = None
    if isinstance(cfg, (SpikesConfig, SpikesSection)):
        spikes_cfg = cfg
    elif isinstance(pa_aperture, (SpikesConfig, SpikesSection)):
        spikes_cfg = pa_aperture
        pa_aperture = None

    # Handle legacy 4th positional argument: cfg as float (core_protection_radius_px)
    if isinstance(cfg, (int, float)):
        if core_protection_radius_px is None:
            core_protection_radius_px = float(cfg)
        spikes_cfg = SpikesConfig()

    if spikes_cfg is None:
        spikes_cfg = SpikesConfig()

    # Resolve rotation angle
    if pa_offset_deg is not None:
        net_rotation = float(pa_offset_deg)
    elif isinstance(pa_aperture, (int, float)):
        det_off = float(getattr(spikes_cfg, "detector_alignment_offset_deg", NOMINAL_DETECTOR_OFFSET_DEG))
        net_rotation = float(pa_aperture) + det_off
    else:
        net_rotation = float(getattr(spikes_cfg, "detector_alignment_offset_deg", 0.0))

    # Resolve core protection radius
    if core_protection_radius_px is None:
        cpr = getattr(spikes_cfg, "core_protection_radius_px", None)
        if cpr is not None:
            if tier == "medium":
                core_protection_radius_px = float(getattr(cpr, "medium", 4.0))
            elif tier == "faint":
                core_protection_radius_px = float(getattr(cpr, "faint", 3.0))
            else:
                core_protection_radius_px = float(getattr(cpr, "bright", 6.0))
        else:
            core_protection_radius_px = 6.0
    else:
        core_protection_radius_px = float(core_protection_radius_px)

    # Resolve detection threshold
    if detection_sigma is None:
        detection_sigma = float(getattr(spikes_cfg, "contaminant_detection_sigma", 3.0))
    else:
        detection_sigma = float(detection_sigma)

    angular_half_width = float(getattr(spikes_cfg, "angular_half_width_deg", 4.0))
    spike_width = float(getattr(spikes_cfg, "spike_width_px", 4.0))

    morph_cfg = getattr(spikes_cfg, "morphological", None)
    morph_sigma = float(getattr(morph_cfg, "threshold_sigma", 2.0)) if morph_cfg else 2.0
    morph_length = int(getattr(morph_cfg, "min_length_px", 15)) if morph_cfg else 15
    morph_dil = int(getattr(morph_cfg, "dilation_iterations", 2)) if morph_cfg else 2

    ny, nx = stamp.shape
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    grid_y, grid_x = np.ogrid[:ny, :nx]
    r = np.sqrt((grid_x - cx)**2 + (grid_y - cy)**2)

    # 2. Fit Moffat model & compute residuals
    max_fit_r = min(max(cx * 0.3, 20.0), 50.0)
    moffat_img, _ = fit_moffat_model(stamp, dq_mask=dq_mask, max_radius=max_fit_r)
    residual = (stamp - moffat_img).astype(np.float32)

    # 3. Dual-prior spike protection
    spike_angles = get_theoretical_spike_angles(net_rotation)
    geom_spike_mask = create_geometric_spike_mask(
        (ny, nx),
        (cx, cy),
        spike_angles,
        angular_half_width_deg=angular_half_width,
        radial_min=max(core_protection_radius_px, 1.0),
        spike_width_px=spike_width,
    )

    morph_spike_mask = detect_morphological_spikes(
        stamp,
        (cx, cy),
        threshold_sigma=morph_sigma,
        min_length_px=morph_length,
        dilation_iterations=morph_dil,
    )

    spike_protection = geom_spike_mask | morph_spike_mask
    core_protection = (r <= core_protection_radius_px)
    protected_stellar_area = spike_protection | core_protection

    # 4. Detect extraneous non-star contaminants
    clean_area = ~protected_stellar_area
    if dq_mask is not None:
        clean_area &= (~dq_mask)

    valid_res = residual[clean_area & np.isfinite(residual)]
    if len(valid_res) > 20:
        res_med = float(np.median(valid_res))
        res_std = float(1.4826 * np.median(np.abs(valid_res - res_med)))
        if res_std <= 0.0:
            res_std = float(np.nanstd(valid_res)) or 1.0
    else:
        res_med = 0.0
        res_std = float(np.nanstd(residual)) if np.any(np.isfinite(residual)) else 1.0

    contaminants = (residual - res_med) > (detection_sigma * res_std)
    if np.any(contaminants):
        contaminants = binary_dilation(contaminants, iterations=1)

    # 5. Strict Invariant: Exclude protected spikes & core from contaminant mask
    contaminants &= (~protected_stellar_area)

    # 6. Assemble final mask
    final_mask = contaminants.copy()
    if dq_mask is not None:
        final_mask |= dq_mask
    final_mask |= (~np.isfinite(stamp))

    return final_mask, protected_stellar_area, residual


__all__ = [
    "ROMAN_BASE_SPIKE_ANGLES_DEG",
    "get_theoretical_spike_angles",
    "create_geometric_spike_mask",
    "detect_morphological_spikes",
    "fit_moffat_model",
    "mask_contaminants_with_spikes_protected",
]
```

---

### 4.2 Top-Level Re-Export Wrapper: `src/masking.py`

```python
"""
Backward-compatibility wrapper re-exporting from romanepsf.masking.
"""

from romanepsf.masking import (
    ROMAN_BASE_SPIKE_ANGLES_DEG,
    create_geometric_spike_mask,
    detect_morphological_spikes,
    fit_moffat_model,
    get_theoretical_spike_angles,
    mask_contaminants_with_spikes_protected,
)

__all__ = [
    "ROMAN_BASE_SPIKE_ANGLES_DEG",
    "create_geometric_spike_mask",
    "detect_morphological_spikes",
    "fit_moffat_model",
    "get_theoretical_spike_angles",
    "mask_contaminants_with_spikes_protected",
]
```

---

### 4.3 Unit Test Suite Blueprint: `tests/unit/test_masking.py`

```python
"""
Unit tests for romanepsf.masking: diffraction spike geometry, morphological filtering,
dual-prior spike protection, and contaminant masking.
"""

import numpy as np
import pytest
from romanepsf.config import SpikesConfig, SpikesSection
from romanepsf.masking import (
    ROMAN_BASE_SPIKE_ANGLES_DEG,
    create_geometric_spike_mask,
    detect_morphological_spikes,
    fit_moffat_model,
    get_theoretical_spike_angles,
    mask_contaminants_with_spikes_protected,
)


class TestTheoreticalSpikeAngles:
    """Tests for 6-fold pupil geometry and spider rotation transformations."""

    def test_base_angles_constant(self):
        expected = [23.55, 55.29, 80.25, 118.65, 142.88, 178.07]
        assert len(ROMAN_BASE_SPIKE_ANGLES_DEG) == 6
        np.testing.assert_allclose(ROMAN_BASE_SPIKE_ANGLES_DEG, expected, atol=1e-3)

    def test_generates_12_rays(self):
        angles = get_theoretical_spike_angles(0.0)
        assert len(angles) == 12
        assert np.all((angles >= 0.0) & (angles < 360.0))

    def test_opposing_symmetry(self):
        angles = get_theoretical_spike_angles(-9.70)
        for ang in angles:
            opp = (ang + 180.0) % 360.0
            assert np.any(np.isclose(angles, opp, atol=1e-3))

    def test_detector_offset_rotation(self):
        angles = get_theoretical_spike_angles(-9.70)
        base = np.array(ROMAN_BASE_SPIKE_ANGLES_DEG)
        expected_base_rot = (base - 9.70) % 180.0
        angles_mod_180 = np.unique(np.round(angles % 180.0, 2))
        np.testing.assert_allclose(np.sort(angles_mod_180), np.sort(expected_base_rot), atol=0.05)

    def test_pa_aperture_and_detector_offset_combined(self):
        angles = get_theoretical_spike_angles(pa_offset_deg=30.0, detector_offset_deg=-9.70)
        assert len(angles) == 12
        expected_first = (23.55 + 30.0 - 9.70) % 360.0
        assert np.any(np.isclose(angles, expected_first, atol=1e-2))

    def test_angle_wrapping_extremes(self):
        ang_pos = get_theoretical_spike_angles(720.0)
        ang_zero = get_theoretical_spike_angles(0.0)
        ang_neg = get_theoretical_spike_angles(-720.0)
        np.testing.assert_allclose(ang_pos, ang_zero, atol=1e-3)
        np.testing.assert_allclose(ang_neg, ang_zero, atol=1e-3)

    def test_monotonic_sorting(self):
        angles = get_theoretical_spike_angles(45.0)
        diffs = np.diff(angles)
        assert np.all(diffs > 0.0)


class TestGeometricSpikeMask:
    """Tests for 2D geometric cone and corridor spike masks."""

    def test_mask_shape_and_dtype(self):
        angles = get_theoretical_spike_angles(-9.70)
        mask = create_geometric_spike_mask((101, 101), (50.0, 50.0), angles)
        assert mask.shape == (101, 101)
        assert mask.dtype == bool

    def test_core_remains_clear(self):
        angles = get_theoretical_spike_angles(-9.70)
        mask = create_geometric_spike_mask((101, 101), (50.0, 50.0), angles, radial_min=8.0)
        assert not mask[50, 50]
        # All pixels within r < 8.0 should be False
        gy, gx = np.ogrid[:101, :101]
        r = np.sqrt((gx - 50.0)**2 + (gy - 50.0)**2)
        assert not np.any(mask[r < 8.0])

    def test_covers_spike_rays(self):
        angles = get_theoretical_spike_angles(-9.70)
        mask = create_geometric_spike_mask((201, 201), (100.0, 100.0), angles, radial_min=5.0)
        for ang in angles:
            rad = np.radians(ang)
            px = int(round(100.0 + 40.0 * np.cos(rad)))
            py = int(round(100.0 + 40.0 * np.sin(rad)))
            assert mask[py, px]

    def test_off_spike_pixels_unmasked(self):
        # A single horizontal spike at 0 deg
        mask = create_geometric_spike_mask((101, 101), (50.0, 50.0), np.array([0.0, 180.0]))
        # (50, 80) is on spike; (80, 50) is perpendicular to spike
        assert mask[50, 80]
        assert not mask[80, 50]

    def test_rectangular_cutout(self):
        angles = get_theoretical_spike_angles(0.0)
        mask = create_geometric_spike_mask((81, 161), (80.0, 40.0), angles)
        assert mask.shape == (81, 161)


class TestMoffatFitting:
    """Tests for stellar core 2D Moffat fitting and residual calculation."""

    def test_fit_synthetic_moffat_core(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.52).astype(np.float32)
        fitted_img, model = fit_moffat_model(star)
        assert model is not None
        assert abs(model.amplitude.value - 300.0) < 30.0

    def test_fit_ignores_saturated_dq_pixels(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (500.0 / (1.0 + (r / 2.5)**2)**1.52).astype(np.float32)
        # Corrupt central 3x3 with unphysical saturated value
        star[39:42, 39:42] = -9999.0
        dq = np.zeros((sz, sz), dtype=bool)
        dq[39:42, 39:42] = True

        fitted_img, model = fit_moffat_model(star, dq_mask=dq)
        assert model is not None
        # Should recover positive peak amplitude despite corrupted core
        assert model.amplitude.value > 100.0

    def test_fit_fallback_on_all_nan(self):
        nan_img = np.full((51, 51), np.nan, dtype=np.float32)
        fitted_img, model = fit_moffat_model(nan_img)
        assert fitted_img.shape == (51, 51)
        assert model is None


class TestMorphologicalRidgeFilter:
    """Tests for continuous directional ridge detection and contaminant rejection."""

    def test_detects_radial_linear_spike(self):
        sz = 101
        data = np.zeros((sz, sz), dtype=np.float32)
        data[50, 60:90] = 40.0  # Spike length 30 px
        detected = detect_morphological_spikes(data, (50.0, 50.0), min_length_px=15)
        assert np.any(detected[50, 65:85])

    def test_rejects_compact_circular_star(self):
        sz = 101
        gy, gx = np.ogrid[:sz, :sz]
        blob = 100.0 * np.exp(-((gx - 75)**2 + (gy - 75)**2) / (2 * 1.5**2))
        detected = detect_morphological_spikes(blob.astype(np.float32), (50.0, 50.0), min_length_px=15)
        assert not np.any(detected)

    def test_rejects_subthreshold_short_line(self):
        sz = 101
        data = np.zeros((sz, sz), dtype=np.float32)
        data[50, 60:71] = 40.0  # Length 11 px (< 15 threshold)
        detected = detect_morphological_spikes(data, (50.0, 50.0), min_length_px=15)
        assert not np.any(detected)

    def test_flat_background_zero_variance_handled(self):
        flat = np.full((81, 81), 10.0, dtype=np.float32)
        detected = detect_morphological_spikes(flat, (40.0, 40.0))
        assert not np.any(detected)


class TestDualPriorProtectionFusion:
    """Tests for invariant protection and contaminant masking."""

    def test_strict_invariant_clean_star(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (400.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(star, dq_mask=None)
        # Core is protected
        assert np.all(prot_area[r <= 4.0])
        # Core is never masked as contaminant
        assert not np.any(final_mask[r <= 4.0])

    def test_masks_off_axis_companion_star(self):
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (400.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        # Companion star at (80, 20)
        companion = (150.0 * np.exp(-((gx - 80)**2 + (gy - 20)**2) / (2 * 1.5**2))).astype(np.float32)
        stamp = star + companion

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(stamp, dq_mask=None)
        # Companion star is masked
        assert final_mask[20, 80]
        # Star core is not masked
        assert not final_mask[50, 50]

    def test_protects_spike_from_masking(self):
        sz = 101
        cx, cy = 50.0, 50.0
        stamp = np.full((sz, sz), 1.8, dtype=np.float32)
        # Add spike along 13.85 deg
        rad = np.radians(13.85)
        for d in range(15, 45):
            px = int(round(cx + d * np.cos(rad)))
            py = int(round(cy + d * np.sin(rad)))
            stamp[py, px] += 30.0

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(stamp, pa_offset_deg=-9.70)
        test_px = int(round(cx + 30.0 * np.cos(rad)))
        test_py = int(round(cy + 30.0 * np.sin(rad)))
        assert prot_area[test_py, test_px]
        assert not final_mask[test_py, test_px]

    def test_propagates_dq_bad_pixels(self):
        stamp = np.ones((51, 51), dtype=np.float32)
        dq = np.zeros((51, 51), dtype=bool)
        dq[10, 10] = True
        final_mask, _, _ = mask_contaminants_with_spikes_protected(stamp, dq_mask=dq)
        assert final_mask[10, 10]

    def test_masks_nans(self):
        stamp = np.ones((51, 51), dtype=np.float32)
        stamp[15, 15] = np.nan
        final_mask, _, _ = mask_contaminants_with_spikes_protected(stamp)
        assert final_mask[15, 15]


class TestInterfaceContract:
    """Tests verifying compliance with authoritative pipeline interface contract."""

    def test_interface_contract_with_spikes_config(self):
        cfg = SpikesConfig()
        stamp = np.ones((81, 81), dtype=np.float32)
        final_mask, prot_area, res = mask_contaminants_with_spikes_protected(
            stamp, dq_mask=None, pa_aperture=30.0, cfg=cfg
        )
        assert final_mask.shape == (81, 81)
        assert prot_area.shape == (81, 81)
        assert res.shape == (81, 81)
        assert final_mask.dtype == bool
        assert prot_area.dtype == bool

    def test_tier_based_core_protection(self):
        cfg = SpikesConfig()
        stamp = np.ones((81, 81), dtype=np.float32)
        _, prot_faint, _ = mask_contaminants_with_spikes_protected(stamp, cfg=cfg, tier="faint")
        _, prot_bright, _ = mask_contaminants_with_spikes_protected(stamp, cfg=cfg, tier="bright")
        # Bright core protection (6.0 px) covers more pixels than faint (3.0 px)
        assert np.sum(prot_bright) > np.sum(prot_faint)
```

---

## 5. Verification Method

To independently verify this investigation and the proposed implementation:

1. **Verify Existing E2E Feature & Boundary Tests**:
   Execute the 33 existing tests covering Features 12, 13, 14, and Boundaries 10, 11, 12 using the project Python environment:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier1_features.py -k "f12 or f13 or f14" -v
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier2_boundaries.py -k "b10 or b11 or b12" -v
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier3_combinations.py -k "pair_06 or pair_07 or pair_08" -v
   ```
   **Expected Outcome**: 33 passed, 0 failed.

2. **Verify Canonical Placement and Wrapper Execution**:
   Verify that placing the implementation at `src/romanepsf/masking.py` and the shim at `src/masking.py` allows both import paths to function identically:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   import romanepsf.masking as m1
   import src.masking as m2
   assert m1.ROMAN_BASE_SPIKE_ANGLES_DEG == m2.ROMAN_BASE_SPIKE_ANGLES_DEG
   print('Import verification passed')
   "
   ```

3. **Verify Contract Call with `SpikesConfig`**:
   Verify that the `TypeError` observed in Section 1.5 is resolved:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   import numpy as np
   from romanepsf.config import SpikesConfig
   from romanepsf.masking import mask_contaminants_with_spikes_protected
   fmask, prot, res = mask_contaminants_with_spikes_protected(np.ones((81, 81), dtype=np.float32), None, 30.0, SpikesConfig())
   assert fmask.shape == (81, 81)
   print('Contract test passed')
   "
   ```

4. **Verify Unit Test Suite Pass**:
   After creating `tests/unit/test_masking.py`:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_masking.py -v
   ```
   **Expected Outcome**: 26 passed, 0 failed.

5. **Invalidation Conditions**:
   - Any modification that causes `final_mask & protected_stellar_area` to evaluate to `True` for valid non-DQ pixels invalidates the core architectural invariant.
   - Any change to `get_theoretical_spike_angles` that breaks the 12-ray opposing 180-degree symmetry or sorting order invalidates downstream geometric masking.
   - Any change that breaks backward compatibility with legacy keyword arguments (`pa_offset_deg`, `core_protection_radius_px`, `detection_sigma`) invalidates existing E2E and integration tests.
