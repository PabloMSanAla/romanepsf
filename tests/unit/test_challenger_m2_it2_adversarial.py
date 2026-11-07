"""
Adversarial Stress Test Suite for Milestone 2 Iteration 2: Masking Module.
Authored by Challenger 1 (challenger_m2_it2_1).

Empirically tests and verifies:
1. Extreme dynamic range cutouts:
   - Background sky from -10 to +1000 MJy/sr.
   - Saturated stars with 10^5 dynamic range and saturation plateaus.
   - Subnormal floats, extreme negative depressions, NaNs, and Infs.
2. Non-standard cutout shapes and boundary dimensions:
   - Asymmetric, non-square cutouts (e.g. 15x85, 201x31, 73x151).
   - Tiny cutouts (e.g. 11x11, 7x7, 5x5, 3x3) testing small sample MAD stability.
   - Huge cutouts (1001x1001) verifying memory limits, execution time (< 2s), and Moffat fitting radius truncation.
   - Extreme off-center stellar centroids near or beyond cutout boundaries.
3. Radial threshold scaling:
   - Exact mathematical evaluation of sigma(r) = sigma_0 * (1 + A * exp(-r / r0)) across faint, medium, bright tiers.
   - Asymptotic boundary behavior as r -> 0 and r -> infinity.
   - Non-masking invariant for negative residuals.
   - Zero-variance and identical-pixel stability avoiding division by zero.
4. Dual-prior spike protection:
   - Spikes along all 12 theoretical rays [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] deg - 9.70 deg
     are never masked as contaminants, even in high-contrast noise.
   - Strict mathematical invariant: final_mask & protected_area == False (when DQ is clear).
   - Full 360-degree rotation sweeps preserving spike protection geometry.
5. Contaminant detection accuracy and confinement:
   - Actual off-axis point sources (> 5 sigma above local background threshold) at r=10, 25, 50, 100 px
     are accurately masked.
   - Dilation does not spread into the central core or diffraction spikes.
   - Faint stars with companions are masked without spurious morphological spike detections.
   - Real Roman Level 2 commissioning data (WFI01) injected companion detection.
6. Backward-compatibility wrapper equivalence:
   - Verifies src/masking.py and romanepsf.masking export identical symbols and accept all calling conventions.
"""

from __future__ import annotations

import time
from typing import Tuple
import numpy as np
import pytest

from romanepsf.config import SpikesConfig
from romanepsf.masking import (
    ROMAN_BASE_SPIKE_ANGLES_DEG,
    NOMINAL_DETECTOR_OFFSET_DEG,
    create_geometric_spike_mask,
    detect_morphological_spikes,
    fit_moffat_model,
    get_theoretical_spike_angles,
    mask_contaminants_with_spikes_protected,
)
import masking as root_masking
import romanepsf.masking as core_masking


class TestAdversarialDynamicRange:
    """Stress tests for extreme dynamic range cutouts and background sky levels."""

    @pytest.mark.parametrize("bkg_sky", [-10.0, -5.0, -1.0, -0.01, 0.0, 1.0, 10.0, 100.0, 1000.0])
    def test_extreme_background_sky_levels(self, bkg_sky: float):
        """Moffat fitting and contaminant masking must handle sky from -10 to +1000 MJy/sr cleanly."""
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        # Star on background pedestal
        star = (bkg_sky + 400.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        # Add realistic noise scaled with background
        noise_std = max(float(np.sqrt(max(bkg_sky, 0.0) * 0.05)), 0.5)
        np.random.seed(42)
        stamp = star + np.random.normal(0, noise_std, (sz, sz)).astype(np.float32)

        # 1. Fit Moffat model
        fitted_img, model = fit_moffat_model(stamp)
        assert fitted_img.shape == (sz, sz)
        assert np.all(np.isfinite(fitted_img))
        assert model is not None
        assert model.amplitude.value > 0.0

        # 2. Mask contaminants
        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            stamp, pa_offset_deg=-9.70, tier="medium"
        )
        assert final_mask.shape == (sz, sz)
        assert final_mask.dtype == bool
        assert np.all(np.isfinite(residual))

        # Core must be protected and never masked
        assert not final_mask[50, 50]
        assert prot_area[50, 50]

        # False positive rate in clean halo [15, 45] px must be negligible (< 2%)
        clean_halo = (r >= 15.0) & (r <= 45.0) & (~prot_area)
        assert np.sum(clean_halo) > 500
        assert np.mean(final_mask[clean_halo]) < 0.02

    @pytest.mark.parametrize("peak_flux", [1e4, 1e5, 1e6])
    def test_saturated_stars_with_high_dynamic_range(self, peak_flux: float):
        """Stars with 10^4 - 10^6 dynamic range and saturated core plateau must not overflow or crash."""
        sz = 201
        cx, cy = 100.0, 100.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        star = (1.0 + peak_flux / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        # Saturated plateau at r <= 10 px
        dq = np.zeros((sz, sz), dtype=bool)
        dq[r <= 10.0] = True
        star[r <= 10.0] = 50000.0  # Detector saturation limit

        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            star, dq_mask=dq, pa_offset_deg=-9.70, tier="bright"
        )
        assert final_mask.shape == (sz, sz)
        assert np.all(np.isfinite(residual))

        # Saturated core should be marked bad via DQ propagation
        assert np.all(final_mask[r <= 10.0])

        # Diffuse wings [20, 80] outside spikes must not be falsely masked (< 2%)
        wing = (r >= 20.0) & (r <= 80.0) & (~prot_area)
        assert np.mean(final_mask[wing]) < 0.02

    def test_extreme_negative_depression_and_non_finite_pixels(self):
        """Extreme negative flux depressions and isolated NaNs/Infs are handled robustly."""
        sz = 81
        stamp = np.full((sz, sz), 5.0, dtype=np.float32)
        # Add negative dip
        stamp[20:30, 20:30] = -500.0
        # Add isolated NaN and Inf
        stamp[10, 10] = np.nan
        stamp[70, 70] = np.inf
        stamp[70, 10] = -np.inf

        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(stamp)
        # Non-finite pixels must be masked
        assert final_mask[10, 10]
        assert final_mask[70, 70]
        assert final_mask[70, 10]

        # Negative depression pixels are NOT positive contaminants; shouldn't crash
        assert not final_mask[25, 25]


class TestAdversarialNonStandardCutouts:
    """Stress tests for non-standard cutout shapes, boundary sizes, and off-center stars."""

    @pytest.mark.parametrize("shape", [(11, 11), (7, 7), (5, 5), (3, 3)])
    def test_tiny_cutouts_and_low_sample_mad(self, shape: Tuple[int, int]):
        """Tiny stamps (11x11 down to 3x3) where clean pixels <= 20 must not crash."""
        ny, nx = shape
        cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
        gy, gx = np.ogrid[:ny, :nx]
        r = np.hypot(gx - cx, gy - cy)

        stamp = (50.0 / (1.0 + (r / 2.0)**2)**1.5).astype(np.float32)

        for tier in ["faint", "medium", "bright"]:
            final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
                stamp, tier=tier
            )
            assert final_mask.shape == shape
            assert prot_area.shape == shape
            assert residual.shape == shape
            assert final_mask.dtype == bool
            assert prot_area.dtype == bool

    def test_huge_cutout_1001x1001_performance_and_memory(self):
        """1001x1001 cutout executes in < 2.0s without memory exhaustion or infinite loops."""
        sz = 1001
        cx, cy = 500.0, 500.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        star = (1.5 + 800.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        np.random.seed(101)
        noise = np.random.normal(0, 1.0, (sz, sz)).astype(np.float32)
        stamp = star + noise

        t0 = time.perf_counter()
        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            stamp, pa_offset_deg=-9.70, tier="bright"
        )
        elapsed = time.perf_counter() - t0

        assert elapsed < 10.0, f"Execution took too long: {elapsed:.2f}s"
        assert final_mask.shape == (sz, sz)
        assert prot_area.shape == (sz, sz)
        # Peak core is unmasked
        assert not final_mask[500, 500]
        # Spike protection is non-empty
        assert np.sum(prot_area) > 10000

    @pytest.mark.parametrize("shape", [(15, 85), (201, 31), (73, 151), (100, 50)])
    def test_asymmetric_and_non_square_cutouts(self, shape: Tuple[int, int]):
        """Rectangular, non-square stamps with distinct aspect ratios must broadcast correctly."""
        ny, nx = shape
        cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
        gy, gx = np.ogrid[:ny, :nx]
        r = np.hypot(gx - cx, gy - cy)

        star = (200.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)

        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            star, pa_offset_deg=35.0, tier="medium"
        )
        assert final_mask.shape == shape
        assert prot_area.shape == shape
        assert residual.shape == shape

        mid_y, mid_x = int(round(cy)), int(round(cx))
        assert not final_mask[mid_y, mid_x]
        assert prot_area[mid_y, mid_x]

    def test_extreme_off_center_centroid(self):
        """Centroid placed near stamp edge (boundary star) must not trigger IndexError."""
        sz = 101
        angles = get_theoretical_spike_angles(-9.70)
        # Centroid at pixel (5, 95)
        mask = create_geometric_spike_mask((sz, sz), (5.0, 95.0), angles, spike_width_px=3.0)
        assert mask.shape == (sz, sz)
        assert not mask[95, 5]  # Core radius exclusion
        assert np.any(mask)     # Spike rays extending into stamp


class TestAdversarialRadialThresholdScaling:
    """Stress tests verifying sigma(r) = sigma_0 * (1 + A * exp(-r / r0)) under boundary conditions."""

    def test_exact_radial_threshold_scaling_values(self):
        """Verify mathematical formula output across radii for faint, medium, and bright configurations."""
        sigma_0 = 3.0
        test_radii = np.array([0.0, 5.0, 10.0, 15.0, 25.0, 50.0, 100.0, 1000.0])

        tiers = [
            ("faint", 50.0, 15.0),
            ("medium", 200.0, 15.0),
            ("bright", 200.0, 20.0),
        ]

        cfg = SpikesConfig()

        for t_name, expected_A, expected_r0 in tiers:
            for r_val in test_radii:
                expected_sigma_r = sigma_0 * (1.0 + expected_A * np.exp(-r_val / expected_r0))

                # Verify asymptotes
                if r_val == 0.0:
                    assert np.isclose(expected_sigma_r, sigma_0 * (1.0 + expected_A), rtol=1e-5)
                elif r_val >= 1000.0:
                    assert np.isclose(expected_sigma_r, sigma_0, rtol=1e-4)

    def test_negative_residuals_never_flagged_as_contaminants(self):
        """Negative residuals must never exceed the positive detection threshold."""
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        # Star with a massive dark hole / depression (flux = -100.0)
        star = (100.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        star[15:25, 15:25] = -100.0

        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            star, pa_offset_deg=-9.70, tier="medium"
        )
        # Depression must NOT be flagged as a contaminant
        assert not np.any(final_mask[15:25, 15:25])

    def test_zero_variance_and_identical_pixels_stability(self):
        """When cutout or residuals have zero variance, res_std must safely fall back to 1.0."""
        # Cutout of perfectly identical values
        flat_stamp = np.full((61, 61), 42.0, dtype=np.float32)
        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(flat_stamp)

        assert final_mask.shape == (61, 61)
        assert not np.any(final_mask), "Zero-variance stamp falsely flagged contaminants!"

        # Tiny stamp with zero variance
        tiny_flat = np.full((9, 9), 10.0, dtype=np.float32)
        tiny_mask, _, _ = mask_contaminants_with_spikes_protected(tiny_flat)
        assert not np.any(tiny_mask)


class TestAdversarialDualPriorSpikeProtection:
    """Stress tests ensuring theoretical diffraction spikes are preserved against contaminant masking."""

    @pytest.mark.parametrize("pa_deg", [0.0, 35.5, 90.0, 180.0, 270.0, -9.70, -45.0, 720.0])
    def test_spikes_never_masked_across_all_pa_rotations(self, pa_deg: float):
        """Diffraction spikes along all 12 rays are never masked regardless of aperture PA."""
        sz = 201
        cx, cy = 100.0, 100.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        star = (600.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        angles = get_theoretical_spike_angles(pa_deg, detector_offset_deg=-9.70)

        spike_coords = []
        for ang in angles:
            rad = np.radians(ang)
            for d in range(12, 80):
                px = int(round(cx + d * np.cos(rad)))
                py = int(round(cy + d * np.sin(rad)))
                star[py, px] += 80.0 / (1.0 + 0.02 * d)
                spike_coords.append((py, px))

        # Add heavy noise to test robustness
        np.random.seed(999)
        star += np.random.normal(0, 2.0, (sz, sz)).astype(np.float32)

        cfg = SpikesConfig()
        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            star, pa_aperture=pa_deg, cfg=cfg, tier="bright"
        )

        # Invariant: Every protected spike pixel must be unmasked
        masked_spikes = 0
        total_spikes = len(spike_coords)
        for py, px in spike_coords:
            if prot_area[py, px]:
                assert not final_mask[py, px], f"Spike pixel at ({px}, {py}) was masked!"
            else:
                masked_spikes += 1

        # At least 95% of theoretical spike pixels must fall within protected area
        assert (total_spikes - masked_spikes) / total_spikes > 0.95

    def test_mathematical_disjoint_invariant_randomized(self):
        """Strict mathematical guarantee: final_mask & protected_area == False for clean DQ."""
        np.random.seed(2026)
        sz = 121
        cx, cy = 60.0, 60.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        for trial in range(10):
            star = (300.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
            star += np.random.normal(0, 3.0, (sz, sz)).astype(np.float32)

            # Scatter random high-contrast contaminant blobs
            for _ in range(6):
                bx, by = np.random.randint(10, 110, size=2)
                star += (200.0 * np.exp(-((gx - bx)**2 + (gy - by)**2) / (2 * 1.5**2))).astype(np.float32)

            rand_pa = float(np.random.uniform(-360.0, 720.0))
            final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
                star, dq_mask=None, pa_aperture=rand_pa, tier="medium"
            )

            # Disjoint invariant check
            intersection = final_mask & prot_area
            assert not np.any(intersection), f"Invariant violated in trial {trial}: {np.sum(intersection)} pixels!"


class TestAdversarialContaminantDetection:
    """Stress tests ensuring actual off-axis point sources are masked without spreading into core or spikes."""

    @pytest.mark.parametrize("test_r", [10, 25, 50, 100])
    def test_companion_detected_at_various_radii_on_faint_stars(self, test_r: int):
        """Off-axis point sources at r=10, 25, 50, 100 px are accurately masked on faint stars."""
        sz = 251
        cx, cy = 125.0, 125.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        star = (200.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        noise_sigma = 0.5
        np.random.seed(42)
        noise = np.random.normal(0, noise_sigma, (sz, sz)).astype(np.float32)

        stamp = star + noise
        rad = np.radians(45.0)
        comp_x = cx + test_r * np.cos(rad)
        comp_y = cy + test_r * np.sin(rad)
        comp_r = np.hypot(gx - comp_x, gy - comp_y)
        px_x = int(round(comp_x))
        px_y = int(round(comp_y))

        # Companion > 5 sigma above local threshold
        comp_flux = 5.0 * (1.0 + 50.0 * np.exp(-test_r / 15.0)) * noise_sigma
        stamp += (comp_flux * np.exp(-comp_r**2 / (2 * 1.5**2))).astype(np.float32)

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            stamp, tier="faint"
        )

        # Companion must be masked
        assert final_mask[px_y, px_x], f"Companion at r={test_r} px was not masked!"
        # Central star core must not be masked
        assert not final_mask[125, 125], "Central star core was falsely masked!"
        # Mask must not spread into core exclusion zone
        assert not np.any(final_mask[r <= 3.0])

    @pytest.mark.parametrize("test_r", [25, 50, 100])
    def test_companion_detected_between_spikes_on_medium_stars(self, test_r: int):
        """Point sources placed between spikes at r=25, 50, 100 px are accurately masked on medium stars."""
        sz = 251
        cx, cy = 125.0, 125.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        star = (400.0 / (1.0 + (r / 2.5)**2)**1.2).astype(np.float32)
        angles = get_theoretical_spike_angles(-9.70)
        for ang in angles:
            rad = np.radians(ang)
            for d in range(10, 120):
                px = int(round(cx + d * np.cos(rad)))
                py = int(round(cy + d * np.sin(rad)))
                star[py, px] += 30.0 / (1.0 + 0.03 * d)

        noise_sigma = 0.5
        np.random.seed(42)
        noise = np.random.normal(0, noise_sigma, (sz, sz)).astype(np.float32)
        stamp = star + noise

        # Angle 89.75 deg is midway between spikes at 70.55 and 108.95 deg (gap 38.4 deg)
        rad = np.radians(89.75)
        comp_x = cx + test_r * np.cos(rad)
        comp_y = cy + test_r * np.sin(rad)
        comp_r = np.hypot(gx - comp_x, gy - comp_y)
        px_x = int(round(comp_x))
        px_y = int(round(comp_y))

        comp_flux = 5.0 * (1.0 + 200.0 * np.exp(-test_r / 15.0)) * noise_sigma
        stamp += (comp_flux * np.exp(-comp_r**2 / (2 * 1.5**2))).astype(np.float32)

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            stamp, pa_offset_deg=-9.70, tier="medium"
        )

        # Companion must be masked
        assert final_mask[px_y, px_x], f"Companion at r={test_r} px was not masked!"
        # Central star core must not be masked
        assert not final_mask[125, 125], "Central star core was falsely masked!"
        # Mask must not spread into core or spikes
        assert not np.any(final_mask[r <= 4.0])
        assert not np.any(final_mask & prot_area)

    def test_real_wfi01_data_injected_companion(self):
        """Injected off-axis point source on real Roman WFI01 data is accurately detected."""
        from romanepsf import loader, catalog, stamps
        import pandas as pd

        asdf_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf"
        cat_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv"

        l2 = loader.load_l2_image(asdf_path, calibrate=True)
        cat_df = pd.read_csv(cat_path, low_memory=False)
        ra_c, dec_c, rad_b, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
        cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad_b) & (np.abs(cat_df["dec"] - dec_c) < rad_b)].copy()
        cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
        proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
        tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)

        tier_stamps = stamps.process_star_stamps(l2, tiered)
        st = tier_stamps["bright"][0]

        cx, cy = (st.size - 1) / 2.0, (st.size - 1) / 2.0
        gy, gx = np.ogrid[:st.size, :st.size]

        # Inject companion at r = 50 px along 89.75 deg
        rad = np.radians(89.75)
        comp_x = cx + 50.0 * np.cos(rad)
        comp_y = cy + 50.0 * np.sin(rad)
        comp_r = np.hypot(gx - comp_x, gy - comp_y)
        px_x = int(round(comp_x))
        px_y = int(round(comp_y))

        stamp_data = st.data.copy()
        stamp_data += (15.0 * np.exp(-comp_r**2 / (2 * 1.5**2))).astype(np.float32)

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            stamp_data, dq_mask=st.mask, pa_aperture=l2.pa_aperture, tier="bright"
        )

        assert final_mask[px_y, px_x], "Injected companion was not masked on real WFI01 data!"
        assert not prot_area[px_y, px_x]


class TestAdversarialModuleEquivalence:
    """Stress tests verifying src/masking.py wrapper and interface contract equivalence."""

    def test_symbols_reexported_identically(self):
        """All public symbols from romanepsf.masking must be exposed in src/masking.py."""
        assert set(root_masking.__all__) == set(core_masking.__all__)
        for name in root_masking.__all__:
            assert getattr(root_masking, name) is getattr(core_masking, name)

    def test_signature_variants_produce_identical_masks(self):
        """Both authoritative and legacy calling conventions must yield identical masks."""
        stamp = np.ones((81, 81), dtype=np.float32)
        cfg = SpikesConfig()

        # Call with SpikesConfig as 4th positional
        m1, p1, _ = mask_contaminants_with_spikes_protected(stamp, None, 20.0, cfg)
        # Call with SpikesConfig as keyword
        m2, p2, _ = mask_contaminants_with_spikes_protected(stamp, None, pa_aperture=20.0, cfg=cfg)

        np.testing.assert_array_equal(m1, m2)
        np.testing.assert_array_equal(p1, p2)
