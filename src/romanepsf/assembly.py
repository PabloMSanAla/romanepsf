"""
PyTorch-Accelerated 2D Extended PSF Synthesis and Multi-Tier Blending.

Constructs 2D tier-specific PSFs using robust outlier-clipped tensor stacking,
determines cross-tier flux normalization factors in unsaturated overlap annuli
via radial profiling (profile.py), and stitches Faint (core), Medium (transition),
and Bright (wings + 6-fold diffraction spikes) into a seamless 2D extended PSF.

STRICT SCIENTIFIC CONSTRAINT:
Preserves full 2D spatial structure and 2D diffraction spikes without radial
circularization or azimuthal averaging. 1D radial profiles are strictly reserved
for saturation plateau detection and cross-tier flux scaling factors.
"""

from typing import Dict, List, Tuple, Optional, Any, Union
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import torch
from astropy.io import fits
from astropy.table import Table

from romanepsf import __version__
from romanepsf.masking import ROMAN_BASE_SPIKE_ANGLES_DEG, NOMINAL_DETECTOR_OFFSET_DEG
from romanepsf.stamps import StellarStamp
from romanepsf.profile import elliptical_profile
from romanepsf.config import resolve_device, AssemblySection, OverlapAnnulusConfig


def stack_tier_stamps_torch(
    stamp_list: List[StellarStamp],
    device: Union[str, torch.device] = "cpu",
    sigma_clip: float = 3.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Stack aligned stamps within a tier using PyTorch tensor acceleration and outlier rejection.

    Parameters
    ----------
    stamp_list : list of StellarStamp
        Aligned stamps belonging to the same brightness tier.
    device : str or torch.device, default 'cpu'
        PyTorch device ('cpu', 'mps', 'cuda', 'auto').
    sigma_clip : float, default 3.0
        Sigma clipping threshold for outlier pixel rejection.

    Returns
    -------
    (stacked_2d_psf, weight_coverage_map) : Tuple[np.ndarray, np.ndarray]
    """
    if not stamp_list:
        raise ValueError("Cannot stack an empty stamp list.")

    if isinstance(device, str):
        dev = resolve_device(device)
    else:
        dev = device

    # Find the maximum size among stamps in the tier
    max_sz = max(s.data.shape[0] for s in stamp_list)
    if max_sz % 2 == 0:
        max_sz += 1
    half_max = (max_sz - 1) // 2

    # Pad/crop all stamps to max_sz
    data_cube = []
    mask_cube = []

    for s in stamp_list:
        d = np.asarray(s.data, dtype=np.float32).copy()
        m = s.mask.copy() if s.mask is not None else np.zeros_like(d, dtype=bool)
        sz = d.shape[0]

        if sz == max_sz:
            d_pad, m_pad = d, m
        else:
            d_pad = np.full((max_sz, max_sz), np.nan, dtype=np.float32)
            m_pad = np.ones((max_sz, max_sz), dtype=bool)
            half = (sz - 1) // 2
            y0 = half_max - half
            y1 = y0 + sz
            x0 = half_max - half
            x1 = x0 + sz
            d_pad[y0:y1, x0:x1] = d
            m_pad[y0:y1, x0:x1] = m

        # Set masked pixels to NaN
        d_pad[m_pad] = np.nan
        data_cube.append(d_pad)
        mask_cube.append((~m_pad) & np.isfinite(d_pad))

    # Convert to PyTorch tensors on compute device
    tensor_cube = torch.tensor(np.array(data_cube), dtype=torch.float32, device=dev)
    valid_cube = torch.tensor(np.array(mask_cube), dtype=torch.bool, device=dev)

    # 1. First-pass median along stack dimension (dim=0)
    med_2d = torch.nanmedian(tensor_cube, dim=0).values

    # 2. Sigma clipping pass (activated when N >= 3)
    if tensor_cube.shape[0] >= 3:
        diff = torch.abs(tensor_cube - med_2d.unsqueeze(0))
        # Robust standard deviation via Median Absolute Deviation (MAD)
        mad = torch.nanmedian(diff, dim=0).values * 1.4826
        mad = torch.nan_to_num(mad, nan=0.0)
        mad_clamped = torch.clamp(mad, min=1e-6)

        outlier_mask = (diff > (sigma_clip * mad_clamped.unsqueeze(0)))
        tensor_cube[outlier_mask] = float("nan")
    else:
        outlier_mask = torch.zeros_like(valid_cube)

    # 3. Final nanmedian after outlier rejection
    final_stack = torch.nanmedian(tensor_cube, dim=0).values
    final_coverage = torch.sum(valid_cube & (~outlier_mask), dim=0)

    stack_np = final_stack.cpu().numpy()
    cov_np = final_coverage.cpu().numpy()

    # Fill unobserved NaN pixels with 0.0
    stack_np = np.nan_to_num(stack_np, nan=0.0)

    # Hollow core protection fallback: if central pixel was masked in all stamps,
    # recover center from median of immediate 3x3 valid neighborhood
    if stack_np[half_max, half_max] == 0.0:
        box = stack_np[max(0, half_max - 1) : half_max + 2, max(0, half_max - 1) : half_max + 2]
        pos_box = box[box > 0.0]
        if len(pos_box) > 0:
            stack_np[half_max, half_max] = float(np.median(pos_box))

    return stack_np, cov_np


def measure_radial_profile_1d(
    image: np.ndarray,
    mask: Optional[np.ndarray] = None,
    rmax: Optional[int] = None,
    device: Union[str, torch.device] = "cpu",
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Measure robust 1D radial surface brightness profile using profile.py.

    STRICT SCIENTIFIC CONSTRAINT:
    Outputs purely 1D radial vectors strictly for saturation boundary detection
    and cross-tier scalar scaling factors. Never circularizes the 2D image.

    Returns
    -------
    (radii_centers, flux_median, flux_err) : Tuple[np.ndarray, np.ndarray, np.ndarray]
    """
    ny, nx = image.shape
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0

    if rmax is None:
        rmax = int(min(cx, cy))

    rad_bins = np.arange(0.5, rmax + 1.0, 1.0)
    rad_centers = 0.5 * (rad_bins[:-1] + rad_bins[1:])

    data_input = np.ma.masked_array(image, mask=mask) if mask is not None else image
    flux, flux_err = elliptical_profile(
        data=data_input,
        rad=rad_bins,
        center=(cx, cy),
        pa=0.0,
        eps=0.0,
        device=device,
        sigma=3.0,
    )
    return rad_centers, flux, flux_err


def determine_overlap_scale_factor_dual(
    prof_inner: np.ndarray,
    prof_outer: np.ndarray,
    r_inner: np.ndarray,
    r_outer: np.ndarray,
    r_min: float,
    r_max: float,
) -> float:
    """
    Compute robust scalar scale factor between two profiles across overlap range [r_min, r_max],
    taking independent radius vectors to eliminate shape mismatch IndexErrors.

    scale = median(prof_inner / prof_outer)

    Parameters
    ----------
    prof_inner : np.ndarray
        1D flux profile of the inner tier.
    prof_outer : np.ndarray
        1D flux profile of the outer tier.
    r_inner : np.ndarray
        Radius coordinates of prof_inner.
    r_outer : np.ndarray
        Radius coordinates of prof_outer.
    r_min : float
        Inner boundary of overlap annulus.
    r_max : float
        Outer boundary of overlap annulus.

    Returns
    -------
    scale : float
        Robust cross-tier flux scaling factor.
    """
    p_in = np.asarray(prof_inner, dtype=np.float64)
    p_out = np.asarray(prof_outer, dtype=np.float64)
    r_in = np.asarray(r_inner, dtype=np.float64)
    r_out = np.asarray(r_outer, dtype=np.float64)

    mask_in = (r_in >= r_min) & (r_in <= r_max)
    mask_out = (r_out >= r_min) & (r_out <= r_max)

    r_in_sel = r_in[mask_in]
    r_out_sel = r_out[mask_out]

    if len(r_in_sel) == 0 or len(r_out_sel) == 0:
        return 1.0

    # If identical coordinates in the overlap range
    if len(r_in_sel) == len(r_out_sel) and np.allclose(r_in_sel, r_out_sel, atol=1e-3):
        v_in = p_in[mask_in]
        v_out = p_out[mask_out]
    else:
        # Match common coordinates within 1e-3 tolerance
        common_r = np.intersect1d(np.round(r_in_sel, 3), np.round(r_out_sel, 3))
        matched = False
        if len(common_r) >= 1:
            idx_in = np.isin(np.round(r_in, 3), common_r)
            idx_out = np.isin(np.round(r_out, 3), common_r)
            v_in_cand = p_in[idx_in]
            v_out_cand = p_out[idx_out]
            if len(v_in_cand) == len(v_out_cand) and len(v_in_cand) >= 1:
                v_in = v_in_cand
                v_out = v_out_cand
                matched = True

        if not matched:
            # Fallback to linear interpolation of outer profile onto inner radii
            v_in = p_in[mask_in]
            v_out = np.interp(r_in_sel, r_out, p_out)

    valid = np.isfinite(v_in) & np.isfinite(v_out) & (v_in > 0.0) & (v_out > 0.0)
    if np.sum(valid) == 0:
        return 1.0

    ratios = v_in[valid] / v_out[valid]
    scale = float(np.median(ratios))
    return scale if (np.isfinite(scale) and scale > 0.0) else 1.0


def determine_overlap_scale_factor(
    prof_inner: np.ndarray,
    prof_outer: np.ndarray,
    radii: np.ndarray,
    r_min: float,
    r_max: float,
    r_outer: Optional[np.ndarray] = None,
) -> float:
    """
    Backward-compatible wrapper for determine_overlap_scale_factor_dual.

    If r_outer is not provided and prof_inner and prof_outer have differing shapes,
    constructs the appropriate outer radius vector based on radii step.
    """
    if r_outer is None:
        if len(radii) == len(prof_outer):
            r_outer = radii
        elif len(radii) == len(prof_inner):
            step = float(radii[1] - radii[0]) if len(radii) > 1 else 1.0
            r_outer = float(radii[0]) + np.arange(len(prof_outer), dtype=np.float64) * step
        else:
            r_outer = radii
    return determine_overlap_scale_factor_dual(prof_inner, prof_outer, radii, r_outer, r_min, r_max)


def blend_2d_annular_profiles(
    inner_image: np.ndarray,
    outer_image: np.ndarray,
    r_start: float,
    r_end: float,
) -> np.ndarray:
    """
    Blend two concentric 2D images across an annular transition zone [r_start, r_end]
    using a C^1 continuous smooth raised-cosine taper partition of unity.

    w(r) = 1.0                                                  for r <= r_start
    w(r) = 0.5 * (1 + cos(pi * (r - r_start) / (r_end - r_start))) for r in [r_start, r_end]
    w(r) = 0.0                                                  for r >= r_end

    Result = w(r) * inner_image + (1 - w(r)) * outer_image
    Partition of unity: w(r) + (1 - w(r)) == 1.0 everywhere.

    Parameters
    ----------
    inner_image : np.ndarray
        Higher-resolution / unsaturated inner 2D image.
    outer_image : np.ndarray
        Wider-field / scaled outer 2D image (defines output geometry).
    r_start : float
        Inner radius of blending annulus.
    r_end : float
        Outer radius of blending annulus.

    Returns
    -------
    blended : np.ndarray
        Seamlessly blended 2D image preserving non-circular structures and spikes.
    """
    ny, nx = outer_image.shape
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    grid_y, grid_x = np.ogrid[:ny, :nx]
    r = np.sqrt((grid_x - cx) ** 2 + (grid_y - cy) ** 2)

    ny_in, nx_in = inner_image.shape
    if (ny_in, nx_in) == (ny, nx):
        embedded_inner = inner_image
    else:
        embedded_inner = np.zeros((ny, nx), dtype=inner_image.dtype)
        half_in_y = (ny_in - 1) / 2.0
        half_in_x = (nx_in - 1) / 2.0

        y_min_in = max(0, int(round(half_in_y - cy)))
        y_max_in = min(ny_in, int(round(half_in_y + (ny - cy))))
        x_min_in = max(0, int(round(half_in_x - cx)))
        x_max_in = min(nx_in, int(round(half_in_x + (nx - cx))))

        y_min_out = max(0, int(round(cy - half_in_y)))
        y_max_out = y_min_out + (y_max_in - y_min_in)
        x_min_out = max(0, int(round(cx - half_in_x)))
        x_max_out = x_min_out + (x_max_in - x_min_in)

        embedded_inner[y_min_out:y_max_out, x_min_out:x_max_out] = inner_image[
            y_min_in:y_max_in, x_min_in:x_max_in
        ]

    # Compute raised-cosine weighting function
    w = np.zeros((ny, nx), dtype=np.float32)
    w[r <= r_start] = 1.0

    if r_end > r_start:
        transition_mask = (r > r_start) & (r < r_end)
        arg = np.pi * (r[transition_mask] - r_start) / (r_end - r_start)
        w[transition_mask] = 0.5 * (1.0 + np.cos(arg))

    blended = w * embedded_inner + (1.0 - w) * outer_image
    return blended


def _embed_or_crop_canvas(image: np.ndarray, target_sz: int) -> np.ndarray:
    """Helper to symmetrically center-align and embed or crop an image into target_sz canvas."""
    if target_sz % 2 == 0:
        target_sz += 1
    ny, nx = image.shape
    if (ny, nx) == (target_sz, target_sz):
        return image.copy()
    canvas = np.zeros((target_sz, target_sz), dtype=np.float32)
    cy, cx = (target_sz - 1) / 2.0, (target_sz - 1) / 2.0
    half_in_y, half_in_x = (ny - 1) / 2.0, (nx - 1) / 2.0

    y_min_in = max(0, int(round(half_in_y - cy)))
    y_max_in = min(ny, int(round(half_in_y + (target_sz - cy))))
    x_min_in = max(0, int(round(half_in_x - cx)))
    x_max_in = min(nx, int(round(half_in_x + (target_sz - cx))))

    y_min_out = max(0, int(round(cy - half_in_y)))
    y_max_out = y_min_out + (y_max_in - y_min_in)
    x_min_out = max(0, int(round(cx - half_in_x)))
    x_max_out = x_min_out + (x_max_in - x_min_in)

    canvas[y_min_out:y_max_out, x_min_out:x_max_out] = image[y_min_in:y_max_in, x_min_in:x_max_in]
    return canvas


def assemble_composite_extended_psf(
    tier_stamps: Dict[str, List[StellarStamp]],
    output_size: Optional[int] = None,
    cfg: Optional[Any] = None,
    device: Union[str, torch.device] = "cpu",
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Build complete 2D composite extended PSF combining Faint, Medium, and Bright tiers.

    Integrates:
    1. Multi-tier outlier-clipped tensor stacking.
    2. Dual-radius overlap scale factor calibration.
    3. C^1 smooth raised-cosine annular partition-of-unity stitching.
    4. Non-negative clipping and global unit flux normalization.

    Parameters
    ----------
    tier_stamps : dict of list of StellarStamp
        Processed stamps keyed by 'bright', 'medium', 'faint'.
    output_size : int, optional
        Final canvas dimension (e.g. 501, 1025, 2049). Defaults to cfg or stacked bright PSF.
    cfg : AssemblySection, dict, or None
        Configuration parameters for overlap ranges and normalization.
    device : str or torch.device, default 'cpu'
        PyTorch device.

    Returns
    -------
    (extended_psf, diagnostics_dict) : Tuple[np.ndarray, Dict[str, Any]]
    """
    # Extract configuration parameters with robust fallbacks
    stack_sigma = 3.0
    r_fm_min, r_fm_max = 8.0, 16.0
    blend_fm_start, blend_fm_end = 10.0, 18.0
    r_mb_min, r_mb_max = 22.0, 45.0
    blend_mb_start, blend_mb_end = 30.0, 48.0
    normalize_flux = True
    default_canvas_size = 1025

    if cfg is not None:
        if hasattr(cfg, "canvas_size"):
            default_canvas_size = getattr(cfg, "canvas_size", default_canvas_size)
            stack_sigma = getattr(cfg, "stack_sigma_clip", stack_sigma)
            normalize_flux = getattr(cfg, "normalize_flux", normalize_flux)
            fm = getattr(cfg, "overlap_fm", None)
            if fm is not None:
                r_fm_min = getattr(fm, "r_min", r_fm_min)
                r_fm_max = getattr(fm, "r_max", r_fm_max)
                blend_fm_start = getattr(fm, "blend_start", blend_fm_start)
                blend_fm_end = getattr(fm, "blend_end", blend_fm_end)
            mb = getattr(cfg, "overlap_mb", None)
            if mb is not None:
                r_mb_min = getattr(mb, "r_min", r_mb_min)
                r_mb_max = getattr(mb, "r_max", r_mb_max)
                blend_mb_start = getattr(mb, "blend_start", blend_mb_start)
                blend_mb_end = getattr(mb, "blend_end", blend_mb_end)
        elif isinstance(cfg, dict):
            default_canvas_size = cfg.get("canvas_size", default_canvas_size)
            stack_sigma = cfg.get("stack_sigma_clip", stack_sigma)
            normalize_flux = cfg.get("normalize_flux", normalize_flux)
            fm = cfg.get("overlap_fm", {})
            r_fm_min = fm.get("r_min", r_fm_min)
            r_fm_max = fm.get("r_max", r_fm_max)
            blend_fm_start = fm.get("blend_start", blend_fm_start)
            blend_fm_end = fm.get("blend_end", blend_fm_end)
            mb = cfg.get("overlap_mb", {})
            r_mb_min = mb.get("r_min", r_mb_min)
            r_mb_max = mb.get("r_max", r_mb_max)
            blend_mb_start = mb.get("blend_start", blend_mb_start)
            blend_mb_end = mb.get("blend_end", blend_mb_end)

    # 1. Determine which tiers are populated
    stamps_f = tier_stamps.get("faint", [])
    stamps_m = tier_stamps.get("medium", [])
    stamps_b = tier_stamps.get("bright", [])
    has_f = bool(stamps_f)
    has_m = bool(stamps_m)
    has_b = bool(stamps_b)

    if not (has_f or has_m or has_b):
        raise ValueError("Cannot assemble composite extended PSF: all tiers are empty.")

    # 2. Stack available tiers individually in 2D
    psf_faint, cov_faint = (
        stack_tier_stamps_torch(stamps_f, device=device, sigma_clip=stack_sigma)
        if has_f
        else (None, None)
    )
    psf_medium, cov_medium = (
        stack_tier_stamps_torch(stamps_m, device=device, sigma_clip=stack_sigma)
        if has_m
        else (None, None)
    )
    psf_bright, cov_bright = (
        stack_tier_stamps_torch(stamps_b, device=device, sigma_clip=stack_sigma)
        if has_b
        else (None, None)
    )

    # 3. Extract 1D radial profiles strictly with coverage masks (Defect 1 fix)
    r_f, prof_f = (
        measure_radial_profile_1d(psf_faint, mask=(cov_faint == 0), device=device)[:2]
        if has_f
        else (None, None)
    )
    r_m, prof_m = (
        measure_radial_profile_1d(psf_medium, mask=(cov_medium == 0), device=device)[:2]
        if has_m
        else (None, None)
    )
    r_b, prof_b = (
        measure_radial_profile_1d(psf_bright, mask=(cov_bright == 0), device=device)[:2]
        if has_b
        else (None, None)
    )

    # Determine final canvas target dimension
    max_avail_sz = max([p.shape[0] for p in [psf_faint, psf_medium, psf_bright] if p is not None])
    target_sz = output_size if output_size is not None else max(max_avail_sz, default_canvas_size)
    if target_sz % 2 == 0:
        target_sz += 1

    k_fm: Optional[float] = None
    k_mb: Optional[float] = None
    psf_medium_scaled = None
    psf_bright_scaled = None
    prof_m_scaled = None

    # 4. Graceful tier synthesis matrix (Defect 3 fix)
    if has_f and has_m and has_b:
        # Full 3-tier synthesis
        k_fm = determine_overlap_scale_factor_dual(prof_f, prof_m, r_f, r_m, r_min=r_fm_min, r_max=r_fm_max)
        psf_medium_scaled = psf_medium * k_fm
        prof_m_scaled = prof_m * k_fm

        k_mb = determine_overlap_scale_factor_dual(prof_m_scaled, prof_b, r_m, r_b, r_min=r_mb_min, r_max=r_mb_max)
        psf_bright_scaled = psf_bright * k_mb

        psf_fm_blend = blend_2d_annular_profiles(
            inner_image=psf_faint,
            outer_image=psf_medium_scaled,
            r_start=blend_fm_start,
            r_end=blend_fm_end,
        )
        bright_canvas = _embed_or_crop_canvas(psf_bright_scaled, target_sz)
        composite_psf_raw = blend_2d_annular_profiles(
            inner_image=psf_fm_blend,
            outer_image=bright_canvas,
            r_start=blend_mb_start,
            r_end=blend_mb_end,
        )

    elif has_f and has_m:
        # 2-tier synthesis (Faint + Medium, e.g. WFI02)
        k_fm = determine_overlap_scale_factor_dual(prof_f, prof_m, r_f, r_m, r_min=r_fm_min, r_max=r_fm_max)
        psf_medium_scaled = psf_medium * k_fm
        prof_m_scaled = prof_m * k_fm

        psf_fm_blend = blend_2d_annular_profiles(
            inner_image=psf_faint,
            outer_image=psf_medium_scaled,
            r_start=blend_fm_start,
            r_end=blend_fm_end,
        )
        composite_psf_raw = _embed_or_crop_canvas(psf_fm_blend, target_sz)

    elif has_m and has_b:
        # 2-tier synthesis (Medium + Bright)
        k_mb = determine_overlap_scale_factor_dual(prof_m, prof_b, r_m, r_b, r_min=r_mb_min, r_max=r_mb_max)
        psf_bright_scaled = psf_bright * k_mb
        prof_m_scaled = prof_m
        bright_canvas = _embed_or_crop_canvas(psf_bright_scaled, target_sz)
        composite_psf_raw = blend_2d_annular_profiles(
            inner_image=psf_medium,
            outer_image=bright_canvas,
            r_start=blend_mb_start,
            r_end=blend_mb_end,
        )

    elif has_f and has_b:
        # 2-tier synthesis (Faint + Bright direct)
        k_fb = determine_overlap_scale_factor_dual(prof_f, prof_b, r_f, r_b, r_min=10.0, r_max=20.0)
        psf_bright_scaled = psf_bright * k_fb
        k_mb = k_fb
        bright_canvas = _embed_or_crop_canvas(psf_bright_scaled, target_sz)
        composite_psf_raw = blend_2d_annular_profiles(
            inner_image=psf_faint,
            outer_image=bright_canvas,
            r_start=12.0,
            r_end=22.0,
        )

    elif has_f:
        composite_psf_raw = _embed_or_crop_canvas(psf_faint, target_sz)
    elif has_m:
        composite_psf_raw = _embed_or_crop_canvas(psf_medium, target_sz)
    else:
        composite_psf_raw = _embed_or_crop_canvas(psf_bright, target_sz)

    # 5. Clean non-finite and negative noise artifacts
    composite_clean = np.where(np.isfinite(composite_psf_raw), composite_psf_raw, 0.0)
    composite_clean = np.maximum(composite_clean, 0.0)

    # 6. Normalize integrated total flux to unity
    total_flux = float(np.sum(composite_clean))
    if normalize_flux and total_flux > 0.0:
        extended_psf = composite_clean / total_flux
    else:
        extended_psf = composite_clean

    diagnostics = {
        "k_fm": k_fm,
        "k_mb": k_mb,
        "total_flux_raw": total_flux,
        "psf_faint": psf_faint,
        "psf_medium": psf_medium,
        "psf_bright": psf_bright,
        "psf_medium_scaled": psf_medium_scaled,
        "psf_bright_scaled": psf_bright_scaled,
        "cov_faint": cov_faint,
        "cov_medium": cov_medium,
        "cov_bright": cov_bright,
        "r_f": r_f,
        "prof_f": prof_f,
        "r_m": r_m,
        "prof_m_scaled": prof_m_scaled,
        "r_b": r_b,
        "prof_b": prof_b,
    }

    return extended_psf, diagnostics


def serialize_composite_epsf_fits(
    composite_epsf: np.ndarray,
    diagnostics: Dict[str, Any],
    detector_summaries: List[Dict[str, Any]],
    output_fits_path: Union[str, Path],
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
    S = int(composite_epsf.shape[0])

    # 1. Primary HDU
    primary_hdu = fits.PrimaryHDU(data=composite_epsf.astype(np.float32))
    hdr = primary_hdu.header
    hdr["EXTNAME"] = ("EPSF", "Composite 2D Extended Point Spread Function")
    hdr["TELESCOP"] = ("ROMAN", "Roman Space Telescope")
    hdr["INSTRUME"] = ("WFI", "Wide Field Instrument")

    n_det = len(detector_summaries)
    if n_det > 1:
        det_name = "ALL18" if n_det == 18 else "COMPOSITE"
    elif n_det == 1:
        det_name = detector_summaries[0].get("detector", "UNKNOWN").upper()
    else:
        det_name = "COMPOSITE"
    hdr["DETECTOR"] = (det_name, "Sensor Chip Assembly")

    hdr["FILTER"] = (str(filter_name), "WFI filter passband")
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
    hdr["CDELT1"] = (float(pixel_scale) / 3600.0, "[deg/pix] Axis 1 coordinate increment")
    hdr["CDELT2"] = (float(pixel_scale) / 3600.0, "[deg/pix] Axis 2 coordinate increment")
    hdr["CTYPE1"] = ("LINEAR", "Linear coordinate system")
    hdr["CTYPE2"] = ("LINEAR", "Linear coordinate system")
    hdr["CUNIT1"] = ("deg", "Coordinate units")
    hdr["CUNIT2"] = ("deg", "Coordinate units")

    # Contributing detectors and star counts
    hdr["NDET"] = (n_det, "Number of contributing detectors")
    if detector_summaries:
        det_list_str = ",".join([str(d.get("detector", "")) for d in detector_summaries])
        if len(det_list_str) > 68:
            det_list_str = f"{detector_summaries[0].get('detector', '')}..{detector_summaries[-1].get('detector', '')}"
    else:
        det_list_str = "NONE"
    hdr["DETLIST"] = (det_list_str, "Contributing detectors")

    n_f = sum(d.get("faint", 0) for d in detector_summaries)
    n_m = sum(d.get("medium", 0) for d in detector_summaries)
    n_b = sum(d.get("bright", 0) for d in detector_summaries)
    n_tot = n_f + n_m + n_b
    hdr["NSTARS"] = (int(n_tot), "Total stars pooled across all tiers")
    hdr["NSTAR_F"] = (int(n_f), "Stars in faint tier")
    hdr["NSTAR_M"] = (int(n_m), "Stars in medium tier")
    hdr["NSTAR_B"] = (int(n_b), "Stars in bright tier")
    hdr["N_BRIGHT"] = (int(n_b), "Count of bright stars used")
    hdr["N_MEDIUM"] = (int(n_m), "Count of medium stars used")
    hdr["N_FAINT"] = (int(n_f), "Count of faint stars used")
    hdr["N_TOTAL"] = (int(n_tot), "Total count of stars used")

    # Scale factors
    k_fm = diagnostics.get("k_fm")
    k_mb = diagnostics.get("k_mb")
    hdr["SCALE_FM"] = (float(k_fm) if k_fm is not None else 1.0, "Faint-to-Medium scale factor k_FM")
    hdr["SCALE_MB"] = (float(k_mb) if k_mb is not None else 1.0, "Medium-to-Bright scale factor k_MB")
    hdr["K_FM"] = (float(k_fm) if k_fm is not None else -1.0, "Faint-to-Medium scale factor")
    hdr["K_MB"] = (float(k_mb) if k_mb is not None else -1.0, "Medium-to-Bright scale factor")

    # Spike angles and orientation
    base_ang_str = ",".join(f"{a:.2f}" for a in ROMAN_BASE_SPIKE_ANGLES_DEG)
    hdr["BASE_ANG"] = (base_ang_str, "Base spike angles (deg)")
    hdr["DET_OFF"] = (float(NOMINAL_DETECTOR_OFFSET_DEG), "Detector alignment clocking offset (deg)")

    if detector_summaries:
        mean_pa = float(np.mean([d.get("pa_aperture", -110.0) for d in detector_summaries]))
    else:
        mean_pa = -110.0
    hdr["PA_APER"] = (mean_pa, "Mean aperture position angle (deg)")
    net_rot = (mean_pa + NOMINAL_DETECTOR_OFFSET_DEG) % 360.0
    hdr["NET_ROT"] = (float(net_rot), "Net spike rotation angle (deg)")

    # Diagnostics & Provenance
    tot_flux = diagnostics.get("total_flux_raw", 1.0)
    hdr["TOTALFLX"] = (float(tot_flux), "Pre-normalization integrated total flux")
    hdr["SUM_FLUX"] = (float(np.sum(composite_epsf)), "Integrated canvas flux")
    hdr["PEAKFLUX"] = (float(np.max(composite_epsf)), "Peak pixel flux in normalized canvas")
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
    max_profile_r = min(r_max, 500)
    radii = np.arange(1.0, max(max_profile_r, 1) + 1.0, 1.0)
    r_c, prof_c = measure_radial_profile_1d(composite_epsf, rmax=int(radii[-1]))[:2]

    if len(r_c) > 0:
        interp_c = np.interp(radii, r_c, prof_c, right=0.0)
    else:
        interp_c = np.zeros_like(radii)

    prof_dict = {
        "RADIUS_PX": radii,
        "RADIUS_ARCSEC": radii * float(pixel_scale),
        "FLUX_COMPOSITE": interp_c,
    }
    rf = diagnostics.get("r_f")
    pf = diagnostics.get("prof_f")
    if rf is not None and pf is not None and len(rf) > 0 and len(pf) > 0:
        prof_dict["FLUX_FAINT"] = np.interp(radii, rf, pf, right=np.nan)
    rm = diagnostics.get("r_m")
    pm = diagnostics.get("prof_m_scaled")
    if rm is not None and pm is not None and len(rm) > 0 and len(pm) > 0:
        prof_dict["FLUX_MED_SCALED"] = np.interp(radii, rm, pm, right=np.nan)
    rb = diagnostics.get("r_b")
    pb = diagnostics.get("prof_b")
    if rb is not None and pb is not None and len(rb) > 0 and len(pb) > 0:
        k_mb_val = k_mb if k_mb is not None else 1.0
        prof_dict["FLUX_BRIGHT_SCALED"] = np.interp(radii, rb, pb * k_mb_val, right=np.nan)

    prof_table = Table(prof_dict)
    prof_hdu = fits.BinTableHDU(prof_table, name="RADIAL_PROFILES")

    # 4. Secondary HDU: DETECTOR_SUMMARY
    if detector_summaries:
        det_rows = {
            "DETECTOR": [str(d.get("detector", "")) for d in detector_summaries],
            "N_FAINT": [int(d.get("faint", 0)) for d in detector_summaries],
            "N_MEDIUM": [int(d.get("medium", 0)) for d in detector_summaries],
            "N_BRIGHT": [int(d.get("bright", 0)) for d in detector_summaries],
            "N_TOTAL": [int(d.get("total", 0)) for d in detector_summaries],
            "PA_APER_DEG": [float(d.get("pa_aperture", 0.0)) for d in detector_summaries],
            "PIXSCALE": [float(d.get("pixel_scale", pixel_scale)) for d in detector_summaries],
            "TIME_SEC": [float(d.get("time_s", 0.0)) for d in detector_summaries],
            "STATUS": [str(d.get("status", "SUCCESS")) for d in detector_summaries],
        }
    else:
        det_rows = {
            "DETECTOR": np.array([], dtype=str),
            "N_FAINT": np.array([], dtype=int),
            "N_MEDIUM": np.array([], dtype=int),
            "N_BRIGHT": np.array([], dtype=int),
            "N_TOTAL": np.array([], dtype=int),
            "PA_APER_DEG": np.array([], dtype=float),
            "PIXSCALE": np.array([], dtype=float),
            "TIME_SEC": np.array([], dtype=float),
            "STATUS": np.array([], dtype=str),
        }
    det_table = Table(det_rows)
    det_hdu = fits.BinTableHDU(det_table, name="DETECTOR_SUMMARY")

    hdul = fits.HDUList([primary_hdu, cov_hdu, prof_hdu, det_hdu])
    hdul.writeto(target_path, overwrite=True)
    return target_path


__all__ = [
    "stack_tier_stamps_torch",
    "measure_radial_profile_1d",
    "determine_overlap_scale_factor_dual",
    "determine_overlap_scale_factor",
    "blend_2d_annular_profiles",
    "_embed_or_crop_canvas",
    "assemble_composite_extended_psf",
    "serialize_composite_epsf_fits",
]
