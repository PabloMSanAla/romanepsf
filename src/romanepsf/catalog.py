"""
Stellar Catalog Ingestion, Astrometric Projection, Centroid Refinement, and Multi-Tier Partitioning.

Handles precomputed and queried catalogs for the Roman Space Telescope WFI:
- Column deduplication and sanitization (fixing phot_g_mean_mag_AB vs phot_g_mean_mag collisions)
- Astrometric projection with mandatory forward roundtrip WCS verification (Delta theta < 0.5'')
- Subpixel centroid refinement via background-subtracted first moments with divergence guarding
- Pairwise Moffat extension isolation filtering (depth 28 mag/arcsec^2, safety factor 1.3)
- Multi-tier classification (Bright < 11.0, Medium 11.0-13.0, Faint >= 13.0) using F146 mag_lambda
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Union
import numpy as np
import pandas as pd
from romanepsf.loader import RomanL2Data, DQ_FLAGS
from scipy import ndimage
from scipy.optimize import curve_fit


def get_psf_extension_moffat(mag, depth=28.0, alpha=0.08, beta=1.52):
    """
    Analytically calculate the PSF extension based on a standard Moffat profile at a given depth.

    Parameters
    ----------
    mag : float or array-like
        Magnitude(s) of the star.
    depth : float, optional
        Depth at the extension in mag arcsecond^-2. Default is 28.0.
    alpha : float, optional
        Scale parameter of the Moffat profile in arcsec. Default is 0.08.
    beta : float, optional
        Shape parameter of the Moffat profile. Default is 1.52.

    Returns
    -------
    float or np.ndarray
        PSF extension in arcseconds.
    """
    mag_arr = np.asarray(mag, dtype=float)
    term = (np.pi * (alpha**2)) / (beta - 1.0)
    mu0 = mag_arr + 2.5 * np.log10(term)
    exponent = (depth - mu0) / (2.5 * beta)
    power_term = 10.0**exponent - 1.0
    power_term = np.maximum(power_term, 0.0)
    extension = alpha * np.sqrt(power_term)
    return extension.item() if extension.ndim == 0 else extension


def sanitize_source_catalog(
    df: pd.DataFrame,
    mag_col: str = "mag_lambda",
) -> pd.DataFrame:
    """
    Sanitize and deduplicate source catalog columns and rows.

    Fixes the duplicate column collision between `phot_g_mean_mag_AB` and `phot_g_mean_mag`.
    Filters out non-stellar solar system objects (e.g. Sun, Moon, planets) with negative
    magnitudes or non-numeric/NaN coordinates.

    Parameters
    ----------
    df : pd.DataFrame
        Raw input catalog DataFrame.
    mag_col : str, default "mag_lambda"
        Primary magnitude column to validate.

    Returns
    -------
    pd.DataFrame
        Sanitized DataFrame with unique columns and valid stellar objects.
    """
    clean_df = df.copy()

    # Strip whitespace from column names
    clean_df.columns = clean_df.columns.astype(str).str.strip()

    # 1. Resolve duplicate column names if already duplicated in memory
    if clean_df.columns.has_duplicates:
        clean_df = clean_df.loc[:, ~clean_df.columns.duplicated()].copy()

    # 2. Fix phot_g_mean_mag_AB vs phot_g_mean_mag renaming without collision
    has_g = "phot_g_mean_mag" in clean_df.columns
    has_g_ab = "phot_g_mean_mag_AB" in clean_df.columns

    if has_g_ab and not has_g:
        clean_df = clean_df.rename(columns={"phot_g_mean_mag_AB": "phot_g_mean_mag"})
    elif has_g_ab and has_g:
        # Both exist: keep phot_g_mean_mag as standard, leave phot_g_mean_mag_AB untouched
        pass

    # 3. Ensure mandatory astrometric columns exist
    if "ra" not in clean_df.columns or "dec" not in clean_df.columns:
        raise ValueError("Source catalog must contain 'ra' and 'dec' coordinate columns.")

    clean_df["ra"] = pd.to_numeric(clean_df["ra"], errors="coerce")
    clean_df["dec"] = pd.to_numeric(clean_df["dec"], errors="coerce")

    # Filter out invalid coordinates
    valid_coords = (
        clean_df["ra"].notna()
        & clean_df["dec"].notna()
        & np.isfinite(clean_df["ra"])
        & np.isfinite(clean_df["dec"])
        & (clean_df["ra"] >= 0.0)
        & (clean_df["ra"] <= 360.0)
        & (clean_df["dec"] >= -90.0)
        & (clean_df["dec"] <= 90.0)
    )
    clean_df = clean_df[valid_coords].copy()

    # 4. Validate active magnitude column and filter out unphysical solar system objects (mag < 0)
    active_mag_col = (
        mag_col
        if mag_col in clean_df.columns
        else ("phot_g_mean_mag" if "phot_g_mean_mag" in clean_df.columns else None)
    )
    if active_mag_col is not None:
        clean_df[active_mag_col] = pd.to_numeric(clean_df[active_mag_col], errors="coerce")
        # Commissioning catalog contains Sun (mag=-26.9), Moon (-4.7), Earth (-9.3)
        valid_mag = (
            clean_df[active_mag_col].notna()
            & np.isfinite(clean_df[active_mag_col])
            & (clean_df[active_mag_col] >= 0.0)
        )
        clean_df = clean_df[valid_mag].copy()

    # Also ensure secondary phot_g_mean_mag (if present and distinct) is numeric and non-negative
    if "phot_g_mean_mag" in clean_df.columns and "phot_g_mean_mag" != active_mag_col:
        clean_df["phot_g_mean_mag"] = pd.to_numeric(clean_df["phot_g_mean_mag"], errors="coerce")
        # Filter unphysical negative magnitudes (< 0) while preserving valid stars with NaN secondary band
        non_negative = clean_df["phot_g_mean_mag"].isna() | (clean_df["phot_g_mean_mag"] >= 0.0)
        clean_df = clean_df[non_negative].copy()

    # 5. Drop duplicate source_id if present
    if "source_id" in clean_df.columns:
        clean_df = clean_df.drop_duplicates(subset=["source_id"]).copy()

    return clean_df.reset_index(drop=True)


def get_detector_sky_bounds(
    l2_data: RomanL2Data,
    margin_deg: float = 0.02,
) -> Tuple[float, float, float, float, float, float, float]:
    """
    Compute RA/Dec center and bounding box for the detector active science area.

    Parameters
    ----------
    l2_data : RomanL2Data
        Calibrated detector data container with GWCS.
    margin_deg : float, default 0.02
        Angular margin in degrees added to detector boundary box.

    Returns
    -------
    Tuple[float, float, float, float, float, float, float]
        (ra_cen, dec_cen, radius_deg, ra_min, ra_max, dec_min, dec_max)
    """
    wcs = l2_data.wcs
    ny, nx = l2_data.data.shape

    pts_x = [0.0, float(nx - 1), float(nx - 1), 0.0, float(nx / 2.0)]
    pts_y = [0.0, 0.0, float(ny - 1), float(ny - 1), float(ny / 2.0)]

    ras, decs = [], []
    for px, py in zip(pts_x, pts_y):
        r, d = wcs(px, py)
        ras.append(float(r))
        decs.append(float(d))

    ra_cen, dec_cen = float(wcs(nx / 2.0, ny / 2.0)[0]), float(wcs(nx / 2.0, ny / 2.0)[1])
    diag_deg = np.hypot(max(ras) - min(ras), max(decs) - min(decs))
    radius_deg = (diag_deg / 2.0) + margin_deg

    return (
        ra_cen,
        dec_cen,
        radius_deg,
        min(ras) - margin_deg,
        max(ras) + margin_deg,
        min(decs) - margin_deg,
        max(decs) + margin_deg,
    )


def query_gaia_for_detector(
    l2_data: RomanL2Data,
    mag_limit: float = 20.0,
    cache_dir: Optional[Union[str, Path]] = "cache",
    precomputed_catalog: Optional[Union[str, Path]] = None,
    mag_col: str = "mag_lambda",
) -> pd.DataFrame:
    """
    Fetch stellar catalog for the detector field of view with disk caching.

    Parameters
    ----------
    l2_data : RomanL2Data
        Calibrated detector dataset.
    mag_limit : float, default 20.0
        Faintest magnitude threshold to include.
    cache_dir : str or Path, optional
        Directory to store cached query results.
    precomputed_catalog : str or Path, optional
        Path to an existing CSV file (e.g. commissioning master catalog).
    mag_col : str, default "mag_lambda"
        Magnitude column name.

    Returns
    -------
    pd.DataFrame
        Sanitized catalog filtered to the detector vicinity.
    """
    det_name = l2_data.detector.lower()
    cache_file = None
    if cache_dir:
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        cache_file = cache_path / f"gaia_dr3_{det_name}_g{int(mag_limit)}.csv"
        if cache_file.is_file():
            df_cached = pd.read_csv(cache_file)
            return sanitize_source_catalog(df_cached, mag_col=mag_col)

    ra_cen, dec_cen, radius_deg, ra_min, ra_max, dec_min, dec_max = get_detector_sky_bounds(l2_data)

    # 1. Fast Spatial HEALPix Cache / Master Catalog Slice
    from romanepsf.gaia_spatial import GaiaSpatialManager
    hpx_dir = Path(cache_dir) / "gaia_healpix" if cache_dir else Path("cache/gaia_healpix")
    mgr = GaiaSpatialManager(cache_dir=hpx_dir, precomputed_catalog=precomputed_catalog, mag_col=mag_col)
    
    # Check if we can slice from local HEALPix cache
    sub = mgr.get_catalog_for_bounds(ra_min, ra_max, dec_min, dec_max, mag_limit=mag_limit)
    if len(sub) > 0:
        clean_sub = sanitize_source_catalog(sub, mag_col=mag_col)
        if cache_file and not cache_file.is_file():
            clean_sub.to_csv(cache_file, index=False)
        return clean_sub

    # 2. Pull from precomputed master catalog if provided directly
    if precomputed_catalog and Path(precomputed_catalog).is_file():
        mgr.partition_from_master_catalog(precomputed_catalog, mag_limit=mag_limit)
        sub = mgr.get_catalog_for_bounds(ra_min, ra_max, dec_min, dec_max, mag_limit=mag_limit)
        if len(sub) > 0:
            clean_sub = sanitize_source_catalog(sub, mag_col=mag_col)
            if cache_file:
                clean_sub.to_csv(cache_file, index=False)
            return clean_sub

    # 2. Fallback to online Gaia DR3 query via TAP ADQL
    from astroquery.gaia import Gaia
    adql = f"""
    SELECT source_id, ra, dec, phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag
    FROM gaiadr3.gaia_source
    WHERE 1 = CONTAINS(
        POINT('ICRS', ra, dec),
        CIRCLE('ICRS', {ra_cen:.6f}, {dec_cen:.6f}, {radius_deg:.4f})
    )
    AND phot_g_mean_mag <= {mag_limit:.2f}
    ORDER BY phot_g_mean_mag ASC
    """
    job = Gaia.launch_job_async(adql)
    res = job.get_results()
    df_gaia = res.to_pandas()
    df_clean = sanitize_source_catalog(df_gaia, mag_col="phot_g_mean_mag")

    if cache_file:
        df_clean.to_csv(cache_file, index=False)

    return df_clean


def project_catalog_to_pixels(
    l2_data: RomanL2Data,
    catalog_df: pd.DataFrame,
    margin_px: int = 50,
    tolerance_arcsec: float = 0.5,
) -> pd.DataFrame:
    """
    Project celestial coordinates (RA, Dec) to detector pixel coordinates (x, y)
    with mandatory forward roundtrip WCS verification.

    Parameters
    ----------
    l2_data : RomanL2Data
        Calibrated detector dataset containing GWCS object and detector identifier.
    catalog_df : pd.DataFrame
        Source catalog containing 'ra', 'dec', and 'source_id'.
    margin_px : int, default 50
        Exclusion margin in pixels from detector active edges [0, 4088].
    tolerance_arcsec : float, default 0.5
        Maximum permitted angular roundtrip difference between catalog (ra, dec)
        and forward wcs(x, y). Eliminates false out-of-footprint matches.

    Returns
    -------
    pd.DataFrame
        DataFrame containing verified stars with columns:
        ['source_id', 'ra', 'dec', 'mag_lambda', 'x', 'y', 'detector', 'delta_theta_arcsec']
    """
    if catalog_df.empty or "ra" not in catalog_df.columns or "dec" not in catalog_df.columns:
        return pd.DataFrame(
            columns=["source_id", "ra", "dec", "mag_lambda", "x", "y", "detector", "delta_theta_arcsec"]
        )

    wcs = l2_data.wcs
    ny, nx = l2_data.data.shape

    ra_vals = catalog_df["ra"].to_numpy(dtype=float)
    dec_vals = catalog_df["dec"].to_numpy(dtype=float)

    # Wrap RA relative to detector center to handle 0/360 boundary in backward transform
    try:
        center_ra, _ = wcs(nx / 2.0, ny / 2.0)
        center_ra = float(np.asarray(center_ra).flat[0])
        ra_for_transform = center_ra + ((ra_vals - center_ra + 180.0) % 360.0 - 180.0)
    except Exception:
        ra_for_transform = ra_vals

    # 1. Vectorized backward transform (sky -> detector pixels)
    if hasattr(wcs, "backward_transform"):
        x_cand, y_cand = wcs.backward_transform(ra_for_transform, dec_vals)
    elif hasattr(wcs, "invert"):
        x_cand, y_cand = wcs.invert(ra_for_transform, dec_vals)
    else:
        raise AttributeError("WCS object does not provide backward_transform or invert method.")

    x_cand = np.asarray(x_cand, dtype=float)
    y_cand = np.asarray(y_cand, dtype=float)

    # 2. Filter pixels within active boundary margin
    finite_mask = np.isfinite(x_cand) & np.isfinite(y_cand)
    in_bounds = (
        finite_mask
        & (x_cand >= margin_px)
        & (x_cand <= (nx - margin_px))
        & (y_cand >= margin_px)
        & (y_cand <= (ny - margin_px))
    )

    cand_indices = np.where(in_bounds)[0]
    if len(cand_indices) == 0:
        return pd.DataFrame(
            columns=["source_id", "ra", "dec", "mag_lambda", "x", "y", "detector", "delta_theta_arcsec"]
        )

    x_sub = x_cand[cand_indices]
    y_sub = y_cand[cand_indices]
    ra_cand = ra_vals[cand_indices]
    dec_cand = dec_vals[cand_indices]

    # 3. Mandatory forward roundtrip verification (pixels -> sky)
    ra_back, dec_back = wcs(x_sub, y_sub)
    ra_back = np.asarray(ra_back, dtype=float)
    dec_back = np.asarray(dec_back, dtype=float)

    cos_dec = np.cos(np.radians(dec_cand))
    delta_ra = (ra_back - ra_cand + 180.0) % 360.0 - 180.0
    delta_ra_arcsec = delta_ra * cos_dec * 3600.0
    delta_dec_arcsec = (dec_back - dec_cand) * 3600.0
    delta_theta_arcsec = np.hypot(delta_ra_arcsec, delta_dec_arcsec)

    verified_mask = delta_theta_arcsec < tolerance_arcsec
    verified_indices = cand_indices[verified_mask]
    verified_sub_idx = np.where(verified_mask)[0]

    if len(verified_indices) == 0:
        return pd.DataFrame(
            columns=["source_id", "ra", "dec", "mag_lambda", "x", "y", "detector", "delta_theta_arcsec"]
        )

    # 4. Construct verified DataFrame preserving catalog attributes
    sub_df = catalog_df.iloc[verified_indices].copy().reset_index(drop=True)
    sub_df["x"] = x_sub[verified_sub_idx]
    sub_df["y"] = y_sub[verified_sub_idx]
    sub_df["detector"] = l2_data.detector
    sub_df["delta_theta_arcsec"] = delta_theta_arcsec[verified_sub_idx]

    # Guarantee canonical columns are present
    if "mag_lambda" not in sub_df.columns:
        if "phot_g_mean_mag" in sub_df.columns:
            sub_df["mag_lambda"] = sub_df["phot_g_mean_mag"]
        else:
            sub_df["mag_lambda"] = np.nan

    return sub_df


def _fit_2d_gaussian_center(
    box: np.ndarray,
    valid_mask: np.ndarray,
    x0_init: float,
    y0_init: float,
    max_shift: float = 5.0,
) -> Tuple[float, float, bool]:
    """
    Fit a 2D Gaussian model to the stellar flux array to determine the subpixel center.

    Parameters
    ----------
    box : np.ndarray
        2D flux array in local box coordinates.
    valid_mask : np.ndarray
        Boolean mask where True indicates valid (non-flagged, finite) pixels.
    x0_init : float
        Initial continuous guess for X in local box coordinates.
    y0_init : float
        Initial continuous guess for Y in local box coordinates.
    max_shift : float, default 5.0
        Maximum allowed offset from initial center for bounding the fit.

    Returns
    -------
    (x_fit, y_fit, success) : Tuple[float, float, bool]
        Fitted continuous center coordinates in local box pixels, and success flag.
    """
    grid_y, grid_x = np.indices(box.shape)

    valid_pts = valid_mask & np.isfinite(box)
    if np.sum(valid_pts) < 6 or (np.max(box[valid_pts]) - np.min(box[valid_pts]) <= 1e-6):
        return x0_init, y0_init, False

    x_pts = grid_x[valid_pts].astype(np.float64)
    y_pts = grid_y[valid_pts].astype(np.float64)
    flux_pts = box[valid_pts].astype(np.float64)

    bg_est = float(np.percentile(flux_pts, 10))
    amp_est = float(np.max(flux_pts) - bg_est)
    if amp_est <= 0:
        amp_est = 1.0

    p0 = [amp_est, float(x0_init), float(y0_init), 2.0, bg_est]
    bounds = (
        [0.0, x0_init - max_shift, y0_init - max_shift, 0.3, -np.inf],
        [np.inf, x0_init + max_shift, y0_init + max_shift, 50.0, np.inf],
    )

    def _gauss_func(coords, A, xc, yc, sigma, B):
        x, y = coords
        return A * np.exp(-((x - xc) ** 2 + (y - yc) ** 2) / (2.0 * sigma**2)) + B

    try:
        popt, _ = curve_fit(
            _gauss_func,
            (x_pts, y_pts),
            flux_pts,
            p0=p0,
            bounds=bounds,
            maxfev=1000,
        )
        A_f, xc_f, yc_f, sig_f, B_f = popt
        if np.isfinite(xc_f) and np.isfinite(yc_f):
            return float(xc_f), float(yc_f), True
    except Exception:
        pass

    return x0_init, y0_init, False


def refine_stellar_centroids(
    l2_data: RomanL2Data,
    df: pd.DataFrame,
    box_radius: Optional[int] = None,
    box_fraction: float = 0.30,
    max_shift_px: float = 5.0,
    cfg: Optional[Any] = None,
    faint_size: int = 81,
    medium_size: int = 201,
    max_bright_size: int = 1001,
    bright_limit: float = 11.0,
    faint_limit: float = 13.0,
) -> pd.DataFrame:
    """
    Refine stellar subpixel centers by fitting a 2D Gaussian model over a local box.
    The box size is defined as 30% (configurable via centroid_box_fraction) of the
    region size for each tier: faint, medium, and bright.

    Parameters
    ----------
    l2_data : RomanL2Data
        Calibrated detector dataset with science flux and DQ arrays.
    df : pd.DataFrame
        Catalog with projected 'x' and 'y' coordinates.
    box_radius : int, optional
        Explicit fixed box radius. If None, dynamically computes the box as box_fraction
        of the tier region size.
    box_fraction : float, default 0.30
        Fraction of the tier region size used to define the bounding box (default: 30%).
    max_shift_px : float, default 5.0
        Maximum allowable shift from initial catalog coordinates before falling back.
    cfg : PipelineConfig, optional
        Pipeline configuration providing tier boundaries and stamp sizes.

    Returns
    -------
    pd.DataFrame
        Updated DataFrame with refined 'x' and 'y', plus 'peak_flux', 'centroid_shift_px',
        and 'centroid_method'.
    """
    if df.empty:
        df_out = df.copy()
        df_out["peak_flux"] = []
        df_out["centroid_shift_px"] = []
        df_out["centroid_method"] = []
        return df_out

    # Resolve configuration parameters if provided
    if cfg is not None:
        cat_sec = getattr(cfg, "catalog", None)
        if cat_sec is not None:
            box_fraction = getattr(cat_sec, "centroid_box_fraction", box_fraction)
            cfg_box_px = getattr(cat_sec, "centroid_refine_box_px", None)
            if cfg_box_px is not None:
                box_radius = cfg_box_px
        stamps_sec = getattr(cfg, "stamps", None)
        if stamps_sec is not None:
            sizes = getattr(stamps_sec, "sizes", None)
            if sizes is not None:
                faint_size = getattr(sizes, "faint", faint_size)
                medium_size = getattr(sizes, "medium", medium_size)
                max_bright_size = getattr(sizes, "bright_max", max_bright_size)
        tiers_sec = getattr(cfg, "tiers", None)
        if tiers_sec is not None:
            bright_limit = getattr(tiers_sec, "bright_limit", bright_limit)
            faint_limit = getattr(tiers_sec, "faint_limit", faint_limit)

    data = l2_data.data
    height, width = data.shape
    pixel_scale = float(getattr(l2_data, "pixel_scale", 0.11))

    from romanepsf.stamps import get_adaptive_stamp_size

    x_refined, y_refined = [], []
    peak_fluxes, shifts = [], []
    methods = []

    for _, row in df.iterrows():
        x_init = float(row["x"])
        y_init = float(row["y"])

        # Determine tier and adaptive region size for this star
        if "tier" in row and pd.notna(row["tier"]):
            tier = str(row["tier"]).lower().strip()
        else:
            mag_val = row.get("mag_lambda", row.get("phot_g_mean_mag", np.nan))
            try:
                mag_float = float(mag_val)
                tier = "bright" if mag_float < bright_limit else ("medium" if mag_float < faint_limit else "faint")
            except (ValueError, TypeError):
                tier = "faint"

        mag_val = row.get("mag_lambda", row.get("phot_g_mean_mag", 15.0))
        try:
            mag_float = float(mag_val)
            if np.isnan(mag_float):
                mag_float = 15.0
        except (ValueError, TypeError):
            mag_float = 15.0

        region_sz = get_adaptive_stamp_size(
            mag=mag_float,
            tier=tier,
            max_size=max_bright_size,
            pixel_scale=pixel_scale,
            faint_size=faint_size,
            medium_size=medium_size,
        )

        if box_radius is not None:
            b_rad = int(box_radius)
        else:
            box_sz = int(round(region_sz * box_fraction))
            if box_sz % 2 == 0:
                box_sz += 1
            box_sz = max(box_sz, 11)
            b_rad = (box_sz - 1) // 2

        ix = int(round(x_init))
        iy = int(round(y_init))

        x0 = max(0, ix - b_rad)
        x1 = min(width, ix + b_rad + 1)
        y0 = max(0, iy - b_rad)
        y1 = min(height, iy + b_rad + 1)

        box = data[y0:y1, x0:x1]

        if box.size == 0 or np.all(np.isnan(box)):
            x_refined.append(x_init)
            y_refined.append(y_init)
            peak_fluxes.append(0.0)
            shifts.append(0.0)
            methods.append("fallback_nan")
            continue

        # Extract quality flags & saturation mask (exclude from fit)
        hard_flags = (
            DQ_FLAGS.get("SATURATED", 2)
            | DQ_FLAGS.get("DO_NOT_USE", 1)
            | DQ_FLAGS.get("DROPOUT", 8)
            | DQ_FLAGS.get("DEAD", 1024)
            | DQ_FLAGS.get("HOT", 2048)
        )
        if hasattr(l2_data, "dq") and l2_data.dq is not None:
            dq_box = l2_data.dq[y0:y1, x0:x1]
            bad_mask = ((dq_box & hard_flags) > 0) | (~np.isfinite(box))
        else:
            bad_mask = ~np.isfinite(box)

        valid_mask = np.isfinite(box) & (~bad_mask)
        valid_pix = box[valid_mask]

        if len(valid_pix) < 6 or np.max(valid_pix) <= 0.0 or (np.max(valid_pix) - np.min(valid_pix) <= 1e-6):
            x_refined.append(x_init)
            y_refined.append(y_init)
            peak_fluxes.append(float(np.max(valid_pix)) if len(valid_pix) > 0 else 0.0)
            shifts.append(0.0)
            methods.append("fallback_flat_or_empty")
            continue

        center_x_box = ix - x0
        center_y_box = iy - y0

        cx_fit, cy_fit, success = _fit_2d_gaussian_center(
            box=box,
            valid_mask=valid_mask,
            x0_init=center_x_box,
            y0_init=center_y_box,
            max_shift=max_shift_px,
        )

        if success:
            cx = x0 + cx_fit
            cy = y0 + cy_fit
            method_used = "2d_gaussian"
        else:
            cx, cy = x_init, y_init
            method_used = "gaussian_fallback"

        shift = float(np.hypot(cx - x_init, cy - y_init))
        if np.isfinite(cx) and np.isfinite(cy) and (shift <= max_shift_px):
            x_refined.append(float(cx))
            y_refined.append(float(cy))
            shifts.append(shift)
            methods.append(method_used)
        else:
            x_refined.append(x_init)
            y_refined.append(y_init)
            shifts.append(0.0)
            methods.append("fallback_divergence")

        peak_fluxes.append(float(np.max(valid_pix)))

    df_out = df.copy()
    if "x_gaia" not in df_out.columns:
        df_out["x_gaia"] = df["x"].to_numpy(dtype=float)
    if "y_gaia" not in df_out.columns:
        df_out["y_gaia"] = df["y"].to_numpy(dtype=float)
    df_out["x"] = x_refined
    df_out["y"] = y_refined
    df_out["peak_flux"] = peak_fluxes
    df_out["centroid_shift_px"] = shifts
    df_out["centroid_method"] = methods
    return df_out


def filter_isolated_stars(
    df: pd.DataFrame,
    pixel_scale: float = 0.11,
    isolation_safety_factor: float = 1.3,
    safety_factor: Optional[float] = None,
    min_dist_arcsec: float = 2.0,
    mag_col: str = "mag_lambda",
    depth: float = 28.0,
) -> pd.DataFrame:
    """
    Reject stars contaminated by nearby neighbors based on analytic Moffat PSF extension.

    Sorts stars by ascending magnitude (brightest first) and enforces:
        dist_px >= max(safety_factor * (ext_i + ext_j), min_dist_arcsec / pixel_scale)
    When two stars violate clearance, the brighter star is preserved and the fainter is rejected.

    Parameters
    ----------
    df : pd.DataFrame
        Catalog with 'x', 'y', and magnitude column.
    pixel_scale : float, default 0.11
        Pixel scale in arcsec/pixel.
    isolation_safety_factor : float, default 1.3
        Multiplier applied to combined Moffat extension radii.
    safety_factor : float, optional
        Alias for isolation_safety_factor.
    min_dist_arcsec : float, default 2.0
        Hard minimum distance between any two stars in arcseconds.
    mag_col : str, default "mag_lambda"
        Magnitude column used to compute PSF extension.
    depth : float, default 28.0
        Surface brightness depth in mag/arcsec^2.

    Returns
    -------
    pd.DataFrame
        Filtered catalog containing only isolated stars.
    """
    if safety_factor is not None:
        isolation_safety_factor = safety_factor

    if len(df) <= 1:
        return df.copy().reset_index(drop=True)

    effective_mag_col = mag_col if mag_col in df.columns else "phot_g_mean_mag"
    if effective_mag_col not in df.columns:
        return df.copy().reset_index(drop=True)

    # Sort brightest first (ascending magnitude). Break ties with source_id for determinism.
    sort_cols = [effective_mag_col]
    if "source_id" in df.columns:
        sort_cols.append("source_id")
    df_sorted = df.sort_values(by=sort_cols).reset_index(drop=True)

    coords = df_sorted[["x", "y"]].to_numpy(dtype=float)
    mags = df_sorted[effective_mag_col].to_numpy(dtype=float)

    # Calculate Moffat extent in arcseconds and pixels
    extensions_arcsec = get_psf_extension_moffat(mags, depth=depth)
    extensions_px = np.asarray(extensions_arcsec, dtype=float) / pixel_scale

    n = len(df_sorted)
    is_kept = np.ones(n, dtype=bool)
    min_clearance_px = min_dist_arcsec / pixel_scale

    if n > 20:
        from scipy.spatial import cKDTree

        tree = cKDTree(coords)
        max_clearance = float(
            max(np.max(extensions_px) * 2.0 * isolation_safety_factor, min_clearance_px)
        )

        for i in range(n):
            if not is_kept[i]:
                continue

            cand_indices = tree.query_ball_point(coords[i], r=max_clearance)
            cand_indices = [idx for idx in cand_indices if idx != i and is_kept[idx]]

            if not cand_indices:
                continue

            cand_arr = np.array(cand_indices, dtype=int)
            dx = coords[cand_arr, 0] - coords[i, 0]
            dy = coords[cand_arr, 1] - coords[i, 1]
            dist_px = np.hypot(dx, dy)

            req_clearance = np.maximum(
                isolation_safety_factor * (extensions_px[i] + extensions_px[cand_arr]),
                min_clearance_px,
            )

            violators = cand_arr[dist_px < req_clearance]
            if len(violators) > 0:
                if np.any(violators < i):
                    is_kept[i] = False
                else:
                    is_kept[violators] = False
    else:
        for i in range(n):
            if not is_kept[i]:
                continue

            dx = coords[:, 0] - coords[i, 0]
            dy = coords[:, 1] - coords[i, 1]
            dist_px = np.hypot(dx, dy)
            dist_px[i] = np.inf  # Ignore self

            required_clearance = np.maximum(
                isolation_safety_factor * (extensions_px[i] + extensions_px),
                min_clearance_px,
            )

            # Check only against currently active/kept stars
            violators = np.where((dist_px < required_clearance) & is_kept)[0]
            if len(violators) > 0:
                # If any brighter star (index < i) violates clearance, star i must be rejected
                if np.any(violators < i):
                    is_kept[i] = False
                else:
                    # Violators are fainter (index > i); reject them to protect primary star i
                    is_kept[violators] = False

    return df_sorted[is_kept].copy().reset_index(drop=True)


def assign_stellar_tiers(
    df: pd.DataFrame,
    bright_limit: float = 11.0,
    faint_limit: float = 13.0,
    mag_col: str = "mag_lambda",
) -> pd.DataFrame:
    """
    Categorize stars into Bright, Medium, and Faint tiers based on Roman F146 mag_lambda.

    Tiers:
    - 'bright': mag < bright_limit (< 11.0)
        Used for extended PSF wings and 6-fold diffraction spikes out to r > 500 px.
    - 'medium': bright_limit <= mag < faint_limit (11.0 <= mag < 13.0)
        Used for transition overlap normalization (8 < r < 45 px).
    - 'faint' : mag >= faint_limit (mag >= 13.0)
        Used for unsaturated central core (r < 10 px).

    Parameters
    ----------
    df : pd.DataFrame
        Catalog with magnitude column.
    bright_limit : float, default 11.0
        Upper brightness boundary for bright tier.
    faint_limit : float, default 13.0
        Lower boundary for faint tier.
    mag_col : str, default "mag_lambda"
        Primary magnitude column.

    Returns
    -------
    pd.DataFrame
        Catalog with added 'tier' column containing 'bright', 'medium', or 'faint'.
    """
    df_out = df.copy()
    if df_out.empty:
        df_out["tier"] = []
        return df_out

    effective_mag_col = mag_col if mag_col in df_out.columns else "phot_g_mean_mag"
    if effective_mag_col not in df_out.columns:
        df_out["tier"] = "faint"
        return df_out

    mags = pd.to_numeric(df_out[effective_mag_col], errors="coerce").to_numpy(dtype=float)
    tiers = np.full(len(df_out), "faint", dtype=object)

    valid_mask = np.isfinite(mags)
    bright_mask = valid_mask & (mags < bright_limit)
    medium_mask = valid_mask & (mags >= bright_limit) & (mags < faint_limit)

    tiers[bright_mask] = "bright"
    tiers[medium_mask] = "medium"
    # Remaining valid (mags >= faint_limit) and invalid/NaN remain 'faint'

    df_out["tier"] = tiers
    return df_out
