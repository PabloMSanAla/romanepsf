"""
Unit Tests for Catalog Ingestion, Astrometric Verification, and Isolation Filtering.

Tests duplicate column bug sanitization, forward roundtrip WCS verification,
subpixel centroid refinement, Moffat isolation clearance, and stellar tier assignment.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from romanepsf.loader import RomanL2Data
from romanepsf.catalog import (
    sanitize_source_catalog,
    project_catalog_to_pixels,
    refine_stellar_centroids,
    filter_isolated_stars,
    assign_stellar_tiers,
)


class MockWCS:
    """Mock WCS allowing controlled roundtrip discrepancy testing."""

    def __init__(self):
        pass

    def backward_transform(self, ra, dec):
        xs = np.full_like(ra, 2044.0, dtype=np.float64)
        ys = np.full_like(dec, 2044.0, dtype=np.float64)
        return xs, ys

    def __call__(self, x, y):
        ra_out = np.full_like(x, 303.12, dtype=np.float64)
        dec_out = np.full_like(y, -19.93, dtype=np.float64)
        return ra_out, dec_out


def test_sanitize_catalog_duplicate_columns():
    """Verify duplicate column bug fix: duplicate mag columns are resolved without 2D slicing."""
    df = pd.DataFrame({
        "source_id": [101, 102],
        "ra": [303.1, 303.2],
        "dec": [-19.9, -19.8],
        "phot_g_mean_mag_AB": [12.5, 14.1],
        "phot_g_mean_mag": [12.4, 14.0],
        "mag_lambda": [11.8, 13.5],
    })

    clean_df = sanitize_source_catalog(df, mag_col="mag_lambda")

    # Column name phot_g_mean_mag must be unique
    assert list(clean_df.columns).count("phot_g_mean_mag") == 1
    # Selecting the column returns a 1D Series
    assert isinstance(clean_df["phot_g_mean_mag"], pd.Series)
    assert clean_df["phot_g_mean_mag"].ndim == 1


def test_sanitize_catalog_filters_solar_system_bodies():
    """Verify non-stellar solar system objects with negative magnitudes are dropped."""
    df = pd.DataFrame({
        "source_id": [1, 2, 3],
        "ra": [303.1, 303.2, 303.3],
        "dec": [-19.9, -19.8, -19.7],
        "mag_lambda": [-26.988, -9.319, 12.5],
    })

    clean_df = sanitize_source_catalog(df, mag_col="mag_lambda")
    assert len(clean_df) == 1
    assert clean_df["source_id"].iloc[0] == 3


def test_forward_roundtrip_wcs_in_footprint():
    """Verify valid star with roundtrip discrepancy < 0.5 arcsec is accepted."""
    df = pd.DataFrame({
        "source_id": [1],
        "ra": [303.12],
        "dec": [-19.93],
        "mag_lambda": [12.0],
    })

    wcs = MockWCS()
    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=np.zeros((4088, 4088), dtype=np.float32), raw_data=np.zeros((4088, 4088), dtype=np.float32),
        err=np.zeros((4088, 4088), dtype=np.float32), dq=np.zeros((4088, 4088), dtype=np.uint32),
        wcs=wcs, pa_aperture=-110.0, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13,
        zp_ab=26.8, meta={}, is_calibrated=True,
    )

    proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    assert len(proj) == 1
    assert "x" in proj.columns and "y" in proj.columns
    assert proj["x"].iloc[0] == 2044.0


def test_forward_roundtrip_wcs_out_of_footprint_rejection():
    """Verify spurious star with roundtrip discrepancy > 0.5 arcsec is strictly rejected."""
    df = pd.DataFrame({
        "source_id": [999],
        "ra": [302.953],
        "dec": [-20.231],
        "mag_lambda": [10.5],
    })

    class DefectiveWCS:
        def backward_transform(self, ra, dec):
            return np.array([2047.92]), np.array([3992.95])
        def __call__(self, x, y):
            # Forward transform diverges
            return np.array([302.782]), np.array([-19.777])

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=np.zeros((4088, 4088), dtype=np.float32), raw_data=np.zeros((4088, 4088), dtype=np.float32),
        err=np.zeros((4088, 4088), dtype=np.float32), dq=np.zeros((4088, 4088), dtype=np.uint32),
        wcs=DefectiveWCS(), pa_aperture=-110.0, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13,
        zp_ab=26.8, meta={}, is_calibrated=True,
    )

    proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    assert len(proj) == 0, "Spurious star with large roundtrip error must be rejected"


def test_edge_margin_filtering():
    """Verify stars falling within boundary margin (50 px) of detector edges are rejected."""
    df = pd.DataFrame({
        "source_id": [1, 2, 3],
        "ra": [303.1, 303.1, 303.1],
        "dec": [-19.9, -19.9, -19.9],
        "mag_lambda": [12.0, 12.0, 12.0],
    })

    class EdgeWCS:
        def backward_transform(self, ra, dec):
            return np.array([25.0, 2000.0, 2000.0]), np.array([2000.0, 2000.0, 4060.0])
        def __call__(self, x, y):
            return np.full_like(x, 303.1), np.full_like(y, -19.9)

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=np.zeros((4088, 4088), dtype=np.float32), raw_data=np.zeros((4088, 4088), dtype=np.float32),
        err=np.zeros((4088, 4088), dtype=np.float32), dq=np.zeros((4088, 4088), dtype=np.uint32),
        wcs=EdgeWCS(), pa_aperture=-110.0, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13,
        zp_ab=26.8, meta={}, is_calibrated=True,
    )

    proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    assert len(proj) == 1
    assert proj["source_id"].iloc[0] == 2


def test_refine_stellar_centroids_synthetic_peak():
    """Verify centroid refinement on a synthetic Gaussian star recovers true subpixel center."""
    ny, nx = 100, 100
    grid_y, grid_x = np.indices((ny, nx))
    true_x, true_y = 50.35, 50.72
    star_img = 100.0 * np.exp(-((grid_x - true_x)**2 + (grid_y - true_y)**2) / (2 * 2.0**2)).astype(np.float32)

    df = pd.DataFrame({
        "source_id": [1],
        "x": [50.0],
        "y": [51.0],
        "mag_lambda": [12.0],
    })

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=star_img, raw_data=star_img,
        err=np.ones_like(star_img), dq=np.zeros_like(star_img, dtype=np.uint32),
        wcs=None, pa_aperture=0.0, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13,
        zp_ab=26.8, meta={}, is_calibrated=True,
    )

    refined = refine_stellar_centroids(l2, df, box_radius=5)
    assert refined["x"].iloc[0] == pytest.approx(true_x, abs=0.05)
    assert refined["y"].iloc[0] == pytest.approx(true_y, abs=0.05)


def test_refine_stellar_centroids_zero_flux_fallback():
    """Verify centroid refinement handles zero-flux box gracefully without NaNs."""
    zero_img = np.zeros((100, 100), dtype=np.float32)
    df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [12.0]})

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=zero_img, raw_data=zero_img,
        err=np.ones_like(zero_img), dq=np.zeros_like(zero_img, dtype=np.uint32),
        wcs=None, pa_aperture=0.0, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13,
        zp_ab=26.8, meta={}, is_calibrated=True,
    )

    refined = refine_stellar_centroids(l2, df, box_radius=5)
    assert refined["x"].iloc[0] == 50.0
    assert refined["y"].iloc[0] == 50.0


def test_filter_isolated_stars_pair_rejection():
    """Verify that in a blended star pair, the brighter star is kept and the fainter is rejected."""
    df = pd.DataFrame({
        "source_id": [1, 2],
        "x": [1000.0, 1015.0],      # separation 15 px (~1.65 arcsec)
        "y": [1000.0, 1000.0],
        "mag_lambda": [10.0, 15.0], # star 1 is bright, star 2 is faint
    })

    isolated = filter_isolated_stars(df, pixel_scale=0.11, safety_factor=1.3, mag_col="mag_lambda")
    assert len(isolated) == 1
    assert isolated["source_id"].iloc[0] == 1


def test_filter_isolated_stars_isolated_pair():
    """Verify widely separated stars are both preserved."""
    df = pd.DataFrame({
        "source_id": [1, 2],
        "x": [500.0, 3500.0],       # separation 3000 px (~330 arcsec)
        "y": [500.0, 3500.0],
        "mag_lambda": [10.0, 12.0],
    })

    isolated = filter_isolated_stars(df, pixel_scale=0.11, safety_factor=1.3, mag_col="mag_lambda")
    assert len(isolated) == 2


def test_filter_isolated_stars_relaxed_medium_and_bright():
    """Verify medium and bright stars permit companions unless a brighter companion is within half cutout width."""
    # Medium star (mag 12.0, cutout 201 px -> half-width 100.5 px)
    # with a fainter companion at 40 px: medium star must be KEPT.
    df_medium_fainter = pd.DataFrame({
        "source_id": [1, 2],
        "x": [1000.0, 1040.0],
        "y": [1000.0, 1000.0],
        "mag_lambda": [12.0, 14.5],  # 1 is medium, 2 is faint
    })
    iso_med = filter_isolated_stars(df_medium_fainter, pixel_scale=0.11, mag_col="mag_lambda")
    # Medium star (source_id=1) is kept; faint star (source_id=2) at 40 px is within faint cutout (40.5 px) of brighter star so rejected
    assert 1 in iso_med["source_id"].values

    # Medium star (mag 12.5) with a brighter companion (mag 11.5) at 60 px (within 100.5 px):
    # Brighter star kept, fainter medium star rejected.
    df_medium_brighter = pd.DataFrame({
        "source_id": [1, 2],
        "x": [1000.0, 1060.0],
        "y": [1000.0, 1000.0],
        "mag_lambda": [11.5, 12.5],
    })
    iso_med_b = filter_isolated_stars(df_medium_brighter, pixel_scale=0.11, mag_col="mag_lambda")
    assert len(iso_med_b) == 1
    assert iso_med_b["source_id"].iloc[0] == 1

    # Medium star (mag 12.5) with a brighter companion (mag 11.5) at 150 px (> 100.5 px):
    # Both medium stars kept!
    df_medium_distant = pd.DataFrame({
        "source_id": [1, 2],
        "x": [1000.0, 1150.0],
        "y": [1000.0, 1000.0],
        "mag_lambda": [11.5, 12.5],
    })
    iso_med_d = filter_isolated_stars(df_medium_distant, pixel_scale=0.11, mag_col="mag_lambda")
    assert len(iso_med_d) == 2


def test_filter_isolated_stars_faint_tier_min_dist():
    """Verify faint stars enforce min_dist_arcsec=2.0 (18.18 px)."""
    # Two faint stars closer than 2.0 arcsec (15 px ~ 1.65 arcsec): brighter kept, fainter rejected
    df_faint_close = pd.DataFrame({
        "source_id": [1, 2],
        "x": [500.0, 515.0],
        "y": [500.0, 500.0],
        "mag_lambda": [14.0, 14.5],
    })
    iso_close = filter_isolated_stars(df_faint_close, pixel_scale=0.11, min_dist_arcsec=2.0, mag_col="mag_lambda")
    assert len(iso_close) == 1
    assert iso_close["source_id"].iloc[0] == 1

    # Two faint stars farther than 2.0 arcsec (25 px ~ 2.75 arcsec): both kept!
    df_faint_far = pd.DataFrame({
        "source_id": [1, 2],
        "x": [500.0, 525.0],
        "y": [500.0, 500.0],
        "mag_lambda": [14.0, 14.5],
    })
    iso_far = filter_isolated_stars(df_faint_far, pixel_scale=0.11, min_dist_arcsec=2.0, mag_col="mag_lambda")
    assert len(iso_far) == 2


def test_assign_stellar_tiers():
    """Verify tier assignment matches project boundaries (<11.0, 11.0-13.0, >=13.0)."""
    df = pd.DataFrame({
        "source_id": [1, 2, 3, 4, 5, 6, 7],
        "mag_lambda": [8.5, 10.99, 11.0, 12.5, 12.99, 13.0, 15.2],
    })

    tiered = assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0, mag_col="mag_lambda")
    tiers = tiered["tier"].tolist()

    assert tiers == [
        "bright",  # 8.5 < 11.0
        "bright",  # 10.99 < 11.0
        "medium",  # 11.0 <= 11.0 < 13.0
        "medium",  # 11.0 <= 12.5 < 13.0
        "medium",  # 11.0 <= 12.99 < 13.0
        "faint",   # 13.0 >= 13.0
        "faint",   # 15.2 >= 13.0
    ]


def test_refine_stellar_centroids_2d_gaussian_tier_box_fraction():
    """Verify 2D Gaussian centroiding using 30% box of region for faint, medium, bright."""
    from romanepsf.loader import DQ_FLAGS
    sz = 200
    img = np.zeros((sz, sz), dtype=np.float32)
    dq = np.zeros((sz, sz), dtype=np.uint32)

    # Star 1 (faint, region 81 -> 30% is 25x25) at (40.4, 40.7)
    true_x1, true_y1 = 40.4, 40.7
    gy, gx = np.indices((sz, sz))
    star1 = 200.0 * np.exp(-((gx - true_x1)**2 + (gy - true_y1)**2) / (2.0 * 1.5**2)) + 5.0

    # Star 2 (medium, region 201 -> 30% is 61x61) with saturated core at (140.2, 140.5)
    true_x2, true_y2 = 140.2, 140.5
    star2 = 5000.0 * np.exp(-((gx - true_x2)**2 + (gy - true_y2)**2) / (2.0 * 2.5**2)) + 5.0
    sat_core = np.hypot(gx - true_x2, gy - true_y2) <= 3.0
    dq[sat_core] = DQ_FLAGS["SATURATED"]
    star2[sat_core] = 10000.0

    img = star1 + star2

    df = pd.DataFrame({
        "source_id": [101, 102],
        "x": [40.0, 140.0],
        "y": [40.0, 140.0],
        "mag_lambda": [14.0, 12.0],
        "tier": ["faint", "medium"],
    })

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=img, raw_data=img,
        err=np.ones_like(img), dq=dq,
        wcs=None, pa_aperture=0.0, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13,
        zp_ab=26.8, meta={}, is_calibrated=True,
    )

    refined = refine_stellar_centroids(l2, df, box_fraction=0.30)

    assert refined["centroid_method"].iloc[0] == "2d_gaussian"
    assert refined["x"].iloc[0] == pytest.approx(true_x1, abs=0.05)
    assert refined["y"].iloc[0] == pytest.approx(true_y1, abs=0.05)

    assert refined["centroid_method"].iloc[1] == "2d_gaussian"
    assert refined["x"].iloc[1] == pytest.approx(true_x2, abs=0.15)
    assert refined["y"].iloc[1] == pytest.approx(true_y2, abs=0.15)

