"""
Adversarial Stress Test Suite for Assembly Module (Milestone 2 Iteration 2).

Target Modules:
- src/romanepsf/assembly.py
- src/assembly.py (backward-compatibility wrapper)

Coverage Areas:
1. Multi-tier permutations (3-tier, 2-tier FM, 2-tier MB, 2-tier FB, 1-tier F/M/B, 0-tier)
2. Tensor stacking edge cases (high NaN fraction, single stamp, 100+ stamps, integer/float dtypes)
3. Dual-radius scale matching edge cases (coordinate mismatches, sub-pixel rounding offsets, non-overlapping radii)
4. Canvas embedding & blending edge cases (even/odd dimensions, smaller/larger output sizes, direct blends)
5. Physical invariants (unit flux conservation, non-negativity, radial monotonicity in overlap zones)

Authored by: Challenger 2 (challenger_m2_it2_2)
"""

from typing import Dict, List
import numpy as np
import pytest
import torch

from romanepsf.stamps import StellarStamp
import romanepsf.assembly as r_assembly
import src.assembly as s_assembly


# ============================================================================
# Synthetic Profile Fixture Helpers
# ============================================================================

def make_synthetic_stamp(
    source_id: int,
    tier: str,
    mag: float,
    size: int,
    flux_scale: float,
    alpha: float = 2.5,
    beta: float = 2.0,
    sat_radius: float = 0.0,
    noise_sigma: float = 0.0,
    mask_saturated: bool = True,
    center_offset: float = 0.0,
) -> StellarStamp:
    """
    Generate synthetic StellarStamp with an analytic Moffat profile:
    I(r) = flux_scale / (1 + (r / alpha)^2)^beta.
    """
    half = (size - 1) / 2.0
    cy, cx = half + center_offset, half + center_offset
    y, x = np.ogrid[:size, :size]
    r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)

    data = (flux_scale / ((1.0 + (r / alpha) ** 2) ** beta)).astype(np.float32)

    mask = np.zeros((size, size), dtype=bool)
    if sat_radius > 0.0:
        sat_mask = r <= sat_radius
        sat_level = float(flux_scale / ((1.0 + (sat_radius / alpha) ** 2) ** beta))
        data[sat_mask] = sat_level
        if mask_saturated:
            mask[sat_mask] = True

    if noise_sigma > 0.0:
        rng = np.random.RandomState(42 + source_id)
        noise = rng.normal(0.0, noise_sigma, (size, size)).astype(np.float32)
        data += noise

    return StellarStamp(
        source_id=source_id,
        tier=tier,
        mag=mag,
        data=data,
        mask=mask,
        center_original=(half, half),
        size=size,
    )


def make_clean_3tier_stamps(
    flux_f: float = 100.0,
    flux_m: float = 1000.0,
    flux_b: float = 20000.0,
    alpha: float = 2.5,
    beta: float = 2.0,
    sz_f: int = 81,
    sz_m: int = 201,
    sz_b: int = 501,
) -> Dict[str, List[StellarStamp]]:
    """Generate clean, noise-free 3-tier stamps with exact known scale factors."""
    s_f = make_synthetic_stamp(
        1, "faint", 14.0, sz_f, flux_f, alpha, beta, sat_radius=0.0
    )
    s_m = make_synthetic_stamp(
        2, "medium", 12.0, sz_m, flux_m, alpha, beta, sat_radius=6.0
    )
    s_b = make_synthetic_stamp(
        3, "bright", 9.0, sz_b, flux_b, alpha, beta, sat_radius=18.0
    )
    return {
        "faint": [s_f],
        "medium": [s_m],
        "bright": [s_b],
    }


# ============================================================================
# 1. Multi-Tier Permutations Tests
# ============================================================================

class TestMultiTierPermutations:
    """Adversarially verify all combinations of tiers including partial and empty sets."""

    def test_three_tier_permutation(self):
        """Verify 3-tier (F+M+B) executes full synthesis, recovering both k_fm and k_mb."""
        stamps = make_clean_3tier_stamps(flux_f=100.0, flux_m=1000.0, flux_b=20000.0)
        epsf, diag = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)

        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert np.all(epsf >= 0.0)
        assert diag["k_fm"] is not None and np.isclose(diag["k_fm"], 0.10, atol=1e-2)
        assert diag["k_mb"] is not None and np.isclose(diag["k_mb"], 0.005, atol=1e-3)

    def test_two_tier_faint_medium_wfi02(self):
        """Verify 2-tier (F+M) synthesis (e.g. WFI02) scales Medium by k_fm with k_mb=None."""
        stamps = make_clean_3tier_stamps(flux_f=100.0, flux_m=1000.0)
        stamps["bright"] = []  # No bright stars
        epsf, diag = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)

        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert np.all(epsf >= 0.0)
        assert diag["k_fm"] is not None and np.isclose(diag["k_fm"], 0.10, atol=1e-2)
        assert diag["k_mb"] is None
        assert diag["psf_bright"] is None

    def test_two_tier_medium_bright(self):
        """Verify 2-tier (M+B) synthesis scales Bright by k_mb with k_fm=None."""
        stamps = make_clean_3tier_stamps(flux_m=1000.0, flux_b=20000.0)
        stamps["faint"] = []  # No faint stars
        epsf, diag = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)

        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert np.all(epsf >= 0.0)
        assert diag["k_fm"] is None
        assert diag["k_mb"] is not None and np.isclose(diag["k_mb"], 0.05, atol=1e-2)
        assert diag["psf_faint"] is None

    def test_two_tier_faint_bright_skipping_medium(self):
        """Verify 2-tier (F+B) synthesis (skipping Medium) scales Bright by k_fb directly."""
        # Bright saturated only up to r=8 so [10, 20] has clean overlap with faint
        s_f = make_synthetic_stamp(1, "faint", 14.0, 81, 100.0, sat_radius=0.0)
        s_b = make_synthetic_stamp(3, "bright", 9.0, 501, 2000.0, sat_radius=8.0)
        stamps = {"faint": [s_f], "medium": [], "bright": [s_b]}

        epsf, diag = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)

        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert np.all(epsf >= 0.0)
        assert diag["k_fm"] is None
        assert diag["k_mb"] is not None and np.isclose(diag["k_mb"], 0.05, atol=1e-2)
        assert diag["psf_medium"] is None

    def test_one_tier_faint_only(self):
        """Verify 1-tier Faint-only embeds faint PSF into target canvas with k_fm=None, k_mb=None."""
        s_f = make_synthetic_stamp(1, "faint", 14.0, 81, 100.0)
        stamps = {"faint": [s_f], "medium": [], "bright": []}
        epsf, diag = r_assembly.assemble_composite_extended_psf(stamps, output_size=251)

        assert epsf.shape == (251, 251)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert diag["k_fm"] is None and diag["k_mb"] is None
        assert epsf[125, 125] > 0.0
        # Perimeter outside 81x81 cutout must be 0.0
        assert epsf[0, 0] == 0.0

    def test_one_tier_medium_only(self):
        """Verify 1-tier Medium-only embeds medium PSF into target canvas."""
        s_m = make_synthetic_stamp(2, "medium", 12.0, 201, 500.0)
        stamps = {"faint": [], "medium": [s_m], "bright": []}
        epsf, diag = r_assembly.assemble_composite_extended_psf(stamps, output_size=251)

        assert epsf.shape == (251, 251)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert diag["k_fm"] is None and diag["k_mb"] is None
        assert epsf[125, 125] > 0.0

    def test_one_tier_bright_only(self):
        """Verify 1-tier Bright-only embeds bright PSF into target canvas."""
        s_b = make_synthetic_stamp(3, "bright", 9.0, 301, 1000.0)
        stamps = {"faint": [], "medium": [], "bright": [s_b]}
        epsf, diag = r_assembly.assemble_composite_extended_psf(stamps, output_size=301)

        assert epsf.shape == (301, 301)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert diag["k_fm"] is None and diag["k_mb"] is None
        assert epsf[150, 150] > 0.0

    def test_zero_tier_all_empty_raises_value_error(self):
        """Verify empty stamp dictionary or all empty tiers raises ValueError with informative message."""
        with pytest.raises(ValueError, match="all tiers are empty"):
            r_assembly.assemble_composite_extended_psf({})

        with pytest.raises(ValueError, match="all tiers are empty"):
            r_assembly.assemble_composite_extended_psf({"faint": [], "medium": [], "bright": []})

        with pytest.raises(ValueError, match="all tiers are empty"):
            r_assembly.assemble_composite_extended_psf({"unrelated_tier": []})


# ============================================================================
# 2. Tensor Stacking Edge Cases Tests
# ============================================================================

class TestTensorStackingEdgeCases:
    """Stress-test stack_tier_stamps_torch on pathological masks, counts, and dtypes."""

    def test_high_nan_fraction_99_percent_masked_single_valid_pixel(self):
        """
        Adversarial test: 100 stamps where 99 stamps have NaN / mask at pixel (25, 25)
        and exactly 1 stamp has a finite value 77.0.
        Must recover 77.0 with coverage count 1 without crashing or zeroing out.
        """
        stamps = []
        for i in range(100):
            d = np.full((51, 51), 10.0, dtype=np.float32)
            m = np.zeros((51, 51), dtype=bool)
            if i < 99:
                d[25, 25] = np.nan
                m[25, 25] = True
            else:
                d[25, 25] = 77.0
                m[25, 25] = False
            stamps.append(StellarStamp(i, "faint", 14.0, d, m, (25, 25), 51))

        stacked, cov = r_assembly.stack_tier_stamps_torch(stamps, device="cpu", sigma_clip=3.0)
        assert np.isclose(stacked[25, 25], 77.0, atol=1e-3)
        assert cov[25, 25] == 1

    def test_high_nan_fraction_100_percent_masked_pixel_returns_zero(self):
        """A pixel that is 100% masked across all stamps must return 0.0 and coverage 0."""
        stamps = []
        for i in range(10):
            d = np.ones((51, 51), dtype=np.float32) * 5.0
            m = np.zeros((51, 51), dtype=bool)
            d[10, 10] = np.nan
            m[10, 10] = True
            stamps.append(StellarStamp(i, "faint", 14.0, d, m, (25, 25), 51))

        stacked, cov = r_assembly.stack_tier_stamps_torch(stamps, device="cpu")
        assert stacked[10, 10] == 0.0
        assert cov[10, 10] == 0

    def test_single_stamp_per_tier_exact_preservation(self):
        """Single stamp per tier returns exact input data and coverage 1 without distortion."""
        d = np.random.RandomState(999).randn(61, 61).astype(np.float32)
        m = np.zeros((61, 61), dtype=bool)
        m[0, 0] = True
        s = StellarStamp(1, "faint", 14.0, d, m, (30, 30), 61)

        stacked, cov = r_assembly.stack_tier_stamps_torch([s], device="cpu")
        assert stacked.shape == (61, 61)
        assert np.isclose(stacked[30, 30], d[30, 30], atol=1e-5)
        assert cov[30, 30] == 1
        assert cov[0, 0] == 0

    def test_large_count_120_stamps_with_outlier_rejection(self):
        """120 stamps with Gaussian noise and 5% severe outliers must correctly reject outliers."""
        rng = np.random.RandomState(1234)
        true_val = 15.0
        stamps = []
        for i in range(120):
            d = np.full((31, 31), true_val, dtype=np.float32) + rng.normal(0.0, 0.5, (31, 31)).astype(np.float32)
            m = np.zeros((31, 31), dtype=bool)
            # Add severe outlier to 6 stamps (~5%)
            if i < 6:
                d[15, 15] = 10000.0
            stamps.append(StellarStamp(i, "faint", 14.0, d, m, (15, 15), 31))

        stacked, cov = r_assembly.stack_tier_stamps_torch(stamps, device="cpu", sigma_clip=3.0)
        assert np.isclose(stacked[15, 15], true_val, atol=0.2)
        assert cov[15, 15] == 114  # 120 - 6 outliers

    @pytest.mark.parametrize("dtype", [np.int16, np.int32, np.int64, np.uint8, np.uint16])
    def test_integer_dtypes_with_masked_pixels(self, dtype):
        """Integer-typed stamp data with masked pixels does not crash on NaN assignment."""
        d = np.ones((41, 41), dtype=dtype) * 20
        m = np.zeros((41, 41), dtype=bool)
        m[5, 5] = True
        s = StellarStamp(1, "faint", 14.0, d, m, (20, 20), 41)

        stacked, cov = r_assembly.stack_tier_stamps_torch([s], device="cpu")
        assert stacked.dtype == np.float32
        assert np.isclose(stacked[20, 20], 20.0)
        assert cov[5, 5] == 0

    def test_float16_and_float64_dtypes(self):
        """Float16 and Float64 dtypes are safely handled and promoted to float32."""
        s16 = StellarStamp(1, "faint", 14.0, np.ones((41, 41), dtype=np.float16) * 10.0, np.zeros((41, 41), bool), (20, 20), 41)
        s32 = StellarStamp(2, "faint", 14.0, np.ones((41, 41), dtype=np.float32) * 12.0, np.zeros((41, 41), bool), (20, 20), 41)
        s64 = StellarStamp(3, "faint", 14.0, np.ones((41, 41), dtype=np.float64) * 14.0, np.zeros((41, 41), bool), (20, 20), 41)

        stacked, cov = r_assembly.stack_tier_stamps_torch([s16, s32, s64], device="cpu")
        assert stacked.dtype == np.float32
        assert np.isclose(stacked[20, 20], 12.0, atol=1e-3)
        assert cov[20, 20] == 3

    def test_heterogeneous_dtypes_within_tier(self):
        """Stamps of mixed dtypes (float32, int32, float64) stack harmoniously."""
        s1 = StellarStamp(1, "faint", 14.0, np.full((31, 31), 10, dtype=np.int32), np.zeros((31, 31), bool), (15, 15), 31)
        s2 = StellarStamp(2, "faint", 14.0, np.full((31, 31), 10.0, dtype=np.float32), np.zeros((31, 31), bool), (15, 15), 31)
        s3 = StellarStamp(3, "faint", 14.0, np.full((31, 31), 10.0, dtype=np.float64), np.zeros((31, 31), bool), (15, 15), 31)

        stacked, cov = r_assembly.stack_tier_stamps_torch([s1, s2, s3], device="cpu")
        assert np.isclose(stacked[15, 15], 10.0)
        assert cov[15, 15] == 3


# ============================================================================
# 3. Dual-Radius Scale Matching Edge Cases Tests
# ============================================================================

class TestDualRadiusScaleMatchingEdgeCases:
    """Stress-test determine_overlap_scale_factor_dual on coordinate anomalies."""

    def test_coordinate_mismatch_incommensurate_step_grids(self):
        """Incommensurate radius steps (e.g. 0.7 vs 1.1) correctly fall back to interpolation."""
        r_in = np.arange(2.0, 30.0, 0.7)
        r_out = np.arange(2.0, 30.0, 1.1)
        # Power law f(r) = A / r^2
        p_in = 500.0 / (r_in ** 2)
        p_out = 50.0 / (r_out ** 2)
        # Expected ratio = 500 / 50 = 10.0
        scale = r_assembly.determine_overlap_scale_factor_dual(
            p_in, p_out, r_in, r_out, r_min=8.0, r_max=20.0
        )
        assert np.isclose(scale, 10.0, atol=0.2)

    def test_coordinate_mismatch_disparate_length_vectors(self):
        """Inner profile has 20 bins, outer profile has 200 bins."""
        r_in = np.arange(0.5, 20.5, 1.0)
        r_out = np.arange(0.5, 200.5, 1.0)
        p_in = 200.0 / (1.0 + r_in)
        p_out = 40.0 / (1.0 + r_out)
        scale = r_assembly.determine_overlap_scale_factor_dual(
            p_in, p_out, r_in, r_out, r_min=8.0, r_max=16.0
        )
        assert np.isclose(scale, 5.0, atol=1e-3)

    def test_sub_pixel_rounding_offsets_near_tolerance(self):
        """Radii with tiny offsets near tolerance boundary (e.g. 10.0004 vs 10.0006) execute smoothly."""
        r_in = np.array([7.0, 8.0004, 9.0006, 10.0002, 11.0])
        r_out = np.array([7.0, 8.0000, 9.0000, 10.0000, 11.0])
        p_in = np.array([14.0, 16.0, 18.0, 20.0, 22.0])
        p_out = np.array([7.0, 8.0, 9.0, 10.0, 11.0])
        scale = r_assembly.determine_overlap_scale_factor_dual(
            p_in, p_out, r_in, r_out, r_min=8.0, r_max=10.5
        )
        assert np.isclose(scale, 2.0, atol=0.05)

    def test_non_overlapping_radii_fallback(self):
        """Completely disjoint radius sets relative to overlap window return fallback 1.0."""
        r_in = np.arange(1.0, 8.0, 1.0)
        r_out = np.arange(25.0, 50.0, 1.0)
        p_in = np.full_like(r_in, 50.0)
        p_out = np.full_like(r_out, 10.0)
        # Window [10, 20] touches neither r_in nor r_out
        scale = r_assembly.determine_overlap_scale_factor_dual(
            p_in, p_out, r_in, r_out, r_min=10.0, r_max=20.0
        )
        assert scale == 1.0

    def test_inverted_overlap_radii_window(self):
        """r_min > r_max returns fallback 1.0."""
        r = np.arange(1.0, 30.0, 1.0)
        scale = r_assembly.determine_overlap_scale_factor_dual(
            np.ones_like(r) * 10.0, np.ones_like(r) * 2.0, r, r, r_min=25.0, r_max=10.0
        )
        assert scale == 1.0

    def test_zero_and_negative_flux_filtering(self):
        """Zero and negative flux entries in the overlap range are ignored."""
        r = np.arange(5.0, 20.0, 1.0)
        p_in = np.array([10.0, 0.0, -5.0, 10.0, 10.0, 10.0, 0.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
        p_out = np.array([2.0, 2.0, 2.0, 0.0, -1.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
        scale = r_assembly.determine_overlap_scale_factor_dual(
            p_in, p_out, r, r, r_min=6.0, r_max=18.0
        )
        assert np.isclose(scale, 5.0, atol=1e-3)

    def test_all_nan_flux_fallback(self):
        """All-NaN profile in overlap range returns 1.0."""
        r = np.arange(5.0, 20.0, 1.0)
        p_nan = np.full_like(r, np.nan)
        p_val = np.ones_like(r) * 10.0
        assert r_assembly.determine_overlap_scale_factor_dual(p_nan, p_val, r, r, 6.0, 18.0) == 1.0
        assert r_assembly.determine_overlap_scale_factor_dual(p_val, p_nan, r, r, 6.0, 18.0) == 1.0


# ============================================================================
# 4. Canvas Embedding and Blending Edge Cases Tests
# ============================================================================

class TestCanvasEmbeddingAndBlendingEdgeCases:
    """Stress-test geometry transformations, canvas sizes, and blending operators."""

    @pytest.mark.parametrize("even_size, expected_odd", [(500, 501), (1024, 1025), (2048, 2049)])
    def test_even_target_dimensions_converted_to_odd(self, even_size, expected_odd):
        """assemble_composite_extended_psf converts even output_size to odd dimension."""
        stamps = make_clean_3tier_stamps()
        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=even_size)
        assert epsf.shape == (expected_odd, expected_odd)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)

    @pytest.mark.parametrize("odd_size", [501, 1025, 2049])
    def test_odd_target_dimensions_preserved(self, odd_size):
        """assemble_composite_extended_psf preserves odd output_size exactly."""
        stamps = make_clean_3tier_stamps()
        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=odd_size)
        assert epsf.shape == (odd_size, odd_size)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)

    def test_output_size_smaller_than_stamp_size(self):
        """Output canvas smaller than bright stamp size (e.g. output 71 vs bright 501) crops cleanly."""
        stamps = make_clean_3tier_stamps(sz_f=81, sz_m=201, sz_b=501)
        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=71)
        assert epsf.shape == (71, 71)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert epsf[35, 35] > 0.0

    def test_output_size_much_larger_than_stamp_size(self):
        """Faint-only 81x81 stamp embedded in 2049x2049 canvas pads zeros and conserves flux."""
        s_f = make_synthetic_stamp(1, "faint", 14.0, 81, 100.0)
        stamps = {"faint": [s_f]}
        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=2049)
        assert epsf.shape == (2049, 2049)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert epsf[1024, 1024] > 0.0
        assert epsf[0, 0] == 0.0

    def test_direct_blend_annular_profiles_even_and_odd_combinations(self):
        """Directly call blend_2d_annular_profiles across even and odd canvas combinations."""
        # 1. Even outer (100x100) and odd inner (51x51)
        inner = np.full((51, 51), 10.0, dtype=np.float32)
        outer = np.full((100, 100), 2.0, dtype=np.float32)
        blended = r_assembly.blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert blended.shape == (100, 100)
        assert blended[50, 50] == 10.0
        assert blended[0, 0] == 2.0

        # 2. Even outer (100x100) and even inner (50x50)
        inner_even = np.full((50, 50), 15.0, dtype=np.float32)
        blended2 = r_assembly.blend_2d_annular_profiles(inner_even, outer, r_start=10.0, r_end=20.0)
        assert blended2.shape == (100, 100)
        assert np.isclose(blended2[50, 50], 15.0)

        # 3. Odd outer (101x101) and even inner (60x60)
        outer_odd = np.full((101, 101), 1.0, dtype=np.float32)
        blended3 = r_assembly.blend_2d_annular_profiles(inner_even, outer_odd, r_start=10.0, r_end=20.0)
        assert blended3.shape == (101, 101)
        assert np.isclose(blended3[50, 50], 15.0)

    def test_direct_embed_or_crop_canvas_boundaries(self):
        """Verify _embed_or_crop_canvas across expansion, cropping, and even/odd conversion."""
        img = np.ones((51, 51), dtype=np.float32)

        # 1. Expand to 101
        c_exp = r_assembly._embed_or_crop_canvas(img, 101)
        assert c_exp.shape == (101, 101)
        assert c_exp[50, 50] == 1.0
        assert c_exp[0, 0] == 0.0

        # 2. Crop to 25
        c_crop = r_assembly._embed_or_crop_canvas(img, 25)
        assert c_crop.shape == (25, 25)
        assert np.all(c_crop == 1.0)

        # 3. Even target converted to odd (100 -> 101)
        c_even = r_assembly._embed_or_crop_canvas(img, 100)
        assert c_even.shape == (101, 101)


# ============================================================================
# 5. Physical Invariants Tests
# ============================================================================

class TestPhysicalInvariants:
    """Verify core physical conservation laws: unit flux, non-negativity, and radial monotonicity."""

    @pytest.mark.parametrize("config_type", ["3tier", "2tier_fm", "2tier_mb", "2tier_fb", "1tier_f", "1tier_m", "1tier_b"])
    def test_unit_flux_conservation_all_permutations(self, config_type):
        """Total integrated flux of ePSF must equal 1.0 within float precision across all permutations."""
        all_stamps = make_clean_3tier_stamps()
        if config_type == "3tier":
            stamps = all_stamps
        elif config_type == "2tier_fm":
            stamps = {"faint": all_stamps["faint"], "medium": all_stamps["medium"]}
        elif config_type == "2tier_mb":
            stamps = {"medium": all_stamps["medium"], "bright": all_stamps["bright"]}
        elif config_type == "2tier_fb":
            stamps = {"faint": all_stamps["faint"], "bright": all_stamps["bright"]}
        elif config_type == "1tier_f":
            stamps = {"faint": all_stamps["faint"]}
        elif config_type == "1tier_m":
            stamps = {"medium": all_stamps["medium"]}
        else:
            stamps = {"bright": all_stamps["bright"]}

        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5), f"Failed unit flux integral for {config_type}"

    def test_strict_non_negativity_with_negative_background_noise(self):
        """Composite ePSF must have no negative flux values even when input stamps have noisy background."""
        stamps = make_clean_3tier_stamps()
        # Inject negative noise
        for tier in ["faint", "medium", "bright"]:
            s = stamps[tier][0]
            rng = np.random.RandomState(42)
            noise = rng.normal(0.0, 5.0, s.data.shape).astype(np.float32)
            s.data = s.data + noise

        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)
        assert np.all(epsf >= 0.0), "Negative flux values detected in ePSF!"
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)

    def test_strict_radial_monotonicity_3_tier(self):
        """
        Physical Invariant: In noise-free conditions, the composite ePSF must be strictly
        monotonically decreasing across cross-tier overlap regions:
        - Faint-to-Medium [8, 20] px
        - Medium-to-Bright [25, 50] px
        """
        # Build noise-free stamps with exact physical scaling
        stamps = make_clean_3tier_stamps(flux_f=100.0, flux_m=1000.0, flux_b=20000.0)
        epsf, diag = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)

        # Measure 1D radial profile of the final composite ePSF
        rad, prof, _ = r_assembly.measure_radial_profile_1d(epsf, rmax=100)

        # 1. Verify monotonicity across Faint-to-Medium blend zone [10, 18] px
        idx_fm = (rad >= 8.0) & (rad <= 20.0)
        prof_fm = prof[idx_fm]
        diff_fm = np.diff(prof_fm)
        assert np.all(diff_fm <= 1e-7), f"Flux surge in F-to-M overlap zone! max diff: {np.max(diff_fm)}"

        # 2. Verify monotonicity across Medium-to-Bright blend zone [30, 48] px
        idx_mb = (rad >= 25.0) & (rad <= 50.0)
        prof_mb = prof[idx_mb]
        diff_mb = np.diff(prof_mb)
        assert np.all(diff_mb <= 1e-7), f"Flux surge in M-to-B overlap zone! max diff: {np.max(diff_mb)}"

        # 3. Overall monotonicity from core (r=2) to wing (r=80)
        idx_full = (rad >= 2.0) & (rad <= 80.0)
        prof_full = prof[idx_full]
        diff_full = np.diff(prof_full)
        assert np.all(diff_full <= 1e-7), f"Non-monotonic radial decay in composite ePSF! max diff: {np.max(diff_full)}"

    def test_strict_radial_monotonicity_2_tier_fm(self):
        """Verify strict monotonicity across [8, 20] px in 2-tier Faint + Medium synthesis (WFI02 scenario)."""
        stamps = make_clean_3tier_stamps(flux_f=100.0, flux_m=1000.0)
        stamps["bright"] = []
        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)

        rad, prof, _ = r_assembly.measure_radial_profile_1d(epsf, rmax=60)
        idx_fm = (rad >= 8.0) & (rad <= 20.0)
        diff_fm = np.diff(prof[idx_fm])
        assert np.all(diff_fm <= 1e-7), f"Flux surge in 2-tier FM overlap zone! max diff: {np.max(diff_fm)}"

    def test_strict_radial_monotonicity_2_tier_mb(self):
        """Verify strict monotonicity across [25, 50] px in 2-tier Medium + Bright synthesis."""
        stamps = make_clean_3tier_stamps(flux_m=1000.0, flux_b=20000.0)
        stamps["faint"] = []
        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)

        rad, prof, _ = r_assembly.measure_radial_profile_1d(epsf, rmax=80)
        idx_mb = (rad >= 25.0) & (rad <= 50.0)
        diff_mb = np.diff(prof[idx_mb])
        assert np.all(diff_mb <= 1e-7), f"Flux surge in 2-tier MB overlap zone! max diff: {np.max(diff_mb)}"

    def test_strict_radial_monotonicity_2_tier_fb(self):
        """Verify strict monotonicity across [10, 25] px in 2-tier Faint + Bright synthesis."""
        s_f = make_synthetic_stamp(1, "faint", 14.0, 81, 100.0, sat_radius=0.0)
        s_b = make_synthetic_stamp(3, "bright", 9.0, 501, 2000.0, sat_radius=8.0)
        stamps = {"faint": [s_f], "medium": [], "bright": [s_b]}
        epsf, _ = r_assembly.assemble_composite_extended_psf(stamps, output_size=501)

        rad, prof, _ = r_assembly.measure_radial_profile_1d(epsf, rmax=80)
        idx_fb = (rad >= 10.0) & (rad <= 25.0)
        diff_fb = np.diff(prof[idx_fb])
        assert np.all(diff_fb <= 1e-7), f"Flux surge in 2-tier FB overlap zone! max diff: {np.max(diff_fb)}"

    def test_backward_compatibility_wrapper_reexports_all_symbols(self):
        """Verify src/assembly.py re-exports every symbol from src/romanepsf/assembly.py identically."""
        symbols = [
            "stack_tier_stamps_torch",
            "measure_radial_profile_1d",
            "determine_overlap_scale_factor_dual",
            "determine_overlap_scale_factor",
            "blend_2d_annular_profiles",
            "_embed_or_crop_canvas",
            "assemble_composite_extended_psf",
        ]
        for sym in symbols:
            assert hasattr(s_assembly, sym), f"src/assembly missing symbol {sym}"
            assert getattr(s_assembly, sym) is getattr(r_assembly, sym), f"Symbol {sym} does not match between modules"
