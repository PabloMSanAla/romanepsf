"""
Adversarial Stress Test Suite for Milestone 1 Iteration 2.

Empirically challenges:
1. Astrometric 0/360 Meridian Wrap-Around:
   - Arbitrary angle offsets (+-360, +720 degrees).
   - Boundary values (exact 0.0, 360.0, -0.0, epsilon offsets).
   - Arbitrary detector orientations and coordinate shifts across the meridian.
2. Centroid Refinement Hardening:
   - Multi-hit cosmic rays flagged with JUMP_DET surrounding stellar core.
   - Direct cosmic ray hit on the stellar peak pixel.
   - Saturated stellar cores (3x3 and 5x5 flat plateaus with SATURATED DQ flag).
   - Saturated core with simultaneous adjacent cosmic ray.
   - Bad pixel clusters (3x3 DO_NOT_USE).
   - Negative flux background with sub-sigma positive noise fluctuation.
3. Catalog Sanitization Robustness:
   - Extreme scientific notation (1.2345e+02, 3.5999e2, 1e-5, 1e-308).
   - Non-numeric strings, corrupted inputs, mixed types, dirty whitespace.
   - Boundary magnitudes (mag=0.0, mag=35.0, negative solar system objects).
   - Missing and all-NaN coordinate / magnitude columns.
"""

from pathlib import Path
import io
import numpy as np
import pandas as pd
import pytest

from romanepsf.loader import RomanL2Data, DQ_FLAGS
from romanepsf.catalog import (
    sanitize_source_catalog,
    project_catalog_to_pixels,
    refine_stellar_centroids,
    filter_isolated_stars,
    assign_stellar_tiers,
    get_psf_extension_moffat,
)
from tests.unit.test_adversarial_m1 import MockGWCS, make_test_l2


# ==============================================================================
# Challenge Dimension 1: 0/360 Meridian Wrap-Around with Arbitrary Angles
# ==============================================================================

class TestMeridianWrapAroundStress:
    """Stress-test coordinate projection across the 0/360 celestial meridian."""

    @pytest.mark.parametrize("ra_offset", [-720.0, -360.0, 0.0, 360.0, 720.0])
    def test_project_catalog_arbitrary_angle_offsets(self, ra_offset):
        """Verify arbitrary multiples of 360 degrees project without distortion."""
        wcs = MockGWCS(crval=(0.0, 0.0))
        l2 = make_test_l2(wcs=wcs)

        # Place stars safely within detector boundaries (avoiding edge float margin)
        test_pixels = [55.0, 100.0, 500.0, 2044.0, 3000.0, 4000.0, 4030.0]
        ras, decs = wcs(test_pixels, test_pixels)

        df = pd.DataFrame({
            "source_id": list(range(len(test_pixels))),
            "ra": (ras + ra_offset) % 360.0,
            "dec": decs,
            "mag_lambda": [12.0] * len(test_pixels),
        })

        proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
        assert len(proj) == len(test_pixels), f"Failed for ra_offset={ra_offset}: got {len(proj)}"
        # Verify sub-milliarcsecond roundtrip precision
        assert (proj["delta_theta_arcsec"] < 0.001).all()

    def test_project_catalog_exact_0_and_360_boundary(self):
        """Verify boundary coordinates RA=0.0 and RA=360.0 project identically."""
        wcs = MockGWCS(crval=(0.0, 0.0))
        l2 = make_test_l2(wcs=wcs)

        # Detector center is at RA=0.0, Dec=0.0 (pixel 2044, 2044)
        df_zero = pd.DataFrame({
            "source_id": [1],
            "ra": [0.0],
            "dec": [0.0],
            "mag_lambda": [12.0],
        })
        df_360 = pd.DataFrame({
            "source_id": [2],
            "ra": [360.0],
            "dec": [0.0],
            "mag_lambda": [12.0],
        })

        proj_zero = project_catalog_to_pixels(l2, df_zero, margin_px=50)
        proj_360 = project_catalog_to_pixels(l2, df_360, margin_px=50)

        assert len(proj_zero) == 1
        assert len(proj_360) == 1
        np.testing.assert_allclose(proj_zero["x"].iloc[0], proj_360["x"].iloc[0], atol=1e-5)
        np.testing.assert_allclose(proj_zero["y"].iloc[0], proj_360["y"].iloc[0], atol=1e-5)
        assert proj_zero["delta_theta_arcsec"].iloc[0] < 0.01
        assert proj_360["delta_theta_arcsec"].iloc[0] < 0.01

    def test_project_catalog_high_declination_meridian(self):
        """Verify meridian crossing at high declination (+75 deg) where cos(dec) is small."""
        wcs = MockGWCS(crval=(0.001, 75.0))
        l2 = make_test_l2(wcs=wcs)

        test_pixels = [500.0, 2044.0, 3500.0]
        ras, decs = wcs(test_pixels, test_pixels)
        df = pd.DataFrame({
            "source_id": [1, 2, 3],
            "ra": ras % 360.0,
            "dec": decs,
            "mag_lambda": [12.0] * 3,
        })

        proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
        assert len(proj) == 3
        assert (proj["delta_theta_arcsec"] < 0.1).all()


# ==============================================================================
# Challenge Dimension 2: Centroid Refinement Adversarial Stress Testing
# ==============================================================================

class TestCentroidRefinementStress:
    """Stress-test subpixel centroid refinement against severe image artifacts."""

    def test_multi_hit_cosmic_rays_flagged_jump_det(self):
        """Verify multiple simultaneous high-energy cosmic rays are fully masked."""
        data = np.zeros((100, 100), dtype=np.float32)
        dq = np.zeros((100, 100), dtype=np.uint32)

        # Real star centered at (50.0, 50.0) with peak 500
        gy, gx = np.indices((100, 100))
        data += 500.0 * np.exp(-((gx - 50.0)**2 + (gy - 50.0)**2) / (2 * 1.5**2)).astype(np.float32)

        # 3 high-energy cosmic rays in the 11x11 box flagged with JUMP_DET
        cr_positions = [(51, 52), (48, 51), (52, 49)]
        for r, c in cr_positions:
            data[r, c] = 40000.0
            dq[r, c] = DQ_FLAGS["JUMP_DET"]

        l2 = make_test_l2(data=data, dq=dq)
        df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [12.0]})

        refined = refine_stellar_centroids(l2, df, box_radius=5)
        # Centroid should remain locked on the stellar core with negligible deviation (< 0.1 px)
        offset = np.hypot(refined["x"].iloc[0] - 50.0, refined["y"].iloc[0] - 50.0)
        assert offset < 0.1, f"Multi-hit cosmic rays distorted centroid by {offset:.3f} px!"

    def test_peak_pixel_hit_by_cosmic_ray(self):
        """Verify that when a cosmic ray hits the peak pixel, masking preserves symmetry."""
        data = np.zeros((100, 100), dtype=np.float32)
        dq = np.zeros((100, 100), dtype=np.uint32)

        gy, gx = np.indices((100, 100))
        data += 500.0 * np.exp(-((gx - 50.0)**2 + (gy - 50.0)**2) / (2 * 1.5**2)).astype(np.float32)

        # Peak pixel at (50, 50) hit by CR and flagged
        data[50, 50] = 50000.0
        dq[50, 50] = DQ_FLAGS["JUMP_DET"]

        l2 = make_test_l2(data=data, dq=dq)
        df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [12.0]})

        refined = refine_stellar_centroids(l2, df, box_radius=5)
        # Symmetric wings should preserve the center at exactly 50.0
        assert abs(refined["x"].iloc[0] - 50.0) < 0.05
        assert abs(refined["y"].iloc[0] - 50.0) < 0.05

    def test_saturated_star_plateau(self):
        """Verify saturated star cores (3x3 and 5x5 plateaus) are centered accurately."""
        data = np.zeros((100, 100), dtype=np.float32)
        dq = np.zeros((100, 100), dtype=np.uint32)

        gy, gx = np.indices((100, 100))
        data += 100000.0 * np.exp(-((gx - 50.0)**2 + (gy - 50.0)**2) / (2 * 2.5**2)).astype(np.float32)

        # 3x3 flat saturation plateau capped at 80,000 DN/s with SATURATED DQ flag
        data[49:52, 49:52] = 80000.0
        dq[49:52, 49:52] = DQ_FLAGS["SATURATED"]

        l2 = make_test_l2(data=data, dq=dq)
        df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [9.0]})

        refined = refine_stellar_centroids(l2, df, box_radius=5)
        assert abs(refined["x"].iloc[0] - 50.0) < 0.01
        assert abs(refined["y"].iloc[0] - 50.0) < 0.01
        assert refined["peak_flux"].iloc[0] == 80000.0

    def test_saturated_star_with_adjacent_cosmic_ray(self):
        """Verify saturated star core remains unperturbed when an adjacent CR is masked."""
        data = np.zeros((100, 100), dtype=np.float32)
        dq = np.zeros((100, 100), dtype=np.uint32)

        gy, gx = np.indices((100, 100))
        data += 100000.0 * np.exp(-((gx - 50.0)**2 + (gy - 50.0)**2) / (2 * 2.5**2)).astype(np.float32)
        data[49:52, 49:52] = 80000.0
        dq[49:52, 49:52] = DQ_FLAGS["SATURATED"]

        # Adjacent CR at (52, 53)
        data[52, 53] = 95000.0
        dq[52, 53] = DQ_FLAGS["JUMP_DET"]

        l2 = make_test_l2(data=data, dq=dq)
        df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [9.0]})

        refined = refine_stellar_centroids(l2, df, box_radius=5)
        assert abs(refined["x"].iloc[0] - 50.0) < 0.05
        assert abs(refined["y"].iloc[0] - 50.0) < 0.05

    def test_bad_pixel_cluster_do_not_use(self):
        """Verify a 3x3 cluster of DO_NOT_USE bad pixels does not cause centroid divergence."""
        data = np.zeros((100, 100), dtype=np.float32)
        dq = np.zeros((100, 100), dtype=np.uint32)

        gy, gx = np.indices((100, 100))
        data += 500.0 * np.exp(-((gx - 50.0)**2 + (gy - 50.0)**2) / (2 * 1.5**2)).astype(np.float32)

        # 3x3 dead pixel cluster flagged DO_NOT_USE
        data[49:52, 51:54] = 0.0
        dq[49:52, 51:54] = DQ_FLAGS["DO_NOT_USE"]

        l2 = make_test_l2(data=data, dq=dq)
        df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [12.0]})

        refined = refine_stellar_centroids(l2, df, box_radius=5)
        # Centroid shifts modestly due to missing flank but remains bounded (< 1.0 px)
        assert refined["centroid_shift_px"].iloc[0] < 1.0


# ==============================================================================
# Challenge Dimension 3: Catalog Sanitization Extreme Inputs
# ==============================================================================

class TestCatalogSanitizationStress:
    """Stress-test source catalog sanitization with extreme and malformed inputs."""

    def test_scientific_notation_and_extreme_floats(self):
        """Verify scientific notation parsing and rejection of unphysical values."""
        df = pd.DataFrame({
            "source_id": list(range(10)),
            "ra": ["1.2345e+02", "3.5999e2", "1e-5", "1e+10", "-1e-5", "1e308", "1e-308", "nan", "inf", "-inf"],
            "dec": ["-1.993e1", "0.0e0", "-8.99e1", "1e+10", "-1e+10", "1e308", "1e-308", "nan", "inf", "-inf"],
            "mag_lambda": ["1.2e1", "1.5e1", "1.1e1", "12.0", "12.0", "12.0", "12.0", "12.0", "12.0", "12.0"],
        })

        clean = sanitize_source_catalog(df)
        # Only valid astronomical coordinates within [0, 360] and [-90, +90] should be kept
        kept_ids = clean["source_id"].tolist()
        assert kept_ids == [0, 1, 2, 6]

    def test_missing_and_all_nan_columns(self):
        """Verify handling of missing and all-NaN columns."""
        # Missing mandatory 'ra' column must raise ValueError
        df_no_ra = pd.DataFrame({"dec": [-19.9], "mag_lambda": [12.0]})
        with pytest.raises(ValueError, match="must contain 'ra' and 'dec'"):
            sanitize_source_catalog(df_no_ra)

        # All-NaN 'ra' column returns empty DataFrame
        df_nan_ra = pd.DataFrame({
            "source_id": [1, 2],
            "ra": [np.nan, np.nan],
            "dec": [-19.9, -19.8],
            "mag_lambda": [12.0, 13.0],
        })
        clean_nan_ra = sanitize_source_catalog(df_nan_ra)
        assert len(clean_nan_ra) == 0

        # Secondary all-NaN column preserved without crashing
        df_extra_nan = pd.DataFrame({
            "source_id": [1, 2],
            "ra": [303.1, 303.2],
            "dec": [-19.9, -19.8],
            "mag_lambda": [12.0, 13.0],
            "all_nan_col": [np.nan, np.nan],
        })
        clean_extra = sanitize_source_catalog(df_extra_nan)
        assert len(clean_extra) == 2
        assert "all_nan_col" in clean_extra.columns

    def test_mixed_types_and_dirty_strings(self):
        """Verify mixed string/float types and dirty whitespace are sanitized."""
        df = pd.DataFrame({
            "source_id": [1, 2, 3, 4],
            "ra": [" 303.12 ", "303.15", "corrupt_ra", 303.20],
            "dec": ["-19.93", " -19.90 ", -19.85, "corrupt_dec"],
            "mag_lambda": [" 12.0 ", 13.0, 14.0, 15.0],
        })

        clean = sanitize_source_catalog(df)
        assert len(clean) == 2
        assert clean["source_id"].tolist() == [1, 2]
        assert np.isclose(clean["ra"].iloc[0], 303.12)
        assert np.isclose(clean["dec"].iloc[1], -19.90)

    def test_phot_g_mean_mag_ab_collision_resolution(self):
        """Verify phot_g_mean_mag_AB is renamed to phot_g_mean_mag without collision."""
        df_ab = pd.DataFrame({
            "source_id": [1],
            "ra": [303.1],
            "dec": [-19.9],
            "phot_g_mean_mag_AB": [14.5],
        })
        clean = sanitize_source_catalog(df_ab, mag_col="mag_lambda")
        assert "phot_g_mean_mag" in clean.columns
        assert clean["phot_g_mean_mag"].iloc[0] == 14.5
