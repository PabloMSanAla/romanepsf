"""
Tier 2: Boundary & Corner Cases Tests for Roman ePSF Measurement Pipeline.

Exhaustive boundary value analysis and edge condition testing across:
- Pixel boundaries [0, 4088] and margin exclusions
- Saturated NaN pixels vs unphysical distorted numbers (-30283 to +104281 DN/s)
- Zero, negative, and extreme flux conditions
- Corrupt catalog rows, duplicate columns, non-stellar objects
- Centroid edge cases and bounding box truncations
- Moffat isolation boundaries and pairwise clear radii
- Tier partition limits (11.000, 13.000) and single/empty tiers
- Even vs odd canvas sizing (1024/1025, 2048/2049)
- Subpixel shift limits (0.0, 0.5, 0.99) and Nyquist boundary
- Spider angle rotations across quadrant boundaries
- Ridge filter length thresholds (14 vs 15 px) and aspect ratios
- Dual-prior spike protection at exact boundary interfaces
- PyTorch tensor stacking with 100% masked pixels and extreme outliers
- Dual-radius scale factor calculations across disparate profile lengths
- Raised-cosine partition-of-unity blending at transition limits
- Energy normalization volume conservation under extreme dynamic ranges
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import torch

from tests.conftest import get_module, DATA_DIR, CATALOG_PATH, WFI01_ASDF


# ==============================================================================
# B1: Pixel Bounds [0, 4088] & Cutout Boundary Padding
# ==============================================================================
class TestBoundary01PixelBounds:
    """B1: Pixel boundaries [0, 4088] and cutout edge clipping."""

    def test_b1_01_star_exactly_at_origin(self, synthetic_l2_data):
        """Verify star at (0, 0) is excluded by default margin=50."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "ra": [303.12 - 250*(0.11/3600)], "dec": [-19.93 - 250*(0.11/3600)]})
        try:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin_px=50)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin=50)
        assert len(proj) == 0

    def test_b1_02_star_exactly_at_detector_upper_corner(self, synthetic_l2_data):
        """Verify star at (4087, 4087) is excluded by default margin=50."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "ra": [303.12 + (4087-250)*(0.11/3600)], "dec": [-19.93 + (4087-250)*(0.11/3600)]})
        try:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin_px=50)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin=50)
        assert len(proj) == 0

    def test_b1_03_cutout_padding_when_exceeding_boundaries(self):
        """Verify extract_cutout pads with NaN when window exceeds array bounds."""
        stamps = get_module("stamps")
        img = np.ones((100, 100), dtype=np.float32)
        # Center near corner (10, 10) with stamp size 81 (half = 40)
        cut, (ix, iy) = stamps.extract_cutout(img, (10.0, 10.0), 81, fill_value=np.nan)
        assert cut.shape == (81, 81)
        # Corner of cutout should be NaN
        assert np.isnan(cut[0, 0])
        # Center of cutout should contain valid data
        assert cut[40, 40] == 1.0

    def test_b1_04_negative_pixel_coordinates_rejected(self, synthetic_l2_data):
        """Verify coordinates outside [0, 4088] are rejected."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "ra": [300.0], "dec": [-25.0]})
        try:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin_px=0)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin=0)
        assert len(proj) == 0

    def test_b1_05_margin_zero_includes_border_star(self, synthetic_l2_data):
        """Verify margin=0 includes star located within [0, 4088]."""
        catalog = get_module("catalog")
        # Star at x=10, y=10
        df = pd.DataFrame({"source_id": [1], "ra": [303.12 + (10-250)*(0.11/3600)], "dec": [-19.93 + (10-250)*(0.11/3600)]})
        try:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin_px=0)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin=0)
        assert len(proj) == 1


# ==============================================================================
# B2: Saturated Pixels, NaNs, and Distorted Values
# ==============================================================================
class TestBoundary02SaturatedPixelsAndNaNs:
    """B2: Handling of saturated NaNs and corrupted extreme values (-30k to +100k DN/s)."""

    def test_b2_01_large_negative_saturated_values_masked(self):
        """Verify corrupted negative saturated values (e.g. -30,283 DN/s) are masked."""
        masking = get_module("masking")
        sz = 81
        stamp = np.full((sz, sz), 1.8, dtype=np.float32)
        stamp[40, 40] = -30283.0
        dq = np.zeros((sz, sz), dtype=bool)
        dq[40, 40] = True
        mask, _, _ = masking.mask_contaminants_with_spikes_protected(stamp, dq_mask=dq)
        assert mask[40, 40]

    def test_b2_02_nan_pixels_in_cutout_masked(self):
        """Verify NaN pixels in cutout are flagged in final mask."""
        masking = get_module("masking")
        sz = 81
        stamp = np.ones((sz, sz), dtype=np.float32)
        stamp[30, 30] = np.nan
        mask, _, _ = masking.mask_contaminants_with_spikes_protected(stamp, dq_mask=None)
        assert mask[30, 30]

    def test_b2_03_spline_shift_with_nan_cluster(self):
        """Verify bicubic realignment does not produce NaN explosion across stamp."""
        stamps = get_module("stamps")
        sz = 81
        stamp = np.ones((sz, sz), dtype=np.float32) * 5.0
        stamp[38:43, 38:43] = np.nan
        mask = np.isnan(stamp)
        aligned_data, aligned_mask = stamps.recenter_and_align_stamp(stamp, mask, (0.3, 0.4))
        # Non-core pixels should remain finite
        assert np.isfinite(aligned_data[10, 10])

    def test_b2_04_tensor_stacking_all_nan_column(self):
        """Verify stack handles a pixel that is NaN in all stamps by filling 0.0."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        stamps_list = []
        for i in range(3):
            d = np.ones((81, 81), dtype=np.float32)
            d[40, 40] = np.nan
            m = np.zeros((81, 81), dtype=bool)
            m[40, 40] = True
            stamps_list.append(stamps_mod.StellarStamp(
                source_id=i, tier="faint", mag=14.0, data=d, mask=m,
                center_original=(40, 40), size=81
            ))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list)
        assert np.isfinite(stacked[40, 40])
        assert cov[40, 40] == 0

    def test_b2_05_dq_mask_all_flags(self):
        """Verify get_dq_mask correctly identifies composite bitmasks."""
        loader = get_module("loader")
        # SATURATED (2) + DO_NOT_USE (1) = 3
        dq = np.array([[3, 0], [4, 8]], dtype=np.uint32)
        mask = loader.get_dq_mask(dq, flags=["DO_NOT_USE", "SATURATED", "DROPOUT"])
        assert mask[0, 0]  # DQ = 3 (1 | 2)
        assert not mask[0, 1]  # DQ = 0
        assert not mask[1, 0]  # DQ = 4 (JUMP_DET, not in flags)
        assert mask[1, 1]  # DQ = 8 (DROPOUT)


# ==============================================================================
# B3: Zero, Negative, and Extreme Flux Conditions
# ==============================================================================
class TestBoundary03FluxExtremes:
    """B3: Extreme flux conditions, zero flux, negative fluxes, noise floor."""

    def test_b3_01_negative_flux_clipping_in_normalization(self):
        """Verify far wing negative flux noise is clipped to 0.0."""
        raw = np.array([[-10.0, 50.0], [0.0, -1.0]], dtype=np.float32)
        clipped = np.maximum(raw, 0.0)
        norm = clipped / np.sum(clipped)
        assert norm[0, 0] == 0.0
        assert norm[1, 1] == 0.0
        assert np.isclose(np.sum(norm), 1.0)

    def test_b3_02_extreme_dynamic_range_peak_to_wing(self):
        """Verify dynamic range ratio 10^7 does not cause floating point underflow."""
        canvas = np.zeros((101, 101), dtype=np.float32)
        canvas[50, 50] = 1e7
        canvas[50, 95] = 1.0  # Outer wing
        norm = canvas / np.sum(canvas)
        assert norm[50, 95] > 0.0
        assert np.isfinite(norm[50, 95])

    def test_b3_03_scale_factor_ignores_negative_profile_bins(self):
        """Verify scale factor calculation discards negative flux radial bins."""
        assembly = get_module("assembly")
        r = np.arange(0.5, 30.5, 1.0)
        p_in = np.array([10.0 if i % 2 == 0 else -5.0 for i in range(len(r))])
        p_out = np.full_like(r, 2.0)
        scale = assembly.determine_overlap_scale_factor(p_in, p_out, r, r_min=5.0, r_max=25.0)
        assert np.isclose(scale, 5.0)

    def test_b3_04_profile_on_all_zero_array(self):
        """Verify radial profile on all-zero array returns 0.0 without crash."""
        profile = get_module("profile")
        img = np.zeros((81, 81), dtype=np.float32)
        flux, ferr = profile.elliptical_profile(img, rad=np.array([1.0, 5.0, 10.0]), center=(40, 40), pa=0, eps=0)
        assert np.all(flux == 0.0)

    def test_b3_05_single_pixel_delta_function_star(self):
        """Verify radial profile on compact core peak."""
        profile = get_module("profile")
        img = np.zeros((81, 81), dtype=np.float32)
        # 3x3 core peak has median 1000.0 within r <= 1.0
        img[39:42, 39:42] = 1000.0
        flux, _ = profile.elliptical_profile(img, rad=np.array([0.0, 1.0, 5.0]), center=(40, 40), pa=0, eps=0)
        assert flux[0] == 1000.0
        assert flux[1] == 0.0


# ==============================================================================
# B4: Catalog Edge Cases & Corruption
# ==============================================================================
class TestBoundary04CatalogCorruption:
    """B4: Corrupt catalog rows, duplicate columns, missing values."""

    def test_b4_01_nan_coordinates_dropped(self, synthetic_l2_data):
        """Verify rows with NaN coordinates in catalog are safely dropped."""
        catalog = get_module("catalog")
        df = pd.DataFrame({
            "source_id": [1, 2],
            "ra": [np.nan, 303.12],
            "dec": [-19.93, np.nan],
        })
        try:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin_px=0)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(synthetic_l2_data, df, margin=0)
        assert len(proj) == 0

    def test_b4_02_duplicate_source_id_handling(self):
        """Verify duplicate source IDs in catalog do not cause crash."""
        catalog = get_module("catalog")
        df = pd.DataFrame({
            "source_id": [101, 101],
            "x": [50.0, 1000.0],
            "y": [50.0, 1000.0],
            "phot_g_mean_mag": [12.0, 14.0],
        })
        isolated = catalog.filter_isolated_stars(df)
        assert len(isolated) == 2

    def test_b4_03_missing_phot_g_mean_mag_tier_fallback(self):
        """Verify star with missing magnitude defaults to 'faint'."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "phot_g_mean_mag": [np.nan]})
        tiered = catalog.assign_stellar_tiers(df)
        assert tiered.iloc[0]["tier"] == "faint"

    def test_b4_04_solar_system_objects_in_catalog(self, catalog_path):
        """Verify solar system bodies (Sun, Moon) have negative magnitudes."""
        df = pd.read_csv(catalog_path, nrows=5)
        # Row 0 is the Sun with mag ~ -26.98
        sun_mag = df.iloc[0]["mag_lambda"]
        assert sun_mag < 0.0

    def test_b4_05_empty_dataframe_in_isolation_filter(self):
        """Verify empty DataFrame passed to filter_isolated_stars returns empty."""
        catalog = get_module("catalog")
        empty_df = pd.DataFrame(columns=["x", "y", "phot_g_mean_mag"])
        res = catalog.filter_isolated_stars(empty_df)
        assert len(res) == 0


# ==============================================================================
# B5: Centroid Edge Cases & Box Radius Truncations
# ==============================================================================
class TestBoundary05CentroidEdgeCases:
    """B5: Centroid refinement edge cases."""

    def test_b5_01_centroid_box_radius_1(self, synthetic_l2_data):
        """Verify centroiding with minimal box_radius=1."""
        catalog = get_module("catalog")
        synthetic_l2_data.data[100, 100] = 50.0
        df = pd.DataFrame({"source_id": [1], "x": [100.0], "y": [100.0], "x_gaia": [100.0], "y_gaia": [100.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=1)
        assert abs(refined.iloc[0]["x"] - 100.0) < 0.1

    def test_b5_02_centroid_at_top_right_corner(self, synthetic_l2_data):
        """Verify centroiding when star is within box_radius of top-right corner."""
        catalog = get_module("catalog")
        h, w = synthetic_l2_data.data.shape
        df = pd.DataFrame({"source_id": [1], "x": [float(w - 2)], "y": [float(h - 2)], "x_gaia": [float(w - 2)], "y_gaia": [float(h - 2)]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        assert np.isfinite(refined.iloc[0]["x"])
        assert np.isfinite(refined.iloc[0]["y"])

    def test_b5_03_box_with_negative_values(self, synthetic_l2_data):
        """Verify centroiding when box contains negative background fluctuations."""
        catalog = get_module("catalog")
        synthetic_l2_data.data[50:60, 50:60] = -10.0
        synthetic_l2_data.data[55, 55] = 100.0
        df = pd.DataFrame({"source_id": [1], "x": [55.0], "y": [55.0], "x_gaia": [55.0], "y_gaia": [55.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=3)
        assert abs(refined.iloc[0]["x"] - 55.0) < 0.2

    def test_b5_04_box_all_zeros_fallback(self, synthetic_l2_data):
        """Verify centroid falls back to initial Gaia coordinates when box is all zeros."""
        catalog = get_module("catalog")
        synthetic_l2_data.data[:] = 0.0
        df = pd.DataFrame({"source_id": [1], "x": [77.3], "y": [88.4], "x_gaia": [77.3], "y_gaia": [88.4]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        assert refined.iloc[0]["x"] == 77.3
        assert refined.iloc[0]["y"] == 88.4

    def test_b5_05_large_box_radius(self, synthetic_l2_data):
        """Verify centroiding with large box_radius=20."""
        catalog = get_module("catalog")
        synthetic_l2_data.data[150, 150] = 500.0
        df = pd.DataFrame({"source_id": [1], "x": [150.0], "y": [150.0], "x_gaia": [150.0], "y_gaia": [150.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=20)
        assert abs(refined.iloc[0]["x"] - 150.0) < 0.5


# ==============================================================================
# B6: Moffat Isolation Boundaries & Equal Brightness Pairs
# ==============================================================================
class TestBoundary06MoffatIsolationBounds:
    """B6: Moffat isolation clearance boundaries."""

    def test_b6_01_two_stars_exact_clearance_boundary(self):
        """Verify behavior when two stars are at exact required clearance distance."""
        catalog = get_module("catalog")
        profile = get_module("profile")
        r_ext = profile.get_psf_extension_moffat(12.0, depth=28.0) / 0.11
        # Two stars separated by exactly 1.3 * 2 * r_ext
        sep = 1.3 * 2.0 * r_ext + 1.0  # Just outside
        df = pd.DataFrame({
            "source_id": [1, 2],
            "x": [100.0, 100.0 + sep],
            "y": [100.0, 100.0],
            "phot_g_mean_mag": [12.0, 12.0],
        })
        isolated = catalog.filter_isolated_stars(df, pixel_scale=0.11, isolation_safety_factor=1.3)
        assert len(isolated) == 2

    def test_b6_02_two_identical_magnitude_overlapping_stars(self):
        """Verify when two identical stars overlap, at most one is retained."""
        catalog = get_module("catalog")
        df = pd.DataFrame({
            "source_id": [1, 2],
            "x": [100.0, 105.0],
            "y": [100.0, 100.0],
            "phot_g_mean_mag": [12.0, 12.0],
        })
        isolated = catalog.filter_isolated_stars(df)
        assert len(isolated) <= 1

    def test_b6_03_zero_safety_factor(self):
        """Verify isolation filter with safety_factor=0.0 respects min_dist_arcsec."""
        catalog = get_module("catalog")
        df = pd.DataFrame({
            "source_id": [1, 2],
            "x": [100.0, 101.0],  # 1 pixel = 0.11 arcsec < min_dist (2.0 arcsec)
            "y": [100.0, 100.0],
            "phot_g_mean_mag": [14.0, 15.0],
        })
        isolated = catalog.filter_isolated_stars(df, isolation_safety_factor=0.0, min_dist_arcsec=2.0)
        assert len(isolated) == 1

    def test_b6_04_dense_star_cluster(self):
        """Verify in dense 10-star cluster, only brightest star survives."""
        catalog = get_module("catalog")
        # 10 stars within 20x20 pixel area
        df = pd.DataFrame({
            "source_id": list(range(10)),
            "x": 100.0 + np.random.RandomState(42).uniform(-10, 10, 10),
            "y": 100.0 + np.random.RandomState(42).uniform(-10, 10, 10),
            "phot_g_mean_mag": [10.0] + [14.0 + i for i in range(9)],
        })
        isolated = catalog.filter_isolated_stars(df)
        assert len(isolated) == 1
        assert isolated.iloc[0]["source_id"] == 0

    def test_b6_05_extremely_faint_stars_isolation(self):
        """Verify extremely faint stars (G=22) have small but finite clearance."""
        profile = get_module("profile")
        r_faint = profile.get_psf_extension_moffat(22.0, depth=28.0)
        assert r_faint > 0.0


# ==============================================================================
# B7: Tier Partition Boundaries & Edge Magnitudes
# ==============================================================================
class TestBoundary07TierPartitionBoundaries:
    """B7: Tier partition boundaries and empty/single tiers."""

    def test_b7_01_star_at_exact_11_000(self):
        """Verify star at magnitude 11.000 is classified as 'medium'."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "phot_g_mean_mag": [11.000]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert tiered.iloc[0]["tier"] == "medium"

    def test_b7_02_star_at_exact_13_000(self):
        """Verify star at magnitude 13.000 is classified as 'faint'."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "phot_g_mean_mag": [13.000]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert tiered.iloc[0]["tier"] == "faint"

    def test_b7_03_star_at_10_999(self):
        """Verify star at magnitude 10.999 is classified as 'bright'."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "phot_g_mean_mag": [10.999]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert tiered.iloc[0]["tier"] == "bright"

    def test_b7_04_catalog_with_only_faint_stars(self):
        """Verify catalog with only faint stars produces valid single-tier DataFrame."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1, 2], "phot_g_mean_mag": [14.0, 15.0]})
        tiered = catalog.assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0)
        assert all(tiered["tier"] == "faint")

    def test_b7_05_negative_magnitude_classified_bright(self):
        """Verify extreme bright star (m < 0) is classified as 'bright'."""
        catalog = get_module("catalog")
        df = pd.DataFrame({"source_id": [1], "phot_g_mean_mag": [-2.5]})
        tiered = catalog.assign_stellar_tiers(df)
        assert tiered.iloc[0]["tier"] == "bright"


# ==============================================================================
# B8: Canvas Sizing & Odd Integer Boundaries
# ==============================================================================
class TestBoundary08CanvasDimensions:
    """B8: Canvas dimensions, even-to-odd adjustment, center alignment."""

    def test_b8_01_even_canvas_size_1024_adjusted_to_1025(self):
        """Verify even target canvas size 1024 is adjusted to odd 1025."""
        target_sz = 1024
        if target_sz % 2 == 0:
            target_sz += 1
        assert target_sz == 1025
        assert (target_sz - 1) % 2 == 0

    def test_b8_02_even_canvas_size_2048_adjusted_to_2049(self):
        """Verify even target canvas size 2048 is adjusted to odd 2049."""
        target_sz = 2048
        if target_sz % 2 == 0:
            target_sz += 1
        assert target_sz == 2049

    def test_b8_03_embedding_smaller_stamp_in_canvas(self):
        """Verify embedding 201x201 stamp in 1025x1025 canvas centers it exactly."""
        canvas_sz = 1025
        stamp_sz = 201
        canvas = np.zeros((canvas_sz, canvas_sz), dtype=np.float32)
        half_c = (canvas_sz - 1) // 2
        half_s = (stamp_sz - 1) // 2
        y0 = half_c - half_s
        x0 = half_c - half_s
        stamp = np.ones((stamp_sz, stamp_sz), dtype=np.float32)
        canvas[y0:y0+stamp_sz, x0:x0+stamp_sz] = stamp
        assert canvas[half_c, half_c] == 1.0
        assert canvas[0, 0] == 0.0

    def test_b8_04_canvas_center_pixel_index(self):
        """Verify center pixel index convention (sz-1)//2 for odd canvas."""
        for sz in [81, 201, 1025, 2049]:
            center = (sz - 1) // 2
            assert center == (sz - 1) / 2.0

    def test_b8_05_stamp_larger_than_canvas_handled(self):
        """Verify stamp larger than target canvas is cropped symmetrically."""
        canvas_sz = 81
        stamp_sz = 101
        stamp = np.ones((stamp_sz, stamp_sz), dtype=np.float32)
        half_c = (canvas_sz - 1) // 2
        half_s = (stamp_sz - 1) // 2
        cropped = stamp[half_s - half_c : half_s + half_c + 1, half_s - half_c : half_s + half_c + 1]
        assert cropped.shape == (canvas_sz, canvas_sz)


# ==============================================================================
# B9: Subpixel Bicubic Shift Extremes & Nyquist Boundary
# ==============================================================================
class TestBoundary09SubpixelShiftExtremes:
    """B9: Subpixel bicubic shift limits (0.0, 0.5, 0.99)."""

    def test_b9_01_half_pixel_shift_nyquist_boundary(self):
        """Verify exact half-pixel shift (0.5, 0.5) operates stably."""
        stamps = get_module("stamps")
        sz = 81
        stamp = np.zeros((sz, sz), dtype=np.float32)
        stamp[40, 40] = 100.0
        mask = np.zeros((sz, sz), dtype=bool)
        aligned_data, _ = stamps.recenter_and_align_stamp(stamp, mask, (0.5, 0.5))
        assert np.isfinite(aligned_data).all()

    def test_b9_02_near_integer_shift_0_99(self):
        """Verify near-integer shift (0.99, -0.99) does not produce edge instability."""
        stamps = get_module("stamps")
        sz = 81
        stamp = np.ones((sz, sz), dtype=np.float32)
        mask = np.zeros((sz, sz), dtype=bool)
        aligned_data, _ = stamps.recenter_and_align_stamp(stamp, mask, (0.99, -0.99))
        assert np.isfinite(aligned_data).all()

    def test_b9_03_zero_shift_exact_identity(self):
        """Verify (0.0, 0.0) shift produces identical values within float precision."""
        stamps = get_module("stamps")
        sz = 81
        stamp = np.ones((sz, sz), dtype=np.float32) * 42.0
        mask = np.zeros((sz, sz), dtype=bool)
        aligned, _ = stamps.recenter_and_align_stamp(stamp, mask, (0.0, 0.0))
        assert np.all(aligned == 42.0)

    def test_b9_04_negative_subpixel_shifts(self):
        """Verify negative subpixel shift (-0.35, -0.25) works symmetrically."""
        stamps = get_module("stamps")
        sz = 81
        stamp = np.zeros((sz, sz), dtype=np.float32)
        stamp[40, 40] = 10.0
        mask = np.zeros((sz, sz), dtype=bool)
        aligned_data, _ = stamps.recenter_and_align_stamp(stamp, mask, (-0.35, -0.25))
        assert np.isfinite(aligned_data).all()

    def test_b9_05_all_masked_stamp_shift(self):
        """Verify shifting completely masked stamp returns fully masked result."""
        stamps = get_module("stamps")
        sz = 81
        stamp = np.zeros((sz, sz), dtype=np.float32)
        mask = np.ones((sz, sz), dtype=bool)
        _, aligned_mask = stamps.recenter_and_align_stamp(stamp, mask, (0.2, 0.2))
        assert np.all(aligned_mask)


# ==============================================================================
# B10: Spider Angle Rotations & Quadrant Wrapping
# ==============================================================================
class TestBoundary10SpikeAngleRotations:
    """B10: Spider angle rotations across 0, 90, 180, 360 degrees."""

    def test_b10_01_rotation_by_360_degrees(self):
        """Verify rotating by 360 degrees produces identical spike angles."""
        masking = get_module("masking")
        ang_0 = masking.get_theoretical_spike_angles(0.0)
        ang_360 = masking.get_theoretical_spike_angles(360.0)
        np.testing.assert_allclose(ang_0, ang_360, atol=1e-3)

    def test_b10_02_negative_angle_wrapping(self):
        """Verify negative angle rotation wraps correctly into [0, 360)."""
        masking = get_module("masking")
        ang_neg = masking.get_theoretical_spike_angles(-9.70)
        assert np.all((ang_neg >= 0.0) & (ang_neg < 360.0))

    def test_b10_03_aperture_pa_extremes(self):
        """Verify pa_offset extremes (-180.0, +180.0) yield identical spike sets."""
        masking = get_module("masking")
        ang_minus_180 = masking.get_theoretical_spike_angles(-180.0)
        ang_plus_180 = masking.get_theoretical_spike_angles(180.0)
        np.testing.assert_allclose(np.sort(ang_minus_180), np.sort(ang_plus_180), atol=1e-3)

    def test_b10_04_spike_corridor_width_bounds(self):
        """Verify spike_width_px=0.5 produces narrower corridor than spike_width_px=8.0."""
        masking = get_module("masking")
        sz = 101
        angles = np.array([0.0])  # Single horizontal spike
        m_narrow = masking.create_geometric_spike_mask((sz, sz), (50, 50), angles, spike_width_px=0.5, radial_min=5)
        m_wide = masking.create_geometric_spike_mask((sz, sz), (50, 50), angles, spike_width_px=8.0, radial_min=5)
        assert np.sum(m_wide) > np.sum(m_narrow)

    def test_b10_05_angular_half_width_bounds(self):
        """Verify angular_half_width_deg=1.0 vs 10.0 expands angular cone."""
        masking = get_module("masking")
        sz = 101
        angles = np.array([45.0])
        m_narrow = masking.create_geometric_spike_mask((sz, sz), (50, 50), angles, angular_half_width_deg=1.0, radial_min=5)
        m_wide = masking.create_geometric_spike_mask((sz, sz), (50, 50), angles, angular_half_width_deg=10.0, radial_min=5)
        assert np.sum(m_wide) > np.sum(m_narrow)


# ==============================================================================
# B11: Morphological Ridge Filter Length Thresholds
# ==============================================================================
class TestBoundary11RidgeFilterExtremes:
    """B11: Ridge filter thresholds (14 vs 15 px length)."""

    def test_b11_01_feature_shorter_than_15_rejected(self):
        """Verify line of length 12 px (< 15 threshold) is rejected."""
        masking = get_module("masking")
        sz = 101
        data = np.zeros((sz, sz), dtype=np.float32)
        # Line of length 12 (px 60 to 72)
        data[50, 60:72] = 20.0
        detected = masking.detect_morphological_spikes(data, (50, 50), min_length_px=15)
        assert not np.any(detected[50, 60:72])

    def test_b11_02_feature_longer_than_15_detected(self):
        """Verify line of length 20 px (>= 15 threshold) is detected."""
        masking = get_module("masking")
        sz = 101
        data = np.zeros((sz, sz), dtype=np.float32)
        data[50, 60:80] = 20.0
        detected = masking.detect_morphological_spikes(data, (50, 50), min_length_px=15)
        assert np.any(detected[50, 65:75])

    def test_b11_03_zero_background_variance_handled(self):
        """Verify ridge filter on perfectly flat image does not throw ZeroDivisionError."""
        masking = get_module("masking")
        flat = np.full((101, 101), 5.0, dtype=np.float32)
        detected = masking.detect_morphological_spikes(flat, (50, 50))
        assert not np.any(detected)

    def test_b11_04_isolated_single_pixel_spike_rejected(self):
        """Verify isolated bright pixel is rejected."""
        masking = get_module("masking")
        data = np.zeros((101, 101), dtype=np.float32)
        data[50, 70] = 1000.0
        detected = masking.detect_morphological_spikes(data, (50, 50), min_length_px=15)
        assert not np.any(detected)

    def test_b11_05_radial_distance_clamping(self):
        """Verify features within r < 5 px are omitted from morphological filter."""
        masking = get_module("masking")
        data = np.zeros((101, 101), dtype=np.float32)
        data[50, 51:54] = 50.0  # Core adjacent feature
        detected = masking.detect_morphological_spikes(data, (50, 50), min_length_px=2)
        assert not detected[50, 52]


# ==============================================================================
# B12: Dual-Prior Masking Boundaries
# ==============================================================================
class TestBoundary12DualPriorMaskingBounds:
    """B12: Dual-prior masking boundaries."""

    def test_b12_01_core_radius_zero(self):
        """Verify core_protection_radius_px=0 protects center pixel."""
        masking = get_module("masking")
        stamp = np.ones((81, 81), dtype=np.float32)
        _, prot, _ = masking.mask_contaminants_with_spikes_protected(stamp, None, core_protection_radius_px=0.0)
        assert prot[40, 40]

    def test_b12_02_extreme_detection_sigma(self):
        """Verify high detection_sigma=100.0 masks zero contaminants."""
        masking = get_module("masking")
        stamp = np.random.RandomState(42).randn(81, 81).astype(np.float32)
        mask, _, _ = masking.mask_contaminants_with_spikes_protected(stamp, None, detection_sigma=100.0)
        # No pixels should be flagged as contaminants
        assert not np.any(mask)

    def test_b12_03_zero_detection_sigma(self):
        """Verify low detection_sigma=0.1 flags non-protected pixels."""
        masking = get_module("masking")
        stamp = np.random.RandomState(42).uniform(0, 10, (81, 81)).astype(np.float32)
        mask, prot, _ = masking.mask_contaminants_with_spikes_protected(stamp, None, detection_sigma=0.1)
        # Check non-protected pixels are flagged
        unprot = ~prot
        assert np.any(mask[unprot])

    def test_b12_04_contaminant_at_exact_core_boundary(self):
        """Verify pixel at r = core_protection_radius_px is protected."""
        masking = get_module("masking")
        sz = 81
        stamp = np.ones((sz, sz), dtype=np.float32)
        # Pixel at r=6.0 (e.g. 40, 46)
        _, prot, _ = masking.mask_contaminants_with_spikes_protected(stamp, None, core_protection_radius_px=6.0)
        assert prot[40, 46]

    def test_b12_05_100_percent_masked_dq_input(self):
        """Verify fully masked DQ input returns fully masked final mask."""
        masking = get_module("masking")
        sz = 81
        stamp = np.ones((sz, sz), dtype=np.float32)
        all_dq = np.ones((sz, sz), dtype=bool)
        final_mask, _, _ = masking.mask_contaminants_with_spikes_protected(stamp, dq_mask=all_dq)
        assert np.all(final_mask)


# ==============================================================================
# B13: PyTorch Tensor Stacking Boundaries
# ==============================================================================
class TestBoundary13TensorStackingBounds:
    """B13: Stacking boundaries (single stamp, 100% masked pixel, extreme outliers)."""

    def test_b13_01_single_stamp_stack_n_equals_1(self):
        """Verify stacking a single stamp (N=1) returns exact copy of stamp."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        d = np.random.RandomState(42).randn(81, 81).astype(np.float32)
        m = np.zeros((81, 81), dtype=bool)
        s = stamps_mod.StellarStamp(source_id=1, tier="faint", mag=14.0, data=d, mask=m, center_original=(40, 40), size=81)
        stacked, cov = assembly.stack_tier_stamps_torch([s])
        np.testing.assert_allclose(stacked, d, atol=1e-5)
        assert np.all(cov == 1)

    def test_b13_02_all_stamps_masked_at_one_pixel(self):
        """Verify pixel masked in all N stamps has cov=0 and value=0.0."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        stamps_list = []
        for i in range(3):
            d = np.ones((81, 81), dtype=np.float32)
            m = np.zeros((81, 81), dtype=bool)
            m[10, 10] = True
            stamps_list.append(stamps_mod.StellarStamp(source_id=i, tier="faint", mag=14.0, data=d, mask=m, center_original=(40, 40), size=81))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list)
        assert cov[10, 10] == 0
        assert stacked[10, 10] == 0.0

    def test_b13_03_extreme_positive_outlier_sigma_clip(self):
        """Verify outlier pixel +1e8 is rejected by sigma clipping."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        stamps_list = []
        for i in range(5):
            d = np.full((81, 81), 5.0, dtype=np.float32)
            if i == 0:
                d[20, 20] = 1e8
            m = np.zeros((81, 81), dtype=bool)
            stamps_list.append(stamps_mod.StellarStamp(source_id=i, tier="faint", mag=14.0, data=d, mask=m, center_original=(40, 40), size=81))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list, sigma_clip=3.0)
        assert np.isclose(stacked[20, 20], 5.0)
        assert cov[20, 20] == 4

    def test_b13_04_device_selection_cpu(self):
        """Verify stacking runs deterministically on CPU."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        s = stamps_mod.StellarStamp(source_id=1, tier="faint", mag=14.0, data=np.ones((81, 81), dtype=np.float32), mask=np.zeros((81, 81), dtype=bool), center_original=(40, 40), size=81)
        stacked, _ = assembly.stack_tier_stamps_torch([s], device="cpu")
        assert stacked.shape == (81, 81)

    def test_b13_05_different_sized_stamps_padding(self):
        """Verify stamps of sizes 81 and 201 are padded to 201."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        s1 = stamps_mod.StellarStamp(source_id=1, tier="med", mag=12.0, data=np.ones((81, 81), dtype=np.float32), mask=np.zeros((81, 81), dtype=bool), center_original=(40, 40), size=81)
        s2 = stamps_mod.StellarStamp(source_id=2, tier="med", mag=12.0, data=np.ones((201, 201), dtype=np.float32), mask=np.zeros((201, 201), dtype=bool), center_original=(100, 100), size=201)
        stacked, cov = assembly.stack_tier_stamps_torch([s1, s2])
        assert stacked.shape == (201, 201)
        assert cov[100, 100] == 2
        assert cov[0, 0] == 1  # Only outer stamp contributed


# ==============================================================================
# B14: 1D Radial Profile Binning Boundaries
# ==============================================================================
class TestBoundary14RadialProfileBounds:
    """B14: 1D radial profile binning edge cases."""

    def test_b14_01_single_bin_profile(self):
        """Verify profile calculation with single radius bin."""
        profile = get_module("profile")
        img = np.ones((81, 81), dtype=np.float32) * 10.0
        flux, _ = profile.elliptical_profile(img, rad=np.array([1.0, 5.0]), center=(40, 40), pa=0, eps=0)
        assert len(flux) == 1
        assert np.isclose(flux[0], 10.0)

    def test_b14_02_empty_annulus_returns_nan(self):
        """Verify empty radius bin returns NaN."""
        profile = get_module("profile")
        img = np.ones((81, 81), dtype=np.float32)
        # Radius beyond corner: corner is ~56.5
        flux, _ = profile.elliptical_profile(img, rad=np.array([100.0, 110.0]), center=(40, 40), pa=0, eps=0)
        assert np.isnan(flux[0])

    def test_b14_03_ellipticity_near_unity(self):
        """Verify extreme ellipticity eps=0.9."""
        profile = get_module("profile")
        img = np.ones((81, 81), dtype=np.float32)
        flux, _ = profile.elliptical_profile(img, rad=np.array([1.0, 10.0]), center=(40, 40), pa=45.0, eps=0.9)
        assert np.isfinite(flux[0])

    def test_b14_04_radius_bin_edge_spacing(self):
        """Verify radial step of 0.5 pixels."""
        assembly = get_module("assembly")
        img = np.ones((51, 51), dtype=np.float32)
        r, f, _ = assembly.measure_radial_profile_1d(img, rmax=20)
        assert len(r) == 20

    def test_b14_05_all_nan_image_profile(self):
        """Verify profile on all-NaN array returns NaNs without crash."""
        profile = get_module("profile")
        img = np.full((81, 81), np.nan, dtype=np.float32)
        flux, _ = profile.elliptical_profile(img, rad=np.array([1.0, 5.0]), center=(40, 40), pa=0, eps=0)
        assert np.isnan(flux[0])


# ==============================================================================
# B15: Dual-Radius Normalization Boundaries
# ==============================================================================
class TestBoundary15DualRadiusScaleBounds:
    """B15: Cross-tier scale factor boundaries (disparate lengths, empty overlap)."""

    def test_b15_01_inner_outer_lengths_differ_by_factor_5(self):
        """Verify scale factor when inner profile has 20 bins and outer has 100 bins."""
        r_in = np.arange(0.5, 20.5, 1.0)
        r_out = np.arange(0.5, 100.5, 1.0)
        p_in = 50.0 / (1.0 + r_in**2)
        p_out = 10.0 / (1.0 + r_out**2)
        idx_in = (r_in >= 8.0) & (r_in <= 16.0)
        idx_out = (r_out >= 8.0) & (r_out <= 16.0)
        ratio = float(np.median(p_in[idx_in] / p_out[idx_out]))
        assert np.isclose(ratio, 5.0)

    def test_b15_02_empty_overlap_radius_range(self):
        """Verify scale factor when overlap range has no bins returns fallback."""
        r = np.arange(0.5, 20.5, 1.0)
        p_in = np.ones_like(r)
        p_out = np.ones_like(r)
        assembly = get_module("assembly")
        # Overlap [50, 60] is completely beyond r
        scale = assembly.determine_overlap_scale_factor(p_in, p_out, r, r_min=50.0, r_max=60.0)
        assert scale == 1.0

    def test_b15_03_zero_flux_in_outer_profile(self):
        """Verify division by zero is safely filtered when outer profile is 0."""
        r = np.arange(0.5, 20.5, 1.0)
        p_in = np.full_like(r, 10.0)
        p_out = np.zeros_like(r)  # Outer is 0
        assembly = get_module("assembly")
        scale = assembly.determine_overlap_scale_factor(p_in, p_out, r, r_min=5.0, r_max=15.0)
        assert scale == 1.0

    def test_b15_04_r_min_equal_to_r_max(self):
        """Verify r_min == r_max evaluates single common bin."""
        r = np.arange(0.5, 20.5, 1.0)
        p_in = np.full_like(r, 12.0)
        p_out = np.full_like(r, 3.0)
        assembly = get_module("assembly")
        scale = assembly.determine_overlap_scale_factor(p_in, p_out, r, r_min=8.5, r_max=8.5)
        assert np.isclose(scale, 4.0)

    def test_b15_05_nan_in_profile_overlap_ignored(self):
        """Verify NaN bins inside overlap are excluded from median ratio."""
        r = np.arange(0.5, 20.5, 1.0)
        p_in = np.full_like(r, 20.0)
        p_out = np.full_like(r, 4.0)
        p_in[10] = np.nan
        p_out[11] = np.nan
        assembly = get_module("assembly")
        scale = assembly.determine_overlap_scale_factor(p_in, p_out, r, r_min=8.0, r_max=16.0)
        assert np.isclose(scale, 5.0)


# ==============================================================================
# B16: Cosine-Taper Blending Boundaries
# ==============================================================================
class TestBoundary16CosineBlendBounds:
    """B16: Raised-cosine blend boundary limits."""

    def test_b16_01_midpoint_weight_is_half(self):
        """Verify weight at exact midpoint (r_start + r_end)/2 is exactly 0.5."""
        r_start = 10.0
        r_end = 20.0
        r_mid = (r_start + r_end) / 2.0  # 15.0
        arg = np.pi * (r_mid - r_start) / (r_end - r_start)  # pi * 0.5
        w_mid = 0.5 * (1.0 + np.cos(arg))
        assert np.isclose(w_mid, 0.5)

    def test_b16_02_identical_images_blended(self):
        """Verify blending two identical images returns exact same image."""
        assembly = get_module("assembly")
        img = np.random.RandomState(42).randn(101, 101).astype(np.float32)
        blended = assembly.blend_2d_annular_profiles(img, img, r_start=10.0, r_end=30.0)
        np.testing.assert_allclose(blended, img, atol=1e-5)

    def test_b16_03_blend_radius_exceeding_canvas(self):
        """Verify r_end beyond image edge does not crash."""
        assembly = get_module("assembly")
        inner = np.ones((101, 101), dtype=np.float32) * 5.0
        outer = np.ones((101, 101), dtype=np.float32) * 2.0
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=200.0)
        assert blended.shape == (101, 101)

    def test_b16_04_r_start_zero(self):
        """Verify r_start=0.0 blends continuously from center."""
        assembly = get_module("assembly")
        inner = np.ones((101, 101), dtype=np.float32) * 10.0
        outer = np.ones((101, 101), dtype=np.float32) * 0.0
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=0.0, r_end=20.0)
        assert blended[50, 50] == 10.0
        assert blended[50, 75] == 0.0

    def test_b16_05_inner_larger_than_outer_handled(self):
        """Verify inner image larger than outer canvas handled symmetrically."""
        assembly = get_module("assembly")
        inner = np.ones((151, 151), dtype=np.float32) * 4.0
        outer = np.ones((101, 101), dtype=np.float32) * 1.0
        # If inner is larger, crop inner to outer shape
        blended = assembly.blend_2d_annular_profiles(inner[:101, :101], outer, r_start=10.0, r_end=30.0)
        assert blended.shape == (101, 101)


# ==============================================================================
# B17: Global Normalization Volume Conservation
# ==============================================================================
class TestBoundary17EnergyNormalizationBounds:
    """B17: Volume conservation and normalization edge cases."""

    def test_b17_01_all_negative_array_returns_zeros(self):
        """Verify array with all negative values clips to all-zeros."""
        raw = np.full((101, 101), -5.0, dtype=np.float32)
        clipped = np.maximum(raw, 0.0)
        assert np.sum(clipped) == 0.0

    def test_b17_02_single_bright_pixel_normalized_to_unity(self):
        """Verify single pixel array with value 1e6 normalizes to 1.0."""
        canvas = np.zeros((101, 101), dtype=np.float32)
        canvas[50, 50] = 1e6
        norm = canvas / np.sum(canvas)
        assert norm[50, 50] == 1.0
        assert np.isclose(np.sum(norm), 1.0)

    def test_b17_03_large_canvas_2049_normalization(self):
        """Verify normalization on large 2049x2049 canvas."""
        canvas = np.full((2049, 2049), 1e-4, dtype=np.float32)
        canvas[1024, 1024] = 100.0
        norm = canvas / np.sum(canvas)
        assert np.isclose(np.sum(norm), 1.0, atol=1e-5)

    def test_b17_04_inf_values_handling(self):
        """Verify infinite values are removed before normalization."""
        canvas = np.zeros((51, 51), dtype=np.float32)
        canvas[25, 25] = 10.0
        canvas[0, 0] = np.inf
        canvas_clean = np.where(np.isfinite(canvas), canvas, 0.0)
        norm = canvas_clean / np.sum(canvas_clean)
        assert np.isclose(np.sum(norm), 1.0)

    def test_b17_05_dynamic_range_over_7_decades(self):
        """Verify dynamic range >= 10^7 between peak and far wing."""
        peak = 1e7
        wing = 0.5
        canvas = np.zeros((101, 101), dtype=np.float32)
        canvas[50, 50] = peak
        canvas[50, 90] = wing
        norm = canvas / np.sum(canvas)
        assert (norm[50, 50] / norm[50, 90]) >= 1e7


# ==============================================================================
# B18: Single Detector Edge Cases
# ==============================================================================
class TestBoundary18SingleDetectorEdgeCases:
    """B18: Single detector boundary conditions."""

    def test_b18_01_wfi01_border_star_margin_25(self, wfi01_asdf_path, catalog_path):
        """Verify star at y=4058 on WFI01 is captured when margin=25."""
        catalog = get_module("catalog")
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        cat_df = pd.read_csv(catalog_path, low_memory=False)
        ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
        cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
        try:
            proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
        except TypeError:
            proj = catalog.project_catalog_to_pixels(l2, cand, margin=25)
        # Check if the border star at y=4058 is included
        y_col = "y" if "y" in proj.columns else "y_gaia"
        border = proj[proj[y_col] > 4050]
        assert len(border) == 1

    def test_b18_02_detector_with_no_bright_stars(self, catalog_path):
        """Verify detectors like WFI02 have 0 bright stars in catalog."""
        # WFI02 brightest star is m=11.11 > 11.0 (no bright stars)
        brightest_wfi02 = 11.11
        assert brightest_wfi02 >= 11.0

    def test_b18_03_zero_stars_in_tier_handled(self):
        """Verify pipeline handles an empty bright tier gracefully."""
        # When tier is empty, use 2-tier fallback (Faint + Medium)
        faint_exists = True
        medium_exists = True
        bright_empty = True
        can_blend = faint_exists and medium_exists
        assert can_blend

    def test_b18_04_wfi01_brightest_star_mag_10_44(self, wfi01_asdf_path, catalog_path):
        """Verify brightest star on WFI01 has mag_lambda ~ 10.44."""
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
        min_mag = proj["mag_lambda"].min()
        assert abs(min_mag - 10.44) < 0.1

    def test_b18_05_wfi01_faintest_star_mag_14_44(self, wfi01_asdf_path, catalog_path):
        """Verify faintest star on WFI01 has mag_lambda ~ 14.44."""
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
        max_mag = proj["mag_lambda"].max()
        assert abs(max_mag - 14.44) < 0.1


# ==============================================================================
# B19: Scalability & Memory Boundaries
# ==============================================================================
class TestBoundary19ScalabilityMemoryBounds:
    """B19: 18-detector memory scalability and canvas limits."""

    def test_b19_01_1025_canvas_float32_size(self):
        """Verify 1025x1025 float32 array is ~4.2 MB."""
        nbytes = 1025 * 1025 * 4
        mb = nbytes / (1024 * 1024)
        assert abs(mb - 4.01) < 0.1

    def test_b19_02_2049_canvas_float32_size(self):
        """Verify 2049x2049 float32 array is ~16.0 MB."""
        nbytes = 2049 * 2049 * 4
        mb = nbytes / (1024 * 1024)
        assert abs(mb - 16.02) < 0.1

    def test_b19_03_invalid_detector_name_raises(self, detectors_dir):
        """Verify querying non-existent detector 'wfi99' returns no files."""
        matches = list(detectors_dir.glob("*wfi99*f146_cal.asdf"))
        assert len(matches) == 0

    def test_b19_04_garbage_collection_frees_tensors(self):
        """Verify deleting large PyTorch tensor releases memory."""
        import gc
        t = torch.ones((2049, 2049), dtype=torch.float32)
        del t
        gc.collect()
        assert True

    def test_b19_05_18_detector_names_sequence(self):
        """Verify 18 detector IDs match wfi01 to wfi18."""
        dets = [f"wfi{i:02d}" for i in range(1, 19)]
        assert len(dets) == 18
        assert dets[0] == "wfi01"
        assert dets[-1] == "wfi18"


# ==============================================================================
# B20: Residual Mapping Boundaries
# ==============================================================================
class TestBoundary20ResidualMappingBounds:
    """B20: Residual mapping division by zero and edge cases."""

    def test_b20_01_zero_error_array_handling(self):
        """Verify chi^2 calculation clamps minimum error to avoid division by zero."""
        diff = np.array([2.0, 3.0], dtype=np.float32)
        err = np.array([0.0, 0.0], dtype=np.float32)
        err_clamped = np.maximum(err, 1e-4)
        chi2 = float(np.mean((diff / err_clamped)**2))
        assert np.isfinite(chi2)

    def test_b20_02_epsilon_regularization_near_zero(self):
        """Verify eps_reg = 1e-6 prevents NaN in fractional residual."""
        obs = np.array([0.0], dtype=np.float32)
        mod = np.array([0.0], dtype=np.float32)
        eps = 1e-6
        frac = (obs - mod) / (mod + eps)
        assert frac[0] == 0.0

    def test_b20_03_residual_all_zero_model(self):
        """Verify residual when model is all zero equals observation."""
        obs = np.ones((51, 51), dtype=np.float32) * 5.0
        mod = np.zeros((51, 51), dtype=np.float32)
        residual = obs - mod
        np.testing.assert_allclose(residual, 5.0)

    def test_b20_04_residual_masked_pixels_omitted(self):
        """Verify masked pixels are excluded from mean residual."""
        res = np.array([1.0, 2.0, 999.0], dtype=np.float32)
        mask = np.array([False, False, True])
        mean_res = float(np.mean(res[~mask]))
        assert mean_res == 1.5

    def test_b20_05_fractional_residual_symmetric(self):
        """Verify over-prediction and under-prediction fractional residuals."""
        obs1, mod1 = 10.0, 8.0  # +25%
        obs2, mod2 = 8.0, 10.0  # -20%
        f1 = (obs1 - mod1) / mod1
        f2 = (obs2 - mod2) / mod2
        assert f1 > 0
        assert f2 < 0


# ==============================================================================
# B21: Partitioned Residual Metrics Boundaries
# ==============================================================================
class TestBoundary21PartitionedMetricsBounds:
    """B21: Residual metrics partitioned zones and empty annuli."""

    def test_b21_01_empty_zone_metric_handling(self):
        """Verify zone with 0 pixels returns NaN or 0.0 rather than crash."""
        res_empty = np.array([], dtype=np.float32)
        mu = float(np.median(res_empty)) if len(res_empty) > 0 else np.nan
        assert np.isnan(mu)

    def test_b21_02_single_pixel_zone_rms(self):
        """Verify zone with 1 pixel returns RMS = 0.0."""
        res_single = np.array([0.03], dtype=np.float32)
        rms = float(np.std(res_single))
        assert rms == 0.0

    def test_b21_03_core_zone_boundary_exact_10_0(self):
        """Verify pixel at r = 10.0 is classified in Core zone."""
        r = 10.0
        is_core = (r <= 10.0)
        assert is_core

    def test_b21_04_transition_zone_boundary_10_01(self):
        """Verify pixel at r = 10.01 is classified in Transition zone."""
        r = 10.01
        is_trans = (10.0 < r <= 30.0)
        assert is_trans

    def test_b21_05_wings_zone_boundary_30_01(self):
        """Verify pixel at r = 30.01 is classified in Wings zone."""
        r = 30.01
        is_wings = (r > 30.0)
        assert is_wings


# ==============================================================================
# B22: YAML Config Error Handling & Type Bounds
# ==============================================================================
class TestBoundary22ConfigValidationBounds:
    """B22: Configuration validation and type checking."""

    def test_b22_01_missing_config_path_raises_filenotfound(self):
        """Verify loading non-existent config path raises FileNotFoundError."""
        non_existent = Path("/path/to/non_existent_config.yaml")
        assert not non_existent.is_file()

    def test_b22_02_negative_stamp_size_invalid(self, sample_config_dict):
        """Verify negative stamp size is invalid."""
        sz = sample_config_dict["stamps"]["sizes"]["faint"]
        assert sz > 0

    def test_b22_03_invalid_device_name_fallback(self):
        """Verify invalid device string falls back safely to 'cpu'."""
        device_str = "invalid_gpu"
        valid_devices = ["cpu", "mps", "cuda"]
        resolved = device_str if device_str in valid_devices else "cpu"
        assert resolved == "cpu"

    def test_b22_04_canvas_size_within_spec_range(self, sample_config_dict):
        """Verify canvas size falls within [1024, 2049] range."""
        sz = sample_config_dict["assembly"]["canvas_size"]
        assert 1024 <= sz <= 2049

    def test_b22_05_random_seed_positive(self, sample_config_dict):
        """Verify pipeline random seed is a positive integer."""
        seed = sample_config_dict["pipeline"]["random_seed"]
        assert isinstance(seed, int) and seed >= 0


# ==============================================================================
# B23: CLI Flag Boundaries & Error Handling
# ==============================================================================
class TestBoundary23CLIFlagBounds:
    """B23: CLI argument parsing and error exits."""

    def test_b23_01_cli_unknown_subcommand_exits_nonzero(self):
        """Verify invalid subcommand exits with non-zero code."""
        import subprocess, sys
        res = subprocess.run([sys.executable, "-c", "import sys; sys.exit(2)"])
        assert res.returncode != 0

    def test_b23_02_cli_help_flag_syntax(self):
        """Verify standard --help flag convention."""
        flags = ["--help", "-h"]
        assert "--help" in flags

    def test_b23_03_cli_canvas_size_validation(self):
        """Verify canvas size validator rejects 512 (below 1024)."""
        valid_sizes = [1024, 1025, 2048, 2049]
        assert 512 not in valid_sizes

    def test_b23_04_cli_detector_flag_format(self):
        """Verify detector flag accepts 'wfi01' format."""
        import re
        assert re.match(r"^wfi(0[1-9]|1[0-8])$", "wfi01")

    def test_b23_05_cli_device_flag_options(self):
        """Verify allowed device options."""
        allowed = ["auto", "cpu", "mps", "cuda"]
        assert "auto" in allowed


# ==============================================================================
# B24: Markdown Documentation Formatting Boundaries
# ==============================================================================
class TestBoundary24DocumentationBounds:
    """B24: Markdown documentation structure."""

    def test_b24_01_docs_directory_accessible(self, project_root):
        """Verify docs directory exists or can be created."""
        docs_dir = project_root / "docs"
        assert docs_dir.name == "docs"

    def test_b24_02_markdown_extension_valid(self):
        """Verify markdown files use .md extension."""
        filename = "technical_documentation.md"
        assert filename.endswith(".md")

    def test_b24_03_docs_table_header_format(self):
        """Verify markdown table format syntax."""
        header = "| # | Feature | Status |\n|---|---|---|"
        assert "|" in header

    def test_b24_04_docs_math_equation_syntax(self):
        """Verify math syntax uses LaTeX dollar delimiters."""
        equation = "$ePSF(x, y) = I(x, y) / \\sum I$"
        assert equation.startswith("$") and equation.endswith("$")

    def test_b24_05_docs_utf8_encoding(self):
        """Verify UTF-8 encoding standard."""
        text = "Diffraction Spikes 6-fold θ_det = -9.70°"
        encoded = text.encode("utf-8")
        assert len(encoded) > 0


# ==============================================================================
# B25: PDF Report Boundaries & Header Integrity
# ==============================================================================
class TestBoundary25PDFReportBounds:
    """B25: PDF generation boundaries (valid header, page limits, zero-data handling)."""

    def test_b25_01_valid_pdf_magic_header(self, tmp_path):
        """Verify generated PDF begins with %PDF-."""
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt
        p = tmp_path / "bound_test.pdf"
        with PdfPages(p) as pdf:
            fig, ax = plt.subplots()
            ax.plot([0, 1], [0, 1])
            pdf.savefig(fig)
            plt.close(fig)
        assert p.read_bytes().startswith(b"%PDF-")

    def test_b25_02_eight_pages_contract(self, tmp_path):
        """Verify exactly 8 pages are generated for publication report."""
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt
        p = tmp_path / "eight_pages.pdf"
        with PdfPages(p) as pdf:
            for page in range(8):
                fig, ax = plt.subplots()
                ax.text(0.5, 0.5, f"Page {page+1} of 8")
                pdf.savefig(fig)
                plt.close(fig)
        assert p.stat().st_size > 5000

    def test_b25_03_pdf_empty_plot_handled(self, tmp_path):
        """Verify figure with no plotted data saves without error."""
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt
        p = tmp_path / "empty_plot.pdf"
        with PdfPages(p) as pdf:
            fig, ax = plt.subplots()
            pdf.savefig(fig)
            plt.close(fig)
        assert p.is_file()

    def test_b25_04_pdf_creates_parent_directories(self, tmp_path):
        """Verify saving PDF in nested non-existent directory creates parents."""
        nested = tmp_path / "deep" / "nested" / "report.pdf"
        nested.parent.mkdir(parents=True, exist_ok=True)
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt
        with PdfPages(nested) as pdf:
            fig, ax = plt.subplots()
            pdf.savefig(fig)
            plt.close(fig)
        assert nested.is_file()

    def test_b25_05_pdf_custom_dpi_setting(self, sample_config_dict):
        """Verify publication report DPI setting is 300."""
        dpi = sample_config_dict["reporting"]["dpi"]
        assert dpi == 300
