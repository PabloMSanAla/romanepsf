"""
Unit tests for romanepsf.masking: diffraction spike geometry, morphological filtering,
dual-prior spike protection, and contaminant masking.
"""

import numpy as np
import pytest
from romanepsf.config import SpikesConfig, SpikesSection
from romanepsf.masking import (
    ROMAN_BASE_SPIKE_ANGLES_DEG,
    create_geometric_spike_mask,
    detect_morphological_spikes,
    fit_moffat_model,
    get_theoretical_spike_angles,
    mask_contaminants_with_spikes_protected,
)


class TestTheoreticalSpikeAngles:
    """Tests for 6-fold pupil geometry and spider rotation transformations."""

    def test_base_angles_constant(self):
        expected = [23.55, 55.29, 80.25, 118.65, 142.88, 178.07]
        assert len(ROMAN_BASE_SPIKE_ANGLES_DEG) == 6
        np.testing.assert_allclose(ROMAN_BASE_SPIKE_ANGLES_DEG, expected, atol=1e-3)

    def test_generates_12_rays(self):
        angles = get_theoretical_spike_angles(0.0)
        assert len(angles) == 12
        assert np.all((angles >= 0.0) & (angles < 360.0))

    def test_opposing_symmetry(self):
        angles = get_theoretical_spike_angles(-9.70)
        for ang in angles:
            opp = (ang + 180.0) % 360.0
            assert np.any(np.isclose(angles, opp, atol=1e-3))

    def test_detector_offset_rotation(self):
        angles = get_theoretical_spike_angles(-9.70)
        base = np.array(ROMAN_BASE_SPIKE_ANGLES_DEG)
        expected_base_rot = (base - 9.70) % 180.0
        angles_mod_180 = np.unique(np.round(angles % 180.0, 2))
        np.testing.assert_allclose(np.sort(angles_mod_180), np.sort(expected_base_rot), atol=0.05)

    def test_pa_aperture_and_detector_offset_combined(self):
        angles = get_theoretical_spike_angles(pa_offset_deg=30.0, detector_offset_deg=-9.70)
        assert len(angles) == 12
        expected_first = (23.55 + 30.0 - 9.70) % 360.0
        assert np.any(np.isclose(angles, expected_first, atol=1e-2))

    def test_angle_wrapping_extremes(self):
        ang_pos = get_theoretical_spike_angles(720.0)
        ang_zero = get_theoretical_spike_angles(0.0)
        ang_neg = get_theoretical_spike_angles(-720.0)
        np.testing.assert_allclose(ang_pos, ang_zero, atol=1e-3)
        np.testing.assert_allclose(ang_neg, ang_zero, atol=1e-3)

    def test_monotonic_sorting(self):
        angles = get_theoretical_spike_angles(45.0)
        diffs = np.diff(angles)
        assert np.all(diffs > 0.0)


class TestGeometricSpikeMask:
    """Tests for 2D geometric cone and corridor spike masks."""

    def test_mask_shape_and_dtype(self):
        angles = get_theoretical_spike_angles(-9.70)
        mask = create_geometric_spike_mask((101, 101), (50.0, 50.0), angles)
        assert mask.shape == (101, 101)
        assert mask.dtype == bool

    def test_core_remains_clear(self):
        angles = get_theoretical_spike_angles(-9.70)
        mask = create_geometric_spike_mask((101, 101), (50.0, 50.0), angles, radial_min=8.0)
        assert not mask[50, 50]
        # All pixels within r < 8.0 should be False
        gy, gx = np.ogrid[:101, :101]
        r = np.sqrt((gx - 50.0)**2 + (gy - 50.0)**2)
        assert not np.any(mask[r < 8.0])

    def test_covers_spike_rays(self):
        angles = get_theoretical_spike_angles(-9.70)
        mask = create_geometric_spike_mask((201, 201), (100.0, 100.0), angles, radial_min=5.0)
        for ang in angles:
            rad = np.radians(ang)
            px = int(round(100.0 + 40.0 * np.cos(rad)))
            py = int(round(100.0 + 40.0 * np.sin(rad)))
            assert mask[py, px]

    def test_off_spike_pixels_unmasked(self):
        # A single horizontal spike at 0 deg
        mask = create_geometric_spike_mask((101, 101), (50.0, 50.0), np.array([0.0, 180.0]))
        # (50, 80) is on spike; (80, 50) is perpendicular to spike
        assert mask[50, 80]
        assert not mask[80, 50]

    def test_rectangular_cutout(self):
        angles = get_theoretical_spike_angles(0.0)
        mask = create_geometric_spike_mask((81, 161), (80.0, 40.0), angles)
        assert mask.shape == (81, 161)


class TestMoffatFitting:
    """Tests for stellar core 2D Moffat fitting and residual calculation."""

    def test_fit_synthetic_moffat_core(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.52).astype(np.float32)
        fitted_img, model = fit_moffat_model(star)
        assert model is not None
        assert abs(model.amplitude.value - 300.0) < 30.0

    def test_fit_ignores_saturated_dq_pixels(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (500.0 / (1.0 + (r / 2.5)**2)**1.52).astype(np.float32)
        # Corrupt central 3x3 with unphysical saturated value
        star[39:42, 39:42] = -9999.0
        dq = np.zeros((sz, sz), dtype=bool)
        dq[39:42, 39:42] = True

        fitted_img, model = fit_moffat_model(star, dq_mask=dq)
        assert model is not None
        # Should recover positive peak amplitude despite corrupted core
        assert model.amplitude.value > 100.0

    def test_fit_fallback_on_all_nan(self):
        nan_img = np.full((51, 51), np.nan, dtype=np.float32)
        fitted_img, model = fit_moffat_model(nan_img)
        assert fitted_img.shape == (51, 51)
        assert model is None


class TestMorphologicalRidgeFilter:
    """Tests for continuous directional ridge detection and contaminant rejection."""

    def test_detects_radial_linear_spike(self):
        sz = 101
        data = np.zeros((sz, sz), dtype=np.float32)
        data[50, 60:90] = 40.0  # Spike length 30 px
        detected = detect_morphological_spikes(data, (50.0, 50.0), min_length_px=15)
        assert np.any(detected[50, 65:85])

    def test_rejects_compact_circular_star(self):
        sz = 101
        gy, gx = np.ogrid[:sz, :sz]
        blob = 100.0 * np.exp(-((gx - 75)**2 + (gy - 75)**2) / (2 * 1.5**2))
        detected = detect_morphological_spikes(blob.astype(np.float32), (50.0, 50.0), min_length_px=15)
        assert not np.any(detected)

    def test_rejects_subthreshold_short_line(self):
        sz = 101
        data = np.zeros((sz, sz), dtype=np.float32)
        data[50, 60:71] = 40.0  # Length 11 px (< 15 threshold)
        detected = detect_morphological_spikes(data, (50.0, 50.0), min_length_px=15)
        assert not np.any(detected)

    def test_flat_background_zero_variance_handled(self):
        flat = np.full((81, 81), 10.0, dtype=np.float32)
        detected = detect_morphological_spikes(flat, (40.0, 40.0))
        assert not np.any(detected)


class TestDualPriorProtectionFusion:
    """Tests for invariant protection and contaminant masking."""

    def test_strict_invariant_clean_star(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (400.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(star, dq_mask=None)
        # Core is protected
        assert np.all(prot_area[r <= 4.0])
        # Core is never masked as contaminant
        assert not np.any(final_mask[r <= 4.0])

    def test_masks_off_axis_companion_star(self):
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (400.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        # Companion star at (80, 20)
        companion = (150.0 * np.exp(-((gx - 80)**2 + (gy - 20)**2) / (2 * 1.5**2))).astype(np.float32)
        stamp = star + companion

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(stamp, dq_mask=None)
        # Companion star is masked
        assert final_mask[20, 80]
        # Star core is not masked
        assert not final_mask[50, 50]

    def test_protects_spike_from_masking(self):
        sz = 101
        cx, cy = 50.0, 50.0
        stamp = np.full((sz, sz), 1.8, dtype=np.float32)
        # Add spike along 13.85 deg
        rad = np.radians(13.85)
        for d in range(15, 45):
            px = int(round(cx + d * np.cos(rad)))
            py = int(round(cy + d * np.sin(rad)))
            stamp[py, px] += 30.0

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(stamp, pa_offset_deg=-9.70)
        test_px = int(round(cx + 30.0 * np.cos(rad)))
        test_py = int(round(cy + 30.0 * np.sin(rad)))
        assert prot_area[test_py, test_px]
        assert not final_mask[test_py, test_px]

    def test_propagates_dq_bad_pixels(self):
        stamp = np.ones((51, 51), dtype=np.float32)
        dq = np.zeros((51, 51), dtype=bool)
        dq[10, 10] = True
        final_mask, _, _ = mask_contaminants_with_spikes_protected(stamp, dq_mask=dq)
        assert final_mask[10, 10]

    def test_masks_nans(self):
        stamp = np.ones((51, 51), dtype=np.float32)
        stamp[15, 15] = np.nan
        final_mask, _, _ = mask_contaminants_with_spikes_protected(stamp)
        assert final_mask[15, 15]

    def test_halo_preservation_in_stellar_wings(self):
        """Verify legitimate stellar halo flux is not falsely masked as contaminants."""
        sz = 201
        cx, cy = 100.0, 100.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        # Realistic extended star with core + diffuse halo
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.2).astype(np.float32)

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            star, dq_mask=None, tier="medium"
        )
        # Check transition annulus [15, 45] px outside protected spike area
        wing_ann = (r >= 15.0) & (r <= 45.0) & (~prot_area)
        assert np.sum(wing_ann) > 500
        mask_frac = np.mean(final_mask[wing_ann])
        # Assert less than 5% of legitimate wing pixels are masked
        assert mask_frac < 0.05, f"Legitimate halo over-masked: {mask_frac * 100:.1f}% masked"

    def test_masks_off_axis_companion_in_outer_wing(self):
        """Verify off-axis companion star in the outer wing is detected while halo is preserved."""
        sz = 201
        cx, cy = 100.0, 100.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.2).astype(np.float32)

        # Off-axis companion star at r = 25 px (angle = 40 deg, between spikes)
        comp_x = 100.0 + 25.0 * np.cos(np.radians(40.0))
        comp_y = 100.0 + 25.0 * np.sin(np.radians(40.0))
        comp_r = np.hypot(gx - comp_x, gy - comp_y)
        companion = (30.0 * np.exp(-comp_r**2 / (2 * 1.5**2))).astype(np.float32)
        stamp = star + companion

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            stamp, dq_mask=None, pa_offset_deg=-9.70, tier="medium"
        )
        # Companion peak must be masked
        px_x, px_y = int(round(comp_x)), int(round(comp_y))
        assert final_mask[px_y, px_x], "Companion star was not masked!"
        # Central star core must not be masked
        assert not final_mask[100, 100], "Target star core was falsely masked!"
        # Surrounding clean halo must be preserved
        clean_wing = (r >= 15.0) & (r <= 45.0) & (~prot_area) & (comp_r > 8.0)
        assert np.mean(final_mask[clean_wing]) < 0.05


class TestInterfaceContract:
    """Tests verifying compliance with authoritative pipeline interface contract."""

    def test_interface_contract_with_spikes_config(self):
        cfg = SpikesConfig()
        stamp = np.ones((81, 81), dtype=np.float32)
        final_mask, prot_area, res = mask_contaminants_with_spikes_protected(
            stamp, dq_mask=None, pa_aperture=30.0, cfg=cfg
        )
        assert final_mask.shape == (81, 81)
        assert prot_area.shape == (81, 81)
        assert res.shape == (81, 81)
        assert final_mask.dtype == bool
        assert prot_area.dtype == bool

    def test_tier_based_core_protection(self):
        cfg = SpikesConfig()
        stamp = np.ones((81, 81), dtype=np.float32)
        _, prot_faint, _ = mask_contaminants_with_spikes_protected(stamp, cfg=cfg, tier="faint")
        _, prot_bright, _ = mask_contaminants_with_spikes_protected(stamp, cfg=cfg, tier="bright")
        # Bright core protection (6.0 px) covers more pixels than faint (3.0 px)
        assert np.sum(prot_bright) > np.sum(prot_faint)


class TestGaiaCompanionMasking:
    """Tests for circular companion aperture masking using get_psf_extension_moffat."""

    def test_circular_aperture_radius_calculation(self):
        from romanepsf.masking import mask_gaia_companion_stars
        from romanepsf.catalog import get_psf_extension_moffat

        sz = 101
        cx, cy = 50.0, 50.0
        mag = 18.0
        depth = 28.0
        pixel_scale = 0.11

        expected_rad_arcsec = get_psf_extension_moffat(mag, depth=depth)
        expected_rad_px = expected_rad_arcsec / pixel_scale

        # Companion star at (75, 50)
        companions = [(75.0, 50.0, mag)]
        comp_mask = mask_gaia_companion_stars(
            (sz, sz), (cx, cy), companions, pixel_scale=pixel_scale, depth=depth
        )

        assert comp_mask.shape == (sz, sz)
        assert comp_mask[50, 75], "Companion center must be masked"
        assert not comp_mask[50, 50], "Target center must NOT be masked"

        # Check edge of circular aperture
        gy, gx = np.ogrid[:sz, :sz]
        r_target = np.hypot(gx - cx, gy - cy)
        r_comp = np.hypot(gx - 75.0, gy - 50.0)
        # Inside aperture outside target core must be masked
        in_comp_aperture = (r_comp <= (expected_rad_px - 1.0)) & (r_target > 4.0)
        assert np.all(comp_mask[in_comp_aperture])
        # Far outside must NOT be masked
        assert not np.any(comp_mask[r_comp > (expected_rad_px + 2.0)])

    def test_dataframe_with_detector_coordinates(self):
        import pandas as pd
        from romanepsf.masking import mask_gaia_companion_stars

        sz = 101
        cx, cy = 50.0, 50.0  # Stamp center
        target_det_x, target_det_y = 1200.0, 1500.0

        # DataFrame with target and companion in detector coordinates
        df = pd.DataFrame([
            {"x": 1200.0, "y": 1500.0, "mag_lambda": 15.0},  # Target itself
            {"x": 1225.0, "y": 1500.0, "mag_lambda": 19.0},  # Companion dx = +25 px
        ])

        comp_mask = mask_gaia_companion_stars(
            (sz, sz),
            (cx, cy),
            df,
            target_center_xy=(target_det_x, target_det_y),
            pixel_scale=0.11,
        )

        # Target center must NOT be masked
        assert not comp_mask[50, 50]
        # Companion at dx = +25 -> stamp coord (75, 50) must be masked
        assert comp_mask[50, 75]

    def test_companion_mask_included_in_pipeline(self):
        import pandas as pd

        sz = 101
        cx, cy = 50.0, 50.0
        stamp = np.ones((sz, sz), dtype=np.float32) * 5.0
        # Add target star
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        stamp += (100.0 / (1.0 + (r / 2.0)**2)**1.5).astype(np.float32)

        # Companion star at (75, 50)
        companions = pd.DataFrame([
            {"x": 500.0, "y": 500.0, "mag_lambda": 16.0},  # Target
            {"x": 525.0, "y": 500.0, "mag_lambda": 18.0},  # Companion
        ])

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            stamp,
            dq_mask=None,
            pa_offset_deg=-9.70,
            companion_stars=companions,
            target_center_xy=(500.0, 500.0),
        )

        # Target core is preserved
        assert not final_mask[50, 50]
        # Companion star is masked
        assert final_mask[50, 75]


class TestUnsharpMaskResidual:
    """Tests for normalized Gaussian unsharp masking residual computation."""

    def test_isolates_compact_point_source(self):
        from romanepsf.masking import compute_unsharp_mask_residual

        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        # Broad smooth halo
        smooth_halo = (200.0 / (1.0 + (r / 10.0)**2)).astype(np.float32)
        # Compact companion point source at (60, 40)
        comp_r = np.hypot(gx - 60.0, gy - 40.0)
        compact_source = (50.0 * np.exp(-comp_r**2 / (2 * 1.5**2))).astype(np.float32)
        stamp = smooth_halo + compact_source

        res = compute_unsharp_mask_residual(stamp, sigma=7.0)

        # Unsharp residual should be strongly positive at the compact companion
        assert res[40, 60] > 20.0
        # In the smooth halo far from core (e.g. radius 25 px away from companion), residual is near zero
        assert abs(res[40, 15]) < 5.0

    def test_handles_nan_and_dq_mask(self):
        from romanepsf.masking import compute_unsharp_mask_residual

        stamp = np.ones((51, 51), dtype=np.float32) * 10.0
        stamp[25, 25] = np.nan
        dq = np.zeros((51, 51), dtype=bool)
        dq[10, 10] = True

        res = compute_unsharp_mask_residual(stamp, sigma=3.0, dq_mask=dq)
        assert np.isnan(res[25, 25])
        assert np.isfinite(res[25, 24])
        # Background is flat, so finite residuals should be virtually 0
        np.testing.assert_allclose(res[np.isfinite(res)], 0.0, atol=1e-4)


class TestRadialHoughTransform:
    """Tests for Star-Centered Rolling Hough Transform spike detection and masking."""

    def test_recovers_synthetic_radial_spikes(self):
        from romanepsf.masking import detect_spikes_rht, create_rht_spike_mask

        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        dx = gx - cx
        dy = gy - cy
        r = np.hypot(dx, dy)

        # Inject 4 linear spikes at 30 deg (+210 deg) and 120 deg (+300 deg)
        synth_sharp = np.zeros((sz, sz), dtype=np.float32)
        test_angles = [30.0, 120.0]
        for ang in test_angles:
            ang_rad = np.radians(ang)
            d_perp = np.abs(-dx * np.sin(ang_rad) + dy * np.cos(ang_rad))
            synth_sharp += (20.0 * np.exp(-d_perp**2 / (2 * 1.0**2)) * (r >= 6.0)).astype(np.float32)

        det_angles, angles_grid, rht_power = detect_spikes_rht(
            synth_sharp,
            (cx, cy),
            r_min=8.0,
            r_max=45.0,
            symmetric_fold=True,
        )

        # Must recover angles near 30, 120, 210, 300 deg
        for expected in [30.0, 120.0, 210.0, 300.0]:
            diffs = np.abs((det_angles - expected + 180.0) % 360.0 - 180.0)
            assert np.min(diffs) <= 1.5, f"Expected angle {expected} not detected by RHT"

        # Check mask creation
        spike_mask = create_rht_spike_mask((sz, sz), (cx, cy), det_angles, r_min=8.0, r_max=45.0)
        assert spike_mask.shape == (sz, sz)
        # Center core should remain clear in spike corridor
        assert not spike_mask[50, 50]
        # Pixels along the 30 deg line should be masked
        px_30 = (int(round(50 + 25 * np.sin(np.radians(30)))), int(round(50 + 25 * np.cos(np.radians(30)))))
        assert spike_mask[px_30]



