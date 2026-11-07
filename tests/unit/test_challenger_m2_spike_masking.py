"""
Adversarial Stress Test Suite for Milestone 2: Diffraction Spike Protection and Masking.
Authored by Challenger 1 (challenger_m2_1).

Empirically stress-tests:
1. 6-fold pupil geometry spike angle transformations across extreme, negative, and wrapping PAs.
2. 2D geometric cone and corridor spike masking across non-square geometries and rotations.
3. 2D Moffat core fitting and residual extraction under extreme noise, saturation plateaus, and corrupted data.
4. Morphological directional ridge filtering discriminating genuine linear spikes from compact companion stars.
5. Dual-prior spike preservation invariants in crowded stellar fields and high-contrast environments.
6. Real Roman commissioning WFI01 Level 2 data spike preservation and core integrity.
"""

from __future__ import annotations

import numpy as np
import pytest
from astropy.modeling import models

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


class TestAdversarialSpikeAngleTransformations:
    """Stress tests for theoretical spike angle generation under extreme rotations."""

    @pytest.mark.parametrize("pa", [0.0, 90.0, 180.0, 270.0, 360.0, 450.0, 720.0, 1080.0, 3600.0, 1e6])
    def test_extreme_positive_pa_angles(self, pa: float):
        angles = get_theoretical_spike_angles(pa)
        assert len(angles) == 12, f"Failed 12 rays for PA={pa}: got {len(angles)}"
        assert np.all(angles >= 0.0), f"Negative angles found for PA={pa}: {angles}"
        # All angles must be strictly ascending
        assert np.all(np.diff(angles) > 0.0), f"Angles not sorted for PA={pa}: {angles}"

        # 180-degree opposing symmetry
        for a in angles:
            opp = (a + 180.0) % 360.0
            assert np.any(np.isclose(angles % 360.0, opp % 360.0, atol=1e-3))

    @pytest.mark.parametrize("pa", [-0.0, -1e-6, -45.0, -90.0, -180.0, -270.0, -360.0, -720.0, -1080.0, -3600.0, -1e6])
    def test_extreme_negative_pa_angles(self, pa: float):
        angles = get_theoretical_spike_angles(pa)
        assert len(angles) == 12, f"Failed 12 rays for negative PA={pa}: got {len(angles)}"
        assert np.all(angles >= 0.0), f"Negative angles found for PA={pa}: {angles}"
        assert np.all(np.diff(angles) > 0.0)

        # Equivalence under modulo 360
        equiv_pos = get_theoretical_spike_angles(pa % 360.0)
        np.testing.assert_allclose(angles % 360.0, equiv_pos % 360.0, atol=1e-3)

    @pytest.mark.parametrize("det_off", [0.0, -9.70, 15.5, -45.0, 180.0, -180.0, 360.0, -360.0])
    def test_detector_offset_variations(self, det_off: float):
        angles = get_theoretical_spike_angles(pa_offset_deg=35.0, detector_offset_deg=det_off)
        assert len(angles) == 12
        expected_base = (np.array(ROMAN_BASE_SPIKE_ANGLES_DEG) + 35.0 + det_off) % 360.0
        for eb in expected_base:
            assert np.any(np.isclose(angles % 360.0, eb % 360.0, atol=1e-3))

    def test_sub_arcsecond_pa_jitter(self):
        """Telescope guide jitter (< 0.01 degree) must preserve ray count and ordering."""
        base_angles = get_theoretical_spike_angles(0.0)
        for jitter in np.linspace(-0.01, 0.01, 25):
            jitter_angles = get_theoretical_spike_angles(jitter)
            assert len(jitter_angles) == 12
            np.testing.assert_allclose(jitter_angles % 360.0, (base_angles + jitter) % 360.0, atol=1e-2)

    def test_invalid_pa_types_and_values(self):
        """Invalid inputs must raise ValueError or TypeError rather than produce corrupt angles."""
        with pytest.raises((ValueError, TypeError)):
            get_theoretical_spike_angles("invalid_angle")  # type: ignore


class TestAdversarialGeometricSpikeMask:
    """Stress tests for geometric cone and corridor masks."""

    def test_full_360_degree_sweep_rotation_coverage(self):
        """Verify geometric mask generates valid non-empty masks across 360-degree rotation sweep."""
        for pa in range(0, 360, 30):
            angles = get_theoretical_spike_angles(float(pa), detector_offset_deg=-9.70)
            mask = create_geometric_spike_mask((151, 151), (75.0, 75.0), angles)
            assert mask.shape == (151, 151)
            assert mask.dtype == bool
            # Total protected pixels for 12 rays on 151x151 stamp occupies ~20-30% of canvas
            assert 1500 < np.sum(mask) < 7500

    @pytest.mark.parametrize("shape", [(101, 101), (51, 151), (151, 51), (80, 80), (301, 301)])
    def test_non_square_and_even_dimensions(self, shape: tuple[int, int]):
        angles = get_theoretical_spike_angles(15.0)
        cy, cx = (shape[0] - 1) / 2.0, (shape[1] - 1) / 2.0
        mask = create_geometric_spike_mask(shape, (cx, cy), angles)
        assert mask.shape == shape
        assert np.any(mask)

    def test_off_center_centroid_near_boundary(self):
        """Centroid placed near image boundary (edge cutout) must not cause IndexError."""
        angles = get_theoretical_spike_angles(0.0)
        # Centroid at (5, 5) on a 101x101 stamp
        mask = create_geometric_spike_mask((101, 101), (5.0, 5.0), angles, radial_min=3.0)
        assert mask.shape == (101, 101)
        assert not mask[5, 5]
        assert np.any(mask)

    def test_core_exclusion_zone_strictly_empty(self):
        """All pixels with r < radial_min must be False in geometric spike mask."""
        angles = get_theoretical_spike_angles(45.0)
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)

        for r_min in [3.0, 6.0, 10.0, 15.0]:
            mask = create_geometric_spike_mask((sz, sz), (cx, cy), angles, radial_min=r_min)
            assert not np.any(mask[r < r_min]), f"Found masked spike pixels inside core r < {r_min}"

    def test_corridor_width_monotonicity(self):
        """Wider corridor parameter must strictly include narrower corridor mask."""
        angles = get_theoretical_spike_angles(0.0)
        mask_narrow = create_geometric_spike_mask((101, 101), (50.0, 50.0), angles, spike_width_px=2.0)
        mask_wide = create_geometric_spike_mask((101, 101), (50.0, 50.0), angles, spike_width_px=5.0)
        # Wide mask must be a superset of narrow mask
        assert np.all(mask_wide[mask_narrow])
        assert np.sum(mask_wide) > np.sum(mask_narrow)


class TestAdversarialMoffatResidualExtraction:
    """Stress tests for Moffat core fitting and residual generation."""

    @pytest.mark.parametrize("noise_sigma", [0.5, 5.0, 25.0, 100.0, 500.0])
    def test_heavy_gaussian_noise_robustness(self, noise_sigma: float):
        np.random.seed(99)
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (200.0 / (1.0 + (r / 2.5)**2)**1.52).astype(np.float32)
        noisy = star + np.random.normal(0, noise_sigma, (sz, sz)).astype(np.float32)

        fitted_img, model = fit_moffat_model(noisy)
        assert fitted_img.shape == (sz, sz)
        assert fitted_img.dtype == np.float32
        assert np.all(np.isfinite(fitted_img))
        assert model is not None

    def test_saturated_core_plateau_with_dq(self):
        """Fit must ignore saturated core plateau when DQ mask flags it."""
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)

        star = (5000.0 / (1.0 + (r / 2.5)**2)**1.52).astype(np.float32)
        # Saturated plateau r <= 8.0 px
        dq = np.zeros((sz, sz), dtype=bool)
        dq[r <= 8.0] = True
        star[r <= 8.0] = -9999.0  # Corrupted unphysical core

        fitted_img, model = fit_moffat_model(star, dq_mask=dq, max_radius=35.0)
        assert model is not None
        # Peak amplitude must be positive and extrapolate beyond boundary value (~125) despite corrupted core
        assert model.amplitude.value > 150.0
        assert np.isfinite(fitted_img).all()

    def test_completely_negative_background_subtracted_stamp(self):
        """Stamp with negative fluxes (extreme over-subtraction) must not crash."""
        neg_stamp = np.full((51, 51), -15.0, dtype=np.float32)
        fitted_img, model = fit_moffat_model(neg_stamp)
        assert fitted_img.shape == (51, 51)
        assert np.all(np.isfinite(fitted_img))

    def test_stamp_dominated_by_nans(self):
        """Stamp with 90% NaNs must gracefully return fallback without crashing."""
        np.random.seed(42)
        nan_stamp = np.full((51, 51), np.nan, dtype=np.float32)
        # Only center 5x5 has values
        nan_stamp[23:28, 23:28] = 50.0
        fitted_img, model = fit_moffat_model(nan_stamp)
        assert fitted_img.shape == (51, 51)
        assert np.all(np.isfinite(fitted_img))


class TestAdversarialMorphologicalRidgeFilter:
    """Stress tests for directional morphological filtering on residuals."""

    def test_detects_spikes_across_various_angles(self):
        """True linear rays at different angles must be identified as morphological spikes."""
        sz = 151
        cx, cy = 75.0, 75.0

        for ang_deg in [0.0, 30.0, 75.0, 135.0, 220.0, 310.0]:
            data = np.zeros((sz, sz), dtype=np.float32)
            rad = np.radians(ang_deg)
            for d in range(10, 50):  # Span 40 px > min_length_px (15)
                px = int(round(cx + d * np.cos(rad)))
                py = int(round(cy + d * np.sin(rad)))
                data[py, px] = 50.0

            detected = detect_morphological_spikes(data, (cx, cy), min_length_px=15)
            # Center of the ray must be detected
            mid_x = int(round(cx + 25.0 * np.cos(rad)))
            mid_y = int(round(cy + 25.0 * np.sin(rad)))
            assert detected[mid_y, mid_x], f"Failed to detect spike at angle {ang_deg} deg"

    def test_rejects_compact_circular_and_elliptical_companions(self):
        """Companion stars must never be identified as morphological spikes."""
        sz = 151
        cx, cy = 75.0, 75.0
        grid_y, grid_x = np.indices((sz, sz))

        data = np.zeros((sz, sz), dtype=np.float32)
        # Circular companion at (110, 75)
        data += 200.0 * np.exp(-((grid_x - 110)**2 + (grid_y - 75)**2) / (2 * 1.5**2))
        # Elliptical companion at (75, 120)
        data += 150.0 * np.exp(-(((grid_x - 75)**2) / (2 * 3.0**2) + ((grid_y - 120)**2) / (2 * 1.5**2)))

        detected = detect_morphological_spikes(data.astype(np.float32), (cx, cy), min_length_px=15)
        assert not np.any(detected[grid_y > 100]), "Elliptical companion was incorrectly classified as spike!"
        assert not np.any(detected[grid_x > 95]), "Circular companion was incorrectly classified as spike!"

    def test_pure_noise_generates_zero_spurious_spikes(self):
        """Random noise with no real spikes must yield an empty mask (no false positives)."""
        np.random.seed(77)
        noise = np.random.normal(0, 1.0, (101, 101)).astype(np.float32)
        detected = detect_morphological_spikes(noise, (50.0, 50.0), threshold_sigma=3.0, min_length_px=15)
        assert not np.any(detected), f"Pure noise generated {np.sum(detected)} spurious spike pixels!"


class TestAdversarialDualPriorPreservationAndCrowdedFields:
    """Stress tests verifying dual-prior protection and contaminant masking invariants."""

    def test_crowded_field_masks_companions_while_preserving_spikes(self):
        """In a crowded field with 12 spikes and 10 companions, all off-spike companions are masked and spikes protected."""
        sz = 201
        cx, cy = 100.0, 100.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        pa = 65.0
        angles = get_theoretical_spike_angles(pa, detector_offset_deg=-9.70)

        # Central star
        star = (1200.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)

        # 12 diffraction spikes
        spike_pixels = []
        for a in angles:
            rad = np.radians(a)
            for dist in range(12, 85):
                px = int(round(cx + dist * np.cos(rad)))
                py = int(round(cy + dist * np.sin(rad)))
                star[py, px] += 120.0 / (1.0 + 0.04 * dist)
                spike_pixels.append((py, px))

        # Add 8 off-spike companion stars
        companions = [
            (145, 100), (60, 100), (100, 145), (100, 55),
            (135, 135), (65, 65), (135, 65), (65, 135)
        ]
        valid_off_spike_companions = []
        for nx, ny in companions:
            nth = np.degrees(np.arctan2(ny - cy, nx - cx)) % 360.0
            min_ang = np.min([np.abs((nth - a + 180) % 360 - 180) for a in angles])
            ndist = np.hypot(nx - cx, ny - cy)
            perp_dist = ndist * np.sin(np.radians(min_ang))
            if perp_dist > 6.0:  # clearly off-spike
                star += (250.0 * np.exp(-((gx - nx)**2 + (gy - ny)**2) / (2 * 1.5**2))).astype(np.float32)
                valid_off_spike_companions.append((nx, ny))

        # Background noise
        np.random.seed(55)
        star += np.random.normal(0, 1.0, (sz, sz)).astype(np.float32)

        cfg = SpikesConfig()
        final_mask, prot_area, res = mask_contaminants_with_spikes_protected(
            star, pa_aperture=pa, cfg=cfg, tier="medium"
        )

        # 1. Invariant: All valid off-spike companion stars must be masked
        assert len(valid_off_spike_companions) >= 4
        for nx, ny in valid_off_spike_companions:
            assert final_mask[ny, nx], f"Companion star at ({nx}, {ny}) was NOT masked!"
            assert not prot_area[ny, nx], f"Companion star at ({nx}, {ny}) was erroneously protected!"

        # 2. Invariant: Diffraction spikes must be protected and unmasked
        spikes_protected_count = 0
        for py, px in spike_pixels:
            if prot_area[py, px]:
                spikes_protected_count += 1
                assert not final_mask[py, px], f"Spike pixel at ({px}, {py}) was masked as contaminant!"
        assert spikes_protected_count > len(spike_pixels) * 0.95

    def test_strict_invariant_protected_pixels_never_in_contaminants(self):
        """Mathematical invariant: final_mask & protected_stellar_area == False (when DQ is clear)."""
        np.random.seed(1234)
        for _ in range(10):
            sz = 101
            cx, cy = 50.0, 50.0
            gy, gx = np.ogrid[:sz, :sz]
            r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
            star = (300.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
            # Random noise
            star += np.random.normal(0, 2.0, (sz, sz)).astype(np.float32)
            # Random companions
            for _ in range(5):
                rx, ry = np.random.randint(15, 85, size=2)
                star += (150.0 * np.exp(-((gx - rx)**2 + (gy - ry)**2) / (2 * 1.5**2))).astype(np.float32)

            rand_pa = np.random.uniform(-360.0, 720.0)
            final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
                star, dq_mask=None, pa_aperture=rand_pa, cfg=SpikesConfig()
            )

            # Strict Invariant: No protected pixel may ever be masked as a contaminant
            overlap = final_mask & prot_area
            assert not np.any(overlap), f"Invariant violated: {np.sum(overlap)} protected pixels were masked!"


class TestRealCommissioningDataAdversarialSpikeIntegrity:
    """Stress tests on actual simulated commissioning Level 2 ASDF data."""

    @pytest.fixture(scope="class")
    def real_wfi01_data(self):
        from romanepsf import loader, catalog
        import pandas as pd

        asdf_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf"
        cat_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv"

        l2 = loader.load_l2_image(asdf_path, calibrate=True)
        cat_df = pd.read_csv(cat_path, low_memory=False)
        ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
        cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
        cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
        proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
        tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
        return l2, tiered

    def test_real_bright_star_spikes_preserved(self, real_wfi01_data):
        """Verify that 6-fold spikes on real WFI01 bright star are strictly preserved."""
        from romanepsf import stamps

        l2, tiered = real_wfi01_data
        cfg = SpikesConfig()
        tier_stamps = stamps.process_star_stamps(l2, tiered, spikes_cfg=cfg)
        assert len(tier_stamps["bright"]) > 0

        st = tier_stamps["bright"][0]
        angles = get_theoretical_spike_angles(l2.pa_aperture, detector_offset_deg=-9.70)
        cx, cy = (st.size - 1) / 2.0, (st.size - 1) / 2.0

        # Sample spike pixels at radii 50, 100, 150, 200, 250, 300
        unmasked = 0
        total = 0
        for a in angles:
            rad = np.radians(a)
            for r_val in [50, 100, 150, 200, 250, 300]:
                px = int(round(cx + r_val * np.cos(rad)))
                py = int(round(cy + r_val * np.sin(rad)))
                total += 1
                if not st.mask[py, px]:
                    unmasked += 1

        preservation_rate = unmasked / total
        assert preservation_rate >= 0.95, f"Spike preservation rate {preservation_rate:.2%} below 95% threshold!"

    def test_faint_stars_core_preservation(self, real_wfi01_data):
        """Verify faint stars provide solid non-hollow cores with positive central peak."""
        from romanepsf import stamps

        l2, tiered = real_wfi01_data
        tier_stamps = stamps.process_star_stamps(l2, tiered)
        faint_stamps = tier_stamps["faint"]
        assert len(faint_stamps) > 0

        valid_cores = 0
        for st in faint_stamps:
            half = (st.size - 1) // 2
            core_flux = st.data[half, half]
            if not st.mask[half, half] and core_flux > 0:
                valid_cores += 1

        # At least 75% of faint stars must have unmasked positive core
        assert valid_cores >= len(faint_stamps) * 0.75
