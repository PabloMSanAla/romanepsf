"""
Roman Space Telescope Level 2 ASDF Data Loader and Calibrator.

Loads Level 2 ASDF data using roman_datamodels, applies photometric calibration,
extracts WCS, science data, error, and data quality (DQ) bitmasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import logging
import warnings

import numpy as np
import roman_datamodels as rdm

# Suppress harmless ASDF package version warnings
try:
    from asdf.exceptions import AsdfPackageVersionWarning
    warnings.filterwarnings("ignore", category=AsdfPackageVersionWarning)
except ImportError:
    pass
warnings.filterwarnings("ignore", message=r".*was created with extension URI.*")
warnings.filterwarnings("ignore", message=r".*AsdfPackageVersionWarning.*")

logger = logging.getLogger("romanepsf.loader")

ACTIVE_SHAPE: Tuple[int, int] = (4088, 4088)
NOMINAL_PIXEL_SCALE: float = 0.11  # arcsec/pixel
NOMINAL_PIXEL_AREA: float = 2.800978e-13  # steradians

# Roman Data Quality bit flags (matching roman_datamodels.dqflags.pixel)
DQ_FLAGS: Dict[str, int] = {
    "GOOD": 0,                   # 0x00000000
    "DO_NOT_USE": 1,             # 0x00000001 (Bit 0): Pixel bad, do not use
    "SATURATED": 2,              # 0x00000002 (Bit 1): Saturated in ramp fit
    "JUMP_DET": 4,               # 0x00000004 (Bit 2): Cosmic ray / jump detected
    "DROPOUT": 8,                # 0x00000008 (Bit 3): Data lost in transmission
    "OUTLIER": 128,              # 0x00000080 (Bit 7): Spatial / temporal outlier
    "NON_SCIENCE": 512,          # 0x00000200 (Bit 9): Non-science pixel
    "DEAD": 1024,                # 0x00000400 (Bit 10): Dead / unresponsive pixel
    "HOT": 2048,                 # 0x00000800 (Bit 11): Unstable hot pixel
    "WARM": 4096,                # 0x00001000 (Bit 12): Warm pixel / high dark current
    "PERSISTENCE": 4096,         # Bit 12 alias
    "LOW_QE": 8192,              # 0x00002000 (Bit 13): Low quantum efficiency
    "NONLINEAR": 65536,          # 0x00010000 (Bit 16): Non-linear response
    "BAD_REF_PIXEL": 131072,     # 0x00020000 (Bit 17): Bad reference pixel
    "OTHER_BAD_PIXEL": 1073741824, # 0x40000000 (Bit 30): Other uncharacterized defect
}

DEFAULT_DQ_MASK_FLAGS = ["DO_NOT_USE", "SATURATED", "DROPOUT"]


@dataclass
class RomanL2Data:
    """Container for calibrated Roman Level 2 detector data."""
    detector: str
    filter_name: str
    data: np.ndarray            # Science flux array (calibrated, e.g. MJy/sr if calibrate=True)
    raw_data: np.ndarray        # Original count rate array (DN/s)
    err: np.ndarray             # Error array (scaled identically to data)
    dq: np.ndarray              # 32-bit Data Quality bitmask array
    wcs: Any                    # GWCS object connecting detector to world coordinates
    pa_aperture: float          # Aperture position angle in degrees
    pixel_scale: float          # Pixel scale in arcsec/pixel (nominal ~0.11)
    conversion_factor: float    # Calibration factor from DN/s to MJy/sr (conversion_megajanskys)
    pixel_area: float           # Pixel area in steradians
    zp_ab: float                # Photometric zero-point in AB magnitude
    meta: Dict[str, Any]        # Complete metadata dictionary
    is_calibrated: bool = True  # True if data is in surface brightness units (MJy/sr)
    var_poisson: Optional[np.ndarray] = None  # Poisson variance array from Level 2 ASDF
    sky_bkg: Optional[np.ndarray] = None      # Deprecated: None to save memory (no big array)
    sky_std: Optional[np.ndarray] = None      # Deprecated: None to save memory (no big array)
    sky_bkg_val: Optional[float] = None       # Robust median scalar sky background
    sky_std_val: Optional[Union[float, int]] = None       # Robust median scalar sky noise std

    def __post_init__(self) -> None:
        if self.data is not None:
            if self.err is not None and self.err.shape != self.data.shape:
                raise ValueError(
                    f"err array shape {self.err.shape} does not match data shape {self.data.shape}"
                )
            if self.dq is not None and self.dq.shape != self.data.shape:
                raise ValueError(
                    f"dq array shape {self.dq.shape} does not match data shape {self.data.shape}"
                )

    @property
    def shape(self) -> Tuple[int, int]:
        return self.data.shape

    def get_dq_mask(self, flags: Optional[Sequence[str]] = None, bitmask: Optional[int] = None) -> np.ndarray:
        """Return boolean bad pixel mask using instance DQ array."""
        return get_dq_mask(self.dq, flags=flags, bitmask=bitmask)

    def get_effective_mask(self, flags: Optional[Sequence[str]] = None, bitmask: Optional[int] = None) -> np.ndarray:
        """Return combined mask of DQ flags and non-finite (NaN/Inf) pixels."""
        return get_effective_mask(self.data, self.dq, flags=flags, bitmask=bitmask)

    def measure_sky_noisechisel(
        self,
        device: Optional[str] = "auto",
        overwrite: bool = False,
        verbose: bool = False,
        subtract_sky: bool = True,
        **kwargs: Any,
    ) -> Tuple[float, float]:
        """
        Measure sky background and sky noise standard deviation using NoiseChisel
        once for this detector, optionally subtracts sky from data, and returns scalar values.

        Parameters
        ----------
        device : str, default 'auto'
            Compute device ('auto', 'cpu', 'cuda').
        overwrite : bool, default False
            If True, recomputes even if already measured.
        verbose : bool, default False
            If True, prints NoiseChisel step timing diagnostics.
        subtract_sky : bool, default True
            If True, subtracts the measured 2D sky from self.data.
        **kwargs : Any
            Additional options passed to NoiseChisel.

        Returns
        -------
        Tuple[float, float]
            (sky_bkg_val, sky_std_val)
        """
        if self.sky_std_val is not None and not overwrite:
            return self.sky_bkg_val, self.sky_std_val

        from romanepsf.background import estimate_detector_sky_noisechisel

        dq_mask = self.get_effective_mask()
        sky_map, std_map, sky_val, std_val = estimate_detector_sky_noisechisel(
            self.data,
            dq_mask=dq_mask,
            device=device,
            verbose=verbose,
            **kwargs,
        )
        if subtract_sky:
            self.data = (self.data - sky_map).astype(np.float32)

        self.sky_bkg_val = float(sky_val)
        self.sky_std_val = float(std_val)
        self.sky_bkg = None
        self.sky_std = None
        del sky_map, std_map

        return self.sky_bkg_val, self.sky_std_val


def get_dq_mask(
    dq: np.ndarray,
    flags: Optional[Sequence[str]] = None,
    bitmask: Optional[int] = None,
) -> np.ndarray:
    """
    Generate a boolean mask where True indicates an invalid or flagged pixel.

    Parameters
    ----------
    dq : np.ndarray
        32-bit unsigned integer Data Quality array.
    flags : list of str, optional
        DQ flag names to mask. Defaults to ['DO_NOT_USE', 'SATURATED', 'DROPOUT'].
    bitmask : int, optional
        Explicit bitmask integer to bitwise-AND against dq. If provided, combined
        with flags.

    Returns
    -------
    np.ndarray (bool)
        Mask of bad pixels (True = flagged/bad).
    """
    if flags is None and bitmask is None:
        flags = DEFAULT_DQ_MASK_FLAGS

    computed_mask = 0
    if flags is not None:
        for f in flags:
            if f in DQ_FLAGS:
                computed_mask |= DQ_FLAGS[f]
            else:
                logger.warning("Unrecognized DQ flag '%s' ignored", f)

    if bitmask is not None:
        computed_mask |= int(bitmask)

    return (dq & computed_mask) > 0


def get_effective_mask(
    data: np.ndarray,
    dq: np.ndarray,
    flags: Optional[Sequence[str]] = None,
    bitmask: Optional[int] = None,
) -> np.ndarray:
    """
    Generate an effective bad pixel mask combining DQ flags and non-finite values.

    Parameters
    ----------
    data : np.ndarray
        Science flux array.
    dq : np.ndarray
        Data Quality array.
    flags : list of str, optional
        DQ flag names to mask.
    bitmask : int, optional
        Explicit integer bitmask.

    Returns
    -------
    np.ndarray (bool)
        Boolean mask where True denotes pixels that cannot be used.
    """
    bad_dq = get_dq_mask(dq, flags=flags, bitmask=bitmask)
    non_finite = ~np.isfinite(data)
    return bad_dq | non_finite


def _extract_detector_name(dm_or_path: Any, path: Path) -> str:
    """Extract standard detector string (e.g. 'WFI01')."""
    if hasattr(dm_or_path, "meta") and hasattr(dm_or_path.meta, "instrument"):
        det = getattr(dm_or_path.meta.instrument, "detector", None)
        if det:
            return str(det).upper()

    stem_lower = path.stem.lower()
    for i in range(1, 19):
        pattern = f"wfi{i:02d}"
        if pattern in stem_lower:
            return pattern.upper()

    return "WFI01"


def load_l2_image(
    asdf_path: Union[str, Path],
    calibrate: bool = True,
    validate_shape: bool = True,
    subtract_sky: bool = True,
    device: Optional[str] = "auto",
) -> RomanL2Data:
    """
    Load and calibrate a Roman Level 2 ASDF image.

    Runs NoiseChisel to measure the smooth sky background and sky noise std once across
    the detector, subtracts the sky background from the data array, and stores only
    the scalar values (sky_bkg_val and sky_std_val) to avoid storing large arrays.

    Parameters
    ----------
    asdf_path : str or Path
        Path to the Level 2 ASDF file.
    calibrate : bool, default True
        If True, multiplies raw count rates (DN/s) by the photometric conversion
        factor (conversion_megajanskys) to obtain calibrated surface brightness (MJy/sr).
    validate_shape : bool, default True
        If True, validates that active array shape is (4088, 4088).
    subtract_sky : bool, default True
        If True and calibrate is True, runs NoiseChisel, subtracts the 2D sky from
        data, and populates scalar sky_bkg_val and sky_std_val.
    device : str, default 'auto'
        Execution device for NoiseChisel ('auto', 'cpu', 'cuda').

    Returns
    -------
    RomanL2Data
        Dataclass containing data array (sky-subtracted), WCS, calibrated metadata,
        and scalar sky_bkg_val and sky_std_val.

    Raises
    ------
    FileNotFoundError
        If asdf_path does not exist.
    ValueError
        If array shape does not match (4088, 4088) when validate_shape is True.
    """
    path = Path(asdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"ASDF file not found: {asdf_path}")

    # Use roman_datamodels to open
    with rdm.open(str(path)) as dm:
        # Extract science arrays
        raw_data = np.asarray(dm.data, dtype=np.float32)
        if validate_shape and raw_data.shape != ACTIVE_SHAPE:
            raise ValueError(
                f"Invalid Roman science array shape {raw_data.shape}. "
                f"Expected active science array shape {ACTIVE_SHAPE}."
            )

        err = (
            np.asarray(dm.err, dtype=np.float32)
            if hasattr(dm, "err") and dm.err is not None
            else np.zeros_like(raw_data)
        )
        if err.shape != raw_data.shape:
            raise ValueError(f"Invalid err array shape {err.shape}, expected {raw_data.shape}")

        dq = (
            np.asarray(dm.dq, dtype=np.uint32)
            if hasattr(dm, "dq") and dm.dq is not None
            else np.zeros(raw_data.shape, dtype=np.uint32)
        )
        if dq.shape != raw_data.shape:
            raise ValueError(f"Invalid dq array shape {dq.shape}, expected {raw_data.shape}")

        wcs = getattr(dm.meta, "wcs", None)

        # Detector and filter information
        detector = _extract_detector_name(dm, path)
        inst_meta = getattr(dm.meta, "instrument", None)
        filter_name = getattr(inst_meta, "optical_element", "F146") if inst_meta else "F146"

        # Photometric calibration metadata
        phot_meta = getattr(dm.meta, "photometry", None)
        if phot_meta is not None:
            raw_conv = getattr(phot_meta, "conversion_megajanskys", 1.0)
            try:
                conv_factor = float(raw_conv)
                if not np.isfinite(conv_factor) or conv_factor <= 0:
                    raise ValueError(f"Invalid photometric conversion factor: {conv_factor}")
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid photometric conversion factor: {raw_conv}") from e
            pixel_area = float(getattr(phot_meta, "pixel_area", NOMINAL_PIXEL_AREA))
        else:
            conv_factor = 1.0
            pixel_area = NOMINAL_PIXEL_AREA

        # Pixel scale calculation from pixel area:
        # sqrt(pixel_area in rad^2) * 206264.806 arcsec/rad
        pixel_scale = (
            float(np.sqrt(pixel_area) * 206264.806)
            if pixel_area > 0
            else NOMINAL_PIXEL_SCALE
        )

        # Zero-point calculation:
        # Flux in Jy for 1 DN/s = conv_factor * 1e6 * pixel_area
        # AB mag = -2.5 * log10(Flux_Jy / 3631.0)
        flux_1dns_jy = conv_factor * 1e6 * pixel_area
        if flux_1dns_jy > 0:
            zp_ab = float(-2.5 * np.log10(flux_1dns_jy / 3631.0))
        else:
            zp_ab = 26.836  # Fallback nominal ZP for F146

        # Position angle extraction:
        # pa_aperture is primary; fall back to wcsinfo.roll_ref or 0.0
        pointing_meta = getattr(dm.meta, "pointing", None)
        wcsinfo_meta = getattr(dm.meta, "wcsinfo", None)
        pa_aperture = 0.0
        if pointing_meta is not None and hasattr(pointing_meta, "pa_aperture") and pointing_meta.pa_aperture is not None:
            pa_aperture = float(pointing_meta.pa_aperture)
        elif wcsinfo_meta is not None and hasattr(wcsinfo_meta, "roll_ref") and wcsinfo_meta.roll_ref is not None:
            pa_aperture = float(wcsinfo_meta.roll_ref)

        # Extract var_poisson if available in Level 2 ASDF
        var_poisson = (
            np.asarray(dm.var_poisson, dtype=np.float32)
            if hasattr(dm, "var_poisson") and dm.var_poisson is not None
            else None
        )
        if var_poisson is not None and var_poisson.shape != raw_data.shape:
            var_poisson = None

        # Apply photometric calibration to science arrays if requested
        if calibrate:
            cal_data = raw_data * conv_factor
            cal_err = err * conv_factor
            cal_var_poisson = (var_poisson * (conv_factor ** 2)).astype(np.float32) if var_poisson is not None else None
        else:
            cal_data = raw_data.copy()
            cal_err = err.copy()
            cal_var_poisson = var_poisson.copy() if var_poisson is not None else None

        sky_bkg_val: Optional[float] = None
        sky_std_val: Optional[float] = None

        # Run NoiseChisel and subtract sky directly from data, returning only scalar values
        if subtract_sky and calibrate:
            try:
                from romanepsf.background import estimate_detector_sky_noisechisel
                dq_effective = get_effective_mask(cal_data, dq)
                sky_map, std_map, s_val, n_val = estimate_detector_sky_noisechisel(
                    cal_data, dq_mask=dq_effective, device=device
                )
                cal_data = (cal_data - sky_map).astype(np.float32)
                sky_bkg_val = float(s_val)
                sky_std_val = float(n_val)
                del sky_map, std_map
                logger.info(
                    f"Subtracted NoiseChisel detector sky background ({sky_bkg_val:.5f} MJy/sr), "
                    f"sky std: {sky_std_val:.5f} [device={device}]"
                )
            except Exception as exc:
                logger.warning(
                    f"NoiseChisel execution during load_l2_image failed: {exc}. "
                    "Skipping sky subtraction."
                )
                sky_bkg_val = 0.0
                sky_std_val = 1.0

        # Compile metadata dictionary
        meta_dict: Dict[str, Any] = {
            "detector": detector,
            "filter": filter_name,
            "exposure_time": getattr(getattr(dm.meta, "exposure", None), "exposure_time", 294.10974),
            "roll_ref": getattr(wcsinfo_meta, "roll_ref", pa_aperture) if wcsinfo_meta else pa_aperture,
            "v3yangle": getattr(wcsinfo_meta, "v3yangle", -60.0) if wcsinfo_meta else -60.0,
            "vparity": getattr(wcsinfo_meta, "vparity", -1) if wcsinfo_meta else -1,
            "pa_aperture": pa_aperture,
            "conversion_megajanskys": conv_factor,
            "pixel_area": pixel_area,
            "zp_ab": zp_ab,
            "pixel_scale": pixel_scale,
            "sky_bkg_val": sky_bkg_val,
            "sky_std_val": sky_std_val,
        }

    return RomanL2Data(
        detector=detector,
        filter_name=filter_name,
        data=cal_data,
        raw_data=raw_data,
        err=cal_err,
        dq=dq,
        wcs=wcs,
        pa_aperture=pa_aperture,
        pixel_scale=pixel_scale,
        conversion_factor=conv_factor,
        pixel_area=pixel_area,
        zp_ab=zp_ab,
        meta=meta_dict,
        is_calibrated=calibrate,
        var_poisson=cal_var_poisson,
        sky_bkg=None,
        sky_std=None,
        sky_bkg_val=sky_bkg_val,
        sky_std_val=sky_std_val,
    )
