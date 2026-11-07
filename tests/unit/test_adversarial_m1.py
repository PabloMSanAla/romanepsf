"""
Adversarial and Edge Case Stress Tests for Milestone 1.

Empirically challenges:
1. WCS Forward Roundtrip Verification: detector boundaries, tangent plane extremes, poles, and RA 0/360 wrap-around.
2. Catalog Deduplication & Sanitization: dirty CSVs, duplicate columns, missing values, extreme magnitudes, non-ASCII, BOM.
3. Centroid Refinement: all-NaN cutouts, negative fluxes, cosmic rays with DQ flags, binary clumps.
"""

from pathlib import Path
import io
import numpy as np
import pandas as pd
import pytest

from romanepsf.loader import RomanL2Data, DQ_FLAGS, load_l2_image
from romanepsf.catalog import (
    sanitize_source_catalog,
    project_catalog_to_pixels,
    refine_stellar_centroids,
    filter_isolated_stars,
    assign_stellar_tiers,
    get_psf_extension_moffat,
)


class MockGWCS:
    """Configurable Mock WCS for testing boundary transformations."""
    def __init__(self, crval=(303.12, -19.93), crpix=(2044.0, 2044.0), scale=0.11/3600.0):
        self.crval_ra = crval[0]
        self.crval_dec = crval[1]
        self.crpix_x = crpix[0]
        self.crpix_y = crpix[1]
        self.scale = scale

    def backward_transform(self, ra, dec):
        ra_arr = np.asarray(ra, dtype=float)
        dec_arr = np.asarray(dec, dtype=float)
        cos_dec = np.cos(np.radians(self.crval_dec))
        d_ra = (ra_arr - self.crval_ra + 180.0) % 360.0 - 180.0
        dx_deg = d_ra * cos_dec
        dy_deg = dec_arr - self.crval_dec
        x = self.crpix_x + dx_deg / self.scale
        y = self.crpix_y + dy_deg / self.scale
        return x, y

    def __call__(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        cos_dec = np.cos(np.radians(self.crval_dec))
        dx_deg = (x_arr - self.crpix_x) * self.scale
        dy_deg = (y_arr - self.crpix_y) * self.scale
        ra = self.crval_ra + dx_deg / cos_dec
        dec = self.crval_dec + dy_deg
        return ra, dec


def make_test_l2(data=None, dq=None, wcs=None):
    """Create a minimal RomanL2Data container for testing."""
    if data is None:
        data = np.zeros((4088, 4088), dtype=np.float32)
    if dq is None:
        dq = np.zeros(data.shape, dtype=np.uint32)
    if wcs is None:
        wcs = MockGWCS()

    return RomanL2Data(
        detector="WFI01",
        filter_name="F146",
        data=data,
        raw_data=data.copy(),
        err=np.ones_like(data),
        dq=dq,
        wcs=wcs,
        pa_aperture=0.0,
        pixel_scale=0.11,
        conversion_factor=1.0,
        pixel_area=2.8e-13,
        zp_ab=26.8,
        meta={},
        is_calibrated=True,
    )


# ==============================================================================
# Challenge Dimension 1: WCS Forward Roundtrip Verification
# ==============================================================================

def test_wcs_exact_boundary_coordinates():
    """Verify stars right on detector boundaries [0.0, 4088.0, 4088.01, -0.01]."""
    wcs = MockGWCS()
    l2 = make_test_l2(wcs=wcs)

    pixels_x = [0.0, 4088.0, 4088.01, -0.01, 50.0, 49.99, 4038.0, 4038.01]
    pixels_y = [0.0, 4088.0, 4088.01, -0.01, 50.0, 49.99, 4038.0, 4038.01]

    ras, decs = wcs(pixels_x, pixels_y)
    df = pd.DataFrame({
        "source_id": list(range(len(pixels_x))),
        "ra": ras,
        "dec": decs,
        "mag_lambda": [12.0] * len(pixels_x),
    })

    proj_50 = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    # With margin_px=50: boundary points outside [50, 4038] must be excluded
    assert 0 not in proj_50["source_id"].values  # (0.0, 0.0) excluded
    assert 1 not in proj_50["source_id"].values  # (4088.0, 4088.0) excluded
    assert 2 not in proj_50["source_id"].values  # (4088.01, 4088.01) excluded
    assert 3 not in proj_50["source_id"].values  # (-0.01, -0.01) excluded
    assert 5 not in proj_50["source_id"].values  # (49.99, 49.99) excluded
    assert 7 not in proj_50["source_id"].values  # (4038.01, 4038.01) excluded


def test_wcs_far_outside_tangent_plane():
    """Verify stars far outside tangent plane and degenerate coordinates do not crash."""
    wcs = MockGWCS()
    l2 = make_test_l2(wcs=wcs)

    df = pd.DataFrame({
        "source_id": [101, 102, 103, 104, 105, 106],
        "ra": [0.0, 180.0, 1e6, -500.0, np.nan, np.inf],
        "dec": [0.0, -85.0, 1e6, -200.0, np.nan, -np.inf],
        "mag_lambda": [12.0] * 6,
    })

    proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    assert len(proj) == 0


def test_wcs_celestial_poles():
    """Verify projection at celestial poles (Dec = +90, -90)."""
    wcs = MockGWCS(crval=(303.12, -19.93))
    l2 = make_test_l2(wcs=wcs)

    df_poles = pd.DataFrame({
        "source_id": [1, 2],
        "ra": [0.0, 180.0],
        "dec": [90.0, -90.0],
        "mag_lambda": [12.0, 12.0],
    })

    proj = project_catalog_to_pixels(l2, df_poles, margin_px=50, tolerance_arcsec=0.5)
    assert len(proj) == 0  # Poles are far outside detector field of view


def test_bug_wcs_ra_wrap_around_0_360():
    """
    BUG REPRODUCTION: Stars crossing RA 0/360 boundary are falsely rejected.
    When a pointing is near RA 0.001 deg, a valid star on detector at RA 359.9508 deg
    is rejected because delta_ra is evaluated as -360.0 deg (~1.3M arcsec) without wrapping.
    """
    wcs = MockGWCS(crval=(0.001, -20.0))
    l2 = make_test_l2(wcs=wcs)

    # Valid star at x=500.0, y=2044.0 (well within detector)
    ra_direct, dec_direct = wcs(500.0, 2044.0)
    ra_catalog = float(ra_direct % 360.0)  # Standard astronomical catalog convention

    df = pd.DataFrame({
        "source_id": [1],
        "ra": [ra_catalog],
        "dec": [dec_direct],
        "mag_lambda": [12.0],
    })

    proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    # The star is physically on the detector and should be accepted.
    # If the bug is present, len(proj) == 0.
    assert len(proj) == 1, (
        f"Star crossing RA 0/360 meridian was falsely rejected! "
        f"ra_catalog={ra_catalog:.4f}, expected on detector at x=500, y=2044."
    )


# ==============================================================================
# Challenge Dimension 2: Catalog Deduplication & Dirty Data
# ==============================================================================

def test_catalog_dirty_duplicates_and_corrupt_types():
    """Verify handling of duplicate columns, duplicate IDs, corrupt types."""
    data = [
        [1, "303.12", "-19.93", 12.0, "valid"],
        [1, "303.12", "-19.93", 12.0, "duplicate_row"],
        [2, "corrupt", "-19.90", 14.0, "bad_ra"],
        [3, "303.15", "corrupt", 14.0, "bad_dec"],
        [4, np.nan, -19.80, 15.0, "nan_ra"],
    ]
    cols = ["source_id", "ra", "dec", "mag_lambda", "comment"]
    df = pd.DataFrame(data, columns=cols)

    clean = sanitize_source_catalog(df, mag_col="mag_lambda")
    assert len(clean) == 1
    assert clean["source_id"].iloc[0] == 1


def test_bug_catalog_solar_system_rejection_without_mag_lambda():
    """
    BUG REPRODUCTION: When catalog uses phot_g_mean_mag instead of mag_lambda,
    sanitize_source_catalog fails to filter negative magnitudes (Sun, Earth, Moon),
    which downstream causes filter_isolated_stars to eliminate all real stars!
    """
    df = pd.DataFrame({
        "source_id": [1, 2, 3],
        "ra": [303.1, 303.2, 303.3],
        "dec": [-19.9, -19.8, -19.7],
        "x": [100.0, 2000.0, 3000.0],
        "y": [100.0, 2000.0, 3000.0],
        "phot_g_mean_mag": [-26.98, 12.0, 14.0],  # Sun (-26.98) + two real stars
    })

    clean = sanitize_source_catalog(df, mag_col="mag_lambda")
    # Sun must be filtered out!
    assert not (clean["phot_g_mean_mag"] < 0).any(), (
        "sanitize_source_catalog failed to filter negative magnitude solar system objects "
        "when catalog uses phot_g_mean_mag!"
    )


def test_bug_catalog_header_spaces():
    """
    BUG REPRODUCTION: CSVs with spaces after commas (e.g. 'source_id, ra, dec')
    crash sanitize_source_catalog because columns are not stripped of whitespace.
    """
    csv_text = "source_id, ra, dec, mag_lambda\n1, 303.12, -19.93, 12.0\n"
    df = pd.read_csv(io.StringIO(csv_text))
    clean = sanitize_source_catalog(df, mag_col="mag_lambda")
    assert len(clean) == 1


# ==============================================================================
# Challenge Dimension 3: Pathological Image Inputs & Centroid Refinement
# ==============================================================================

def test_centroid_all_nan_and_inf_boxes():
    """Verify all-NaN and all-Inf cutouts gracefully fall back to initial coords."""
    d_nan = np.full((100, 100), np.nan, dtype=np.float32)
    l2_nan = make_test_l2(data=d_nan)
    df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [12.0]})

    refined_nan = refine_stellar_centroids(l2_nan, df, box_radius=5)
    assert refined_nan["x"].iloc[0] == 50.0
    assert refined_nan["y"].iloc[0] == 50.0
    assert refined_nan["centroid_shift_px"].iloc[0] == 0.0

    d_inf = np.full((100, 100), np.inf, dtype=np.float32)
    l2_inf = make_test_l2(data=d_inf)
    refined_inf = refine_stellar_centroids(l2_inf, df, box_radius=5)
    assert refined_inf["x"].iloc[0] == 50.0
    assert refined_inf["y"].iloc[0] == 50.0


def test_bug_centroid_cosmic_ray_hijack_dq_ignored():
    """
    BUG REPRODUCTION: Centroid refinement ignores l2_data.dq bitmask,
    allowing an adjacent cosmic ray flagged with JUMP_DET to hijack the star center.
    """
    data = np.zeros((100, 100), dtype=np.float32)
    dq = np.zeros((100, 100), dtype=np.uint32)

    # Real star at (50.0, 50.0) with peak 500
    gy, gx = np.indices((100, 100))
    data += 500.0 * np.exp(-((gx - 50.0)**2 + (gy - 50.0)**2) / (2 * 1.5**2)).astype(np.float32)

    # Cosmic ray at (52, 51) with flux 50000, flagged in DQ
    data[51, 52] = 50000.0
    dq[51, 52] = DQ_FLAGS["JUMP_DET"]

    l2 = make_test_l2(data=data, dq=dq)
    df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [12.0]})

    refined = refine_stellar_centroids(l2, df, box_radius=5)
    # The centroid should remain near the true star (50.0, 50.0) by masking the cosmic ray
    # If the bug is present, x shifts to ~51.75
    assert abs(refined["x"].iloc[0] - 50.0) < 0.5, (
        f"Centroid was hijacked by cosmic ray! refined_x={refined['x'].iloc[0]:.3f}, "
        f"true star is at x=50.0, shift={refined['centroid_shift_px'].iloc[0]:.3f} px"
    )


def test_bug_centroid_negative_flux_noise_shift():
    """
    BUG REPRODUCTION: On an all-negative noise box, refine_stellar_centroids
    shifts the centroid by > 2 pixels based on pure noise gradient.
    """
    data = np.zeros((100, 100), dtype=np.float32)
    y, x = np.indices((100, 100))
    data[:] = -100.0 + x * 0.5  # Pure negative noise gradient (-100 to -50)

    l2 = make_test_l2(data=data)
    df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [12.0]})

    refined = refine_stellar_centroids(l2, df, box_radius=5)
    # Since peak is negative, it should not compute an arbitrary noise centroid shift!
    assert refined["centroid_shift_px"].iloc[0] == 0.0, (
        f"Centroid was shifted on pure negative background noise! "
        f"shift={refined['centroid_shift_px'].iloc[0]:.3f} px, peak={refined['peak_flux'].iloc[0]:.1f}"
    )
