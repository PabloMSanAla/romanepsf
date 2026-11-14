"""
Postage Stamp Extraction, Adaptive Sizing, Subpixel Alignment, and Background Subtraction.

Milestone 2, Features 9, 10, 11:
1. Adaptive odd stamp sizing by stellar tier:
   - Faint (m >= 13.0): 81x81 pixels
   - Medium (11.0 <= m < 13.0): 201x201 pixels
   - Bright (m < 11.0): up to 1001x1001 pixels (dynamically scaled via Moffat extension)
2. Accurate cutout extraction with boundary padding and coordinate tracking.
3. Robust annular or percentile background estimation and subtraction per stamp.
4. Subpixel bicubic spline realignment to exact integer grid center ((S-1)/2, (S-1)/2)
   with NaN guarding and flux conservation.
5. Faint core DQ bit 1 (SATURATED) protection against zeroing valid positive core pixels.
6. Seamless integration with RomanL2Data and tiered catalog DataFrames.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import logging
import numpy as np
import pandas as pd
from scipy.ndimage import shift, map_coordinates, uniform_filter

from romanepsf.loader import RomanL2Data, DQ_FLAGS, get_dq_mask
from romanepsf.catalog import get_psf_extension_moffat
from romanepsf.masking import mask_contaminants_with_spikes_protected

logger = logging.getLogger("romanepsf.stamps")


@dataclass
class StellarStamp:
    """Container for a single preprocessed, aligned, and background-subtracted stellar stamp."""
    source_id: Any
    tier: str
    mag: float
    data: np.ndarray            # Sub-pixel aligned flux image (float32)
    mask: np.ndarray            # Boolean mask (True = bad / contaminated / saturated)
    center_original: Tuple[float, float]
    size: int
    norm_factor: float = 1.0    # Photometric scale factor relative to reference tier
    bkg_value: float = 0.0      # Estimated local background subtracted from stamp
    bkg_rms: float = 0.0        # Background RMS uncertainty
    oversample: int = 1         # Subpixel oversampling factor (e.g. 4 for faint/medium)
    debug_info: Optional[Dict[str, Any]] = None


# Alias for PROJECT.md contract compatibility
StampData = StellarStamp


def get_adaptive_stamp_size(
    mag: float,
    tier: str,
    max_size: int = 1001,
    pixel_scale: float = 0.11,
    faint_size: int = 81,
    medium_size: int = 201,
) -> int:
    """
    Calculate an odd-integer postage stamp size tailored to the star's magnitude and tier.

    Parameters
    ----------
    mag : float
        Stellar magnitude (e.g. F146 mag_lambda).
    tier : str
        Stellar tier ('bright', 'medium', 'faint').
    max_size : int, default 1001
        Maximum allowed stamp dimension for bright stars.
    pixel_scale : float, default 0.11
        Pixel scale in arcsec/pixel.
    faint_size : int, default 81
        Configurable dimension for faint stars.
    medium_size : int, default 201
        Configurable dimension for medium stars.

    Returns
    -------
    int
        Odd integer dimension S such that (S - 1) // 2 is an exact integer index.
    """
    t = str(tier).lower().strip()
    if t == "bright":
        ext_arcsec = get_psf_extension_moffat(mag, depth=30.0)
        # Allocate 2.2x extension to capture full wings and diffraction spikes
        raw_sz = int(round(ext_arcsec * 2.2 / pixel_scale))
        sz = min(max(raw_sz, 301), max_size)
    elif t == "medium":
        sz = medium_size
    else:  # faint
        sz = faint_size

    # Ensure odd dimension so that (sz - 1) / 2 is an exact integer index
    if sz % 2 == 0:
        sz += 1
    return sz


def extract_cutout(
    image: np.ndarray,
    center: Tuple[float, float],
    size: int,
    fill_value: float = np.nan,
) -> Tuple[np.ndarray, Tuple[int, int]]:
    """
    Extract a square cutout of size (size, size) centered at integer rounded coordinates.
    Pads with fill_value if the cutout extends beyond image boundaries.

    Parameters
    ----------
    image : np.ndarray
        2D source array (H, W).
    center : (cx, cy)
        Continuous or integer coordinates of the star center.
    size : int
        Odd integer size of the desired square cutout.
    fill_value : float, default np.nan
        Value used to pad pixels outside the source image boundary.

    Returns
    -------
    cutout : np.ndarray
        Extracted square array of shape (size, size).
    (ix, iy) : Tuple[int, int]
        Integer rounded coordinates used as the cutout center.
    """
    height, width = image.shape
    cx, cy = center
    ix, iy = int(round(cx)), int(round(cy))
    half = (size - 1) // 2

    x0 = ix - half
    x1 = ix + half + 1
    y0 = iy - half
    y1 = iy + half + 1

    out = np.full((size, size), fill_value, dtype=image.dtype)

    # Intersection with image bounds
    src_x0 = max(0, x0)
    src_x1 = min(width, x1)
    src_y0 = max(0, y0)
    src_y1 = min(height, y1)

    dst_x0 = src_x0 - x0
    dst_x1 = dst_x0 + (src_x1 - src_x0)
    dst_y0 = src_y0 - y0
    dst_y1 = dst_y0 + (src_y1 - src_y0)

    if src_x1 > src_x0 and src_y1 > src_y0:
        out[dst_y0:dst_y1, dst_x0:dst_x1] = image[src_y0:src_y1, src_x0:src_x1]

    return out, (ix, iy)


def estimate_stamp_background(
    stamp: np.ndarray,
    mask: Optional[np.ndarray] = None,
    method: str = "annulus",
    r_inner_frac: float = 0.80,
    r_outer_frac: float = 0.98,
    sigma_clip: float = 3.0,
    percentile_val: float = 10.0,
) -> Tuple[float, float]:
    """
    Robustly estimate the local sky background level and RMS noise in a postage stamp.

    Parameters
    ----------
    stamp : np.ndarray
        2D flux array.
    mask : np.ndarray, optional
        Boolean mask where True denotes bad/masked pixels to ignore.
    method : {'annulus', 'percentile'}, default 'annulus'
        Background estimation strategy:
        - 'annulus': Sigma-clipped median in outer circular/elliptical annulus.
        - 'percentile': Lower percentile of valid unmasked pixels.
    r_inner_frac : float, default 0.80
        Inner radius of background annulus as a fraction of stamp half-width.
    r_outer_frac : float, default 0.98
        Outer radius of background annulus as a fraction of stamp half-width.
    sigma_clip : float, default 3.0
        Outlier rejection threshold for iterative sigma clipping.
    percentile_val : float, default 10.0
        Percentile value used if method='percentile' or annular fallback occurs.

    Returns
    -------
    bkg_val : float
        Estimated background level.
    bkg_rms : float
        Estimated background RMS noise.
    """
    ny, nx = stamp.shape
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    r_max = max(cx, cy)

    grid_y, grid_x = np.indices((ny, nx))
    r = np.hypot(grid_x - cx, grid_y - cy)

    valid = np.isfinite(stamp)
    if mask is not None:
        valid &= (~mask)

    if method == "annulus":
        r_in = r_inner_frac * r_max
        r_out = r_outer_frac * r_max
        annulus_mask = valid & (r >= r_in) & (r <= r_out)
        annulus_pix = stamp[annulus_mask]

        if len(annulus_pix) >= 15:
            # Iterative sigma clipping
            vals = annulus_pix.copy()
            for _ in range(3):
                med = float(np.median(vals))
                mad = float(np.median(np.abs(vals - med)))
                std = 1.4826 * mad
                if std <= 1e-12:
                    break
                clip = np.abs(vals - med) <= (sigma_clip * std)
                if np.sum(clip) < 5 or np.all(clip):
                    break
                vals = vals[clip]
            bkg_val = float(np.median(vals))
            bkg_rms = float(1.4826 * np.median(np.abs(vals - bkg_val))) if len(vals) > 1 else 0.0
            return bkg_val, bkg_rms

    # Fallback to percentile on outer pixels or all valid pixels
    outer_pix = stamp[valid & (r >= 0.5 * r_max)]
    if len(outer_pix) < 10:
        outer_pix = stamp[valid]

    if len(outer_pix) == 0:
        return 0.0, 0.0

    bkg_val = float(np.percentile(outer_pix, percentile_val))
    bkg_rms = float(np.nanstd(outer_pix)) if len(outer_pix) > 1 else 0.0
    return bkg_val, bkg_rms


def subtract_stamp_background(stamp: np.ndarray, bkg_val: float) -> np.ndarray:
    """Subtract scalar background level while preserving NaNs."""
    return stamp - bkg_val


def recenter_and_align_stamp(
    stamp: np.ndarray,
    mask: np.ndarray,
    subpixel_offset: Tuple[float, float],
    fill_bkg: Optional[float] = None,
    order: int = 3,
    oversample: int = 1,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Shift stamp and mask so the star's continuous centroid aligns exactly with the grid center.
    Optionally evaluates on an oversampled subpixel grid (e.g. oversample=4).

    Parameters
    ----------
    stamp : np.ndarray
        Cutout flux image.
    mask : np.ndarray
        Boolean mask (True = bad / masked).
    subpixel_offset : (dx, dy)
        Fractional offset (centroid - integer_center).
        To center the peak, we apply shift (-dy, -dx).
    fill_bkg : float, optional
        Background fill value for NaNs before spline evaluation.
    order : int, default 3
        Spline interpolation order for science flux (order=3 bicubic).
        Mask is always shifted with order=0 (nearest neighbor).
    oversample : int, default 1
        Subpixel oversampling factor (e.g. 4 for 4x oversampling).

    Returns
    -------
    aligned_data : np.ndarray (float32)
        Subpixel centered flux array (at native or oversampled resolution).
    aligned_mask : np.ndarray (bool)
        Shifted boolean mask with newly exposed boundary pixels marked True.
    """
    dx, dy = subpixel_offset

    # Fill NaNs with median background prior to spline shift to avoid NaN propagation
    valid = np.isfinite(stamp) & (~mask)
    if fill_bkg is not None:
        bkg = fill_bkg
    else:
        bkg = float(np.median(stamp[valid])) if np.any(valid) else 0.0

    clean_stamp = np.where(np.isfinite(stamp), stamp, bkg)

    if oversample <= 1:
        shift_y = -dy
        shift_x = -dx
        aligned_data = shift(clean_stamp, [shift_y, shift_x], order=order, mode="constant", cval=bkg)
        aligned_mask = shift(mask.astype(float), [shift_y, shift_x], order=0, mode="constant", cval=1.0) > 0.5
        aligned_mask |= (~np.isfinite(aligned_data))
        return aligned_data.astype(np.float32), aligned_mask

    # Continuous subpixel oversampled alignment
    ny, nx = stamp.shape
    O = int(oversample)
    ny_over = (ny - 1) * O + 1
    nx_over = (nx - 1) * O + 1
    cy_over = (ny_over - 1) / 2.0
    cx_over = (nx_over - 1) / 2.0
    cy_in = (ny - 1) / 2.0
    cx_in = (nx - 1) / 2.0

    u = np.arange(nx_over, dtype=np.float64)
    v = np.arange(ny_over, dtype=np.float64)
    uu, vv = np.meshgrid(u, v)

    x_sample = cx_in + dx + (uu - cx_over) / O
    y_sample = cy_in + dy + (vv - cy_over) / O

    aligned_data = map_coordinates(clean_stamp, [y_sample, x_sample], order=order, mode="constant", cval=bkg)
    aligned_mask = map_coordinates(mask.astype(float), [y_sample, x_sample], order=0, mode="constant", cval=1.0) > 0.5
    aligned_mask |= (~np.isfinite(aligned_data))

    return aligned_data.astype(np.float32), aligned_mask


def downsample_oversampled_stamp(image: np.ndarray, oversample: int = 4) -> np.ndarray:
    """
    Downsample an oversampled array by physical detector pixel area integration (boxcar block average).
    """
    O = int(oversample)
    if O <= 1:
        return image
    ny_over, nx_over = image.shape
    filtered = uniform_filter(image.astype(np.float32), size=O, mode="constant", cval=0.0)
    idx_y = np.arange(0, ny_over, O)
    idx_x = np.arange(0, nx_over, O)
    return filtered[np.ix_(idx_y, idx_x)].astype(np.float32)


def _get_row_magnitude(row: pd.Series, preferred_col: str = "mag_lambda") -> float:
    """Safely extract star magnitude from catalog row across column naming variants."""
    if preferred_col in row and pd.notna(row[preferred_col]):
        try:
            return float(row[preferred_col])
        except (ValueError, TypeError):
            pass

    for col in ["mag_lambda", "phot_g_mean_mag", "phot_g_mean_mag_AB", "mag"]:
        if col in row and pd.notna(row[col]):
            try:
                return float(row[col])
            except (ValueError, TypeError):
                continue

    return 15.0  # Safe faint magnitude fallback


def process_star_stamps(
    l2_data: RomanL2Data,
    catalog_df: pd.DataFrame,
    spikes_cfg: Optional[Any] = None,
    stamps_cfg: Optional[Any] = None,
    max_bright_size: int = 1001,
    max_stars_per_tier: Optional[Dict[str, int]] = None,
    subtract_background: bool = True,
    bkg_method: str = "annulus",
    mag_col: str = "mag_lambda",
    faint_core_protect_finite: bool = True,
    companion_stars: Optional[pd.DataFrame] = None,
    companion_depth: float = 28.0,
) -> Dict[str, List[StellarStamp]]:
    """
    Extract, mask, recenter, and align postage stamps for isolated stars grouped by tier.

    Handles config schema polymorphic arguments:
    Can be called as:
      process_star_stamps(l2, df)
      process_star_stamps(l2, df, max_bright_size=1001, max_stars_per_tier={...})
      process_star_stamps(l2, df, spikes_cfg, stamps_cfg)

    Parameters
    ----------
    l2_data : RomanL2Data
        Calibrated detector dataset.
    catalog_df : pd.DataFrame
        Filtered and tiered catalog of isolated stars.
    spikes_cfg : SpikesSection or int, optional
        Spike configuration object or positional max_bright_size.
    stamps_cfg : StampsSection or dict, optional
        Stamp configuration dataclass or positional max_stars_per_tier.
    max_bright_size : int, default 1001
        Maximum cutout size for bright stars.
    max_stars_per_tier : dict, optional
        Limits on number of stars per tier (e.g. {'bright': 10, 'medium': 30, 'faint': 50}).
    subtract_background : bool, default True
        If True, estimates and subtracts local sky background per stamp.
    bkg_method : {'annulus', 'percentile'}, default 'annulus'
        Background estimation algorithm.
    mag_col : str, default 'mag_lambda'
        Magnitude column name.
    faint_core_protect_finite : bool, default True
        If True, prevents DQ bit 1 (SATURATED) from masking valid positive core pixels in faint stars.

    Returns
    -------
    Dict[str, List[StellarStamp]]
        Processed stamps keyed by tier: 'bright', 'medium', 'faint'.
    """
    # 1. Handle polymorphic configuration argument signatures
    if isinstance(spikes_cfg, (int, float)):
        max_bright_size = int(spikes_cfg)
        spikes_cfg = None

    if isinstance(stamps_cfg, dict):
        max_stars_per_tier = stamps_cfg
        stamps_cfg = None
    elif stamps_cfg is not None and hasattr(stamps_cfg, "sizes"):
        max_bright_size = getattr(stamps_cfg.sizes, "bright_max", max_bright_size)
        faint_core_protect_finite = getattr(stamps_cfg, "faint_core_protect_finite", faint_core_protect_finite)

    if max_stars_per_tier is None:
        max_stars_per_tier = {"bright": 20, "medium": 50, "faint": 100}

    stamps_by_tier: Dict[str, List[StellarStamp]] = {"bright": [], "medium": [], "faint": []}
    if catalog_df is None or catalog_df.empty:
        return stamps_by_tier

    roll_ref = float(getattr(l2_data, "pa_aperture", l2_data.meta.get("roll_ref", 0.0)))
    pixel_scale = float(getattr(l2_data, "pixel_scale", 0.11))

    # Base bad pixel mask (excluding SATURATED for custom faint core logic)
    dq_hard_bad = get_dq_mask(l2_data.dq, ["DO_NOT_USE", "DROPOUT"])
    dq_saturated = get_dq_mask(l2_data.dq, ["SATURATED"])

    for tier in ["bright", "medium", "faint"]:
        if "tier" in catalog_df.columns:
            sub_df = catalog_df[catalog_df["tier"].str.lower() == tier].copy()
        else:
            sub_df = catalog_df.copy()

        if sub_df.empty:
            continue

        # Sort brightest first (ascending magnitude) using robust magnitude helper
        mags_temp = [_get_row_magnitude(row, preferred_col=mag_col) for _, row in sub_df.iterrows()]
        sub_df["_sort_mag"] = mags_temp
        sub_df = sub_df.sort_values("_sort_mag", ascending=True).drop(columns=["_sort_mag"])

        limit = max_stars_per_tier.get(tier, len(sub_df))
        sub_df = sub_df.head(limit)

        for _, row in sub_df.iterrows():
            mag = _get_row_magnitude(row, preferred_col=mag_col)
            cx, cy = float(row["x"]), float(row["y"])

            # 1. Determine adaptive size
            sz = get_adaptive_stamp_size(mag, tier, max_size=max_bright_size, pixel_scale=pixel_scale)

            # 2. Extract raw cutouts
            raw_cutout, (ix, iy) = extract_cutout(l2_data.data, (cx, cy), sz, fill_value=np.nan)
            raw_hard_dq, _ = extract_cutout(dq_hard_bad.astype(np.uint8), (cx, cy), sz, fill_value=1)
            raw_sat_dq, _ = extract_cutout(dq_saturated.astype(np.uint8), (cx, cy), sz, fill_value=1)
            raw_vp = None
            var_p = getattr(l2_data, "var_poisson", None)
            if isinstance(var_p, np.ndarray) and var_p.ndim == 2:
                raw_vp, _ = extract_cutout(var_p, (cx, cy), sz, fill_value=np.nan)

            # 3. DQ Mask construction & Faint Core Protection
            dq_mask_bool = raw_hard_dq.astype(bool)
            sat_bool = raw_sat_dq.astype(bool)

            half = (sz - 1) // 2
            core_rad = 6.0 if tier == "bright" else 4.0

            if tier == "faint" and faint_core_protect_finite:
                # Protect core pixels with finite positive flux from being zeroed by DQ bit 1
                grid_y, grid_x = np.indices((sz, sz))
                r_core = np.hypot(grid_x - half, grid_y - half)
                in_core = r_core <= core_rad
                valid_finite_pos = np.isfinite(raw_cutout) & (raw_cutout > 0)
                sat_bool[in_core & valid_finite_pos] = False

            dq_mask_bool |= sat_bool

            # 4. Background estimation & optional subtraction
            if subtract_background:
                bkg_val, bkg_rms = estimate_stamp_background(raw_cutout, mask=dq_mask_bool, method=bkg_method)
                flux_cutout = subtract_stamp_background(raw_cutout, bkg_val)
            else:
                bkg_val, bkg_rms = 0.0, 0.0
                flux_cutout = raw_cutout.copy()

            # 5. Apply dual-prior spike protection & contaminant masking
            comps_table = companion_stars if companion_stars is not None else catalog_df
            det_id = getattr(l2_data, "detector", None)
            bp_id = getattr(l2_data, "filter_name", "F146")
            res_map = None
            if mask_contaminants_with_spikes_protected is not None:
                if spikes_cfg is not None:
                    mask, _, res_map = mask_contaminants_with_spikes_protected(
                        flux_cutout,
                        dq_mask_bool,
                        pa_aperture=roll_ref,
                        cfg=spikes_cfg,
                        tier=tier,
                        companion_stars=comps_table,
                        target_center_xy=(cx, cy),
                        pixel_scale=pixel_scale,
                        companion_depth=companion_depth,
                        detector=det_id,
                        bandpass=bp_id,
                        var_poisson=raw_vp,
                    )
                else:
                    mask, _, res_map = mask_contaminants_with_spikes_protected(
                        flux_cutout,
                        dq_mask_bool,
                        pa_offset_deg=roll_ref,
                        core_protection_radius_px=core_rad,
                        tier=tier,
                        companion_stars=comps_table,
                        target_center_xy=(cx, cy),
                        pixel_scale=pixel_scale,
                        companion_depth=companion_depth,
                        detector=det_id,
                        bandpass=bp_id,
                        var_poisson=raw_vp,
                    )
            else:
                mask = dq_mask_bool | (~np.isfinite(flux_cutout))

            # 6. Sub-pixel recentering
            sub_dx = cx - ix
            sub_dy = cy - iy
            aligned_data, aligned_mask = recenter_and_align_stamp(flux_cutout, mask, (sub_dx, sub_dy))

            # Record companion stars within stamp for debug diagnostics & overlay
            stamp_companions = []
            if comps_table is not None and isinstance(comps_table, pd.DataFrame):
                max_extent = half + 50.0
                df_c = comps_table[
                    (comps_table["x"] >= cx - max_extent)
                    & (comps_table["x"] <= cx + max_extent)
                    & (comps_table["y"] >= cy - max_extent)
                    & (comps_table["y"] <= cy + max_extent)
                ]
                for _, c_row in df_c.iterrows():
                    if "source_id" in c_row and str(c_row["source_id"]) == str(row.get("source_id")):
                        continue
                    sc_x = (half + sub_dx) + (float(c_row["x"]) - cx)
                    sc_y = (half + sub_dy) + (float(c_row["y"]) - cy)
                    dist_c = np.hypot(sc_x - (half + sub_dx), sc_y - (half + sub_dy))
                    if dist_c <= core_rad:
                        continue
                    c_mag = float(c_row.get("phot_g_mean_mag", c_row.get("mag_lambda", c_row.get(mag_col, companion_depth))))
                    from romanepsf.catalog import get_psf_extension_moffat
                    r_ext = max(float(get_psf_extension_moffat(c_mag, depth=companion_depth)) / pixel_scale, 3.0)
                    if (sc_x + r_ext >= 0) and (sc_x - r_ext < sz) and (sc_y + r_ext >= 0) and (sc_y - r_ext < sz):
                        stamp_companions.append({
                            "source_id": c_row.get("source_id", "Companion"),
                            "x": sc_x,
                            "y": sc_y,
                            "radius_px": r_ext,
                            "mag": c_mag,
                        })

            rad_model = (flux_cutout - res_map) if res_map is not None else flux_cutout
            debug_dict = {
                "raw_stamp": flux_cutout,
                "unaligned_mask": mask,
                "residual": res_map if res_map is not None else np.zeros_like(flux_cutout),
                "radial_model": rad_model,
                "conversion_factor": float(getattr(l2_data, "conversion_factor", 1.0)),
                "is_calibrated": bool(getattr(l2_data, "is_calibrated", True)),
                "center_stamp": (half + sub_dx, half + sub_dy),
                "gaia_companions": stamp_companions,
            }

            stamp_obj = StellarStamp(
                source_id=row.get("source_id", None),
                tier=tier,
                mag=mag,
                data=aligned_data,
                mask=aligned_mask,
                center_original=(cx, cy),
                size=sz,
                norm_factor=1.0,
                bkg_value=bkg_val,
                bkg_rms=bkg_rms,
                debug_info=debug_dict,
            )
            stamps_by_tier[tier].append(stamp_obj)

    return stamps_by_tier


__all__ = [
    "StellarStamp",
    "StampData",
    "get_adaptive_stamp_size",
    "extract_cutout",
    "estimate_stamp_background",
    "subtract_stamp_background",
    "recenter_and_align_stamp",
    "process_star_stamps",
]
