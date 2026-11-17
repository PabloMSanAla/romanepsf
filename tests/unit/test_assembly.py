"""
Comprehensive Unit Tests for romanepsf.assembly module.

Covers:
- Robust tier tensor stacking with PyTorch acceleration and sigma clipping
- 1D radial profile measurement strictly for calibration
- Dual-radius overlap scale factor calculation (eliminating IndexError)
- Backward-compatible overlap scale factor wrapper
- Seamless 2D raised-cosine partition-of-unity annular blending
- Composite ePSF assembly with canvas sizing, non-negative clipping, and unit normalization
- Non-hollow core protection and diagnostics validation
"""

import numpy as np
import pytest
import torch

import romanepsf.assembly as assembly
import romanepsf.profile as profile


class TestStackTierStampsTorch:
    """Unit tests for stack_tier_stamps_torch."""

    def test_median_stack_constant_signal(self):
        """Verify stack of 5 identical stamps recovers exact signal and coverage 5."""
        stamps_list = []
        for i in range(5):
            d = np.full((81, 81), 12.0, dtype=np.float32)
            m = np.zeros((81, 81), dtype=bool)
            stamps_list.append(assembly.StellarStamp(
                source_id=i, tier="faint", mag=14.0, data=d, mask=m, center_original=(40, 40), size=81
            ))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list, device="cpu")
        assert stacked.shape == (81, 81)
        assert np.isclose(stacked[40, 40], 12.0)
        assert cov[40, 40] == 5

    def test_sigma_clip_rejects_positive_outlier(self):
        """Verify +1000 sigma outlier pixel is rejected by sigma clipping."""
        stamps_list = []
        for i in range(5):
            d = np.full((81, 81), 10.0, dtype=np.float32)
            if i == 0:
                d[40, 40] = 99999.0
            m = np.zeros((81, 81), dtype=bool)
            stamps_list.append(assembly.StellarStamp(
                source_id=i, tier="faint", mag=14.0, data=d, mask=m, center_original=(40, 40), size=81
            ))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list, device="cpu", sigma_clip=3.0)
        assert np.isclose(stacked[40, 40], 10.0, atol=0.5)
        assert cov[40, 40] == 4

    def test_coverage_map_masked_pixels(self):
        """Verify coverage count decrements when pixels are masked."""
        stamps_list = []
        for i in range(4):
            d = np.ones((81, 81), dtype=np.float32)
            m = np.zeros((81, 81), dtype=bool)
            if i >= 2:
                m[40, 40] = True
            stamps_list.append(assembly.StellarStamp(
                source_id=i, tier="faint", mag=14.0, data=d, mask=m, center_original=(40, 40), size=81
            ))
        _, cov = assembly.stack_tier_stamps_torch(stamps_list, device="cpu")
        assert cov[40, 40] == 2

    def test_heterogeneous_stamp_sizes_padded(self):
        """Verify stamps of sizes 81 and 201 are padded to 201."""
        s1 = assembly.StellarStamp(
            source_id=1, tier="med", mag=12.0, data=np.ones((81, 81), dtype=np.float32),
            mask=np.zeros((81, 81), dtype=bool), center_original=(40, 40), size=81
        )
        s2 = assembly.StellarStamp(
            source_id=2, tier="med", mag=12.0, data=np.ones((201, 201), dtype=np.float32),
            mask=np.zeros((201, 201), dtype=bool), center_original=(100, 100), size=201
        )
        stacked, cov = assembly.stack_tier_stamps_torch([s1, s2], device="cpu")
        assert stacked.shape == (201, 201)
        assert cov[100, 100] == 2
        assert cov[0, 0] == 1

    def test_empty_stamp_list_raises_error(self):
        """Verify empty stamp list raises ValueError."""
        with pytest.raises(ValueError, match="Cannot stack an empty stamp list"):
            assembly.stack_tier_stamps_torch([])

    def test_single_stamp_stack(self):
        """Verify N=1 stack returns original stamp and cov=1."""
        d = np.random.RandomState(42).randn(81, 81).astype(np.float32)
        m = np.zeros((81, 81), dtype=bool)
        s = assembly.StellarStamp(source_id=1, tier="faint", mag=14.0, data=d, mask=m, center_original=(40, 40), size=81)
        stacked, cov = assembly.stack_tier_stamps_torch([s], device="cpu")
        np.testing.assert_allclose(stacked, d, atol=1e-5)
        assert np.all(cov == 1)

    def test_two_stamps_stack_no_false_rejection(self):
        """Verify N=2 stamps stack without false outlier rejection."""
        s1 = assembly.StellarStamp(source_id=1, tier="faint", mag=14.0, data=np.ones((81, 81), dtype=np.float32) * 10.0, mask=np.zeros((81, 81), dtype=bool), center_original=(40, 40), size=81)
        s2 = assembly.StellarStamp(source_id=2, tier="faint", mag=14.0, data=np.ones((81, 81), dtype=np.float32) * 12.0, mask=np.zeros((81, 81), dtype=bool), center_original=(40, 40), size=81)
        stacked, cov = assembly.stack_tier_stamps_torch([s1, s2], device="cpu")
        assert cov[40, 40] == 2

    def test_all_masked_center_hollow_core_fallback(self):
        """Verify masked center pixel recovers non-zero flux from 3x3 neighborhood."""
        d = np.ones((81, 81), dtype=np.float32) * 50.0
        m = np.zeros((81, 81), dtype=bool)
        m[40, 40] = True  # Mask center pixel
        s = assembly.StellarStamp(source_id=1, tier="faint", mag=14.0, data=d, mask=m, center_original=(40, 40), size=81)
        stacked, _ = assembly.stack_tier_stamps_torch([s], device="cpu")
        # Center pixel must not remain 0.0
        assert stacked[40, 40] > 0.0


class TestMeasureRadialProfile1D:
    """Unit tests for measure_radial_profile_1d."""

    def test_profile_dimensions_match(self):
        """Verify matching length for radii, flux, and flux_err with geometric spacing."""
        img = np.ones((101, 101), dtype=np.float32)
        r, f, ferr = assembly.measure_radial_profile_1d(img, rmax=40)
        assert len(r) == len(f) == len(ferr) > 0
        assert r[0] < r[-1]
        assert np.isclose(r[-1], 40.0, atol=1.0)
        # Check geometric growth:
        ratios = r[1:] / r[:-1]
        assert np.allclose(ratios, 1.03, atol=2e-3)

        # Also verify linear fallback when requested
        r_lin, f_lin, ferr_lin = assembly.measure_radial_profile_1d(img, rmax=40, bin_spacing="linear")
        assert len(r_lin) == len(f_lin) == len(ferr_lin) == 40
        assert np.isclose(r_lin[0], 1.0)
        assert np.isclose(r_lin[-1], 40.0)

    def test_custom_rmax(self):
        """Verify rmax argument controls profile extent."""
        img = np.ones((51, 51), dtype=np.float32)
        r, f, _ = assembly.measure_radial_profile_1d(img, rmax=20)
        assert len(r) == len(f) > 0
        assert np.isclose(r[-1], 20.0, atol=1.0)


class TestDetermineOverlapScaleFactorDual:
    """Unit tests for determine_overlap_scale_factor_dual."""

    def test_dual_radii_different_lengths_no_index_error(self):
        """Verify scale factor calculation between 40-bin inner and 100-bin outer profiles."""
        r_in = np.arange(0.5, 40.5, 1.0)
        r_out = np.arange(0.5, 100.5, 1.0)
        p_in = 100.0 / (1.0 + r_in**2)
        p_out = 10.0 / (1.0 + r_out**2)
        scale = assembly.determine_overlap_scale_factor_dual(p_in, p_out, r_in, r_out, r_min=8.0, r_max=16.0)
        assert np.isclose(scale, 10.0, atol=0.01)

    def test_known_scale_recovery(self):
        """Verify exact recovery of scale factor 4.5."""
        r_in = np.arange(0.5, 50.5, 1.0)
        r_out = np.arange(0.5, 50.5, 1.0)
        p_in = 450.0 / (1.0 + r_in**2)
        p_out = 100.0 / (1.0 + r_out**2)
        scale = assembly.determine_overlap_scale_factor_dual(p_in, p_out, r_in, r_out, r_min=10.0, r_max=20.0)
        assert np.isclose(scale, 4.5, atol=0.01)

    def test_filters_non_positive_and_nan_fluxes(self):
        """Verify negative, zero, and NaN bins are excluded from scale factor ratio."""
        r_in = np.arange(0.5, 30.5, 1.0)
        r_out = np.arange(0.5, 30.5, 1.0)
        p_in = np.full_like(r_in, 10.0)
        p_out = np.full_like(r_out, 2.0)
        # Poison bins
        p_in[10] = 0.0
        p_in[11] = -5.0
        p_out[12] = np.nan
        p_out[13] = -2.0
        scale = assembly.determine_overlap_scale_factor_dual(p_in, p_out, r_in, r_out, r_min=8.0, r_max=20.0)
        assert np.isclose(scale, 5.0)

    def test_fallback_on_empty_overlap(self):
        """Verify empty overlap range returns fallback 1.0."""
        r_in = np.arange(0.5, 20.5, 1.0)
        r_out = np.arange(0.5, 20.5, 1.0)
        p_in = np.ones_like(r_in)
        p_out = np.ones_like(r_out)
        # [50, 60] is completely beyond radius vectors
        scale = assembly.determine_overlap_scale_factor_dual(p_in, p_out, r_in, r_out, r_min=50.0, r_max=60.0)
        assert scale == 1.0

    def test_single_bin_overlap(self):
        """Verify single common bin (r_min == r_max) computes scale factor."""
        r_in = np.arange(0.5, 20.5, 1.0)
        r_out = np.arange(0.5, 20.5, 1.0)
        p_in = np.full_like(r_in, 12.0)
        p_out = np.full_like(r_out, 3.0)
        scale = assembly.determine_overlap_scale_factor_dual(p_in, p_out, r_in, r_out, r_min=8.5, r_max=8.5)
        assert np.isclose(scale, 4.0)


class TestDetermineOverlapScaleFactorLegacy:
    """Unit tests for backward-compatible determine_overlap_scale_factor wrapper."""

    def test_legacy_wrapper_with_different_lengths(self):
        """Verify legacy wrapper reconstructs outer radii when only single radii array is given."""
        r_in = np.arange(0.5, 40.5, 1.0)
        p_in = 100.0 / (1.0 + r_in**2)
        p_out = 10.0 / (1.0 + np.arange(0.5, 100.5, 1.0)**2)
        # Calling with single r_in of length 40 while p_out has length 100
        scale = assembly.determine_overlap_scale_factor(p_in, p_out, r_in, r_min=8.0, r_max=16.0)
        assert np.isclose(scale, 10.0, atol=0.01)

    def test_legacy_wrapper_with_identical_lengths(self):
        """Verify legacy wrapper with same-length arrays."""
        r = np.arange(0.5, 50.5, 1.0)
        p_in = 50.0 / (1.0 + r**2)
        p_out = 10.0 / (1.0 + r**2)
        scale = assembly.determine_overlap_scale_factor(p_in, p_out, r, r_min=10.0, r_max=20.0)
        assert np.isclose(scale, 5.0, atol=0.01)


class TestBlend2DAnnularProfiles:
    """Unit tests for blend_2d_annular_profiles."""

    def test_partition_of_unity(self):
        """Verify w(r) + (1 - w(r)) == 1.0 everywhere."""
        inner = np.ones((101, 101), dtype=np.float32)
        outer = np.ones((101, 101), dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=15.0, r_end=35.0)
        np.testing.assert_allclose(blended, 1.0, atol=1e-6)

    def test_inner_boundary(self):
        """Verify for r <= r_start, blended equals inner image exactly."""
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=15.0, r_end=35.0)
        assert blended[50, 50] == 10.0
        assert blended[50, 55] == 10.0  # r = 5 <= 15

    def test_outer_boundary(self):
        """Verify for r >= r_end, blended equals outer image exactly."""
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=15.0, r_end=35.0)
        assert blended[50, 95] == 2.0  # r = 45 >= 35

    def test_midpoint_weight(self):
        """Verify weight at midpoint is exactly 0.5."""
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 0.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert np.isclose(blended[50, 65], 5.0, atol=1e-3)  # r = 15 = midpoint

    def test_smaller_inner_embedded_in_larger_outer(self):
        """Verify smaller inner image (51x51) embeds centered in outer canvas (101x101)."""
        inner = np.full((51, 51), 7.0, dtype=np.float32)
        outer = np.full((101, 101), 3.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert blended.shape == (101, 101)
        assert blended[50, 50] == 7.0
        assert blended[0, 0] == 3.0

    def test_larger_inner_cropped_to_smaller_outer(self):
        """Verify larger inner image (151x151) is center-cropped to outer canvas (101x101)."""
        inner = np.full((151, 151), 8.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert blended.shape == (101, 101)
        assert blended[50, 50] == 8.0


class TestAssembleCompositeExtendedPSF:
    """Unit tests for assemble_composite_extended_psf."""

    @pytest.fixture
    def synthetic_tier_stamps(self):
        """Create synthetic multi-tier stamps."""
        # Faint (81x81)
        sz_f = 81
        c_f = (sz_f - 1) // 2
        gy_f, gx_f = np.ogrid[:sz_f, :sz_f]
        rf = np.sqrt((gx_f - c_f)**2 + (gy_f - c_f)**2)
        d_f = (5000.0 / (1.0 + (rf / 2.0)**2)).astype(np.float32)
        s_f = assembly.StellarStamp(source_id=1, tier="faint", mag=14.0, data=d_f, mask=np.zeros_like(d_f, dtype=bool), center_original=(c_f, c_f), size=sz_f)

        # Medium (201x201) - scaled by 0.2 (simulating brighter star flux calibration)
        sz_m = 201
        c_m = (sz_m - 1) // 2
        gy_m, gx_m = np.ogrid[:sz_m, :sz_m]
        rm = np.sqrt((gx_m - c_m)**2 + (gy_m - c_m)**2)
        d_m = (25000.0 / (1.0 + (rm / 2.0)**2)).astype(np.float32)
        # Saturate core
        d_m[rm <= 4.0] = 2000.0
        s_m = assembly.StellarStamp(source_id=2, tier="medium", mag=12.0, data=d_m, mask=np.zeros_like(d_m, dtype=bool), center_original=(c_m, c_m), size=sz_m)

        # Bright (501x501) - scaled by 0.04
        sz_b = 501
        c_b = (sz_b - 1) // 2
        gy_b, gx_b = np.ogrid[:sz_b, :sz_b]
        rb = np.sqrt((gx_b - c_b)**2 + (gy_b - c_b)**2)
        d_b = (125000.0 / (1.0 + (rb / 2.0)**2)).astype(np.float32)
        # Saturate inner zone
        d_b[rb <= 15.0] = 2000.0
        s_b = assembly.StellarStamp(source_id=3, tier="bright", mag=9.0, data=d_b, mask=np.zeros_like(d_b, dtype=bool), center_original=(c_b, c_b), size=sz_b)

        return {"faint": [s_f], "medium": [s_m], "bright": [s_b]}

    def test_full_assembly_three_tiers(self, synthetic_tier_stamps):
        """Verify end-to-end 3-tier assembly produces normalized ePSF."""
        epsf, diag = assembly.assemble_composite_extended_psf(synthetic_tier_stamps, output_size=501)
        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        # Center pixel must be positive and peak
        assert epsf[250, 250] > 0.0
        assert np.argmax(epsf) == np.ravel_multi_index((250, 250), epsf.shape)
        # Diagnostics
        assert "k_fm" in diag
        assert "k_mb" in diag
        assert diag["k_fm"] > 0.0
        assert diag["k_mb"] > 0.0

    def test_canvas_size_smaller_than_bright_stamp(self, synthetic_tier_stamps):
        """Verify cropping when output_size < bright stamp size (e.g. 301 < 501)."""
        epsf, _ = assembly.assemble_composite_extended_psf(synthetic_tier_stamps, output_size=301)
        assert epsf.shape == (301, 301)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)

    def test_canvas_size_larger_than_bright_stamp(self, synthetic_tier_stamps):
        """Verify embedding when output_size > bright stamp size (e.g. 1025 > 501)."""
        epsf, _ = assembly.assemble_composite_extended_psf(synthetic_tier_stamps, output_size=1025)
        assert epsf.shape == (1025, 1025)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert epsf[512, 512] > 0.0

    def test_non_negative_clipping(self, synthetic_tier_stamps):
        """Verify synthesized PSF has no negative pixels."""
        epsf, _ = assembly.assemble_composite_extended_psf(synthetic_tier_stamps, output_size=501)
        assert np.all(epsf >= 0.0)

    def test_assembly_missing_bright_tier_fallback(self, synthetic_tier_stamps):
        """Verify graceful 2-tier assembly when bright tier is empty (e.g. WFI02)."""
        stamps_2tier = {
            "faint": synthetic_tier_stamps["faint"],
            "medium": synthetic_tier_stamps["medium"],
            "bright": [],
        }
        epsf, diag = assembly.assemble_composite_extended_psf(stamps_2tier, output_size=501)
        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert epsf[250, 250] > 0.0
        assert diag["k_fm"] > 0.0
        assert diag["k_mb"] is None
        assert diag["psf_bright"] is None

    def test_assembly_missing_faint_tier_fallback(self, synthetic_tier_stamps):
        """Verify graceful 2-tier assembly when faint tier is empty."""
        stamps_2tier = {
            "faint": [],
            "medium": synthetic_tier_stamps["medium"],
            "bright": synthetic_tier_stamps["bright"],
        }
        epsf, diag = assembly.assemble_composite_extended_psf(stamps_2tier, output_size=501)
        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert diag["k_mb"] > 0.0
        assert diag["k_fm"] is None

    def test_assembly_single_tier_fallback(self, synthetic_tier_stamps):
        """Verify graceful single-tier assembly."""
        stamps_1tier = {
            "faint": synthetic_tier_stamps["faint"],
            "medium": [],
            "bright": [],
        }
        epsf, diag = assembly.assemble_composite_extended_psf(stamps_1tier, output_size=251)
        assert epsf.shape == (251, 251)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert diag["k_fm"] is None
        assert diag["k_mb"] is None

    def test_wfi01_assembly_monotonicity_and_scaling(self):
        """Verify WFI01 commissioning data assembly produces physical k_mb and monotonic decay."""
        import os
        import pandas as pd
        from romanepsf import loader, catalog, stamps

        asdf_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf"
        csv_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv"
        if not (os.path.exists(asdf_path) and os.path.exists(csv_path)):
            pytest.skip("Commissioning dataset not found on disk.")

        l2 = loader.load_l2_image(asdf_path, calibrate=True)
        cat_df = pd.read_csv(csv_path, low_memory=False)
        ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
        cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
        cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
        proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
        tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
        tier_stamps = stamps.process_star_stamps(l2, tiered)

        epsf, diag = assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
        assert diag["k_mb"] is not None
        assert 0.010 < diag["k_mb"] < 0.100, f"Unphysical k_mb: {diag['k_mb']}"
        c = 250
        # Verify no 25x flux surge across transition: flux at r=48 must be strictly less than at r=30
        assert epsf[c, c + 48] < epsf[c, c + 30], "Flux surge detected across [30, 48] px"

    def test_overlap_annulus_resolve_radii_depth_mode(self):
        """Verify dynamic calculation of normalization and blending radii from depths."""
        from romanepsf.config import OverlapAnnulusConfig

        cfg_fm = OverlapAnnulusConfig(
            mode="depth",
            norm_depth=(20.0, 23.0),
            blend_depth=(25.0, 27.0),
        )
        r_min, r_max, b_start, b_end = cfg_fm.resolve_radii(mag=19.0, pixel_scale=0.11, max_stamp_radius=25.5)
        assert 2.0 < r_min < 4.0
        assert 6.0 < r_max < 8.0
        assert 12.0 < b_start < 14.0
        assert 22.0 < b_end <= 25.5

        cfg_mb = OverlapAnnulusConfig(
            mode="depth",
            norm_depth=(20.0, 23.0),
            blend_depth=(25.0, 27.0),
        )
        r_min, r_max, b_start, b_end = cfg_mb.resolve_radii(mag=11.0, pixel_scale=0.11, max_stamp_radius=410.5)
        assert 30.0 < r_min < 35.0
        assert 78.0 < r_max < 83.0
        assert 140.0 < b_start < 155.0
        assert 260.0 < b_end < 280.0

    def test_overlap_annulus_safety_clamping(self):
        """Verify safety clamping prevents radii from exceeding inner stamp size."""
        from romanepsf.config import OverlapAnnulusConfig

        cfg_small = OverlapAnnulusConfig(
            mode="depth",
            norm_depth=(25.0, 28.0),
            blend_depth=(28.0, 30.0),
        )
        # Even with extreme depths, clamped within max_stamp_radius * 0.95
        r_min, r_max, b_start, b_end = cfg_small.resolve_radii(mag=11.0, pixel_scale=0.11, max_stamp_radius=50.0)
        assert b_end <= 50.0 * 0.95
        assert b_start < b_end
        assert r_max <= b_end
        assert r_min < r_max
