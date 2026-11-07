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

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Tuple, Union, Any
import numpy as np
import torch

try:
    from romanepsf.config import resolve_device
except ImportError:
    try:
        from src.romanepsf.config import resolve_device
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
