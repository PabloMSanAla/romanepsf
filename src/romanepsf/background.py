"""
NoiseChisel sky background and noise measurement for Roman Level 2 detector images.

Provides GPU/PyTorch accelerated estimation of 2D sky background and standard deviation
maps using noisechisel-torch (Gnuastro's NoiseChisel algorithm).
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple, Union, Any
import numpy as np

logger = logging.getLogger("romanepsf.background")


def resolve_noisechisel_device(device: Optional[str] = None) -> str:
    """
    Resolve the optimal compute device for NoiseChisel.

    Parameters
    ----------
    device : str, optional
        Requested device string ('auto', 'cpu', 'cuda', 'mps').

    Returns
    -------
    str
        'cuda' if CUDA is available and requested, otherwise 'cpu'.
    """
    import torch

    req = str(device).lower().strip() if device is not None else "auto"
    if req in ("auto", "cuda", "gpu"):
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"
    if req == "mps":
        # noisechisel-torch requires float64 precision for some quantile stats,
        # which MPS does not support; default cleanly to CPU without warnings.
        return "cpu"
    return "cpu"


def estimate_detector_sky_noisechisel(
    image: np.ndarray,
    dq_mask: Optional[np.ndarray] = None,
    device: Optional[str] = "auto",
    tilesize: Tuple[int, int] = (30, 30),
    interpnumngb: int = 15,
    verbose: bool = False,
    **kwargs: Any,
) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """
    Measure full 2D sky background and sky noise standard deviation maps
    using the PyTorch implementation of NoiseChisel (noisechisel-torch).

    Runs once for an entire Roman detector image (e.g. 4088 x 4088).

    Parameters
    ----------
    image : np.ndarray
        2D detector science flux array (e.g. calibrated surface brightness MJy/sr).
    dq_mask : np.ndarray, optional
        Boolean bad pixel mask (True = flagged/bad/saturated pixel to ignore).
    device : str, default 'auto'
        Execution device ('auto', 'cpu', 'cuda').
    tilesize : Tuple[int, int], default (30, 30)
        Tile dimension in pixels for tessellation.
    interpnumngb : int, default 15
        Number of nearest neighbors for tile interpolation.
    verbose : bool, default False
        If True, prints NoiseChisel step timing diagnostics.
    **kwargs : Any
        Additional keyword options passed to NoiseChisel.

    Returns
    -------
    sky_map : np.ndarray
        2D float32 image of smooth sky background across detector.
    std_map : np.ndarray
        2D float32 image of sky noise standard deviation across detector.
    sky_val : float
        Robust median scalar sky background value.
    std_val : float
        Robust median scalar sky noise standard deviation.
    """
    target_device = resolve_noisechisel_device(device)
    ny, nx = image.shape

    # Prepare input array with masked and non-finite pixels set to NaN
    work_img = np.array(image, dtype=np.float32, copy=True)
    if dq_mask is not None:
        work_img[dq_mask] = np.nan
    work_img[~np.isfinite(work_img)] = np.nan

    # Guard for small images (e.g., unit test mock fixtures)
    min_tiles_needed = max(interpnumngb + 1, 16)
    est_tiles_y = ny // tilesize[0]
    est_tiles_x = nx // tilesize[1]
    if (est_tiles_y * est_tiles_x) < min_tiles_needed or ny < 120 or nx < 120:
        logger.debug(
            f"Image shape {image.shape} is too small for standard tilesize {tilesize}. "
            "Using fallback robust sigma-clipped sky estimation."
        )
        return _fallback_sky_estimation(work_img)

    try:
        import noisechisel_torch as nc

        runner = nc.NoiseChisel(
            device=target_device,
            tilesize=tilesize,
            interpnumngb=interpnumngb,
            verbose=verbose,
            **kwargs,
        )
        res = runner(work_img)
        res_dict = res.numpy()

        sky_map = np.asarray(res_dict["sky"], dtype=np.float32)
        std_map = np.asarray(res_dict["std"], dtype=np.float32)

        # Robust scalar summaries
        valid_sky = sky_map[np.isfinite(sky_map)]
        sky_val = float(np.median(valid_sky)) if len(valid_sky) > 0 else 0.0

        if hasattr(res, "med_std") and np.isfinite(res.med_std):
            std_val = float(res.med_std)
        else:
            valid_std = std_map[np.isfinite(std_map)]
            std_val = float(np.median(valid_std)) if len(valid_std) > 0 else 1.0

        # Fill any remaining unobserved NaN boundary tiles with median values
        sky_map = np.where(np.isfinite(sky_map), sky_map, sky_val).astype(np.float32)
        std_map = np.where(np.isfinite(std_map), std_map, std_val).astype(np.float32)

        logger.info(
            f"NoiseChisel detector sky background: median={sky_val:.5f}, "
            f"sky std: median={std_val:.5f} [device={target_device}]"
        )
        return sky_map, std_map, sky_val, std_val

    except Exception as exc:
        logger.warning(
            f"NoiseChisel execution encountered an issue ({exc}). "
            "Falling back to robust sigma-clipped sky estimation.",
            exc_info=True,
        )
        return _fallback_sky_estimation(work_img)


def _fallback_sky_estimation(
    work_img: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """Fallback sigma-clipped sky estimation for mock fixtures or failed tile runs."""
    valid = work_img[np.isfinite(work_img)]
    if len(valid) == 0:
        sky_val = 0.0
        std_val = 1.0
    else:
        try:
            from astropy.stats import sigma_clipped_stats
            _, med_val, s_val = sigma_clipped_stats(valid, sigma=3.0, maxiters=5)
            sky_val = float(med_val)
            std_val = float(s_val) if (s_val is not None and s_val > 0) else float(np.std(valid))
        except Exception:
            sky_val = float(np.median(valid))
            mad = float(np.median(np.abs(valid - sky_val)))
            std_val = float(1.4826 * mad) if mad > 0 else float(np.std(valid))

    if not np.isfinite(std_val) or std_val <= 0:
        std_val = 1.0

    sky_map = np.full(work_img.shape, sky_val, dtype=np.float32)
    std_map = np.full(work_img.shape, std_val, dtype=np.float32)
    return sky_map, std_map, sky_val, std_val
