"""
Adversarial Stress Test Suite for 2D Composite ePSF Assembly and Radial Profile Scaling.

Target Modules:
- romanepsf.assembly
- romanepsf.profile

Authored by: Challenger 2 (challenger_m2_2)
"""

import numpy as np
import pytest
import torch

from romanepsf.stamps import StellarStamp
from romanepsf.assembly import (
    stack_tier_stamps_torch,
    measure_radial_profile_1d,
    determine_overlap_scale_factor_dual,
    determine_overlap_scale_factor,
    blend_2d_annular_profiles,
    assemble_composite_extended_psf,
)


# ============================================================================
# 1. Pathological Tests for Overlap Scale Factor Calibration
# ============================================================================

class TestOverlapScaleFactorPathological:
    """Stress-test determine_overlap_scale_factor_dual with pathological inputs."""

    def test_completely_disjoint_radii_intervals(self):
        """Disjoint radius intervals with no overlap must return fallback 1.0."""
        r_in = np.arange(1.0, 10.0, 1.0)
        r_out = np.arange(50.0, 60.0, 1.0)
        p_in = np.ones_like(r_in) * 10.0
        p_out = np.ones_like(r_out) * 2.0
        # Overlap window in between: [20, 30]
        scale = determine_overlap_scale_factor_dual(p_in, p_out, r_in, r_out, r_min=20.0, r_max=30.0)
        assert scale == 1.0

    def test_overlap_window_outside_both_radii(self):
        """Overlap window entirely beyond both radius ranges must return fallback 1.0."""
        r_in = np.arange(1.0, 10.0, 1.0)
        r_out = np.arange(5.0, 15.0, 1.0)
        p_in = np.ones_like(r_in) * 10.0
        p_out = np.ones_like(r_out) * 2.0
        scale = determine_overlap_scale_factor_dual(p_in, p_out, r_in, r_out, r_min=100.0, r_max=120.0)
        assert scale == 1.0

    def test_inverted_overlap_boundaries(self):
        """r_min > r_max must return fallback 1.0 without crashing."""
        r = np.arange(1.0, 30.0, 1.0)
        p_in = np.full_like(r, 10.0)
        p_out = np.full_like(r, 2.0)
        scale = determine_overlap_scale_factor_dual(p_in, p_out, r, r, r_min=25.0, r_max=10.0)
        assert scale == 1.0

    def test_all_zero_fluxes_both_tiers(self):
        """All-zero fluxes in both tiers must return fallback 1.0."""
        r = np.arange(1.0, 30.0, 1.0)
        p_in = np.zeros_like(r)
        p_out = np.zeros_like(r)
        scale = determine_overlap_scale_factor_dual(p_in, p_out, r, r, r_min=5.0, r_max=15.0)
        assert scale == 1.0

    def test_all_zero_fluxes_one_tier(self):
        """All-zero fluxes in one tier must return fallback 1.0 without division by zero."""
        r = np.arange(1.0, 30.0, 1.0)
        scale_in_zero = determine_overlap_scale_factor_dual(np.zeros_like(r), np.ones_like(r), r, r, 5.0, 15.0)
        assert scale_in_zero == 1.0

        scale_out_zero = determine_overlap_scale_factor_dual(np.ones_like(r), np.zeros_like(r), r, r, 5.0, 15.0)
        assert scale_out_zero == 1.0

    def test_negative_fluxes_both_tiers(self):
        """Negative fluxes in both tiers must be filtered out and return fallback 1.0."""
        r = np.arange(1.0, 30.0, 1.0)
        p_in = -np.ones_like(r) * 5.0
        p_out = -np.ones_like(r) * 2.0
        scale = determine_overlap_scale_factor_dual(p_in, p_out, r, r, r_min=5.0, r_max=15.0)
        assert scale == 1.0

    def test_negative_fluxes_one_tier(self):
        """Negative fluxes in either tier must be excluded from valid ratio."""
        r = np.arange(1.0, 30.0, 1.0)
        scale_in_neg = determine_overlap_scale_factor_dual(-np.ones_like(r), np.ones_like(r), r, r, 5.0, 15.0)
        assert scale_in_neg == 1.0

        scale_out_neg = determine_overlap_scale_factor_dual(np.ones_like(r), -np.ones_like(r), r, r, 5.0, 15.0)
        assert scale_out_neg == 1.0

    def test_all_nan_and_inf_fluxes(self):
        """Non-finite fluxes (NaN, Inf) must return fallback 1.0."""
        r = np.arange(1.0, 30.0, 1.0)
        p_nan = np.full_like(r, np.nan)
        p_inf = np.full_like(r, np.inf)
        assert determine_overlap_scale_factor_dual(p_nan, p_nan, r, r, 5.0, 15.0) == 1.0
        assert determine_overlap_scale_factor_dual(p_inf, p_inf, r, r, 5.0, 15.0) == 1.0
        assert determine_overlap_scale_factor_dual(p_nan, p_inf, r, r, 5.0, 15.0) == 1.0

    def test_disparate_step_sizes_clean_ratio(self):
        """Disparate step sizes (0.5 vs 1.0) recover exact known scaling."""
        r1 = np.arange(5.0, 25.0, 0.5)
        r2 = np.arange(5.0, 25.0, 1.0)
        p1 = 100.0 / r1
        p2 = 10.0 / r2
        scale = determine_overlap_scale_factor_dual(p1, p2, r1, r2, r_min=10.0, r_max=20.0)
        assert np.isclose(scale, 10.0, atol=1e-3)

    def test_disparate_step_sizes_incommensurate_interpolation_fallback(self):
        """Incommensurate step sizes (0.7 vs 0.3) trigger interpolation fallback and recover scale."""
        r1 = np.arange(5.0, 25.0, 0.7)
        r2 = np.arange(5.0, 25.0, 0.3)
        p1 = 80.0 / r1
        p2 = 10.0 / r2
        scale = determine_overlap_scale_factor_dual(p1, p2, r1, r2, r_min=10.0, r_max=20.0)
        assert np.isclose(scale, 8.0, atol=0.1)

    def test_disparate_step_sizes_coarse_outer_grid(self):
        """Very coarse outer grid (step 5.0) vs fine inner grid (step 0.1)."""
        r1 = np.arange(1.0, 50.0, 0.1)
        r2 = np.arange(1.0, 50.0, 5.0)
        p1 = 50.0 / (1.0 + r1)
        p2 = 10.0 / (1.0 + r2)
        scale = determine_overlap_scale_factor_dual(p1, p2, r1, r2, r_min=10.0, r_max=40.0)
        assert np.isclose(scale, 5.0, atol=0.1)

    def test_reversed_or_decreasing_radius_vector(self):
        """Reverse-ordered outer radius vector behaves gracefully."""
        r1 = np.arange(5.0, 25.0, 0.7)
        r2 = np.arange(25.0, 5.0, -0.3)
        p1 = 100.0 / r1
        p2 = 10.0 / r2
        scale = determine_overlap_scale_factor_dual(p1, p2, r1, r2, r_min=10.0, r_max=20.0)
        assert np.isclose(scale, 10.0, atol=0.5)

    def test_legacy_wrapper_empty_radii_behavior(self):
        """Legacy wrapper determine_overlap_scale_factor with empty radii raises IndexError or falls back."""
        with pytest.raises(IndexError):
            determine_overlap_scale_factor(np.array([]), np.array([1.0, 2.0]), np.array([]), 5.0, 10.0)

    def test_sub_millipixel_rounding_collision_handled(self):
        """
        Hardening verification:
        When r_in has multiple points within 1e-3 (e.g. 8.0001 and 8.0004),
        determine_overlap_scale_factor_dual falls back to linear interpolation
        and calculates a valid scale factor without broadcast ValueError.
        """
        r_in = np.array([7.0, 8.0001, 8.0004, 9.0, 10.0])
        r_out = np.array([7.0, 8.0, 9.0, 10.0])
        p_in = np.array([10.0, 20.0, 20.0, 30.0, 40.0])
        p_out = np.array([1.0, 2.0, 3.0, 4.0])
        scale = determine_overlap_scale_factor_dual(p_in, p_out, r_in, r_out, r_min=8.0, r_max=10.0)
        assert np.isfinite(scale)
        assert scale > 0.0


# ============================================================================
# 2. Adversarial Tests for 2D Annular Blending
# ============================================================================

class TestAnnularBlendingAdversarial:
    """Stress-test blend_2d_annular_profiles and partition-of-unity blending."""

    def test_partition_of_unity_exact_sum(self):
        """Partition of unity: sum of weights w(r) + (1 - w(r)) is strictly 1.0 everywhere."""
        for sz in [81, 101, 201]:
            inner = np.ones((sz, sz), dtype=np.float32)
            outer = np.ones((sz, sz), dtype=np.float32)
            blended = blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=30.0)
            np.testing.assert_allclose(blended, 1.0, atol=1e-6)

    def test_blending_weights_bounded_in_zero_one(self):
        """Blended image between constant 0 and constant 100 is bounded in [0, 100]."""
        inner = np.zeros((151, 151), dtype=np.float32)
        outer = np.full((151, 151), 100.0, dtype=np.float32)
        blended = blend_2d_annular_profiles(inner, outer, r_start=15.0, r_end=45.0)
        assert np.min(blended) >= -1e-6
        assert np.max(blended) <= 100.0 + 1e-6

    def test_coincident_blend_radii_step_function(self):
        """r_start == r_end produces a sharp step transition without ZeroDivisionError."""
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = blend_2d_annular_profiles(inner, outer, r_start=20.0, r_end=20.0)
        assert blended.shape == (101, 101)
        assert blended[50, 50] == 10.0
        assert blended[0, 0] == 2.0

    def test_inverted_blend_radii(self):
        """r_start > r_end does not divide by zero and preserves boundaries."""
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = blend_2d_annular_profiles(inner, outer, r_start=30.0, r_end=15.0)
        assert blended.shape == (101, 101)
        assert blended[50, 50] == 10.0
        assert blended[0, 0] == 2.0

    def test_negative_r_start(self):
        """Negative r_start produces valid continuous blending."""
        inner = np.full((101, 101), 10.0, dtype=np.float32)
        outer = np.full((101, 101), 2.0, dtype=np.float32)
        blended = blend_2d_annular_profiles(inner, outer, r_start=-5.0, r_end=15.0)
        assert np.all(np.isfinite(blended))
        assert blended[0, 0] == 2.0

    def test_smaller_inner_embedded_into_even_outer(self):
        """Embedding smaller inner into even outer canvas (e.g. 51 into 100x100)."""
        inner = np.full((51, 51), 5.0, dtype=np.float32)
        outer = np.full((100, 100), 1.0, dtype=np.float32)
        blended = blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert blended.shape == (100, 100)
        assert blended[0, 0] == 1.0

    def test_larger_inner_than_even_outer_handled(self):
        """
        Hardening verification:
        When outer canvas has even dimensions (e.g. 100x100) and inner is larger (e.g. 151x151),
        symmetrical cropping calculation executes without broadcast ValueError.
        """
        inner = np.ones((151, 151), dtype=np.float32)
        outer = np.ones((100, 100), dtype=np.float32)
        blended = blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert blended.shape == (100, 100)
        assert np.isclose(blended[50, 50], 1.0)

    def test_non_square_mismatched_inner_aspect_ratio_handled(self):
        """
        Hardening verification:
        When inner image is non-square (e.g. 101x51) where ny_in > ny_out but nx_in <= nx_out,
        symmetrical canvas embedding/cropping handles mixed aspect ratios without ValueError.
        """
        inner = np.ones((101, 51), dtype=np.float32)
        outer = np.ones((81, 81), dtype=np.float32)
        blended = blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert blended.shape == (81, 81)
        assert np.isclose(blended[40, 40], 1.0)


# ============================================================================
# 3. Stress Tests for PyTorch Tensor Stacking
# ============================================================================

class TestTensorStackingStress:
    """Stress-test stack_tier_stamps_torch across edge cases."""

    def test_empty_stamp_tier_raises_value_error(self):
        """Empty stamp list raises ValueError."""
        with pytest.raises(ValueError, match="Cannot stack an empty stamp list"):
            stack_tier_stamps_torch([], device="cpu")

    def test_single_star_tier_exact_preservation(self):
        """Single-star tier returns exact input array and coverage 1 everywhere."""
        data = np.arange(81 * 81, dtype=np.float32).reshape((81, 81))
        mask = np.zeros((81, 81), dtype=bool)
        s = StellarStamp(1, "faint", 14.0, data, mask, (40, 40), 81)
        stk, cov = stack_tier_stamps_torch([s], device="cpu")
        np.testing.assert_allclose(stk, data)
        assert np.all(cov == 1)

    def test_all_nan_stamps_yields_zero_fallback(self):
        """Stamps containing only NaNs return all-zero array without unhandled NaN propagation."""
        d_nan = np.full((81, 81), np.nan, dtype=np.float32)
        m = np.zeros((81, 81), dtype=bool)
        s1 = StellarStamp(1, "faint", 14.0, d_nan.copy(), m.copy(), (40, 40), 81)
        s2 = StellarStamp(2, "faint", 14.0, d_nan.copy(), m.copy(), (40, 40), 81)
        stk, cov = stack_tier_stamps_torch([s1, s2], device="cpu")
        assert np.all(np.isfinite(stk))
        assert np.all(stk == 0.0)

    def test_all_masked_stamps_yields_zero_coverage(self):
        """Stamps with 100% masked pixels return 0.0 stack and 0 coverage."""
        d = np.full((81, 81), 100.0, dtype=np.float32)
        m = np.ones((81, 81), dtype=bool)
        s1 = StellarStamp(1, "faint", 14.0, d.copy(), m.copy(), (40, 40), 81)
        s2 = StellarStamp(2, "faint", 14.0, d.copy(), m.copy(), (40, 40), 81)
        stk, cov = stack_tier_stamps_torch([s1, s2], device="cpu")
        assert np.all(stk == 0.0)
        assert np.all(cov == 0)

    def test_hollow_core_neighborhood_recovery(self):
        """When central pixel is masked in all stamps, hollow core fallback recovers positive signal."""
        stamps = []
        for i in range(3):
            d = np.ones((81, 81), dtype=np.float32) * 50.0
            m = np.zeros((81, 81), dtype=bool)
            m[40, 40] = True  # Center masked
            stamps.append(StellarStamp(i, "faint", 14.0, d, m, (40, 40), 81))
        stk, _ = stack_tier_stamps_torch(stamps, device="cpu")
        assert stk[40, 40] == 50.0

    @pytest.mark.parametrize("outlier_frac", [0.1, 0.2, 0.3, 0.4, 0.5])
    def test_outlier_rejection_up_to_fifty_percent(self, outlier_frac):
        """Outlier rejection via MAD successfully isolates clean signal up to 50% contamination."""
        n_total = 20
        n_outliers = int(round(n_total * outlier_frac))
        n_clean = n_total - n_outliers

        stamps = []
        for i in range(n_clean):
            stamps.append(StellarStamp(i, "faint", 14.0, np.full((31, 31), 10.0, dtype=np.float32), np.zeros((31, 31), bool), (15, 15), 31))
        for i in range(n_outliers):
            stamps.append(StellarStamp(n_clean + i, "faint", 14.0, np.full((31, 31), 99999.0, dtype=np.float32), np.zeros((31, 31), bool), (15, 15), 31))

        stk, cov = stack_tier_stamps_torch(stamps, device="cpu", sigma_clip=3.0)
        assert np.isclose(stk[15, 15], 10.0, atol=1e-3)
        assert cov[15, 15] == n_clean

    def test_infinite_values_rejected_by_sigma_clipping(self):
        """Infinite pixel values (+inf, -inf) are rejected by sigma clipping."""
        s1 = StellarStamp(1, "faint", 14.0, np.full((81, 81), 15.0, dtype=np.float32), np.zeros((81, 81), bool), (40, 40), 81)
        s2 = StellarStamp(2, "faint", 14.0, np.full((81, 81), 15.0, dtype=np.float32), np.zeros((81, 81), bool), (40, 40), 81)
        s3 = StellarStamp(3, "faint", 14.0, np.full((81, 81), np.inf, dtype=np.float32), np.zeros((81, 81), bool), (40, 40), 81)
        s4 = StellarStamp(4, "faint", 14.0, np.full((81, 81), -np.inf, dtype=np.float32), np.zeros((81, 81), bool), (40, 40), 81)

        stk, cov = stack_tier_stamps_torch([s1, s2, s3, s4], device="cpu", sigma_clip=3.0)
        assert np.isclose(stk[40, 40], 15.0, atol=1e-3)
        assert cov[40, 40] == 2
        assert np.all(np.isfinite(stk))

    def test_mps_acceleration_device(self):
        """Verify tensor stacking executes on MPS device if available."""
        if not torch.backends.mps.is_available():
            pytest.skip("Apple MPS not available on host system.")
        s = StellarStamp(1, "faint", 14.0, np.ones((81, 81), dtype=np.float32) * 8.0, np.zeros((81, 81), bool), (40, 40), 81)
        stk, cov = stack_tier_stamps_torch([s], device="mps")
        assert np.isclose(stk[40, 40], 8.0)
        assert cov[40, 40] == 1

    def test_integer_dtype_stamp_handled(self):
        """
        Hardening verification:
        When an input stamp has an integer dtype (e.g. int32) and any masked pixels,
        casting to float32 ensures NaN assignment and stacking succeed without ValueError.
        """
        s_int = StellarStamp(
            source_id=1,
            tier="faint",
            mag=14.0,
            data=np.ones((81, 81), dtype=np.int32) * 10,
            mask=np.zeros((81, 81), dtype=bool),
            center_original=(40, 40),
            size=81,
        )
        s_int.mask[40, 40] = True
        stack, cov = stack_tier_stamps_torch([s_int], device="cpu")
        assert stack.shape == (81, 81)
        assert cov[40, 40] == 0
        assert stack[40, 40] == 10.0  # recovered via 3x3 neighborhood hollow core fallback


# ============================================================================
# 4. Stress Tests for Composite Extended PSF Assembly & Unit Flux Integral
# ============================================================================

class TestCompositeAssemblyAndUnitFluxIntegral:
    """Stress-test assemble_composite_extended_psf and unit flux conservation."""

    @pytest.fixture
    def standard_multi_tier_stamps(self):
        """Construct standard 3-tier synthetic stamps."""
        sz_f, sz_m, sz_b = 81, 201, 501
        c_f, c_m, c_b = 40, 100, 250
        gy_f, gx_f = np.ogrid[:sz_f, :sz_f]
        rf = np.sqrt((gx_f - c_f)**2 + (gy_f - c_f)**2)
        d_f = (1000.0 / (1.0 + (rf / 2.0)**2)).astype(np.float32)

        gy_m, gx_m = np.ogrid[:sz_m, :sz_m]
        rm = np.sqrt((gx_m - c_m)**2 + (gy_m - c_m)**2)
        d_m = (10000.0 / (1.0 + (rm / 2.0)**2)).astype(np.float32)
        d_m[rm <= 5.0] = 1000.0  # saturated core

        gy_b, gx_b = np.ogrid[:sz_b, :sz_b]
        rb = np.sqrt((gx_b - c_b)**2 + (gy_b - c_b)**2)
        d_b = (50000.0 / (1.0 + (rb / 2.0)**2)).astype(np.float32)
        d_b[rb <= 20.0] = 1000.0  # saturated inner

        return {
            "faint": [StellarStamp(1, "faint", 14.0, d_f, np.zeros_like(d_f, bool), (c_f, c_f), sz_f)],
            "medium": [StellarStamp(2, "medium", 12.0, d_m, np.zeros_like(d_m, bool), (c_m, c_m), sz_m)],
            "bright": [StellarStamp(3, "bright", 9.0, d_b, np.zeros_like(d_b, bool), (c_b, c_b), sz_b)],
        }

    @pytest.mark.parametrize("target_size", [51, 81, 151, 251, 501, 1025, 2049])
    def test_unit_flux_integral_across_target_sizes(self, standard_multi_tier_stamps, target_size):
        """Sum of extended PSF must equal 1.0 across all output canvas dimensions."""
        epsf, diag = assemble_composite_extended_psf(standard_multi_tier_stamps, output_size=target_size)
        assert epsf.shape == (target_size, target_size)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert np.all(epsf >= 0.0)
        c = (target_size - 1) // 2
        assert epsf[c, c] > 0.0

    def test_canvas_size_even_converted_to_odd(self, standard_multi_tier_stamps):
        """Even requested output_size (e.g. 1024) is converted to odd (1025) and preserves unit flux."""
        epsf, _ = assemble_composite_extended_psf(standard_multi_tier_stamps, output_size=1024)
        assert epsf.shape == (1025, 1025)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)

    def test_strictly_non_positive_stamps_zero_flux(self):
        """When all input stamps are zero or negative, output is all-zero without NaN."""
        sz_f, sz_m, sz_b = 81, 201, 501
        c_f, c_m, c_b = 40, 100, 250
        stamps_neg = {
            "faint": [StellarStamp(1, "faint", 14.0, np.full((sz_f, sz_f), -10.0, dtype=np.float32), np.zeros((sz_f, sz_f), bool), (c_f, c_f), sz_f)],
            "medium": [StellarStamp(2, "medium", 12.0, np.full((sz_m, sz_m), -5.0, dtype=np.float32), np.zeros((sz_m, sz_m), bool), (c_m, c_m), sz_m)],
            "bright": [StellarStamp(3, "bright", 9.0, np.full((sz_b, sz_b), -2.0, dtype=np.float32), np.zeros((sz_b, sz_b), bool), (c_b, c_b), sz_b)],
        }
        epsf, diag = assemble_composite_extended_psf(stamps_neg, output_size=251)
        assert np.all(epsf == 0.0)
        assert diag["total_flux_raw"] == 0.0

    def test_noisy_negative_background_clips_and_normalizes(self):
        """Stamps with negative background fluctuations clip to 0 and normalize unit flux."""
        sz_f, sz_m, sz_b = 81, 201, 501
        c_f, c_m, c_b = 40, 100, 250

        d_f = np.full((sz_f, sz_f), -2.0, dtype=np.float32)
        d_f[c_f, c_f] = 500.0

        d_m = np.full((sz_m, sz_m), -1.0, dtype=np.float32)
        d_m[c_m - 5 : c_m + 6, c_m - 5 : c_m + 6] = 200.0

        d_b = np.full((sz_b, sz_b), -0.5, dtype=np.float32)
        d_b[c_b - 15 : c_b + 16, c_b - 15 : c_b + 16] = 100.0

        stamps = {
            "faint": [StellarStamp(1, "faint", 14.0, d_f, np.zeros((sz_f, sz_f), bool), (c_f, c_f), sz_f)],
            "medium": [StellarStamp(2, "medium", 12.0, d_m, np.zeros((sz_m, sz_m), bool), (c_m, c_m), sz_m)],
            "bright": [StellarStamp(3, "bright", 9.0, d_b, np.zeros((sz_b, sz_b), bool), (c_b, c_b), sz_b)],
        }
        epsf, diag = assemble_composite_extended_psf(stamps, output_size=251)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert np.all(epsf >= 0.0)
        assert epsf[125, 125] > 0.0

    def test_inverted_flux_hierarchy_scales_correctly(self):
        """Inverted tier fluxes (faint > medium > bright) recover proper cross-tier scale factors."""
        sz_f, sz_m, sz_b = 81, 201, 501
        c_f, c_m, c_b = 40, 100, 250

        stamps_inv = {
            "faint": [StellarStamp(1, "faint", 14.0, np.full((sz_f, sz_f), 1000.0, dtype=np.float32), np.zeros((sz_f, sz_f), bool), (c_f, c_f), sz_f)],
            "medium": [StellarStamp(2, "medium", 12.0, np.full((sz_m, sz_m), 100.0, dtype=np.float32), np.zeros((sz_m, sz_m), bool), (c_m, c_m), sz_m)],
            "bright": [StellarStamp(3, "bright", 9.0, np.full((sz_b, sz_b), 10.0, dtype=np.float32), np.zeros((sz_b, sz_b), bool), (c_b, c_b), sz_b)],
        }
        epsf, diag = assemble_composite_extended_psf(stamps_inv, output_size=501)
        assert np.isclose(diag["k_fm"], 10.0, atol=1e-3)
        assert np.isclose(diag["k_mb"], 100.0, atol=1e-3)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)

    def test_missing_or_empty_tier_raises_value_error(self):
        """assemble_composite_extended_psf when all tiers are empty raises ValueError."""
        stamps_all_empty = {
            "faint": [],
            "medium": [],
            "bright": [],
        }
        with pytest.raises(ValueError, match="all tiers are empty"):
            assemble_composite_extended_psf(stamps_all_empty)
