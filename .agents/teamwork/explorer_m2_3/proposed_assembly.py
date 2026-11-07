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
import numpy as np
import torch

try:
    from romanepsf.stamps import StellarStamp
except ImportError:
    try:
        from src.stamps import StellarStamp
    except ImportError:
        from dataclasses import dataclass

        @dataclass
        class StellarStamp:
            source_id: Any
            tier: str
            mag: float
            data: np.ndarray
            mask: np.ndarray
            center_original: Tuple[float, float]
            size: int
            norm_factor: float = 1.0

try:
    from romanepsf.profile import elliptical_profile
except ImportError:
    try:
        from src.profile import elliptical_profile
    except ImportError:
        from .proposed_profile import elliptical_profile

try:
    from romanepsf.config import resolve_device, AssemblySection, OverlapAnnulusConfig
except ImportError:
    try:
        from src.romanepsf.config import resolve_device, AssemblySection, OverlapAnnulusConfig
    except ImportError:
        def resolve_device(device_str: str = "auto") -> torch.device:
            dev = str(device_str).lower().strip()
            if dev == "auto":
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    return torch.device("mps")
                elif torch.cuda.is_available():
                    return torch.device("cuda")
                else:
                    return torch.device("cpu")
            elif dev in ("mps", "cuda", "cpu"):
                return torch.device(dev)
            return torch.device("cpu")

        class OverlapAnnulusConfig:
            def __init__(self, r_min: float, r_max: float, blend_start: float = 10.0, blend_end: float = 18.0):
                self.r_min = r_min
                self.r_max = r_max
                self.blend_start = blend_start
                self.blend_end = blend_end

        class AssemblySection:
            def __init__(self, canvas_size: int = 1025, stack_sigma_clip: float = 3.0, normalize_flux: bool = True):
                self.canvas_size = canvas_size
                self.stack_sigma_clip = stack_sigma_clip
                self.overlap_fm = OverlapAnnulusConfig(8.0, 16.0, 10.0, 18.0)
                self.overlap_mb = OverlapAnnulusConfig(22.0, 45.0, 30.0, 48.0)
                self.normalize_flux = normalize_flux


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
        d = s.data.copy()
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
        mask_cube.append(~m_pad)

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
        if len(common_r) >= 1:
            idx_in = np.isin(np.round(r_in, 3), common_r)
            idx_out = np.isin(np.round(r_out, 3), common_r)
            v_in = p_in[idx_in]
            v_out = p_out[idx_out]
        else:
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
    elif ny_in <= ny and nx_in <= nx:
        # Embed smaller inner image into outer canvas center
        embedded_inner = np.zeros((ny, nx), dtype=inner_image.dtype)
        half_in_y = (ny_in - 1) // 2
        half_in_x = (nx_in - 1) // 2
        y0 = int(round(cy - half_in_y))
        y1 = y0 + ny_in
        x0 = int(round(cx - half_in_x))
        x1 = x0 + nx_in
        embedded_inner[y0:y1, x0:x1] = inner_image
    else:
        # Inner image is larger than outer canvas, center-crop inner image
        half_y = (ny - 1) // 2
        half_x = (nx - 1) // 2
        cy_in = (ny_in - 1) // 2
        cx_in = (nx_in - 1) // 2
        embedded_inner = inner_image[
            cy_in - half_y : cy_in + half_y + 1,
            cx_in - half_x : cx_in + half_x + 1,
        ].copy()

    # Compute raised-cosine weighting function
    w = np.zeros((ny, nx), dtype=np.float32)
    w[r <= r_start] = 1.0

    if r_end > r_start:
        transition_mask = (r > r_start) & (r < r_end)
        arg = np.pi * (r[transition_mask] - r_start) / (r_end - r_start)
        w[transition_mask] = 0.5 * (1.0 + np.cos(arg))

    blended = w * embedded_inner + (1.0 - w) * outer_image
    return blended


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

    # 1. Stack each tier individually in 2D
    psf_faint, cov_faint = stack_tier_stamps_torch(tier_stamps["faint"], device=device, sigma_clip=stack_sigma)
    psf_medium, cov_medium = stack_tier_stamps_torch(tier_stamps["medium"], device=device, sigma_clip=stack_sigma)
    psf_bright, cov_bright = stack_tier_stamps_torch(tier_stamps["bright"], device=device, sigma_clip=stack_sigma)

    # 2. Extract 1D radial profiles strictly for overlap calibration
    r_f, prof_f, _ = measure_radial_profile_1d(psf_faint, device=device)
    r_m, prof_m, _ = measure_radial_profile_1d(psf_medium, device=device)
    r_b, prof_b, _ = measure_radial_profile_1d(psf_bright, device=device)

    # Overlap 1: Faint <-> Medium (dual-radius matching)
    k_fm = determine_overlap_scale_factor_dual(prof_f, prof_m, r_f, r_m, r_min=r_fm_min, r_max=r_fm_max)
    psf_medium_scaled = psf_medium * k_fm
    prof_m_scaled = prof_m * k_fm

    # Overlap 2: Medium <-> Bright (dual-radius matching)
    k_mb = determine_overlap_scale_factor_dual(prof_m_scaled, prof_b, r_m, r_b, r_min=r_mb_min, r_max=r_mb_max)
    psf_bright_scaled = psf_bright * k_mb

    # 3. Blend Faint (core) and Scaled Medium (transition)
    psf_fm_blend = blend_2d_annular_profiles(
        inner_image=psf_faint,
        outer_image=psf_medium_scaled,
        r_start=blend_fm_start,
        r_end=blend_fm_end,
    )

    # 4. Canvas sizing: Handle embedding or cropping bright PSF
    target_sz = output_size if output_size is not None else max(psf_bright.shape[0], default_canvas_size)
    if target_sz % 2 == 0:
        target_sz += 1

    bright_sz = psf_bright_scaled.shape[0]
    if bright_sz == target_sz:
        bright_canvas = psf_bright_scaled
    elif bright_sz < target_sz:
        # Embed smaller bright PSF into larger target canvas
        bright_canvas = np.zeros((target_sz, target_sz), dtype=np.float32)
        half_t = (target_sz - 1) // 2
        half_b = (bright_sz - 1) // 2
        y0 = half_t - half_b
        x0 = half_t - half_b
        bright_canvas[y0 : y0 + bright_sz, x0 : x0 + bright_sz] = psf_bright_scaled
    else:
        # Crop larger bright PSF down to target canvas
        half_t = (target_sz - 1) // 2
        half_b = (bright_sz - 1) // 2
        y0 = half_b - half_t
        x0 = half_b - half_t
        bright_canvas = psf_bright_scaled[y0 : y0 + target_sz, x0 : x0 + target_sz].copy()

    # Blend Faint-Medium and Scaled Bright (wings + spikes)
    composite_psf_raw = blend_2d_annular_profiles(
        inner_image=psf_fm_blend,
        outer_image=bright_canvas,
        r_start=blend_mb_start,
        r_end=blend_mb_end,
    )

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
