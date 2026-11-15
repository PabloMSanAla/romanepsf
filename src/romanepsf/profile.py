#!/usr/bin/env python3
"""
PyTorch-Accelerated Elliptical Surface Brightness Profile Extraction.

STRICT SCIENTIFIC CONSTRAINT:
1D radial profiles via profile.py are strictly reserved for identifying
saturation plateau radii (r_sat) and calculating scalar cross-tier overlap
scale factors (k_FM, k_MB). Azimuthal averaging or circularizing the 2D PSF
canvas is strictly prohibited. The synthesized ePSF model directly retains
full 2D spatial structure and 2D diffraction spikes.
"""

from __future__ import annotations

import time
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple, Union, Any
import numpy as np
import torch

from romanepsf.config import resolve_device

logger = logging.getLogger("romanepsf.profile")


def get_geometric_radial_bins(
    r_min: float = 0.5,
    r_max: float = 500.0,
    growth_rate: float = 1.03,
    as_tensor: bool = False,
    device: Union[str, torch.device] = "cpu",
    dtype: torch.dtype = torch.float32,
) -> Union[np.ndarray, torch.Tensor]:
    """
    Generate logarithmically/geometrically spaced radial bin edges via np.geomspace
    (or torch.logspace for PyTorch tensors) where each consecutive bin grows by growth_rate:
        r_{k+1} = r_k * growth_rate (default 1.03x)

    Parameters
    ----------
    r_min : float, default 0.5
        Inner radius of the first bin boundary in pixels (> 0).
    r_max : float, default 500.0
        Outer radius of the final bin boundary in pixels.
    growth_rate : float, default 1.03
        Multiplicative geometric growth rate per bin (> 1.0).
    as_tensor : bool, default False
        If True, returns a PyTorch 1D Tensor on the target device.
    device : str or torch.device, default 'cpu'
        Target PyTorch device if as_tensor=True.
    dtype : torch.dtype, default torch.float32
        Data type if as_tensor=True.

    Returns
    -------
    bins : np.ndarray or torch.Tensor
        Strictly monotonically increasing geometric bin boundaries from r_min to r_max.
    """
    if r_min <= 0:
        raise ValueError(f"r_min must be strictly positive, got {r_min}")
    if r_max <= r_min:
        raise ValueError(f"r_max ({r_max}) must be greater than r_min ({r_min})")
    if growth_rate <= 1.0:
        raise ValueError(f"growth_rate must be strictly greater than 1.0, got {growth_rate}")

    n_bins = int(np.ceil(np.log(float(r_max) / float(r_min)) / np.log(float(growth_rate)))) + 1
    n_bins = max(n_bins, 2)

    if as_tensor:
        if isinstance(device, str):
            dev = resolve_device(device)
        else:
            dev = device
        log_min = float(np.log10(r_min))
        log_max = float(np.log10(r_max))
        return torch.logspace(log_min, log_max, n_bins, device=dev, dtype=dtype)
    else:
        return np.geomspace(float(r_min), float(r_max), n_bins, dtype=np.float64)


def create_ellipse_meshgrid_torch(
    eps: float,
    pa: float,
    center: Tuple[float, float],
    grid_shape: Tuple[int, int],
    device: Union[str, torch.device] = "cpu",
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """
    Create meshgrid of semimajor axis following an elliptical shape using PyTorch.

    Parameters
    ----------
    eps : float
        Ellipticity of the ellipse (0 <= eps < 1). Clamped to [0.0, 0.9999] for safety.
    pa : float
        Position angle of the ellipse in degrees (counterclockwise from x-axis).
    center : tuple of float
        Center of the ellipse (cx, cy).
    grid_shape : tuple of int
        Shape of the meshgrid (height, width).
    device : str or torch.device, default 'cpu'
        Computing device ('cpu', 'mps', 'cuda', or 'auto').
    dtype : torch.dtype, default torch.float32
        Floating point precision.

    Returns
    -------
    sma : torch.Tensor
        2D Tensor of semi-major axis values.
    """
    if isinstance(device, str):
        dev = resolve_device(device)
    else:
        dev = device

    cx, cy = float(center[0]), float(center[1])
    height, width = int(grid_shape[0]), int(grid_shape[1])

    eps_clamped = float(np.clip(eps, 0.0, 0.9999))

    y = torch.arange(height, device=dev, dtype=dtype) - cy
    x = torch.arange(width, device=dev, dtype=dtype) - cx
    grid_y, grid_x = torch.meshgrid(y, x, indexing="ij")

    pa_rad = float(np.radians(pa))
    cos_pa = float(np.cos(pa_rad))
    sin_pa = float(np.sin(pa_rad))

    x_rot = grid_x * cos_pa + grid_y * sin_pa
    y_rot = -grid_x * sin_pa + grid_y * cos_pa

    sma = torch.sqrt(x_rot**2 + y_rot**2 / ((1.0 - eps_clamped) ** 2))
    return sma


def _clip_single_bin(
    vals_slice: Union[np.ndarray, list],
    maxiters: int = 5,
    sigma: float = 3.0,
) -> Tuple[float, float]:
    """
    Worker function for iterative sigma clipping on a 1D pixel value slice.

    Parameters
    ----------
    vals_slice : array-like
        Raw pixel values within a single radius bin.
    maxiters : int, default 5
        Maximum clipping iterations.
    sigma : float, default 3.0
        Rejection threshold in units of standard deviation.

    Returns
    -------
    (median, std) : tuple of float
        Robust median and standard deviation, or (np.nan, np.nan) if no valid pixels.
    """
    v = np.asarray(vals_slice)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return np.nan, np.nan

    for _ in range(maxiters):
        if len(v) < 2:
            break
        med = float(np.median(v))
        mad = float(np.median(np.abs(v - med)))
        std = 1.4826 * mad if mad > 0.0 else float(np.std(v, ddof=0))
        if std == 0.0:
            break
        mask = np.abs(v - med) <= (sigma * std)
        if np.all(mask):
            break
        v = v[mask]

    if len(v) > 0:
        med_final = float(np.median(v))
        mad_final = float(np.median(np.abs(v - med_final)))
        std_final = 1.4826 * mad_final if mad_final > 0.0 else float(np.std(v, ddof=0))
        return med_final, std_final
    return np.nan, np.nan


def elliptical_profile(
    data: Any,
    rad: Any,
    center: Tuple[float, float],
    pa: float = 0.0,
    eps: float = 0.0,
    device: Union[str, torch.device] = "cpu",
    sigma: float = 3.0,
    maxiters: int = 5,
    num_workers: int = 8,
    return_timings: bool = False,
) -> Union[Tuple[np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray, Dict[str, float]]]:
    """
    Measure the elliptical radial profile of an image using PyTorch acceleration.

    STRICT SCIENTIFIC CONSTRAINT:
    Used strictly for saturation plateau detection and overlap scale factor calibration.
    Does NOT circularize or average the underlying 2D image data.

    Parameters
    ----------
    data : array_like or np.ma.MaskedArray
        2D image array.
    rad : array_like
        Array of radius bin edges (at least 2 edges).
    center : tuple of float
        (cx, cy) coordinates of the stellar centroid in pixels.
    pa : float, default 0.0
        Position angle in degrees.
    eps : float, default 0.0
        Ellipticity (0 <= eps < 1).
    device : str or torch.device, default 'cpu'
        Computing device ('cpu', 'mps', 'cuda', 'auto').
    sigma : float, default 3.0
        Clipping threshold in standard deviations.
    maxiters : int, default 5
        Maximum clipping iterations.
    num_workers : int, default 8
        Number of worker threads for parallel bin clipping.
    return_timings : bool, default False
        Whether to return execution stage breakdown timings.

    Returns
    -------
    flux : np.ndarray
        Median flux in each radius bin.
    flux_err : np.ndarray
        Standard deviation in each radius bin.
    timings : dict, optional
        Breakdown of elapsed execution time per stage.
    """
    t_start = time.perf_counter()
    timings = {}

    rad_arr = np.asarray(rad, dtype=np.float32)
    if len(rad_arr) < 2:
        raise ValueError("rad must contain at least 2 bin edges.")

    # Extract raw data and mask
    if hasattr(data, "mask") and np.any(data.mask):
        mask = np.asarray(data.mask, dtype=bool)
        raw_data = np.asarray(data.data, dtype=np.float32)
    else:
        mask = None
        raw_data = np.asarray(data, dtype=np.float32)

    if raw_data.ndim != 2:
        raise ValueError("Image data must be a 2D array.")

    # Ensure native byte-order (FITS data is often big-endian '>f4')
    if raw_data.dtype.byteorder not in ("=", "|"):
        raw_data = raw_data.astype(np.float32)

    if isinstance(device, str):
        dev = resolve_device(device)
    else:
        dev = device

    # Stage 1: Compute elliptical coordinates on PyTorch device
    t0 = time.perf_counter()
    sma = create_ellipse_meshgrid_torch(eps, pa, center, raw_data.shape, device=dev)
    if dev.type == "mps" and hasattr(torch, "mps"):
        torch.mps.synchronize()
    elif dev.type == "cuda" and torch.cuda.is_available():
        torch.cuda.synchronize()
    t1 = time.perf_counter()
    timings["meshgrid_time"] = t1 - t0

    # Stage 2: Flatten and filter masked values
    t0 = time.perf_counter()
    sma_flat = sma.cpu().flatten()
    vals_flat = torch.from_numpy(raw_data).flatten()

    if mask is not None:
        valid_pixel_mask = torch.from_numpy(~mask).flatten()
        sma_flat = sma_flat[valid_pixel_mask]
        vals_flat = vals_flat[valid_pixel_mask]

    # Stage 3: Bin digitizing / bucketize and sorting
    rad_t = torch.from_numpy(rad_arr)
    bin_idx = torch.bucketize(sma_flat, rad_t) - 1

    num_bins = len(rad_arr) - 1
    valid_bins = (bin_idx >= 0) & (bin_idx < num_bins)
    bin_idx = bin_idx[valid_bins]
    vals_flat = vals_flat[valid_bins]

    sort_order = torch.argsort(bin_idx)
    vals_sorted = vals_flat[sort_order].numpy()
    bin_sorted = bin_idx[sort_order]

    counts = torch.bincount(bin_sorted, minlength=num_bins).numpy()
    offsets = np.zeros(num_bins + 1, dtype=int)
    offsets[1:] = np.cumsum(counts)
    t2 = time.perf_counter()
    timings["bin_sort_time"] = t2 - t0

    # Stage 4: Parallel robust statistics per bin
    t0 = time.perf_counter()
    flux = np.full(num_bins, np.nan, dtype=np.float32)
    flux_err = np.full(num_bins, np.nan, dtype=np.float32)

    def process_bin(b: int) -> Tuple[int, float, float]:
        c = counts[b]
        if c == 0:
            return b, np.nan, np.nan
        v_slice = vals_sorted[offsets[b] : offsets[b + 1]]
        med, std = _clip_single_bin(v_slice, maxiters=maxiters, sigma=sigma)
        return b, med, std

    workers = min(num_workers, max(1, num_bins))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = executor.map(process_bin, range(num_bins))
        for b, med, std in results:
            flux[b] = med
            flux_err[b] = std

    t3 = time.perf_counter()
    timings["sigma_clip_time"] = t3 - t0
    timings["total_profile_time"] = t3 - t_start

    if return_timings:
        return flux, flux_err, timings
    return flux, flux_err


def get_psf_extension_moffat(
    mag: Any,
    depth: float = 30.0,
    alpha: float = 0.08,
    beta: float = 1.52,
) -> Union[float, np.ndarray]:
    """
    Analytically calculate the PSF extension based on a standard Moffat profile at a given depth.

    Parameters
    ----------
    mag : float or array-like
        Magnitude(s) of the star.
    depth : float, default 30.0
        Surface brightness detection depth in mag arcsecond^-2.
    alpha : float, default 0.08
        Scale parameter of the Moffat profile in arcseconds.
    beta : float, default 1.52
        Shape parameter (power-law index) of the Moffat profile. Must be > 1.0.

    Returns
    -------
    extension : float or np.ndarray
        PSF extension in arcseconds.
    """
    if beta <= 1.0:
        raise ValueError("Moffat beta parameter must be > 1.0 for finite integrated flux.")

    mag_arr = np.asarray(mag, dtype=float)

    # Integrated volume normalization constant term
    term_c = (np.pi * alpha**2) / (beta - 1.0)
    mu0 = mag_arr + 2.5 * np.log10(term_c)

    # Invert Moffat surface brightness profile to solve for radius r
    exponent = (depth - mu0) / (2.5 * beta)
    bracket = 10.0**exponent - 1.0
    bracket_pos = np.maximum(bracket, 0.0)

    extension = alpha * np.sqrt(bracket_pos)
    return float(extension.item()) if extension.ndim == 0 else extension


def measure_angular_profile_torch(
    image: np.ndarray,
    center: Tuple[float, float],
    dq_mask: Optional[np.ndarray] = None,
    comp_mask: Optional[np.ndarray] = None,
    companions: Optional[Sequence[Dict[str, Any]]] = None,
    core_rad: float = 6.0,
    r_min: float = 1.0,
    r_max: Optional[float] = None,
    num_bins: int = 360,
    device: Union[str, torch.device] = "cpu",
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Measure full-image azimuthal (angular) intensity profile theta in [0, 360) deg using PyTorch.

    Vectorized implementation:
    1. Generates 2D meshgrid of polar coordinates (r, theta) on the computing device.
    2. Excludes non-finite values, central core singularity (r < r_min), data quality flags (dq_mask),
       and other Gaia companion stars (comp_mask or companions list).
    3. Digitize angular distribution into equally spaced theta bins using torch.bucketize.
    4. Computes median flux within each bin without per-pixel Python loops.

    Parameters
    ----------
    image : np.ndarray
        2D image array (e.g. residual map or stamp).
    center : tuple of float
        (cx, cy) coordinates of the primary star centroid.
    dq_mask : np.ndarray, optional
        Data quality flag bitmask or boolean mask. Non-zero/True pixels are excluded.
    comp_mask : np.ndarray, optional
        Boolean mask of neighbor companion star apertures to exclude.
    companions : list of dict, optional
        List of companion star dicts with 'x', 'y', and 'radius_px' (used if comp_mask is None).
    core_rad : float, default 6.0
        Core protection radius; companion exclusion masks apply strictly outside this radius.
    r_min : float, default 1.0
        Inner radius cutoff to avoid the centroid coordinate singularity.
    r_max : float, optional
        Outer radius cutoff. If None, considers all valid pixels across the entire image.
    num_bins : int, default 360
        Number of equally spaced angular bins covering [0, 360) degrees.
    device : str or torch.device, default 'cpu'
        Target computing device ('cpu', 'mps', 'cuda', or 'auto').

    Returns
    -------
    bin_centers : np.ndarray
        Array of bin center angles in degrees in [0, 360).
    medians : np.ndarray
        Median intensity in each angular bin (NaN if bin contains no valid pixels).
    """
    if isinstance(device, str):
        dev = resolve_device(device)
    else:
        dev = device

    raw_data = np.asarray(image, dtype=np.float32)
    if raw_data.ndim != 2:
        raise ValueError(f"Image data must be a 2D array, got shape {raw_data.shape}")

    # Ensure native byte-order
    if raw_data.dtype.byteorder not in ("=", "|"):
        raw_data = raw_data.astype(np.float32)

    ny, nx = raw_data.shape
    cx, cy = float(center[0]), float(center[1])

    data_t = torch.as_tensor(raw_data, dtype=torch.float32, device=dev)

    gy, gx = torch.meshgrid(
        torch.arange(ny, device=dev, dtype=torch.float32),
        torch.arange(nx, device=dev, dtype=torch.float32),
        indexing="ij",
    )
    dy = gy - cy
    dx = gx - cx
    theta = torch.remainder(torch.rad2deg(torch.atan2(dy, dx)), 360.0)
    r = torch.hypot(dx, dy)

    valid = torch.isfinite(data_t) & (r >= float(r_min))
    if r_max is not None:
        valid &= (r <= float(r_max))

    if dq_mask is not None:
        dq_t = torch.as_tensor(dq_mask > 0, dtype=torch.bool, device=dev)
        valid &= (~dq_t)

    if comp_mask is not None:
        c_mask_t = torch.as_tensor(comp_mask > 0, dtype=torch.bool, device=dev)
        valid &= (~c_mask_t)
    elif companions:
        c_mask_t = torch.zeros((ny, nx), dtype=torch.bool, device=dev)
        for comp in companions:
            cx_c = float(comp.get("x", 0.0))
            cy_c = float(comp.get("y", 0.0))
            r_c = float(comp.get("radius_px", 3.0))
            dist_comp = torch.hypot(gx - cx_c, gy - cy_c)
            c_mask_t |= (dist_comp <= r_c)
        c_mask_t &= (r > float(core_rad))
        valid &= (~c_mask_t)

    bin_edges = torch.linspace(0.0, 360.0, num_bins + 1, device=dev)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    th_v = theta[valid]
    val_v = data_t[valid]

    if th_v.numel() == 0:
        return bin_centers.cpu().numpy(), np.full(num_bins, np.nan, dtype=np.float32)

    bin_scale = float(num_bins) / 360.0
    bin_idx = torch.clamp(
        torch.floor(th_v * bin_scale).to(torch.long),
        0,
        num_bins - 1,
    )

    sort_order = torch.argsort(bin_idx)
    bin_sorted = bin_idx[sort_order]
    val_sorted = val_v[sort_order]

    counts = torch.bincount(bin_sorted, minlength=num_bins)
    offsets = torch.zeros(num_bins + 1, dtype=torch.long, device=dev)
    offsets[1:] = torch.cumsum(counts, dim=0)

    medians = torch.full((num_bins,), float("nan"), dtype=torch.float32, device=dev)
    for b in range(num_bins):
        cnt = int(counts[b].item())
        if cnt > 0:
            medians[b] = torch.median(val_sorted[offsets[b] : offsets[b + 1]])

    return bin_centers.cpu().numpy(), medians.cpu().numpy()


def save_spike_polar_profiles_parquet(
    pooled_stamps: Dict[str, Sequence[Any]],
    output_parquet_path: Union[str, Path],
    sca_name: Union[int, str] = "wfi01",
) -> Path:
    """
    Extract and save polar profiles (intensity vs theta) and detected spike angles
    for all stars in a run into a Parquet table.

    Parameters
    ----------
    pooled_stamps : dict
        Dictionary mapping tier names ('bright', 'medium', 'faint') to lists of StellarStamp objects.
    output_parquet_path : str or Path
        Target destination path for the .parquet table.
    sca_name : int or str, default 'wfi01'
        SCA detector identifier (e.g. 1, 18, 'wfi01').

    Returns
    -------
    Path
        Path to the saved Parquet table.
    """
    import pandas as pd
    from romanepsf.config import normalize_sca_id

    sca_str = normalize_sca_id(sca_name)
    out_path = Path(output_parquet_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, Any]] = []

    for tier_name in ["bright", "medium", "faint"]:
        stamps = pooled_stamps.get(tier_name, [])
        for stamp in stamps:
            sid = getattr(stamp, "source_id", None)
            mag = float(getattr(stamp, "mag", np.nan))
            dbg = getattr(stamp, "debug_info", None) or {}
            spike_det = dbg.get("spike_details") or {}

            # Center coordinates
            center_xy = dbg.get("center_stamp", getattr(stamp, "center_original", (np.nan, np.nan)))
            cx, cy = (float(center_xy[0]), float(center_xy[1])) if center_xy is not None else (np.nan, np.nan)

            # Extract polar profile
            theta = spike_det.get("angular_profile_theta")
            flux = spike_det.get("angular_profile_flux")

            # Detected spike angles
            prim_angles = spike_det.get("primary_spike_angles", [])
            sec_angles = spike_det.get("secondary_spike_angles", [])
            all_angles = spike_det.get("refined_spike_angles", [])

            if theta is None or flux is None:
                # If spike_details were not populated, compute profile on the fly
                stamp_data = getattr(stamp, "data", None)
                if stamp_data is not None and getattr(stamp_data, "size", 0) > 0:
                    try:
                        th_calc, flx_calc = measure_angular_profile_torch(
                            data=stamp_data,
                            center=(cx, cy),
                            num_bins=360,
                        )
                        theta = th_calc
                        flux = flx_calc
                    except Exception:
                        theta = np.linspace(0.5, 359.5, 360)
                        flux = np.full(360, np.nan)
                else:
                    theta = np.linspace(0.5, 359.5, 360)
                    flux = np.full(360, np.nan)

            rec = {
                "source_id": str(sid) if sid is not None else "",
                "sca": sca_str,
                "tier": str(tier_name),
                "mag": mag,
                "center_x": cx,
                "center_y": cy,
                "n_primary_spikes": int(len(prim_angles)),
                "n_secondary_spikes": int(len(sec_angles)),
                "primary_spike_angles": [float(a) for a in prim_angles],
                "secondary_spike_angles": [float(a) for a in sec_angles],
                "all_spike_angles": [float(a) for a in all_angles],
                "theta_deg": [float(t) for t in theta],
                "polar_flux": [float(f) for f in flux],
            }
            records.append(rec)

    df = pd.DataFrame(records)
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved {len(df)} star polar profiles for {sca_str} to Parquet: {out_path}")
    return out_path


__all__ = [
    "get_geometric_radial_bins",
    "create_ellipse_meshgrid_torch",
    "elliptical_profile",
    "get_psf_extension_moffat",
    "measure_angular_profile_torch",
    "save_spike_polar_profiles_parquet",
]

