"""
Unit tests for MTO2 (Max-Tree Object Representation & Deblending) Masking Module.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

from romanepsf.mto2 import (
    MTO2Config,
    estimate_local_background,
    segment_sources_mto2,
    mask_sources_not_main_star_mto2,
)


def _generate_synthetic_stamp_with_companions(shape=(101, 101), seed=42):
    """Generate synthetic star stamp with central star, 3 companions, and Gaussian noise."""
    ny, nx = shape
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    y, x = np.ogrid[:ny, :nx]

    # Central star (Moffat-like)
    r_c = np.sqrt((x - cx)**2 + (y - cy)**2)
    flux = 1000.0 / (1.0 + (r_c / 3.0)**2)**2.5

    # 3 Companion stars:
    # Comp 1 at (20, 20)
    r1 = np.sqrt((x - 20)**2 + (y - 20)**2)
    flux += 180.0 * np.exp(-r1**2 / 8.0)

    # Comp 2 at (80, 25)
    r2 = np.sqrt((x - 80)**2 + (y - 25)**2)
    flux += 120.0 * np.exp(-r2**2 / 6.0)

    # Comp 3 at (30, 80)
    r3 = np.sqrt((x - 30)**2 + (y - 80)**2)
    flux += 220.0 * np.exp(-r3**2 / 10.0)

    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1.0, shape).astype(np.float32)
    stamp = (flux + noise).astype(np.float32)
    return stamp, (cx, cy)


class TestMTO2LocalBackground:
    """Tests for robust local background estimation."""

    def test_estimate_local_background_clean_stamp(self):
        rng = np.random.default_rng(123)
        img = rng.normal(15.0, 2.0, (100, 100)).astype(np.float32)
        mean, var, gain = estimate_local_background(img)
        assert np.isclose(mean, 15.0, atol=0.2)
        assert np.isclose(var, 4.0, atol=0.4)
        assert gain > 0

    def test_estimate_local_background_with_nans(self):
        rng = np.random.default_rng(123)
        img = rng.normal(10.0, 1.5, (100, 100)).astype(np.float32)
        img[0:10, 0:10] = np.nan
        mean, var, gain = estimate_local_background(img)
        assert np.isfinite(mean)
        assert np.isfinite(var)
        assert np.isclose(mean, 10.0, atol=0.2)


class TestMTO2Segmentation:
    """Tests for MTO2 Max-Tree source segmentation."""

    def test_segment_sources_detects_multiple_companions(self):
        stamp, (cx, cy) = _generate_synthetic_stamp_with_companions((101, 101))
        seg_map, catalog = segment_sources_mto2(
            stamp,
            s_sigma=1.5,
            alpha=1e-5,
            move_factor=0.1,
            area_ratio=0.90,
        )

        assert seg_map.shape == stamp.shape
        assert len(catalog) >= 3, f"Expected at least 3 detected companion objects, got {len(catalog)}"

        # Verify companion centroids are detected within 3 px of true locations
        detected_centroids = [info["centroid_xy"] for info in catalog.values()]
        expected_locations = [(20, 20), (80, 25), (30, 80)]

        for ex_x, ex_y in expected_locations:
            min_dist = min(
                np.sqrt((dx - ex_x)**2 + (dy - ex_y)**2)
                for dx, dy in detected_centroids
            )
            assert min_dist < 4.0, f"Expected companion at ({ex_x}, {ex_y}) not detected; min_dist={min_dist}"


class TestMTO2MaskingNonStarSources:
    """Tests for mask_sources_not_main_star_mto2."""

    def test_masks_companions_while_protecting_main_star_core(self):
        stamp, (cx, cy) = _generate_synthetic_stamp_with_companions((101, 101))
        core_r = 6.0

        final_mask, seg_map, main_ids = mask_sources_not_main_star_mto2(
            stamp,
            center_xy=(cx, cy),
            core_protection_radius_px=core_r,
            s_sigma=1.5,
            alpha=1e-5,
            dilation_px=2,
        )

        # 1. Main star core MUST be strictly unmasked
        grid_y, grid_x = np.ogrid[:101, :101]
        dist_from_c = np.sqrt((grid_x - cx)**2 + (grid_y - cy)**2)
        assert not np.any(final_mask[dist_from_c <= core_r]), "Main star core pixels were wrongly masked!"

        # 2. Companion stars MUST be masked
        assert final_mask[20, 20], "Companion 1 at (20, 20) was not masked!"
        assert final_mask[25, 80], "Companion 2 at (80, 25) was not masked!"
        assert final_mask[80, 30], "Companion 3 at (30, 80) was not masked!"

    def test_strictly_protects_diffraction_spikes(self):
        stamp, (cx, cy) = _generate_synthetic_stamp_with_companions((101, 101))

        # Create a synthetic spike corridor across the stamp through companion 1
        protected_spikes = np.zeros(stamp.shape, dtype=bool)
        protected_spikes[18:23, :] = True  # Horizontal spike corridor overlapping companion 1

        final_mask, _, _ = mask_sources_not_main_star_mto2(
            stamp,
            center_xy=(cx, cy),
            core_protection_radius_px=6.0,
            protected_spikes=protected_spikes,
            dilation_px=2,
        )

        # Spikes must never be masked
        assert not np.any(final_mask[protected_spikes]), "Protected diffraction spikes were masked!"

    def test_handles_nans_and_dq_mask(self):
        stamp, (cx, cy) = _generate_synthetic_stamp_with_companions((101, 101))
        stamp[10, 10] = np.nan
        stamp[11, 11] = np.inf

        dq = np.zeros(stamp.shape, dtype=bool)
        dq[50, 70] = True

        final_mask, _, _ = mask_sources_not_main_star_mto2(
            stamp,
            center_xy=(cx, cy),
            dq_mask=dq,
        )

        assert final_mask[10, 10], "NaN pixel was not masked!"
        assert final_mask[11, 11], "Inf pixel was not masked!"
        assert final_mask[50, 70], "DQ bad pixel was not masked!"

    def test_pure_noise_zero_false_positives(self):
        rng = np.random.default_rng(999)
        noise_stamp = rng.normal(0, 1.0, (81, 81)).astype(np.float32)

        final_mask, seg_map, main_ids = mask_sources_not_main_star_mto2(
            noise_stamp,
            center_xy=(40.0, 40.0),
            core_protection_radius_px=4.0,
            alpha=1e-6,
        )

        # In pure noise at alpha=1e-6, zero significant non-star objects should be masked
        assert np.sum(final_mask) == 0, f"Expected 0 false positives, got {np.sum(final_mask)} masked pixels"

    def test_integration_with_mask_contaminants_with_spikes_protected(self):
        from romanepsf.masking import mask_contaminants_with_spikes_protected
        stamp, (cx, cy) = _generate_synthetic_stamp_with_companions((101, 101))

        # Test with contaminant_detector="mto2" and method="unsharp"
        final_mask, protected_area, residual = mask_contaminants_with_spikes_protected(
            stamp,
            core_protection_radius_px=6.0,
            method="unsharp",
            contaminant_detector="mto2",
        )

        assert final_mask.shape == stamp.shape
        assert not np.any(final_mask[protected_area]), "Protected area must never be masked"
        assert final_mask[20, 20], "Companion 1 was not masked by MTO2"
        assert final_mask[80, 30], "Companion 3 was not masked by MTO2"
        assert protected_area[25, 80], "Companion 2 should intersect a diffraction spike"
        assert not final_mask[25, 80], "Spike corridor intersecting companion 2 must remain protected"

    def test_overlapping_core_id_entire_region_unmasked(self):
        """Verify that any MTO2 ID overlapping the protected center is entirely unmasked across its whole extent."""
        stamp = np.zeros((101, 101), dtype=np.float32)
        cx, cy = 50.0, 50.0
        y, x = np.ogrid[:101, :101]

        # Central star core
        r_c = np.sqrt((x - cx)**2 + (y - cy)**2)
        stamp += 1000.0 / (1.0 + (r_c / 3.0)**2)**2.0

        # An extended asymmetric lobe/wing segment that overlaps the core (r <= 4)
        # but extends out to r = 18 px (e.g. x between 48 and 68, y between 48 and 52)
        lobe_mask = (x >= 48) & (x <= 68) & (y >= 48) & (y <= 52)
        stamp[lobe_mask] += 150.0

        # A distant companion at (20, 20) with no core overlap
        r_comp = np.sqrt((x - 20)**2 + (y - 20)**2)
        stamp += 100.0 * np.exp(-r_comp**2 / 8.0)

        core_r = 5.0
        final_mask, seg_map, main_ids = mask_sources_not_main_star_mto2(
            stamp,
            center_xy=(cx, cy),
            core_protection_radius_px=core_r,
            s_sigma=1.0,
            alpha=1e-5,
            dilation_px=0,
        )

        # Distant companion must be masked
        assert final_mask[20, 20], "Distant companion at (20, 20) should be masked"

        # The lobe pixel at (65, 50) is at distance 15 px (well outside core_r=5 px)
        # But because the lobe segment overlaps the core, its entire region must NOT be masked!
        lobe_id = seg_map[50, 65]
        assert lobe_id in main_ids, f"Lobe segment {lobe_id} should be classified as main star ID"
        assert not final_mask[50, 65], "Lobe pixel outside core radius was wrongly masked!"

    def test_direct_method_mto2_on_stamp(self):
        from romanepsf.masking import mask_contaminants_with_spikes_protected
        stamp, (cx, cy) = _generate_synthetic_stamp_with_companions((101, 101))

        final_mask, protected_area, residual = mask_contaminants_with_spikes_protected(
            stamp,
            core_protection_radius_px=6.0,
            method="mto2",
        )

        assert final_mask.shape == stamp.shape
        # Spikes must never be masked
        assert not np.any(final_mask[protected_area]), "Protected area must never be masked"
        # Off-spike companions must be masked
        assert final_mask[20, 20], "Companion 1 was not masked by method='mto2'"
        assert final_mask[80, 30], "Companion 3 was not masked by method='mto2'"
        # Companion 2 lies directly on a 24-spike ray corridor and thus is protected
        assert protected_area[25, 80], "Companion 2 should intersect a diffraction spike"
        assert not final_mask[25, 80], "Spike corridor intersecting companion 2 must remain protected"

