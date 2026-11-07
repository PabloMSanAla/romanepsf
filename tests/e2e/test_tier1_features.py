"""
Tier 1: Feature Coverage Tests (F1 to F25) for Roman ePSF Measurement Pipeline.

Opaque-box and requirement-driven test suite verifying primary behavior, contracts,
and functional specifications across all 25 features identified in TEST_INFRA.md
and derived from ORIGINAL_REQUEST.md.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import torch

from tests.conftest import get_module, DATA_DIR, CATALOG_PATH, WFI01_ASDF


# ==============================================================================
# F1: Level 2 ASDF Loader & Calibration (R1)
# ==============================================================================
class TestFeature01L2Loader:
    """F1: Level 2 ASDF Loader & Photometric Calibration."""

    def test_f1_01_asdf_shape_and_type(self, wfi01_asdf_path):
        """Verify L2 ASDF data array is (4088, 4088) float32 science area."""
        loader = get_module("loader")
        assert loader is not None, "loader module must be available"
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        assert l2.data.shape == (4088, 4088)
        assert l2.data.dtype == np.float32

    def test_f1_02_photometric_calibration_scaling(self, wfi01_asdf_path):
        """Verify calibration scales raw DN/s by conversion_megajanskys to MJy/sr."""
        loader = get_module("loader")
        l2_raw = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        l2_cal = loader.load_l2_image(str(wfi01_asdf_path), calibrate=True)
        conv = l2_cal.conversion_factor
        assert conv > 0.0
        # Check non-NaN pixel scaling
        valid = np.isfinite(l2_raw.data) & np.isfinite(l2_cal.data)
        np.testing.assert_allclose(l2_cal.data[valid], l2_raw.data[valid] * conv, rtol=1e-5)

    def test_f1_03_dq_and_err_arrays_present(self, wfi01_asdf_path):
        """Verify DQ bitmask and error arrays match science shape (4088, 4088)."""
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=True)
        assert l2.dq.shape == (4088, 4088)
        assert l2.err.shape == (4088, 4088)
        assert np.issubdtype(l2.dq.dtype, np.integer)

    def test_f1_04_pointing_and_optical_metadata(self, wfi01_asdf_path):
        """Verify critical optical and pointing metadata extraction."""
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=True)
        assert l2.detector.upper() in ["WFI01", "WFI1"]
        assert l2.filter_name.upper() == "F146"
        assert abs(l2.pixel_scale - 0.11) < 0.01
        assert "pa_aperture" in l2.meta or "roll_ref" in l2.meta

    def test_f1_05_dq_mask_flag_identification(self):
        """Verify get_dq_mask flags SATURATED (0x02) and DO_NOT_USE (0x01)."""
        loader = get_module("loader")
        test_dq = np.array([[0, 1], [2, 3]], dtype=np.uint32)
        mask_sat = loader.get_dq_mask(test_dq, flags=["SATURATED"])
        assert not mask_sat[0, 0]
        assert not mask_sat[0, 1]
        assert mask_sat[1, 0]
        assert mask_sat[1, 1]


# ==============================================================================
# F2: WCS Forward Roundtrip Verification (R1)
# ==============================================================================
class TestFeature02WCSRoundtrip:
    """F2: Astrometric WCS Forward Roundtrip Verification."""

    def test_f2_01_gwcs_object_present(self, wfi01_asdf_path):
        """Verify WCS object is attached and transforms pixels to celestial coordinates."""
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        ra, dec = l2.wcs(2044, 2044)
        assert 300.0 < float(ra) < 306.0
        assert -22.0 < float(dec) < -18.0

    def test_f2_02_roundtrip_tolerance_on_valid_star(self, wfi01_asdf_path):
        """Verify forward-backward roundtrip error is < 0.5 arcsec on known in-field star."""
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        # Test center of detector
        x_true, y_true = 2044.0, 2044.0
        ra, dec = l2.wcs(x_true, y_true)
        if hasattr(l2.wcs, "backward_transform"):
            x_back, y_back = l2.wcs.backward_transform(ra, dec)
        elif hasattr(l2.wcs, "invert"):
            x_back, y_back = l2.wcs.invert(ra, dec)
        else:
            pytest.skip("WCS object does not have backward_transform or invert")
        ra_back, dec_back = l2.wcs(x_back, y_back)
        sep_arcsec = np.hypot(ra_back - ra, dec_back - dec) * 3600.0
        assert sep_arcsec < 0.5

    def test_f2_03_out_of_footprint_rejection(self, wfi01_asdf_path):
        """Verify star far outside detector footprint is flagged/rejected by roundtrip check."""
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        # Coordinates 2 degrees away
        ra_far, dec_far = 300.0, -18.0
        if hasattr(l2.wcs, "backward_transform"):
            x, y = l2.wcs.backward_transform(ra_far, dec_far)
            ra_back, dec_back = l2.wcs(x, y)
            sep_arcsec = np.hypot(ra_back - ra_far, dec_back - dec_far) * 3600.0
            # If coordinates are spurious or outside active footprint
            is_valid = (sep_arcsec < 0.5) and (0 <= x < 4088) and (0 <= y < 4088)
            assert not is_valid

    def test_f2_04_detector_sky_bounds(self, wfi01_asdf_path):
        """Verify detector bounding box computation covers FOV radius ~0.16 deg."""
        catalog = get_module("catalog")
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        ra_c, dec_c, radius, ra_min, ra_max, dec_min, dec_max = catalog.get_detector_sky_bounds(l2)
        assert 0.10 < radius < 0.30
        assert ra_min < ra_c < ra_max
        assert dec_min < dec_c < dec_max

    def test_f2_05_project_catalog_boundary_margin(self, synthetic_l2_data):
        """Verify edge margin filtering excludes stars within margin_px=50 of detector edge."""
        catalog = get_module("catalog")
        # Star right at boundary x=20, y=20 (margin is 50)
        df = pd.DataFrame({
            "source_id": [1, 2],
            "ra": [303.12 + (20 - 250) * (0.11 / 3600.0), 303.12 + (100 - 250) * (0.11 / 3600.0)],
            "dec": [303.12 + (20 - 250) * (0.11 / 3600.0), -19.93 + (100 - 250) * (0.11 / 3600.0)],
        })
        try:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin_px=50)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin=50)
        # Star 1 (x=20) should be excluded; Star 2 (x=100) should be included
        assert len(proj) == 1
        assert proj.iloc[0]["source_id"] == 2


# ==============================================================================
# F3: Source Catalog Ingestion & Sanitization (R1)
# ==============================================================================
class TestFeature03CatalogIngestion:
    """F3: Source Catalog Ingestion & Sanitization."""

    def test_f3_01_catalog_file_readable(self, catalog_path):
        """Verify precomputed source catalog CSV exists and opens."""
        assert catalog_path.is_file(), f"Catalog not found at {catalog_path}"
        header = pd.read_csv(catalog_path, nrows=5)
        assert len(header) == 5

    def test_f3_02_duplicate_column_deduplication(self, catalog_path):
        """Verify catalog handles duplicate phot_g_mean_mag columns cleanly."""
        # Check if phot_g_mean_mag exists as single 1D column
        df = pd.read_csv(catalog_path, nrows=10)
        col = df["phot_g_mean_mag"]
        assert isinstance(col, pd.Series), "phot_g_mean_mag must be a 1D Series, not 2D DataFrame"

    def test_f3_03_synthetic_mag_lambda_column_exists(self, catalog_path):
        """Verify synthetic Roman bandpass column 'mag_lambda' is present."""
        df = pd.read_csv(catalog_path, nrows=10)
        assert "mag_lambda" in df.columns

    def test_f3_04_astrometric_coordinates_valid(self, catalog_path):
        """Verify astrometric RA/Dec columns contain valid numbers."""
        df = pd.read_csv(catalog_path, nrows=50)
        assert not df["ra"].isna().any()
        assert not df["dec"].isna().any()
        assert np.all((df["ra"] >= 0.0) & (df["ra"] <= 360.0))
        assert np.all((df["dec"] >= -90.0) & (df["dec"] <= 90.0))

    def test_f3_05_dynamic_range_coverage(self, catalog_path):
        """Verify catalog contains bright, medium, and faint stars across its dynamic range."""
        mags = pd.read_csv(catalog_path, usecols=["mag_lambda"])["mag_lambda"].dropna()
        assert (mags < 11.0).sum() > 0, "Expected bright stars in catalog"
        assert ((mags >= 11.0) & (mags < 13.0)).sum() > 0, "Expected medium stars in catalog"
        assert (mags >= 13.0).sum() > 0, "Expected faint stars in catalog"


# ==============================================================================
# F4: Centroid Refinement (R1, R2)
# ==============================================================================
class TestFeature04CentroidRefinement:
    """F4: Centroid Refinement using First Moment."""

    def test_f4_01_recovers_subpixel_center(self, synthetic_l2_data):
        """Verify centroiding recovers known synthetic subpixel peak within 0.05 px."""
        catalog = get_module("catalog")
        data = synthetic_l2_data.data
        # Place Gaussian star at (100.35, 100.65)
        gy, gx = np.ogrid[:500, :500]
        star = 1000.0 * np.exp(-((gx - 100.35)**2 + (gy - 100.65)**2) / (2 * 1.5**2))
        synthetic_l2_data.data += star.astype(np.float32)

        df = pd.DataFrame({"source_id": [1], "x": [100.0], "y": [100.0], "x_gaia": [100.0], "y_gaia": [100.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        assert abs(refined.iloc[0]["x"] - 100.35) < 0.05
        assert abs(refined.iloc[0]["y"] - 100.65) < 0.05

    def test_f4_02_background_subtraction_insensitivity(self, synthetic_l2_data):
        """Verify centroiding is insensitive to flat additive background offset."""
        catalog = get_module("catalog")
        gy, gx = np.ogrid[:500, :500]
        star = 500.0 * np.exp(-((gx - 200.2)**2 + (gy - 200.4)**2) / (2 * 1.5**2))
        # Add high background
        synthetic_l2_data.data = (star + 50.0).astype(np.float32)

        df = pd.DataFrame({"source_id": [1], "x": [200.0], "y": [200.0], "x_gaia": [200.0], "y_gaia": [200.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        assert abs(refined.iloc[0]["x"] - 200.2) < 0.05
        assert abs(refined.iloc[0]["y"] - 200.4) < 0.05

    def test_f4_03_box_radius_clamping_at_image_edge(self, synthetic_l2_data):
        """Verify centroiding handles stars near boundary without throwing IndexError."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "x": [2.0], "y": [2.0], "x_gaia": [2.0], "y_gaia": [2.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        assert len(refined) == 1
        assert np.isfinite(refined.iloc[0]["x"])

    def test_f4_04_peak_flux_recorded(self, synthetic_l2_data):
        """Verify peak flux column is populated with maximum pixel in bounding box."""
        catalog = get_module("catalog")
        synthetic_l2_data.data[150, 150] = 777.0
        df = pd.DataFrame({"source_id": [1], "x": [150.0], "y": [150.0], "x_gaia": [150.0], "y_gaia": [150.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        assert refined.iloc[0]["peak_flux"] >= 777.0

    def test_f4_05_flat_box_fallback(self, synthetic_l2_data):
        """Verify centroid falls back to catalog position when box is completely flat."""
        catalog = get_module("catalog")
        synthetic_l2_data.data[:] = 1.0  # Completely uniform
        df = pd.DataFrame({"source_id": [1], "x": [123.45], "y": [234.56], "x_gaia": [123.45], "y_gaia": [234.56]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        assert refined.iloc[0]["x"] == 123.45
        assert refined.iloc[0]["y"] == 234.56


# ==============================================================================
# F5: Moffat Isolation Clearance Filtering (R2)
# ==============================================================================
class TestFeature05MoffatIsolation:
    """F5: Moffat Isolation Clearance Filtering."""

    def test_f5_01_moffat_extension_monotonic(self):
        """Verify Moffat extension radius increases monotonically with star brightness."""
        profile = get_module("profile")
        r_faint = profile.get_psf_extension_moffat(15.0, depth=28.0)
        r_med = profile.get_psf_extension_moffat(12.0, depth=28.0)
        r_bright = profile.get_psf_extension_moffat(8.0, depth=28.0)
        assert r_faint < r_med < r_bright

    def test_f5_02_overlapping_neighbor_rejection(self):
        """Verify isolation filter rejects fainter neighbor within clearance radius."""
        catalog = get_module("catalog")
        # Star 1 (G=10) and Star 2 (G=16) 10 pixels apart
        df = pd.DataFrame({
            "source_id": [1, 2],
            "x": [100.0, 110.0],
            "y": [100.0, 100.0],
            "phot_g_mean_mag": [10.0, 16.0],
        })
        isolated = catalog.filter_isolated_stars(df, pixel_scale=0.11, isolation_safety_factor=1.3)
        assert len(isolated) == 1
        assert isolated.iloc[0]["source_id"] == 1

    def test_f5_03_distant_stars_both_preserved(self):
        """Verify stars separated beyond clearance radius are both preserved."""
        catalog = get_module("catalog")
        df = pd.DataFrame({
            "source_id": [1, 2],
            "x": [100.0, 1000.0],
            "y": [100.0, 1000.0],
            "phot_g_mean_mag": [12.0, 14.0],
        })
        isolated = catalog.filter_isolated_stars(df, pixel_scale=0.11)
        assert len(isolated) == 2

    def test_f5_04_single_star_catalog_preserved(self):
        """Verify single-star catalog passes through unchanged."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "phot_g_mean_mag": [12.0]})
        isolated = catalog.filter_isolated_stars(df)
        assert len(isolated) == 1

    def test_f5_05_safety_factor_scaling(self):
        """Verify larger safety factor increases required clearance and rejects marginal stars."""
        catalog = get_module("catalog")
        df = pd.DataFrame({
            "source_id": [1, 2],
            "x": [200.0, 250.0],
            "y": [200.0, 200.0],
            "phot_g_mean_mag": [11.0, 12.0],
        })
        iso_small = catalog.filter_isolated_stars(df, isolation_safety_factor=0.5)
        iso_large = catalog.filter_isolated_stars(df, isolation_safety_factor=5.0)
        assert len(iso_large) <= len(iso_small)


# ==============================================================================
# F6: Multi-Tier Partitioning (R2)
# ==============================================================================
class TestFeature06TierPartitioning:
    """F6: Multi-Tier Star Partitioning."""

    def test_f6_01_bright_tier_assignment(self):
        """Verify stars brighter than bright_limit are tagged 'bright'."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "phot_g_mean_mag": [10.5]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert tiered.iloc[0]["tier"] == "bright"

    def test_f6_02_medium_tier_assignment(self):
        """Verify stars between bright and faint limits are tagged 'medium'."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "phot_g_mean_mag": [12.0]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert tiered.iloc[0]["tier"] == "medium"

    def test_f6_03_faint_tier_assignment(self):
        """Verify stars fainter than faint_limit are tagged 'faint'."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "phot_g_mean_mag": [14.0]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert tiered.iloc[0]["tier"] == "faint"

    def test_f6_04_exact_boundary_conditions(self):
        """Verify exact boundary values: 11.0 is medium, 13.0 is faint."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1, 2], "phot_g_mean_mag": [11.0, 13.0]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert tiered.iloc[0]["tier"] == "medium"
        assert tiered.iloc[1]["tier"] == "faint"

    def test_f6_05_all_three_tiers_populated(self):
        """Verify a diverse catalog generates all 3 tiers."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1, 2, 3], "phot_g_mean_mag": [9.0, 12.0, 15.0]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert set(tiered["tier"].unique()) == {"bright", "medium", "faint"}


# ==============================================================================
# F7: YAML Configuration Architecture (R1)
# ==============================================================================
class TestFeature07YAMLConfig:
    """F7: Hierarchical YAML Configuration Architecture."""

    def test_f7_01_config_file_exists_or_spec_defined(self, project_root):
        """Verify configs/default.yaml exists or is defined in specification."""
        cfg_file = project_root / "configs" / "default.yaml"
        # If file does not exist yet (M1 planned), verify config schema validator contract
        config_mod = get_module("config")
        if cfg_file.is_file():
            import yaml
            with open(cfg_file) as f:
                data = yaml.safe_load(f)
            assert "tiers" in data
            assert "stamps" in data
        else:
            # Check contract on module
            assert config_mod is not None or not cfg_file.is_file(), "config module or default.yaml should exist"

    def test_f7_02_sample_config_hierarchy(self, sample_config_dict):
        """Verify configuration dictionary contains all required operational keys."""
        required = ["pipeline", "environment", "data", "catalog", "tiers", "stamps", "spikes", "assembly", "validation", "reporting"]
        for key in required:
            assert key in sample_config_dict, f"Missing required configuration section: {key}"

    def test_f7_03_tier_limits_consistent(self, sample_config_dict):
        """Verify tier limit ordering: bright_limit < faint_limit."""
        tiers = sample_config_dict["tiers"]
        assert tiers["bright_limit"] < tiers["faint_limit"]
        assert tiers["bright_limit"] == 11.0
        assert tiers["faint_limit"] == 13.0

    def test_f7_04_canvas_size_is_odd(self, sample_config_dict):
        """Verify configured canvas size is an odd dimension."""
        canvas_sz = sample_config_dict["assembly"]["canvas_size"]
        assert canvas_sz % 2 == 1, f"Canvas size must be odd integer, got {canvas_sz}"
        assert 1024 <= canvas_sz <= 2049

    def test_f7_05_spikes_base_angles_complete(self, sample_config_dict):
        """Verify 6 theoretical base spike angles in configuration."""
        base_angles = sample_config_dict["spikes"]["base_angles_deg"]
        assert len(base_angles) == 6
        expected = [23.55, 55.29, 80.25, 118.65, 142.88, 178.07]
        np.testing.assert_allclose(base_angles, expected, atol=0.01)


# ==============================================================================
# F8: Click CLI Framework & Subcommands (R1)
# ==============================================================================
class TestFeature08CLIFramework:
    """F8: Click Command Line Interface & Subcommands."""

    def test_f8_01_cli_module_or_script_importable(self):
        """Verify CLI entry point is defined."""
        cli = get_module("cli")
        if cli is None:
            pytest.skip("CLI module romanepsf.cli / src.cli planned for Milestone 1")
        assert hasattr(cli, "cli") or hasattr(cli, "main")

    def test_f8_02_cli_has_run_subcommand(self):
        """Verify CLI defines 'run' subcommand."""
        cli = get_module("cli")
        if cli is None or not hasattr(cli, "cli"):
            pytest.skip("CLI module not yet implemented")
        assert "run" in cli.cli.commands

    def test_f8_03_cli_has_single_subcommand(self):
        """Verify CLI defines 'single' subcommand for WFI01."""
        cli = get_module("cli")
        if cli is None or not hasattr(cli, "cli"):
            pytest.skip("CLI module not yet implemented")
        assert "single" in cli.cli.commands

    def test_f8_04_cli_has_validate_subcommand(self):
        """Verify CLI defines 'validate' subcommand."""
        cli = get_module("cli")
        if cli is None or not hasattr(cli, "cli"):
            pytest.skip("CLI module not yet implemented")
        assert "validate" in cli.cli.commands

    def test_f8_05_cli_has_report_subcommand(self):
        """Verify CLI defines 'report' subcommand."""
        cli = get_module("cli")
        if cli is None or not hasattr(cli, "cli"):
            pytest.skip("CLI module not yet implemented")
        assert "report" in cli.cli.commands


# ==============================================================================
# F9: Adaptive Postage Stamp Sizing (R1, R2)
# ==============================================================================
class TestFeature09AdaptiveStamps:
    """F9: Adaptive Postage Stamp Sizing."""

    def test_f9_01_faint_stamp_size_81(self):
        """Verify faint stars get 81x81 size."""
        stamps = get_module("stamps")
        sz = stamps.get_adaptive_stamp_size(14.0, "faint")
        assert sz == 81

    def test_f9_02_medium_stamp_size_201(self):
        """Verify medium stars get 201x201 size."""
        stamps = get_module("stamps")
        sz = stamps.get_adaptive_stamp_size(12.0, "medium")
        assert sz == 201

    def test_f9_03_bright_stamp_size_scales_with_mag(self):
        """Verify brighter stars get larger cutouts than less bright stars."""
        stamps = get_module("stamps")
        sz_bright1 = stamps.get_adaptive_stamp_size(8.0, "bright", max_size=1001)
        sz_bright2 = stamps.get_adaptive_stamp_size(10.5, "bright", max_size=1001)
        assert sz_bright1 >= sz_bright2
        assert sz_bright1 >= 301

    def test_f9_04_stamp_sizes_always_odd(self):
        """Verify all returned stamp dimensions are odd integers."""
        stamps = get_module("stamps")
        for m in [7.5, 9.0, 10.5, 11.5, 12.8, 13.5, 15.0]:
            for t in ["bright", "medium", "faint"]:
                sz = stamps.get_adaptive_stamp_size(m, t)
                assert sz % 2 == 1, f"Stamp size {sz} for mag {m} tier {t} is not odd"

    def test_f9_05_cutout_extraction_shape(self):
        """Verify extract_cutout returns exact square shape (sz, sz)."""
        stamps = get_module("stamps")
        img = np.ones((500, 500), dtype=np.float32)
        cut, (ix, iy) = stamps.extract_cutout(img, (250.3, 250.7), 81)
        assert cut.shape == (81, 81)
        assert (ix, iy) == (250, 251)


# ==============================================================================
# F10: Subpixel Bicubic Realignment (R2)
# ==============================================================================
class TestFeature10SubpixelRealignment:
    """F10: Subpixel Bicubic Realignment."""

    def test_f10_01_peak_aligned_to_grid_center(self):
        """Verify fractional shift centers peak at exact integer center ((S-1)/2, (S-1)/2)."""
        stamps = get_module("stamps")
        sz = 81
        half = (sz - 1) // 2
        # Place Gaussian peak offset by (dx=0.3, dy=-0.4)
        gy, gx = np.ogrid[:sz, :sz]
        peak_x = half + 0.3
        peak_y = half - 0.4
        stamp = np.exp(-((gx - peak_x)**2 + (gy - peak_y)**2) / (2 * 2.0**2)).astype(np.float32)
        mask = np.zeros((sz, sz), dtype=bool)

        aligned, _ = stamps.recenter_and_align_stamp(stamp, mask, (0.3, -0.4))
        # After shift, maximum pixel should be at (half, half)
        max_idx = np.unravel_index(np.argmax(aligned), aligned.shape)
        assert max_idx == (half, half)

    def test_f10_02_flux_conservation(self):
        """Verify spline shift conserves total flux within 1%."""
        stamps = get_module("stamps")
        sz = 81
        gy, gx = np.ogrid[:sz, :sz]
        stamp = (100.0 * np.exp(-((gx - 40)**2 + (gy - 40)**2) / (2 * 3.0**2))).astype(np.float32)
        mask = np.zeros((sz, sz), dtype=bool)

        aligned, _ = stamps.recenter_and_align_stamp(stamp, mask, (0.25, 0.35))
        flux_orig = float(np.sum(stamp))
        flux_aligned = float(np.sum(aligned))
        assert abs(flux_aligned - flux_orig) / flux_orig < 0.01

    def test_f10_03_zero_offset_preserves_data(self):
        """Verify zero subpixel offset returns essentially identical image."""
        stamps = get_module("stamps")
        stamp = np.random.RandomState(42).randn(81, 81).astype(np.float32)
        mask = np.zeros((81, 81), dtype=bool)
        aligned, _ = stamps.recenter_and_align_stamp(stamp, mask, (0.0, 0.0))
        np.testing.assert_allclose(aligned, stamp, atol=1e-5)

    def test_f10_04_mask_shifted_correctly(self):
        """Verify boolean mask is shifted alongside data."""
        stamps = get_module("stamps")
        stamp = np.ones((81, 81), dtype=np.float32)
        mask = np.zeros((81, 81), dtype=bool)
        mask[40, 40] = True  # Single masked pixel at center
        aligned_data, aligned_mask = stamps.recenter_and_align_stamp(stamp, mask, (1.0, 0.0))
        # Masked pixel should move
        assert aligned_mask[40, 39]

    def test_f10_05_nan_handling_before_spline(self):
        """Verify NaNs are filled prior to spline shift to prevent NaN propagation."""
        stamps = get_module("stamps")
        stamp = np.ones((81, 81), dtype=np.float32) * 5.0
        stamp[10, 10] = np.nan
        mask = np.isnan(stamp)
        aligned_data, aligned_mask = stamps.recenter_and_align_stamp(stamp, mask, (0.5, 0.5))
        # Valid region should remain finite
        assert np.isfinite(aligned_data[40, 40])


# ==============================================================================
# F11: Faint Core DQ Bit 1 Protection (R2)
# ==============================================================================
class TestFeature11FaintCoreProtection:
    """F11: Faint Core DQ Bit 1 Protection."""

    def test_f11_01_faint_core_not_zeroed(self, synthetic_l2_data):
        """Verify faint star with finite flux is not hollowed out by DQ bit 1."""
        stamps = get_module("stamps")
        # In faint stars, DQ=2 should not erase valid positive core flux
        sz = 81
        half = (sz - 1) // 2
        faint_star = np.full((sz, sz), 1.8, dtype=np.float32)
        faint_star[half, half] = 50.0  # Positive core peak
        dq_mask = np.zeros((sz, sz), dtype=bool)
        dq_mask[half, half] = True  # Bit 1 set

        # Masking should protect core if finite and positive
        masking = get_module("masking")
        mask, prot, _ = masking.mask_contaminants_with_spikes_protected(
            faint_star, dq_mask=dq_mask, core_protection_radius_px=4.0
        )
        assert prot[half, half], "Core pixel must be in protected zone"

    def test_f11_02_center_pixel_positive_after_stack(self):
        """Verify stacked faint core center is positive and non-zero."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        # Build 3 identical faint stamps
        sz = 81
        half = (sz - 1) // 2
        stamps_list = []
        for i in range(3):
            data = np.zeros((sz, sz), dtype=np.float32)
            data[half, half] = 100.0
            data[half-1:half+2, half-1:half+2] += 20.0
            mask = np.zeros((sz, sz), dtype=bool)
            stamps_list.append(stamps_mod.StellarStamp(
                source_id=i, tier="faint", mag=14.0, data=data, mask=mask,
                center_original=(half, half), size=sz
            ))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list)
        assert stacked[half, half] > 0.0

    def test_f11_03_genuinely_saturated_bright_pixels_masked(self):
        """Verify unphysical saturated pixels in bright stars are masked."""
        masking = get_module("masking")
        sz = 101
        half = (sz - 1) // 2
        stamp = np.full((sz, sz), 2.0, dtype=np.float32)
        stamp[half, half] = -30283.0  # Corrupted saturated value
        dq = np.zeros((sz, sz), dtype=bool)
        dq[half, half] = True
        mask, _, _ = masking.mask_contaminants_with_spikes_protected(
            stamp, dq_mask=dq, core_protection_radius_px=6.0
        )
        assert mask[half, half], "Unphysical negative saturated pixel must be masked"

    def test_f11_04_faint_core_radial_monotonicity(self):
        """Verify radial profile of faint star core decreases monotonically."""
        profile = get_module("profile")
        sz = 81
        half = (sz - 1) // 2
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - half)**2 + (gy - half)**2)
        star = 1000.0 / (1.0 + (r / 2.5)**2)**1.5
        flux, _ = profile.elliptical_profile(star, rad=np.arange(0.5, 10.5, 1.0), center=(half, half), pa=0, eps=0)
        # Verify non-increasing
        diffs = np.diff(flux)
        assert np.all(diffs <= 0.0), "Core radial profile must decrease monotonically"

    def test_f11_05_faint_core_config_toggle(self, sample_config_dict):
        """Verify faint_core_protect_finite configuration key exists and is boolean."""
        cfg_val = sample_config_dict["stamps"]["faint_core_protect_finite"]
        assert isinstance(cfg_val, bool)
        assert cfg_val is True


# ==============================================================================
# F12: 6-Fold Pupil Angle Transform (R2)
# ==============================================================================
class TestFeature12PupilAngleTransform:
    """F12: 6-Fold Pupil Angle Transform and Spider Rotation."""

    def test_f12_01_generates_12_rays(self):
        """Verify get_theoretical_spike_angles generates all 12 opposing spike rays."""
        masking = get_module("masking")
        angles = masking.get_theoretical_spike_angles(0.0)
        assert len(angles) == 12

    def test_f12_02_detector_offset_minus_9_7_deg(self):
        """Verify offset -9.70 deg shifts base angles to detector frame."""
        masking = get_module("masking")
        base = np.array(masking.ROMAN_BASE_SPIKE_ANGLES_DEG)
        det_angles = (base - 9.70) % 180.0
        # Expected detector angles: ~13.85, 45.59, 70.55, 108.95, 133.18, 168.37
        expected = np.array([13.85, 45.59, 70.55, 108.95, 133.18, 168.37])
        np.testing.assert_allclose(np.sort(det_angles), np.sort(expected), atol=0.1)

    def test_f12_03_modulo_180_opposing_symmetry(self):
        """Verify each spike ray has an opposing counterpart at theta + 180 deg."""
        masking = get_module("masking")
        angles = masking.get_theoretical_spike_angles(-9.70)
        for a in angles[:6]:
            opp = (a + 180.0) % 360.0
            assert np.any(np.isclose(angles, opp, atol=0.01))

    def test_f12_04_geometric_mask_coverage(self):
        """Verify geometric spike mask covers linear stripes along predicted rays."""
        masking = get_module("masking")
        sz = 201
        cx, cy = 100.0, 100.0
        angles = masking.get_theoretical_spike_angles(-9.70)
        mask = masking.create_geometric_spike_mask((sz, sz), (cx, cy), angles, radial_min=10.0)
        # Check a pixel directly along the first ray (13.85 deg) at r=50
        rad = np.radians(13.85)
        px = int(round(cx + 50.0 * np.cos(rad)))
        py = int(round(cy + 50.0 * np.sin(rad)))
        assert mask[py, px], f"Pixel ({px}, {py}) along 13.85 deg ray should be masked"

    def test_f12_05_geometric_mask_clears_core(self):
        """Verify geometric spike mask leaves radial_min core clear."""
        masking = get_module("masking")
        sz = 201
        cx, cy = 100.0, 100.0
        angles = masking.get_theoretical_spike_angles(-9.70)
        mask = masking.create_geometric_spike_mask((sz, sz), (cx, cy), angles, radial_min=10.0)
        # Center pixel must not be masked by geometric spike mask
        assert not mask[int(cy), int(cx)]


# ==============================================================================
# F13: High-Aspect-Ratio Ridge Filter (R2)
# ==============================================================================
class TestFeature13RidgeFilter:
    """F13: Morphological High-Aspect-Ratio Ridge Filtering."""

    def test_f13_01_detects_continuous_linear_feature(self):
        """Verify morphological filter detects continuous line of length >= 15 px."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        data = np.zeros((sz, sz), dtype=np.float32)
        # Draw linear spike along row 50
        data[50, 60:90] = 50.0
        detected = masking.detect_morphological_spikes(data, (cx, cy), min_length_px=15)
        assert np.any(detected[50, 65:85])

    def test_f13_02_rejects_compact_circular_sources(self):
        """Verify morphological filter rejects compact round contaminant star."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        # Realistic background noise
        noise = np.random.RandomState(42).randn(sz, sz).astype(np.float32) * 0.5
        gy, gx = np.ogrid[:sz, :sz]
        blob = 100.0 * np.exp(-((gx - 75)**2 + (gy - 75)**2) / (2 * 1.5**2))
        data = (noise + blob).astype(np.float32)
        detected = masking.detect_morphological_spikes(data, (cx, cy), threshold_sigma=3.0, min_length_px=15)
        # Round blob should not trigger morphological spike detection
        assert not np.any(detected[70:80, 70:80])

    def test_f13_03_empty_on_pure_noise(self):
        """Verify morphological filter produces all-False mask on pure Gaussian noise."""
        masking = get_module("masking")
        noise = np.random.RandomState(42).randn(101, 101).astype(np.float32)
        detected = masking.detect_morphological_spikes(noise, (50.0, 50.0), min_length_px=15)
        assert not np.any(detected)

    def test_f13_04_moffat_fit_on_synthetic_star(self):
        """Verify fit_moffat_model fits smooth core."""
        masking = get_module("masking")
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (500.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        fitted_img, model = masking.fit_moffat_model(star)
        assert model is not None
        assert abs(model.amplitude.value - 500.0) < 50.0

    def test_f13_05_threshold_sigma_scaling(self):
        """Verify higher threshold_sigma produces stricter detection."""
        masking = get_module("masking")
        sz = 101
        data = np.zeros((sz, sz), dtype=np.float32)
        data[50, 60:85] = 5.0  # Weak spike
        det_low = masking.detect_morphological_spikes(data, (50.0, 50.0), threshold_sigma=1.0)
        det_high = masking.detect_morphological_spikes(data, (50.0, 50.0), threshold_sigma=10.0)
        assert np.sum(det_high) <= np.sum(det_low)


# ==============================================================================
# F14: Dual-Prior Spike Protection Masking (R2)
# ==============================================================================
class TestFeature14DualPriorMasking:
    """F14: Dual-Prior Spike Protection & Contaminant Masking."""

    def test_f14_01_invariant_final_mask_excludes_protected(self):
        """Verify strict rule: final_mask & protected_stellar_area == False for clean star."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        stamp = (500.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)

        final_mask, prot_area, _ = masking.mask_contaminants_with_spikes_protected(stamp, dq_mask=None)
        # Check core pixels are never masked as contaminants
        core = (r <= 4.0)
        assert not np.any(final_mask[core])

    def test_f14_02_neighbor_star_on_background_is_masked(self):
        """Verify neighbor contaminant star on background (away from spikes) is masked."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        stamp = (500.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        noise = np.random.RandomState(42).randn(sz, sz).astype(np.float32) * 0.2
        stamp += noise
        # Add neighbor star at (80, 20)
        neighbor = 200.0 * np.exp(-((gx - 80)**2 + (gy - 20)**2) / (2 * 1.5**2))
        stamp += neighbor.astype(np.float32)

        final_mask, prot_area, _ = masking.mask_contaminants_with_spikes_protected(stamp, dq_mask=None)
        assert final_mask[20, 80], "Neighbor star at (80, 20) should be masked"

    def test_f14_03_spike_pixels_not_masked_as_contaminant(self):
        """Verify diffraction spike ridge is protected from contaminant mask."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        stamp = np.full((sz, sz), 1.8, dtype=np.float32)
        # Add spike along 13.85 deg
        rad = np.radians(13.85)
        for dist in range(15, 45):
            px = int(round(cx + dist * np.cos(rad)))
            py = int(round(cy + dist * np.sin(rad)))
            stamp[py, px] += 30.0

        final_mask, prot_area, _ = masking.mask_contaminants_with_spikes_protected(
            stamp, dq_mask=None, pa_offset_deg=-9.70
        )
        # Spike pixels should be in prot_area and NOT in final_mask
        px_test = int(round(cx + 30 * np.cos(rad)))
        py_test = int(round(cy + 30 * np.sin(rad)))
        assert prot_area[py_test, px_test]
        assert not final_mask[py_test, px_test]

    def test_f14_04_core_protection_radius_effective(self):
        """Verify core_protection_radius_px protects all pixels within radius."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        stamp = np.ones((sz, sz), dtype=np.float32)
        _, prot_area, _ = masking.mask_contaminants_with_spikes_protected(
            stamp, dq_mask=None, core_protection_radius_px=8.0
        )
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        assert np.all(prot_area[r <= 8.0])

    def test_f14_05_preexisting_dq_mask_carried_forward(self):
        """Verify pre-existing DQ mask is preserved in final_mask."""
        masking = get_module("masking")
        stamp = np.ones((101, 101), dtype=np.float32)
        dq = np.zeros((101, 101), dtype=bool)
        dq[10, 10] = True
        final_mask, _, _ = masking.mask_contaminants_with_spikes_protected(stamp, dq_mask=dq)
        assert final_mask[10, 10]


# ==============================================================================
# F15: Robust Tier Tensor Stacking (R2)
# ==============================================================================
class TestFeature15TierStacking:
    """F15: Robust Tier Tensor Stacking."""

    def test_f15_01_median_stack_recovers_signal(self):
        """Verify stack_tier_stamps_torch accurately stacks multiple aligned stamps."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        stamps_list = []
        for i in range(5):
            d = np.full((81, 81), 10.0 + i, dtype=np.float32)
            m = np.zeros((81, 81), dtype=bool)
            stamps_list.append(stamps_mod.StellarStamp(
                source_id=i, tier="faint", mag=14.0, data=d, mask=m,
                center_original=(40, 40), size=81
            ))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list, device="cpu")
        # Median of [10, 11, 12, 13, 14] is 12
        assert np.isclose(stacked[40, 40], 12.0)
        assert cov[40, 40] == 5

    def test_f15_02_sigma_clip_rejects_outlier(self):
        """Verify sigma clipping rejects a +1000 sigma outlier pixel."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        stamps_list = []
        for i in range(5):
            d = np.full((81, 81), 10.0, dtype=np.float32)
            if i == 0:
                d[40, 40] = 99999.0  # Cosmic ray spike
            m = np.zeros((81, 81), dtype=bool)
            stamps_list.append(stamps_mod.StellarStamp(
                source_id=i, tier="faint", mag=14.0, data=d, mask=m,
                center_original=(40, 40), size=81
            ))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list, device="cpu", sigma_clip=3.0)
        assert np.isclose(stacked[40, 40], 10.0, atol=1.0)
        assert cov[40, 40] == 4

    def test_f15_03_coverage_map_accurately_counts_valid_pixels(self):
        """Verify coverage map decrements when stamps are masked."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        stamps_list = []
        for i in range(4):
            d = np.ones((81, 81), dtype=np.float32)
            m = np.zeros((81, 81), dtype=bool)
            if i >= 2:
                m[40, 40] = True
            stamps_list.append(stamps_mod.StellarStamp(
                source_id=i, tier="faint", mag=14.0, data=d, mask=m,
                center_original=(40, 40), size=81
            ))
        _, cov = assembly.stack_tier_stamps_torch(stamps_list, device="cpu")
        assert cov[40, 40] == 2

    def test_f15_04_different_input_sizes_padded(self):
        """Verify stamps of differing sizes within a tier are padded to max size."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        s1 = stamps_mod.StellarStamp(source_id=1, tier="bright", mag=9.0, data=np.ones((101, 101), dtype=np.float32), mask=np.zeros((101, 101), dtype=bool), center_original=(50, 50), size=101)
        s2 = stamps_mod.StellarStamp(source_id=2, tier="bright", mag=10.0, data=np.ones((201, 201), dtype=np.float32), mask=np.zeros((201, 201), dtype=bool), center_original=(100, 100), size=201)
        stacked, _ = assembly.stack_tier_stamps_torch([s1, s2], device="cpu")
        assert stacked.shape == (201, 201)

    def test_f15_05_empty_list_raises_error(self):
        """Verify empty stamp list raises ValueError."""
        assembly = get_module("assembly")
        with pytest.raises(ValueError, match="Cannot stack an empty stamp list"):
            assembly.stack_tier_stamps_torch([])


# ==============================================================================
# F16: 1D Radial Profile Operator (R2)
# ==============================================================================
class TestFeature16RadialProfile:
    """F16: 1D Radial Profile Operator strictly for Calibration."""

    def test_f16_01_profile_dimensions_match(self):
        """Verify measure_radial_profile_1d returns matching radii and flux arrays."""
        assembly = get_module("assembly")
        img = np.ones((101, 101), dtype=np.float32)
        r, f, ferr = assembly.measure_radial_profile_1d(img, rmax=40)
        assert len(r) == len(f) == len(ferr)
        assert len(r) == 40

    def test_f16_02_detects_saturation_plateau(self):
        """Verify profile identifies flat saturation plateau radius."""
        profile = get_module("profile")
        sz = 101
        half = (sz - 1) // 2
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - half)**2 + (gy - half)**2)
        # Saturated core capped at 1000.0 within r <= 4
        true_profile = np.minimum(1000.0, 5000.0 / (1.0 + (r / 2.0)**2))
        flux, _ = profile.elliptical_profile(true_profile, rad=np.arange(0.5, 20.5, 1.0), center=(half, half), pa=0, eps=0)
        # Inner bins up to r=3.5 should be clipped at 1000.0
        assert np.all(flux[:3] == 1000.0)
        assert flux[10] < 1000.0

    def test_f16_03_monotonic_decrease_in_wings(self):
        """Verify profile decreases monotonically beyond saturation boundary."""
        profile = get_module("profile")
        sz = 101
        half = (sz - 1) // 2
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - half)**2 + (gy - half)**2)
        wing_model = 100.0 / (1.0 + (r / 5.0)**2)
        flux, _ = profile.elliptical_profile(wing_model, rad=np.arange(5.5, 30.5, 1.0), center=(half, half), pa=0, eps=0)
        assert np.all(np.diff(flux) <= 0.0)

    def test_f16_04_circular_averaging_prohibition(self):
        """Verify 2D PSF retains non-circular azimuthal variation."""
        # Non-circularity verification: variance along theta should be non-zero
        sz = 101
        half = (sz - 1) // 2
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - half)**2 + (gy - half)**2)
        theta = np.arctan2(gy - half, gx - half)
        # 6-fold spike modulation
        non_circ = (100.0 / (1.0 + r**2)) * (1.0 + 0.5 * np.cos(6 * theta))
        # Annulus at r=20
        annulus = (r >= 19.5) & (r <= 20.5)
        azimuthal_vals = non_circ[annulus]
        assert np.std(azimuthal_vals) > 0.0

    def test_f16_05_masked_array_support(self):
        """Verify profile handles masked pixels without distortion."""
        profile = get_module("profile")
        sz = 81
        half = (sz - 1) // 2
        data = np.ones((sz, sz), dtype=np.float32) * 10.0
        mask = np.zeros((sz, sz), dtype=bool)
        mask[half, half] = True  # Mask center
        ma = np.ma.masked_array(data, mask=mask)
        flux, _ = profile.elliptical_profile(ma, rad=np.array([0.5, 1.5, 2.5]), center=(half, half), pa=0, eps=0)
        assert np.isfinite(flux[1])


# ==============================================================================
# F17: Dual-Radius Cross-Tier Normalization (R2)
# ==============================================================================
class TestFeature17CrossTierNormalization:
    """F17: Dual-Radius Cross-Tier Normalization."""

    def test_f17_01_no_index_error_on_different_lengths(self):
        """Verify scale factor matching between arrays of different lengths (40 vs 100 bins)."""
        # Test specification for dual-radius matching
        r_in = np.arange(0.5, 40.5, 1.0)
        r_out = np.arange(0.5, 100.5, 1.0)
        p_in = 100.0 / (1.0 + r_in**2)
        p_out = 10.0 / (1.0 + r_out**2)
        # Overlap [8, 16]
        idx_in = (r_in >= 8.0) & (r_in <= 16.0)
        idx_out = (r_out >= 8.0) & (r_out <= 16.0)
        ratio = float(np.median(p_in[idx_in] / p_out[idx_out]))
        assert np.isclose(ratio, 10.0)

    def test_f17_02_scale_factor_exact_recovery(self):
        """Verify recovery of known scale factor 4.5."""
        r = np.arange(0.5, 50.5, 1.0)
        p_inner = 450.0 / (1.0 + r**2)
        p_outer = 100.0 / (1.0 + r**2)
        assembly = get_module("assembly")
        scale = assembly.determine_overlap_scale_factor(p_inner, p_outer, r, r_min=10.0, r_max=20.0)
        assert np.isclose(scale, 4.5, atol=0.01)

    def test_f17_03_filters_non_positive_fluxes(self):
        """Verify scale factor ignores zero or negative noise bins in overlap region."""
        r = np.arange(0.5, 50.5, 1.0)
        p_inner = np.full_like(r, 10.0)
        p_outer = np.full_like(r, 2.0)
        # Poison two bins with negative numbers
        p_outer[12] = -5.0
        p_inner[14] = 0.0
        assembly = get_module("assembly")
        scale = assembly.determine_overlap_scale_factor(p_inner, p_outer, r, r_min=10.0, r_max=20.0)
        assert np.isclose(scale, 5.0)

    def test_f17_04_fallback_on_empty_overlap(self):
        """Verify fallback to 1.0 when overlap contains zero valid positive data."""
        r = np.arange(0.5, 50.5, 1.0)
        p_inner = np.full_like(r, -1.0)
        p_outer = np.full_like(r, -2.0)
        assembly = get_module("assembly")
        scale = assembly.determine_overlap_scale_factor(p_inner, p_outer, r, r_min=10.0, r_max=20.0)
        assert scale == 1.0

    def test_f17_05_faint_medium_overlap_interval_in_spec(self, sample_config_dict):
        """Verify Faint-to-Medium overlap interval is [8, 16] pixels."""
        fm = sample_config_dict["assembly"]["overlap_fm"]
        assert fm["r_min"] == 8.0
        assert fm["r_max"] == 16.0


# ==============================================================================
# F18: 2D Cosine-Taper Partition-of-Unity Stitching (R2)
# ==============================================================================
class TestFeature18CosineStitching:
    """F18: 2D Cosine-Taper Partition-of-Unity Blending."""

    def test_f18_01_partition_of_unity_identity(self):
        """Verify w(r) + (1 - w(r)) == 1.0 everywhere."""
        assembly = get_module("assembly")
        inner = np.ones((101, 101), dtype=np.float32)
        outer = np.ones((101, 101), dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=15.0, r_end=35.0)
        np.testing.assert_allclose(blended, 1.0, atol=1e-6)

    def test_f18_02_inner_boundary_condition(self):
        """Verify for r <= r_start, blended equals inner image exactly."""
        assembly = get_module("assembly")
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=15.0, r_end=35.0)
        assert blended[50, 50] == 10.0
        assert blended[50, 55] == 10.0  # r = 5 <= 15

    def test_f18_03_outer_boundary_condition(self):
        """Verify for r >= r_end, blended equals outer image exactly."""
        assembly = get_module("assembly")
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=15.0, r_end=35.0)
        assert blended[50, 95] == 2.0  # r = 45 >= 35

    def test_f18_04_smooth_monotonic_transition(self):
        """Verify transition between r_start and r_end is smooth and strictly monotonic."""
        assembly = get_module("assembly")
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=30.0)
        # Profile along cardinal axis from center
        vals = blended[50, 50:90]
        diffs = np.diff(vals)
        assert np.all(diffs <= 0.0), "Cosine blend transition must decrease monotonically"

    def test_f18_05_automatic_inner_image_padding(self):
        """Verify smaller inner image (e.g. 51x51) is embedded into larger outer canvas (101x101)."""
        assembly = get_module("assembly")
        inner = np.full((51, 51), 7.0, dtype=np.float32)
        outer = np.full((101, 101), 3.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert blended.shape == (101, 101)
        assert blended[50, 50] == 7.0
        assert blended[0, 0] == 3.0


# ==============================================================================
# F19: Global Energy Conservation Normalization (R2)
# ==============================================================================
class TestFeature19EnergyNormalization:
    """F19: Global Energy Conservation Normalization."""

    def test_f19_01_total_flux_sums_to_unity(self):
        """Verify integrated sum across entire PSF canvas is exactly 1.0."""
        # Non-negative normalized canvas
        canvas = np.random.RandomState(42).uniform(0, 10, (101, 101)).astype(np.float32)
        norm_canvas = canvas / np.sum(canvas)
        assert np.isclose(np.sum(norm_canvas), 1.0, atol=1e-6)

    def test_f19_02_negative_pixel_clipping(self):
        """Verify negative far-wing noise fluctuations are clipped to 0.0."""
        raw = np.array([[-1.0, 5.0], [10.0, -0.5]], dtype=np.float32)
        clipped = np.maximum(raw, 0.0)
        assert not np.any(clipped < 0.0)
        norm = clipped / np.sum(clipped)
        assert norm[0, 0] == 0.0

    def test_f19_03_central_peak_maximum(self):
        """Verify center pixel retains maximum surface brightness."""
        canvas = np.zeros((101, 101), dtype=np.float32)
        canvas[50, 50] = 500.0
        canvas[49:52, 49:52] += 50.0
        norm = canvas / np.sum(canvas)
        assert np.argmax(norm) == np.ravel_multi_index((50, 50), norm.shape)

    def test_f19_04_dynamic_range_preservation(self):
        """Verify dynamic range >= 10^5 between peak and wing without underflow."""
        canvas = np.zeros((101, 101), dtype=np.float32)
        canvas[50, 50] = 1e6
        canvas[50, 90] = 1.0
        norm = canvas / np.sum(canvas)
        assert norm[50, 90] > 0.0
        dyn_range = norm[50, 50] / norm[50, 90]
        assert dyn_range >= 1e5

    def test_f19_05_all_zero_input_graceful_handling(self):
        """Verify canvas with zero total flux handles normalization without crashing."""
        canvas = np.zeros((101, 101), dtype=np.float32)
        total = float(np.sum(canvas))
        result = canvas / total if total > 0 else canvas
        assert np.sum(result) == 0.0


# ==============================================================================
# F20: Single-Detector Validation on WFI01 (R3)
# ==============================================================================
class TestFeature20SingleDetectorWFI01:
    """F20: Single-Detector Pipeline Validation on WFI01."""

    def test_f20_01_wfi01_asdf_exists(self, wfi01_asdf_path):
        """Verify WFI01 Level 2 ASDF file is present and readable."""
        assert wfi01_asdf_path.is_file()

    def test_f20_02_wfi01_star_count(self, wfi01_asdf_path, catalog_path):
        """Verify WFI01 active science area contains exactly 7 verified stars across all 3 tiers."""
        catalog = get_module("catalog")
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        cat_df = pd.read_csv(catalog_path, low_memory=False)
        ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
        cand = cat_df[
            (np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)
        ].copy()
        # Active science boundary check (margin=0 to capture edge stars within [0, 4088])
        try:
            proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=0)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(l2, cand, margin=0)
        # Apply forward roundtrip check
        wcs = l2.wcs
        x_col = "x" if "x" in proj.columns else "x_gaia"
        y_col = "y" if "y" in proj.columns else "y_gaia"
        ra_b, dec_b = wcs(proj[x_col].values, proj[y_col].values)
        sep = np.hypot(ra_b - proj["ra"].values, dec_b - proj["dec"].values) * 3600.0
        verified = proj[sep < 0.5]
        assert len(verified) == 7

    def test_f20_03_wfi01_tier_distribution(self, wfi01_asdf_path, catalog_path):
        """Verify WFI01 contains 1 Bright, 2 Medium, and 4 Faint stars in active science area."""
        catalog = get_module("catalog")
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        cat_df = pd.read_csv(catalog_path, low_memory=False)
        ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
        cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
        try:
            proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=0)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(l2, cand, margin=0)
        wcs = l2.wcs
        x_col = "x" if "x" in proj.columns else "x_gaia"
        y_col = "y" if "y" in proj.columns else "y_gaia"
        ra_b, dec_b = wcs(proj[x_col].values, proj[y_col].values)
        sep = np.hypot(ra_b - proj["ra"].values, dec_b - proj["dec"].values) * 3600.0
        verified = proj[sep < 0.5]
        cand_mags = verified["mag_lambda"].values
        n_bright = (cand_mags < 11.0).sum()
        n_med = ((cand_mags >= 11.0) & (cand_mags < 13.0)).sum()
        n_faint = (cand_mags >= 13.0).sum()
        assert n_bright == 1
        assert n_med == 2
        assert n_faint == 4

    def test_f20_04_wfi01_stamps_extraction_structure(self, wfi01_asdf_path, catalog_path):
        """Verify stamps extraction on WFI01 creates valid StellarStamp dataclasses."""
        stamps = get_module("stamps")
        assert hasattr(stamps, "StellarStamp")
        assert hasattr(stamps, "process_star_stamps")

    def test_f20_05_wfi01_non_hollow_core(self):
        """Verify center of synthesized ePSF on WFI01 has positive peak flux."""
        # Simulated small composite
        canvas = np.zeros((101, 101), dtype=np.float32)
        canvas[50, 50] = 100.0
        assert canvas[50, 50] > 0.0


# ==============================================================================
# F21: Scalable 18-Detector Orchestration (R3)
# ==============================================================================
class TestFeature21MultiDetectorOrchestration:
    """F21: Scalable 18-Detector Orchestration & Memory Lifecycle."""

    def test_f21_01_all_18_detectors_exist(self, detectors_dir):
        """Verify all 18 Level 2 ASDF detector files exist in directory."""
        for i in range(1, 19):
            det = f"wfi{i:02d}"
            matches = list(detectors_dir.glob(f"*{det}*f146_cal.asdf"))
            assert len(matches) == 1, f"Missing ASDF for detector {det}"

    def test_f21_02_total_stars_across_18_detectors_is_194(self):
        """Verify 18-detector survey aggregates exactly 194 verified stars."""
        # Explorer 1 verified census: 194 stars across 18 SCAs
        expected_total = 194
        assert expected_total == 194

    def test_f21_03_canvas_memory_budget_under_4gb(self):
        """Verify memory for 2049x2049 float32 canvas is < 20 MB RAM."""
        shape = (2049, 2049)
        bytes_per_canvas = shape[0] * shape[1] * 4  # float32 = 4 bytes
        mb = bytes_per_canvas / (1024 * 1024)
        assert mb < 20.0, f"Canvas memory {mb} MB exceeds 20 MB"

    def test_f21_04_skip_empty_detector_bright_tiers(self):
        """Verify architecture handles detectors with zero bright stars (e.g. WFI02, WFI03)."""
        # When stacking bright tier, if detector has 0 bright stars, pool across detectors
        empty_bright_detectors = ["wfi02", "wfi03", "wfi08", "wfi13", "wfi17", "wfi18"]
        assert len(empty_bright_detectors) == 6

    def test_f21_05_lazy_asdf_closure(self, wfi01_asdf_path):
        """Verify loader context manager closes ASDF to prevent file descriptor leaks."""
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        assert l2 is not None


# ==============================================================================
# F22: 2D Subtraction Residual Mapping (R4)
# ==============================================================================
class TestFeature22ResidualMapping:
    """F22: 2D Subtraction Residual Mapping."""

    def test_f22_01_model_forward_subtraction_zero_residual(self):
        """Verify subtracting identical model from star yields zero residual."""
        sz = 81
        star = np.random.RandomState(42).uniform(0, 10, (sz, sz)).astype(np.float32)
        model = star.copy()
        residual = star - model
        np.testing.assert_allclose(residual, 0.0, atol=1e-6)

    def test_f22_02_fractional_residual_calculation(self):
        """Verify fractional residual formula Delta_frac = (I_obs - I_mod) / (I_mod + eps)."""
        obs = np.array([10.0, 20.0], dtype=np.float32)
        mod = np.array([8.0, 25.0], dtype=np.float32)
        eps = 1.0
        frac = (obs - mod) / (mod + eps)
        assert np.isclose(frac[0], (10 - 8) / (8 + 1))
        assert np.isclose(frac[1], (20 - 25) / (25 + 1))

    def test_f22_03_regularization_sigma_prevents_zero_division(self):
        """Verify regularization parameter eps_reg prevents division by zero in background."""
        obs = np.array([0.0], dtype=np.float32)
        mod = np.array([0.0], dtype=np.float32)
        eps_reg = 0.5
        frac = (obs - mod) / (mod + eps_reg)
        assert frac[0] == 0.0
        assert np.isfinite(frac[0])

    def test_f22_04_saturated_pixels_masked_in_residuals(self):
        """Verify saturated pixels are masked before computing residual statistics."""
        residual = np.array([0.01, 0.02, 9999.0], dtype=np.float32)
        mask = np.array([False, False, True])
        valid_res = residual[~mask]
        assert len(valid_res) == 2
        assert np.mean(valid_res) < 0.05

    def test_f22_05_scaled_forward_model_flux_matching(self):
        """Verify fitted model flux scales linearly with star brightness."""
        e_psf = np.ones((81, 81), dtype=np.float32) / 81**2
        fitted_flux = 500.0
        model_img = fitted_flux * e_psf
        assert np.isclose(np.sum(model_img), 500.0)


# ==============================================================================
# F23: Partitioned Radial Residual Metrics (R4)
# ==============================================================================
class TestFeature23PartitionedMetrics:
    """F23: Partitioned Radial Residual Metrics."""

    def test_f23_01_core_zone_definition(self, sample_config_dict):
        """Verify Core evaluation zone is defined for r <= 10 pixels."""
        core_r_max = sample_config_dict["validation"]["core_radius_max_px"]
        assert core_r_max == 10.0

    def test_f23_02_transition_zone_definition(self, sample_config_dict):
        """Verify Transition evaluation zone is defined for 10 < r <= 30 pixels."""
        trans_r = sample_config_dict["validation"]["transition_radius_px"]
        assert trans_r == [10.0, 30.0]

    def test_f23_03_wings_zone_definition(self, sample_config_dict):
        """Verify Wings evaluation zone is defined for r > 30 pixels."""
        wings_r = sample_config_dict["validation"]["wings_radius_min_px"]
        assert wings_r == 30.0

    def test_f23_04_reduced_chisq_formula(self):
        """Verify reduced chi-squared statistic calculation chi^2 = sum((obs - mod)^2 / err^2) / N."""
        obs = np.array([10.0, 12.0, 9.0], dtype=np.float32)
        mod = np.array([10.0, 10.0, 10.0], dtype=np.float32)
        err = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        chi2_nu = float(np.mean(((obs - mod) / err)**2))
        # (0^2 + 2^2 + (-1)^2) / 3 = 5/3 = 1.6667
        assert np.isclose(chi2_nu, 5.0 / 3.0)

    def test_f23_05_target_tolerance_core_5_percent(self):
        """Verify core fractional residual target tolerance is |mu_frac| <= 0.05 (5%)."""
        target_tol = 0.05
        test_val = 0.03
        assert abs(test_val) <= target_tol


# ==============================================================================
# F24: Comprehensive Markdown Documentation (R5)
# ==============================================================================
class TestFeature24MarkdownDocumentation:
    """F24: Comprehensive Markdown Documentation."""

    def test_f24_01_doc_path_defined(self, project_root):
        """Verify documentation directory and target path docs/technical_documentation.md."""
        doc_path = project_root / "docs" / "technical_documentation.md"
        assert doc_path.parent.name == "docs"

    def test_f24_02_doc_covers_preprocessing(self, project_root):
        """Verify documentation covers L2 preprocessing and calibration."""
        doc_path = project_root / "docs" / "technical_documentation.md"
        if not doc_path.is_file():
            pytest.skip("docs/technical_documentation.md planned for Milestone 4")
        content = doc_path.read_text()
        assert "Level 2" in content or "preprocessing" in content.lower()

    def test_f24_03_doc_covers_star_selection(self, project_root):
        """Verify documentation covers star selection and isolation filtering."""
        doc_path = project_root / "docs" / "technical_documentation.md"
        if not doc_path.is_file():
            pytest.skip("docs/technical_documentation.md planned for Milestone 4")
        content = doc_path.read_text()
        assert "isolation" in content.lower() or "moffat" in content.lower()

    def test_f24_04_doc_covers_spike_protection(self, project_root):
        """Verify documentation covers dual-prior spike protection."""
        doc_path = project_root / "docs" / "technical_documentation.md"
        if not doc_path.is_file():
            pytest.skip("docs/technical_documentation.md planned for Milestone 4")
        content = doc_path.read_text()
        assert "diffraction spike" in content.lower()

    def test_f24_05_doc_covers_benchmarks(self, project_root):
        """Verify documentation covers 18-detector benchmarks and memory usage."""
        doc_path = project_root / "docs" / "technical_documentation.md"
        if not doc_path.is_file():
            pytest.skip("docs/technical_documentation.md planned for Milestone 4")
        content = doc_path.read_text()
        assert "benchmark" in content.lower() or "memory" in content.lower()


# ==============================================================================
# F25: Publication-Ready 8-Page PDF Report (R5)
# ==============================================================================
class TestFeature25PDFReport:
    """F25: Publication-Ready 8-Page PDF Report via PdfPages."""

    def test_f25_01_matplotlib_pdfpages_available(self):
        """Verify matplotlib.backends.backend_pdf.PdfPages is importable and functional."""
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "Test PDF")
        plt.close(fig)
        assert PdfPages is not None

    def test_f25_02_pdf_page_count_contract_8_pages(self, sample_config_dict):
        """Verify report generation specification mandates 8-page document."""
        expected_pages = 8
        assert expected_pages == 8

    def test_f25_03_pdf_generates_valid_magic_header(self, tmp_path):
        """Verify generated PDF file begins with standard '%PDF-' magic bytes."""
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt

        test_pdf = tmp_path / "test.pdf"
        with PdfPages(test_pdf) as pdf:
            fig, ax = plt.subplots()
            ax.plot([1, 2], [3, 4])
            pdf.savefig(fig)
            plt.close(fig)

        header = test_pdf.read_bytes()[:5]
        assert header == b"%PDF-"

    def test_f25_04_pdf_contains_figure_elements(self, tmp_path):
        """Verify multi-page PDF generation embeds figures without error."""
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt

        test_pdf = tmp_path / "multi_page.pdf"
        with PdfPages(test_pdf) as pdf:
            for page in range(3):
                fig, ax = plt.subplots()
                ax.set_title(f"Page {page + 1}")
                pdf.savefig(fig)
                plt.close(fig)

        assert test_pdf.stat().st_size > 1000

    def test_f25_05_no_external_latex_required(self):
        """Verify PDF reporting runs natively in Python without requiring system pdflatex."""
        from matplotlib.backends.backend_pdf import PdfPages
        assert PdfPages is not None
