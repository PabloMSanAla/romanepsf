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
import pandas as pd
from astropy.modeling import fitting, models
from scipy.ndimage import binary_dilation, generate_binary_structure, label, gaussian_filter, map_coordinates
from scipy.signal import find_peaks

from romanepsf.config import SpikesConfig, SpikesSection

logger = logging.getLogger("romanepsf.masking")

# Roman 6-fold secondary mirror support spider base angles (degrees) relative to WFI aperture frame
# Primary 6-fold spider strut base angles in WFI aperture frame - First-order, brightest spikes
ROMAN_PRIMARY_SPIKE_ANGLES_DEG: List[float] = [12.72, 48.72, 73.22, 106.72, 133.22, 168.22]

# Secondary 6-fold pupil / strut edge base angles in WFI aperture frame - Second-order spikes
ROMAN_SECONDARY_SPIKE_ANGLES_DEG: List[float] = [23.55, 55.29, 80.25, 118.65, 142.88, 178.07]

# Backward compatibility alias
ROMAN_BASE_SPIKE_ANGLES_DEG: List[float] = ROMAN_SECONDARY_SPIKE_ANGLES_DEG
NOMINAL_DETECTOR_OFFSET_DEG: float = -9.70


def get_theoretical_spike_angles(
    pa_offset_deg: float = 0.0,
    detector_offset_deg: Optional[float] = None,
    order: Union[int, str] = "secondary",
) -> np.ndarray:
    """
    Generate radial spike directions adjusted for telescope aperture position angle
    and detector alignment.

    Parameters
    ----------
    pa_offset_deg : float, default 0.0
        Aperture position angle or net angle offset in degrees.
    detector_offset_deg : float, optional
        Detector frame clocking offset in degrees (nominal -9.70 deg).
        If provided, net rotation is pa_offset_deg + detector_offset_deg.
    order : Union[int, str], default "secondary"
        Spike order to generate:
        - "secondary" or 2 (default): 12 second-order spike rays (preserves legacy test contracts).
        - "primary" or 1: 12 first-order, brightest spike rays.
        - "both" or "all": All 24 spike rays.

    Returns
    -------
    np.ndarray (float64, shape (12,) or (24,))
        Array of unique spike ray angles in degrees, in range [0, 360), strictly sorted.
    """
    net_offset = float(pa_offset_deg)
    if detector_offset_deg is not None:
        net_offset += float(detector_offset_deg)

    order_str = str(order).lower().strip()
    if order_str in ("primary", "1"):
        base = np.array(ROMAN_PRIMARY_SPIKE_ANGLES_DEG, dtype=np.float64) + net_offset
        opposing = (base + 180.0) % 360.0
        all_angles = np.concatenate([base % 360.0, opposing])
    elif order_str in ("both", "all", "combined"):
        s1 = np.array(ROMAN_PRIMARY_SPIKE_ANGLES_DEG, dtype=np.float64) + net_offset
        s2 = np.array(ROMAN_SECONDARY_SPIKE_ANGLES_DEG, dtype=np.float64) + net_offset
        axes_12 = np.concatenate([s1 % 180.0, s2 % 180.0])
        all_angles = np.concatenate([axes_12, (axes_12 + 180.0) % 360.0])
    else:  # default "secondary" or 2
        base = np.array(ROMAN_SECONDARY_SPIKE_ANGLES_DEG, dtype=np.float64) + net_offset
        opposing = (base + 180.0) % 360.0
        all_angles = np.concatenate([base % 360.0, opposing])

    return np.unique(np.round(all_angles, 4))


def get_all_spike_angles(
    pa_offset_deg: float = 0.0,
    detector_offset_deg: Optional[float] = None,
) -> np.ndarray:
    """
    Generate all 24 radial spike directions covering both first-order (brightest)
    and second-order diffraction spikes across Roman WFI.

    Parameters
    ----------
    pa_offset_deg : float, default 0.0
        Aperture position angle or net angle offset in degrees.
    detector_offset_deg : float, optional
        Detector frame clocking offset in degrees (nominal -9.70 deg).

    Returns
    -------
    np.ndarray (float64, shape (24,))
        Array of 24 unique spike ray angles in degrees, in range [0, 360), strictly sorted.
    """
    return get_theoretical_spike_angles(
        pa_offset_deg=pa_offset_deg,
        detector_offset_deg=detector_offset_deg,
        order="both",
    )


def refine_spike_angles(
    stamp: np.ndarray,
    center: Tuple[float, float],
    candidate_angles: Sequence[float],
    search_window_deg: float = 3.5,
    step_deg: float = 0.5,
    r_min: float = 15.0,
    r_max: float = 120.0,
) -> np.ndarray:
    """
    Empirically refine diffraction spike angles by maximizing radial ridge flux.

    Sweeps candidate angular offsets around each nominal spike ray direction
    to snap precisely to observed diffraction spike ridges, compensating for
    local SCA clocking, roll_ref variations, and optical distortion.

    Parameters
    ----------
    stamp : np.ndarray
        2D stellar cutout (flux or Moffat residual).
    center : Tuple[float, float]
        Stellar centroid in stamp pixel coordinates.
    candidate_angles : Sequence[float]
        Array or list of nominal spike angles in degrees [0, 360).
    search_window_deg : float, default 3.5
        Angular search half-window in degrees.
    step_deg : float, default 0.5
        Angular step size for line flux evaluation.
    r_min : float, default 15.0
        Inner radius in pixels for radial line integration.
    r_max : float, default 120.0
        Outer radius in pixels for radial line integration.

    Returns
    -------
    np.ndarray
        Array of refined spike ray angles in degrees [0, 360), strictly sorted.
    """
    height, width = stamp.shape
    cx, cy = center
    grid_y, grid_x = np.ogrid[:height, :width]
    dx = grid_x - cx
    dy = grid_y - cy
    r = np.sqrt(dx**2 + dy**2)
    theta = np.degrees(np.arctan2(dy, dx)) % 360.0

    r_hi = min(r_max, min(cx, cy, width - 1 - cx, height - 1 - cy) - 2.0)
    if r_hi <= r_min + 5.0 or not np.any(np.isfinite(stamp)):
        return np.sort(np.unique(np.round(np.array(candidate_angles, dtype=np.float64) % 360.0, 4)))

    ann_mask = (r >= r_min) & (r <= r_hi) & np.isfinite(stamp)
    delta_offsets = np.arange(-search_window_deg, search_window_deg + 1e-4, step_deg)

    ann_vals = stamp[ann_mask]
    ann_med = float(np.median(ann_vals))
    ann_mad = float(1.4826 * np.median(np.abs(ann_vals - ann_med)))
    flux_thresh = ann_med + max(ann_mad, 0.05)
    min_spike_span = min(15.0, 0.4 * (r_hi - r_min))

    refined = []
    for ang in candidate_angles:
        ang_norm = float(ang) % 360.0
        best_ang = ang_norm
        best_flux = -np.inf
        best_has_ridge = False
        for d in delta_offsets:
            cand_ang = (ang_norm + d) % 360.0
            dth = np.abs((theta - cand_ang + 180.0) % 360.0 - 180.0)
            ray_mask = ann_mask & (dth <= 1.5)
            if np.sum(ray_mask) >= 6:
                flx_vals = stamp[ray_mask]
                r_vals = r[ray_mask]
                hi_mask = flx_vals > flux_thresh
                span = float(np.ptp(r_vals[hi_mask])) if np.sum(hi_mask) >= 4 else 0.0
                if span >= min_spike_span:
                    flx = float(np.median(flx_vals))
                    if flx > best_flux:
                        best_flux = flx
                        best_ang = cand_ang
                        best_has_ridge = True

        refined.append(round(best_ang if best_has_ridge else ang_norm, 4))

    return np.sort(np.unique(refined))


def create_geometric_spike_mask(
    shape: Tuple[int, int],
    center: Tuple[float, float],
    angles_deg: np.ndarray,
    angular_half_width_deg: float = 4.0,
    radial_min: float = 3.0,
    spike_width_px: float = 4.0,
    width_growth_rate: float = 0.025,
) -> np.ndarray:
    """
    Create a 2D boolean mask indicating theoretical diffraction spike corridors.

    Combines an angular tolerance cone with a radially-expanding corridor along each ray.
    Excludes the central core (r < radial_min) which is handled by core protection.
    Corridor half-width widens with radius:
        effective_width(r) = spike_width_px + width_growth_rate * max(r - radial_min, 0.0)

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
        Base half-width of the linear spike corridor in pixels.
    width_growth_rate : float, default 0.025
        Rate at which spike corridor half-width expands with radial distance in pixels/pixel.

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
    effective_width = spike_width_px + float(width_growth_rate) * np.maximum(r - radial_min, 0.0)

    for ang in angles_deg:
        ang_norm = float(ang) % 360.0
        # Angular difference taking periodic boundary into account
        diff = np.abs((theta - ang_norm + 180.0) % 360.0 - 180.0)
        # Distance perpendicular to spike line
        ang_rad = np.radians(ang_norm)
        perp_dist = np.abs(-np.sin(ang_rad) * dx + np.cos(ang_rad) * dy)

        is_spike = (diff <= angular_half_width_deg) & (perp_dist <= effective_width)
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

    bkg_std = max(bkg_std, 0.05)

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
            theta = np.arctan2(feat_dy, feat_dx)
            mean_theta = np.arctan2(np.mean(np.sin(theta)), np.mean(np.cos(theta)))
            diff_th = (theta - mean_theta + np.pi) % (2 * np.pi) - np.pi
            circ_std = np.degrees(np.std(diff_th))
            # True spikes have narrow angular spread
            if circ_std < 20.0:
                spike_mask |= feat_mask

    if np.any(spike_mask) and dilation_iterations > 0:
        spike_mask = binary_dilation(spike_mask, iterations=dilation_iterations)

    return spike_mask


class MoffatModelWrapper:
    """
    Wrapper around AstroPhot model providing Astropy-compatible parameter properties.
    Ensures seamless interoperability between AstroPhot and Astropy modeling interfaces.
    """
    def __init__(self, ap_model):
        self._ap_model = ap_model
        self.I0 = ap_model.I0
        self.Rd = ap_model.Rd
        self.n = ap_model.n
        self.center = ap_model.center
        self.amplitude = ap_model.I0
        self.gamma = ap_model.Rd
        self.alpha = ap_model.n

    def __getattr__(self, name):
        return getattr(self._ap_model, name)

    def __call__(self, *args, **kwargs):
        return self._ap_model(*args, **kwargs)


def fit_moffat_astrophot(
    stamp: np.ndarray,
    dq_mask: Optional[np.ndarray] = None,
    max_radius: Optional[float] = None,
    min_radius: Optional[float] = None,
    mask: Optional[np.ndarray] = None,
    variance: Optional[np.ndarray] = None,
    bkg_rms: Optional[float] = None,
) -> Tuple[np.ndarray, Any]:
    """
    Fit a 2D circularly symmetric Moffat profile to stellar flux using AstroPhot (https://astrophot.readthedocs.io/).

    Constructs an AstroPhot TargetImage with Poisson variance weighting, masks the central core
    (r < min_radius) and neighbor Gaia stars (mask), and fits a MoffatGalaxy model with Levenberg-Marquardt.
    Evaluates the fitted model image analytically across the entire stamp.

    Parameters
    ----------
    stamp : np.ndarray
        2D stamp flux array.
    dq_mask : np.ndarray, optional
        Boolean mask of invalid/saturated pixels (True = bad).
    max_radius : float, optional
        Maximum radius from stamp center included in fit.
    min_radius : float, optional
        Inner radius below which pixels are excluded from the fit (masks central core).
    mask : np.ndarray, optional
        Additional boolean mask of pixels to exclude from the fit (e.g. companion Gaia stars).
    variance : np.ndarray, optional
        Pre-computed variance image. If None, constructed as Poisson noise variance.
    bkg_rms : float, optional
        Background RMS noise estimate.

    Returns
    -------
    Tuple[np.ndarray, Any]
        (fitted_image, fitted_model)
    """
    import astrophot as ap

    ny, nx = stamp.shape
    cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
    grid_y, grid_x = np.ogrid[:ny, :nx]
    r = np.hypot(grid_x - cx, grid_y - cy)

    # Estimate background from outer perimeter
    outer_cutout = np.isfinite(stamp) & (r > 0.75 * np.nanmax(r))
    if dq_mask is not None:
        outer_cutout &= (~dq_mask)
    bkg = float(np.median(stamp[outer_cutout])) if np.any(outer_cutout) else 0.0

    if bkg_rms is None:
        if np.any(outer_cutout):
            outer_vals = stamp[outer_cutout]
            bkg_rms = float(1.4826 * np.median(np.abs(outer_vals - bkg)))
            if bkg_rms <= 0.0:
                bkg_rms = float(np.std(outer_vals)) or 0.5
        else:
            bkg_rms = 0.5
    bkg_rms = max(float(bkg_rms), 0.1)

    flux_sub = np.where(np.isfinite(stamp), stamp - bkg, 0.0).astype(np.float32)
    peak_val = max(float(np.nanmax(flux_sub)), 1.0)

    # Combine all exclusions for fit mask
    combined_mask = (~np.isfinite(stamp))
    if dq_mask is not None:
        combined_mask |= dq_mask
    if mask is not None:
        combined_mask |= mask
    if min_radius is not None and min_radius > 0:
        combined_mask |= (r < min_radius)
    if max_radius is not None:
        combined_mask |= (r > max_radius)

    # Create Poisson variance image if not provided:
    # Var = max(flux_sub, 0) + bkg_rms^2
    if variance is None:
        var_img = np.maximum(flux_sub, 0.0) + max(bkg_rms, 1.0)**2
    else:
        var_img = np.maximum(variance, 0.01)

    # Sub-window extraction around center to ensure high fitting speed on large stamps
    fit_r = max_radius if max_radius is not None else min(cx, cy) * 0.8
    sub_r = int(np.ceil(fit_r)) + 5
    x0 = max(0, int(round(cx)) - sub_r)
    x1 = min(nx, int(round(cx)) + sub_r + 1)
    y0 = max(0, int(round(cy)) - sub_r)
    y1 = min(ny, int(round(cy)) + sub_r + 1)

    sub_flux = flux_sub[y0:y1, x0:x1]
    sub_var = var_img[y0:y1, x0:x1]
    sub_mask = combined_mask[y0:y1, x0:x1]
    sub_cx = float(cx - x0)
    sub_cy = float(cy - y0)

    target = ap.TargetImage(
        data=sub_flux,
        variance=sub_var,
        mask=sub_mask,
        pixelscale=1.0,
    )

    model = ap.models.MoffatGalaxy(
        target=target,
        center=[sub_cx, sub_cy],
        PA=0.0,
        q=1.0,
        I0=peak_val,
        Rd=3.0,
        n=1.5,
    )
    model.center.to_static()
    model.PA.to_static()
    model.q.to_static()

    fitter = ap.fit.LM(model, verbose=False)
    fitter.fit()

    fitted_I0 = float(model.I0.value)
    fitted_Rd = max(float(model.Rd.value), 0.5)
    fitted_n = max(float(model.n.value), 1.05)

    wrapped_model = MoffatModelWrapper(model)
    # Evaluate full-sized 2D Moffat image analytically across the entire stamp
    moffat_full = (fitted_I0 / (1.0 + (r / fitted_Rd)**2)**fitted_n + bkg).astype(np.float32)
    return moffat_full, wrapped_model


def fit_moffat_astropy(
    stamp: np.ndarray,
    dq_mask: Optional[np.ndarray] = None,
    max_radius: Optional[float] = None,
    min_radius: Optional[float] = None,
    mask: Optional[np.ndarray] = None,
    sigma_image: Optional[np.ndarray] = None,
    bkg_rms: Optional[float] = None,
) -> Tuple[np.ndarray, Any]:
    """
    Fit a 2D Moffat profile to stellar flux using Astropy LevMarLSQFitter.
    """
    ny, nx = stamp.shape
    cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
    grid_y, grid_x = np.mgrid[:ny, :nx]
    r = np.sqrt((grid_x - cx)**2 + (grid_y - cy)**2)

    valid = np.isfinite(stamp)
    if dq_mask is not None:
        valid &= (~dq_mask)
    if mask is not None:
        valid &= (~mask)
    if min_radius is not None and min_radius > 0:
        valid &= (r >= min_radius)
    if max_radius is not None:
        valid &= (r <= max_radius)

    if not np.any(valid):
        return np.zeros_like(stamp, dtype=np.float32), None

    outer_cutout = np.isfinite(stamp) & (r > 0.75 * np.nanmax(r))
    if dq_mask is not None:
        outer_cutout &= (~dq_mask)
    bkg = float(np.median(stamp[outer_cutout])) if np.any(outer_cutout) else 0.0

    if bkg_rms is None:
        if np.any(outer_cutout):
            outer_vals = stamp[outer_cutout]
            bkg_rms = float(1.4826 * np.median(np.abs(outer_vals - bkg)))
            if bkg_rms <= 0.0:
                bkg_rms = float(np.std(outer_vals)) or 0.5
        else:
            bkg_rms = 0.5
    bkg_rms = max(float(bkg_rms), 0.1)

    finite_stamp = stamp[np.isfinite(stamp)]
    peak_val = float(np.nanmax(finite_stamp)) - bkg if len(finite_stamp) > 0 else 1.0
    peak_val = max(peak_val, 1.0)

    if sigma_image is None:
        flux_excess = np.maximum(stamp - bkg, 0.0)
        sigma_image = np.sqrt(flux_excess + max(bkg_rms, 1.0)**2)

    weights = 1.0 / np.clip(sigma_image[valid], 0.1, None)

    init_moffat = models.Moffat2D(
        amplitude=peak_val,
        x_0=float(cx),
        y_0=float(cy),
        gamma=2.5,
        alpha=1.52,
    )
    init_moffat.x_0.bounds = (cx - 5.0, cx + 5.0)
    init_moffat.y_0.bounds = (cy - 5.0, cy + 5.0)
    init_moffat.amplitude.bounds = (0.0, None)
    init_moffat.gamma.bounds = (0.5, 30.0)
    init_moffat.alpha.bounds = (1.1, 4.0)

    fitter = fitting.LevMarLSQFitter()
    try:
        fitted = fitter(init_moffat, grid_x[valid], grid_y[valid], stamp[valid] - bkg, weights=weights)
        fitted_image = (fitted(grid_x, grid_y) + bkg).astype(np.float32)
        return fitted_image, fitted
    except Exception:
        fallback_img = (init_moffat(grid_x, grid_y) + bkg).astype(np.float32)
        return fallback_img, init_moffat


def fit_moffat_model(
    stamp: np.ndarray,
    dq_mask: Optional[np.ndarray] = None,
    max_radius: Optional[float] = None,
    min_radius: Optional[float] = None,
    mask: Optional[np.ndarray] = None,
    sigma_image: Optional[np.ndarray] = None,
    variance: Optional[np.ndarray] = None,
    bkg_rms: Optional[float] = None,
    engine: str = "astrophot",
) -> Tuple[np.ndarray, Any]:
    """
    Fit a 2D Moffat profile to stellar flux using AstroPhot (default) or Astropy.

    Weighting by Poisson noise and masking central/neighbor stars.
    For medium and bright stars, AstroPhot (https://astrophot.readthedocs.io/)
    performs fast, robust Levenberg-Marquardt fitting of the Moffat profile.

    Parameters
    ----------
    stamp : np.ndarray
        2D stamp flux array.
    dq_mask : np.ndarray, optional
        Boolean mask of invalid/saturated pixels (True = bad).
    max_radius : float, optional
        Maximum radius from stamp center included in fit.
    min_radius : float, optional
        Inner radius below which pixels are excluded from the fit (masks central core).
    mask : np.ndarray, optional
        Additional boolean mask of pixels to exclude from the fit (e.g. companion Gaia stars).
    sigma_image : np.ndarray, optional
        Pre-computed 2D noise / uncertainty image.
    variance : np.ndarray, optional
        Pre-computed 2D variance image.
    bkg_rms : float, optional
        Background RMS noise estimate.
    engine : str, default "astrophot"
        Fitting engine to use: 'astrophot' or 'astropy'.

    Returns
    -------
    Tuple[np.ndarray, Any]
        (fitted_image, fitted_model)
    """
    if engine.lower() == "astrophot":
        try:
            return fit_moffat_astrophot(
                stamp,
                dq_mask=dq_mask,
                max_radius=max_radius,
                min_radius=min_radius,
                mask=mask,
                variance=variance,
                bkg_rms=bkg_rms,
            )
        except Exception as exc:
            logger.warning("AstroPhot Moffat fit encountered exception (%s); falling back to Astropy LevMar.", exc)

    return fit_moffat_astropy(
        stamp,
        dq_mask=dq_mask,
        max_radius=max_radius,
        min_radius=min_radius,
        mask=mask,
        sigma_image=sigma_image,
        bkg_rms=bkg_rms,
    )


def compute_unsharp_mask_residual(
    stamp: np.ndarray,
    sigma: float = 7.0,
    dq_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Compute high-pass residual image via unsharp masking (normalized Gaussian subtraction).

    Removes smooth, diffuse stellar halo and broad background structure without relying
    on an idealized parametric profile, preserving genuine stellar wings while isolating
    compact point sources, companion stars, diffraction spikes, and sharp contaminants.

    Parameters
    ----------
    stamp : np.ndarray
        2D flux array.
    sigma : float, default 7.0
        Gaussian smoothing kernel standard deviation in pixels.
    dq_mask : np.ndarray, optional
        Boolean mask of known bad pixels to exclude from smoothing weights.

    Returns
    -------
    residual : np.ndarray (float32)
        Unsharp-masked residual (stamp - gaussian_filtered(stamp)).
    """
    from scipy.ndimage import gaussian_filter

    valid = np.isfinite(stamp)
    if dq_mask is not None:
        valid &= (~dq_mask)

    weights = valid.astype(np.float32)
    filled = np.where(valid, stamp, 0.0).astype(np.float32)

    smooth_data = gaussian_filter(filled, sigma=sigma)
    smooth_weights = gaussian_filter(weights, sigma=sigma)

    smooth = np.zeros_like(smooth_data)
    nonzero = smooth_weights > 1e-6
    smooth[nonzero] = smooth_data[nonzero] / smooth_weights[nonzero]

    unsharp_res = np.where(np.isfinite(stamp), stamp - smooth, np.nan).astype(np.float32)
    return unsharp_res


def radial_hough_transform(
    sharp_image: np.ndarray,
    center: Tuple[float, float],
    r_min: float = 8.0,
    r_max: Optional[float] = None,
    num_angles: int = 720,
    symmetric_fold: bool = True,
    corridor_half_width_px: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute Star-Centered Radial Rolling Hough Transform (RHT) along rays radiating from center.

    Integrates high-pass sharp flux along linear paths at angle theta from the stellar centroid.
    Antipodal folding (theta + 180 deg) exploits opposing spider strut symmetry and strongly
    suppresses asymmetric point sources or companion stars.

    Parameters
    ----------
    sharp_image : np.ndarray
        2D high-pass / unsharp-masked flux image.
    center : (cx, cy)
        Stellar centroid in pixel coordinates.
    r_min : float, default 8.0
        Inner radius to avoid the saturated / core region.
    r_max : float, optional
        Outer radius for integration. Defaults to 0.85 * distance to nearest boundary.
    num_angles : int, default 720
        Number of angular samples across [0, 360) (0.5 deg resolution).
    symmetric_fold : bool, default True
        If True, combines antipodal rays theta and theta + 180 deg.
    corridor_half_width_px : float, default 1.0
        Half-width for transverse sampling across each ray.

    Returns
    -------
    angles_deg : np.ndarray
        Sampled angles in degrees [0, 360).
    rht_power : np.ndarray
        Normalized RHT accumulator power [0, 1] as a function of angle.
    """
    ny, nx = sharp_image.shape
    cx, cy = center
    if r_max is None:
        r_max = min(cx, cy, nx - cx - 1, ny - cy - 1) * 0.9

    thetas_deg = np.linspace(0, 360.0, num_angles, endpoint=False)
    num_radial = max(int(r_max - r_min), 15)
    radii = np.linspace(r_min, r_max, num_radial)

    clean_sharp = np.nan_to_num(sharp_image, nan=0.0)
    offsets = [-corridor_half_width_px, 0.0, corridor_half_width_px] if corridor_half_width_px > 0 else [0.0]
    rht_power = np.zeros(num_angles, dtype=np.float64)

    for i, th_deg in enumerate(thetas_deg):
        th = np.radians(th_deg)
        cos_t, sin_t = np.cos(th), np.sin(th)
        perp_x, perp_y = -sin_t, cos_t

        line_sum = 0.0
        for off in offsets:
            xs = cx + radii * cos_t + off * perp_x
            ys = cy + radii * sin_t + off * perp_y
            v = map_coordinates(clean_sharp, [ys, xs], order=1, mode="constant", cval=0.0)
            line_sum += np.sum(np.maximum(v, 0.0))

        rht_power[i] = line_sum / (len(offsets) * num_radial)

    if symmetric_fold:
        half_shift = num_angles // 2
        rht_power = 0.5 * (rht_power + np.roll(rht_power, half_shift))

    p_min, p_max = np.min(rht_power), np.max(rht_power)
    if p_max > p_min:
        rht_norm = (rht_power - p_min) / (p_max - p_min)
    else:
        rht_norm = rht_power

    return thetas_deg, rht_norm


def detect_spikes_rht(
    sharp_image: np.ndarray,
    center: Tuple[float, float],
    r_min: float = 8.0,
    r_max: Optional[float] = None,
    min_peak_distance_deg: float = 6.0,
    prominence_rel: float = 0.15,
    symmetric_fold: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Detect empirical spike angles from Star-Centered RHT angular power spectrum peaks.

    Parameters
    ----------
    sharp_image : np.ndarray
        2D high-pass unsharp flux image.
    center : (cx, cy)
        Stellar centroid in pixel coordinates.
    r_min : float, default 8.0
        Inner radius to avoid the central core.
    r_max : float, optional
        Outer radius for integration.
    min_peak_distance_deg : float, default 6.0
        Minimum angular separation between adjacent detected peaks.
    prominence_rel : float, default 0.15
        Relative prominence threshold for peak detection.
    symmetric_fold : bool, default True
        If True, enforces antipodal symmetry across opposing spider strut rays.

    Returns
    -------
    detected_angles : np.ndarray
        Array of detected spike angles in degrees [0, 360).
    angles_deg : np.ndarray
        Full angular grid [0, 360).
    rht_power : np.ndarray
        Normalized RHT angular power spectrum.
    """
    angles_deg, rht_power = radial_hough_transform(
        sharp_image,
        center,
        r_min=r_min,
        r_max=r_max,
        num_angles=720,
        symmetric_fold=symmetric_fold,
    )

    dist_bins = int(round(min_peak_distance_deg / (360.0 / len(angles_deg))))
    prominence = max(prominence_rel * (np.percentile(rht_power, 85) - np.percentile(rht_power, 15)), 0.02)

    if symmetric_fold:
        idx_180 = len(angles_deg) // 2
        angles_180 = angles_deg[:idx_180]
        power_180 = rht_power[:idx_180]

        pad = 20
        wrapped_power = np.concatenate([power_180[-pad:], power_180, power_180[:pad]])
        peaks, _ = find_peaks(wrapped_power, distance=dist_bins, prominence=prominence)

        valid_peaks_180 = []
        for p in peaks:
            idx = p - pad
            if 0 <= idx < len(angles_180):
                valid_peaks_180.append(idx)

        base_angles = angles_180[valid_peaks_180]
        detected_angles = np.sort(np.unique(np.concatenate([base_angles, (base_angles + 180.0) % 360.0])))
    else:
        pad = 30
        wrapped_power = np.concatenate([rht_power[-pad:], rht_power, rht_power[:pad]])
        peaks, _ = find_peaks(wrapped_power, distance=dist_bins, prominence=prominence)
        valid_peaks = []
        for p in peaks:
            idx = p - pad
            if 0 <= idx < len(angles_deg):
                valid_peaks.append(idx)
        detected_angles = angles_deg[valid_peaks]

    return detected_angles, angles_deg, rht_power


def create_rht_spike_mask(
    shape: Tuple[int, int],
    center: Tuple[float, float],
    detected_angles_deg: np.ndarray,
    sharp_image: Optional[np.ndarray] = None,
    angular_half_width_deg: float = 1.8,
    spike_width_px: float = 6.0,
    r_min: float = 6.0,
    r_max: Optional[float] = None,
    adaptive_flux_filter: bool = False,
) -> np.ndarray:
    """
    Create 2D binary spike protection mask from detected RHT angles.

    Parameters
    ----------
    shape : (ny, nx)
        Postage stamp shape.
    center : (cx, cy)
        Stellar centroid in pixel coordinates.
    detected_angles_deg : np.ndarray
        Array of spike angles detected by RHT.
    sharp_image : np.ndarray, optional
        High-pass sharp flux image used for optional adaptive thresholding.
    angular_half_width_deg : float, default 1.8
        Angular corridor half-width in degrees.
    spike_width_px : float, default 6.0
        Perpendicular corridor width in pixels.
    r_min : float, default 6.0
        Inner radius boundary.
    r_max : float, optional
        Outer radius boundary.
    adaptive_flux_filter : bool, default False
        If True, restricts the corridor to positive sharp flux pixels.

    Returns
    -------
    spike_mask : np.ndarray (bool)
        Binary mask covering all detected spike corridors.
    """
    ny, nx = shape
    cx, cy = center
    gy, gx = np.ogrid[:ny, :nx]
    dx = gx - cx
    dy = gy - cy
    r = np.hypot(dx, dy)

    if r_max is None:
        r_max = np.hypot(cx, cy)

    pixel_angles = (np.degrees(np.arctan2(dy, dx)) + 360.0) % 360.0
    spike_mask = np.zeros(shape, dtype=bool)

    for ang in detected_angles_deg:
        ang_rad = np.radians(ang)
        cos_a, sin_a = np.cos(ang_rad), np.sin(ang_rad)

        ang_diff = np.abs((pixel_angles - ang + 180.0) % 360.0 - 180.0)
        d_perp = np.abs(-dx * sin_a + dy * cos_a)
        d_along = dx * cos_a + dy * sin_a

        in_corridor = (ang_diff <= angular_half_width_deg) | (d_perp <= (spike_width_px / 2.0))
        in_ray = in_corridor & (d_along >= r_min) & (r <= r_max)

        if adaptive_flux_filter and sharp_image is not None:
            close_axis = d_perp <= 1.5
            pos_flux = sharp_image > 0.0
            in_ray &= (close_axis | pos_flux)

        spike_mask |= in_ray

    return spike_mask


def mask_gaia_companion_stars(
    shape: Tuple[int, int],
    center: Tuple[float, float],
    companions: Optional[Union[pd.DataFrame, Sequence[Tuple[float, float, float]]]],
    target_center_xy: Optional[Tuple[float, float]] = None,
    pixel_scale: float = 0.11,
    depth: float = 28.0,
    min_radius_px: float = 3.0,
    core_exclusion_radius_px: float = 4.0,
) -> np.ndarray:
    """
    Generate circular aperture masks around neighbor Gaia stars within cutout stamp.

    Uses get_psf_extension_moffat to analytically compute the circular aperture
    radius in arcseconds at the given photometric depth, converted to pixels.

    Parameters
    ----------
    shape : Tuple[int, int]
        (height, width) of stamp.
    center : Tuple[float, float]
        Target star centroid (cx, cy) in stamp coordinates.
    companions : DataFrame or Sequence of (x_stamp, y_stamp, mag)
        List or DataFrame of companion stars in stamp frame or detector frame.
    target_center_xy : Tuple[float, float], optional
        Target star center (x, y) in detector coordinates (needed if companions DataFrame
        is given in detector coordinates).
    pixel_scale : float, default 0.11
        Detector pixel scale in arcseconds/pixel.
    depth : float, default 28.0
        Surface brightness limiting depth in mag/arcsec^2.
    min_radius_px : float, default 3.0
        Minimum circular aperture radius in pixels.
    core_exclusion_radius_px : float, default 4.0
        Exclusion radius around target center to protect the primary star core.

    Returns
    -------
    np.ndarray (bool)
        Boolean mask of circular companion apertures.
    """
    height, width = shape
    cx, cy = center
    grid_y, grid_x = np.ogrid[:height, :width]
    r_target = np.hypot(grid_x - cx, grid_y - cy)
    comp_mask = np.zeros(shape, dtype=bool)

    if companions is None:
        return comp_mask

    from romanepsf.catalog import get_psf_extension_moffat

    items: List[Tuple[float, float, float]] = []
    if isinstance(companions, pd.DataFrame):
        df = companions
        if target_center_xy is not None and "x" in df.columns and "y" in df.columns:
            max_extent = max(width, height) + 200.0
            df = df[
                (df["x"] >= target_center_xy[0] - max_extent)
                & (df["x"] <= target_center_xy[0] + max_extent)
                & (df["y"] >= target_center_xy[1] - max_extent)
                & (df["y"] <= target_center_xy[1] + max_extent)
            ]

        mag_col = None
        for col in ["mag_lambda", "phot_g_mean_mag", "phot_g_mean_mag_AB", "mag"]:
            if col in df.columns:
                mag_col = col
                break
        for _, row in df.iterrows():
            if "x_stamp" in row and "y_stamp" in row:
                sx, sy = float(row["x_stamp"]), float(row["y_stamp"])
            elif target_center_xy is not None and "x" in row and "y" in row:
                sx = cx + (float(row["x"]) - target_center_xy[0])
                sy = cy + (float(row["y"]) - target_center_xy[1])
            elif "x" in row and "y" in row:
                sx, sy = float(row["x"]), float(row["y"])
            else:
                continue
            m = float(row[mag_col]) if mag_col and pd.notna(row[mag_col]) else 20.0
            items.append((sx, sy, m))
    elif isinstance(companions, (list, tuple)):
        items = list(companions)

    for item in items:
        if len(item) >= 3:
            sx, sy, mag = float(item[0]), float(item[1]), float(item[2])
            dist_to_center = np.hypot(sx - cx, sy - cy)
            if dist_to_center <= core_exclusion_radius_px:
                continue
            r_arcsec = get_psf_extension_moffat(mag, depth=depth)
            r_px = max(float(r_arcsec) / pixel_scale, min_radius_px)
            if (sx + r_px < 0) or (sx - r_px >= width) or (sy + r_px < 0) or (sy - r_px >= height):
                continue
            r_comp = np.hypot(grid_x - sx, grid_y - sy)
            comp_mask |= (r_comp <= r_px)

    comp_mask &= (r_target > core_exclusion_radius_px)
    return comp_mask


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
    companion_stars: Optional[Union[pd.DataFrame, Sequence[Tuple[float, float, float]]]] = None,
    target_center_xy: Optional[Tuple[float, float]] = None,
    pixel_scale: float = 0.11,
    companion_depth: float = 28.0,
    method: str = "moffat",
    unsharp_sigma: float = 7.0,
    width_growth_rate: Optional[float] = None,
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
        Stellar tier ('bright', 'medium', 'faint') for tier-dependent core radii and masking.
        For faint stars, residual-based contaminant masking is omitted to preserve genuine stellar flux.

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
        net_rotation = 0.0

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
    if width_growth_rate is None:
        effective_growth_rate = float(getattr(spikes_cfg, "width_growth_rate", 0.025))
    else:
        effective_growth_rate = float(width_growth_rate)

    morph_cfg = getattr(spikes_cfg, "morphological", None)
    morph_sigma = float(getattr(morph_cfg, "threshold_sigma", 2.0)) if morph_cfg else 2.0
    morph_length = int(getattr(morph_cfg, "min_length_px", 15)) if morph_cfg else 15
    morph_dil = int(getattr(morph_cfg, "dilation_iterations", 2)) if morph_cfg else 2

    ny, nx = stamp.shape
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    grid_y, grid_x = np.ogrid[:ny, :nx]
    r = np.sqrt((grid_x - cx)**2 + (grid_y - cy)**2)

    is_faint = (tier is not None and str(tier).lower().strip() == "faint")

    if is_faint:
        # Faint stars: omit Moffat fitting, omit diffraction spikes, omit contaminant masking.
        # Direct pass-through for subsequent centering, resampling, normalization, and stacking.
        residual = np.where(np.isfinite(stamp), stamp, 0.0).astype(np.float32)
        protected_stellar_area = (r <= core_protection_radius_px)
        final_mask = np.zeros(stamp.shape, dtype=bool)
        if dq_mask is not None:
            final_mask |= dq_mask
        final_mask |= (~np.isfinite(stamp))
        return final_mask, protected_stellar_area, residual

    # Pre-compute circular aperture masks for neighbor Gaia stars (used for both Moffat fitting and contaminant masking)
    comp_mask = None
    if companion_stars is not None:
        comp_mask = mask_gaia_companion_stars(
            (ny, nx),
            (cx, cy),
            companion_stars,
            target_center_xy=target_center_xy,
            pixel_scale=pixel_scale,
            depth=companion_depth,
            core_exclusion_radius_px=core_protection_radius_px,
        )

    # 2. Compute residual map (via Moffat model subtraction or unsharp masking)
    method_lower = str(method).lower().strip()
    if method_lower == "unsharp":
        residual = compute_unsharp_mask_residual(stamp, sigma=unsharp_sigma, dq_mask=dq_mask)
    else:
        # Default: Moffat analytical model subtraction using AstroPhot
        # Mask the central core region during the fit for bright and medium stars
        tier_str = str(tier).lower().strip() if tier is not None else ""
        if tier_str in ("bright", "medium"):
            min_fit_r = float(core_protection_radius_px)
        else:
            min_fit_r = None

        max_fit_r = min(max(cx * 0.4, 30.0), 100.0)

        moffat_img, _ = fit_moffat_model(
            stamp,
            dq_mask=dq_mask,
            max_radius=max_fit_r,
            min_radius=min_fit_r,
            mask=comp_mask,
            engine="astrophot",
        )
        residual = (stamp - moffat_img).astype(np.float32)

    # 3. Spike protection covering theoretical spikes + empirical refinement
    spike_order = getattr(spikes_cfg, "spike_order", None)
    if spike_order is not None and str(spike_order).lower() in ("both", "all", "combined"):
        base_spike_angles = get_all_spike_angles(net_rotation)
    elif spike_order is not None and str(spike_order).lower() in ("primary", "1"):
        base_spike_angles = get_theoretical_spike_angles(net_rotation, order="primary")
    else:
        # Default: secondary (12 rays) unless configured as "both" or "primary"
        order_to_use = spike_order if spike_order is not None else "secondary"
        base_spike_angles = get_theoretical_spike_angles(net_rotation, order=order_to_use)

    if is_faint:
        # Faint stars do not exhibit detectable diffraction spikes; omit spike protection
        geom_spike_mask = np.zeros(stamp.shape, dtype=bool)
        morph_spike_mask = np.zeros(stamp.shape, dtype=bool)
    else:
        refined_spike_angles = refine_spike_angles(
            residual,
            (cx, cy),
            base_spike_angles,
            search_window_deg=float(getattr(spikes_cfg, "refine_search_window_deg", 3.5)),
            step_deg=float(getattr(spikes_cfg, "refine_step_deg", 0.5)),
            r_min=max(core_protection_radius_px, 15.0),
            r_max=min(max(cx * 0.8, 35.0), 150.0),
        )
        geom_spike_mask = create_geometric_spike_mask(
            (ny, nx),
            (cx, cy),
            refined_spike_angles,
            angular_half_width_deg=angular_half_width,
            radial_min=max(core_protection_radius_px, 1.0),
            spike_width_px=spike_width,
            width_growth_rate=effective_growth_rate,
        )
        morph_spike_mask = detect_morphological_spikes(
            residual,
            (cx, cy),
            threshold_sigma=morph_sigma,
            min_length_px=morph_length,
            dilation_iterations=morph_dil,
        )

    spike_protection = geom_spike_mask | morph_spike_mask
    core_protection = (r <= core_protection_radius_px)
    protected_stellar_area = spike_protection | core_protection

    # 4. Detect extraneous non-star contaminants
    # Note: For faint stars, residual contaminant masking is omitted to preserve faint stellar wings
    if is_faint:
        contaminants = np.zeros(stamp.shape, dtype=bool)
    else:
        clean_area = ~protected_stellar_area
        if dq_mask is not None:
            clean_area &= (~dq_mask)

        try:
            from astropy.stats import sigma_clipped_stats
            import cv2

            valid_res = residual[clean_area & np.isfinite(residual)]
            if len(valid_res) > 20:
                _, res_med, res_std = sigma_clipped_stats(valid_res, sigma=3.0, maxiters=5)
            else:
                res_med, res_std = 0.0, float(np.nanstd(residual)) or 1.0

            # User new mask method: residual > median + 1.5 * std (with floor for noiseless/synthetic data)
            threshold_val = res_med + max(1.5 * res_std, 0.1)
            contam_raw = (residual > threshold_val).astype(np.uint8)

            # Morphological opening and dilation: erode 1x1 then dilate 3x3
            contam_opened = cv2.erode(contam_raw, np.ones((1, 1), np.uint8), iterations=1)
            contam_dilated = cv2.dilate(contam_opened, np.ones((3, 3), np.uint8), iterations=1)
            contaminants = contam_dilated.astype(bool)

            # Strict Invariant: Exclude protected spikes & core from contaminant mask
            contaminants[protected_stellar_area] = False

        except Exception as exc:
            logger.warning("Falling back to standard contaminant detection: %s", exc)
            valid_res = residual[clean_area & np.isfinite(residual)]
            if len(valid_res) > 20:
                res_med = float(np.median(valid_res))
                res_std = float(1.4826 * np.median(np.abs(valid_res - res_med)))
                if res_std <= 0.0:
                    res_std = float(np.nanstd(valid_res)) or 1.0
            else:
                res_med = 0.0
                res_std = float(np.nanstd(residual)) if np.any(np.isfinite(residual)) else 1.0

            sigma_r = detection_sigma * (1.0 + 50.0 * np.exp(-r / 15.0))
            contam_raw = (residual - res_med) > (sigma_r * res_std)
            contaminants = binary_dilation(contam_raw, iterations=1) if np.any(contam_raw) else contam_raw
            contaminants &= (~protected_stellar_area)

    # 5. Include circular aperture masks for other Gaia stars using get_psf_extension_moffat
    if comp_mask is not None:
        contaminants |= comp_mask

    # 6. Assemble final mask
    final_mask = contaminants.copy()
    if dq_mask is not None:
        final_mask |= dq_mask
    final_mask |= (~np.isfinite(stamp))

    return final_mask, protected_stellar_area, residual


__all__ = [
    "ROMAN_PRIMARY_SPIKE_ANGLES_DEG",
    "ROMAN_SECONDARY_SPIKE_ANGLES_DEG",
    "ROMAN_BASE_SPIKE_ANGLES_DEG",
    "NOMINAL_DETECTOR_OFFSET_DEG",
    "get_theoretical_spike_angles",
    "get_all_spike_angles",
    "refine_spike_angles",
    "create_geometric_spike_mask",
    "detect_morphological_spikes",
    "compute_unsharp_mask_residual",
    "radial_hough_transform",
    "detect_spikes_rht",
    "create_rht_spike_mask",
    "fit_moffat_model",
    "fit_moffat_astrophot",
    "fit_moffat_astropy",
    "mask_gaia_companion_stars",
    "mask_contaminants_with_spikes_protected",
]
