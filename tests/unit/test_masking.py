"""
Unit tests for romanepsf.masking: diffraction spike geometry, morphological filtering,
dual-prior spike protection, and contaminant masking.
"""

import numpy as np
import pandas as pd
import pytest
from romanepsf.config import SpikesConfig, SpikesSection
from romanepsf.masking import (
    ROMAN_BASE_SPIKE_ANGLES_DEG,
    build_2d_radial_profile_model,
    create_geometric_spike_mask,
    detect_morphological_spikes,
    detect_spike_peaks_from_profile,
    fit_moffat_model,
    fit_sersic_model,
    fit_sersic_astrophot,
    fit_sersic_astropy,
    fit_sersic_moffat_model,
    fit_superback_model,
    fit_stpsf_model,
    fit_stellar_model,
    get_theoretical_spike_angles,
    mask_contaminants_with_spikes_protected,
    segment_connected_components,
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

    def test_fit_with_masked_central_core(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.52).astype(np.float32)
        # Fit with core r < 5.0 masked
        fitted_img, model = fit_moffat_model(star, min_radius=5.0)
        assert model is not None
        assert model.amplitude.value > 100.0
        assert 0.5 <= model.gamma.value <= 30.0

    def test_fit_masks_neighbor_star(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.52).astype(np.float32)
        # Add neighbor star at (65, 40)
        neighbor = (100.0 * np.exp(-((gx - 65)**2 + (gy - 40)**2) / 8.0)).astype(np.float32)
        stamp = star + neighbor
        neighbor_mask = np.hypot(gx - 65, gy - 40) <= 6.0

        fitted_img, model = fit_moffat_model(stamp, mask=neighbor_mask)
        assert model is not None
        assert abs(model.amplitude.value - 300.0) < 50.0


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


class TestSuperbackAndStpsfFitting:
    """Tests for SUPERBACK (rosalia) and STPSF physical PSF fitting."""

    def test_fit_superback_model(self):
        pytest.importorskip("bottleneck")
        sz = 81
        stamp = np.full((sz, sz), 2.0, dtype=np.float32)
        stamp[40, 40] = 500.0
        model_img, amp = fit_superback_model(
            stamp,
            detector="WFI01",
            position=(2048.0, 2048.0),
            bandpass="F146",
            num_anchors=2,
        )
        assert model_img.shape == (sz, sz)
        assert amp > 0
        assert np.all(np.isfinite(model_img))

    def test_fit_stpsf_model(self):
        sz = 81
        stamp = np.full((sz, sz), 2.0, dtype=np.float32)
        stamp[40, 40] = 500.0
        model_img, amp = fit_stpsf_model(
            stamp,
            detector="WFI01",
            position=(2048.0, 2048.0),
            bandpass="F146",
            nlambda=1,
        )
        assert model_img.shape == (sz, sz)
        assert amp > 0
        assert np.all(np.isfinite(model_img))

    def test_fit_stellar_model_dispatch_tiers(self):
        pytest.importorskip("bottleneck")
        sz = 81
        stamp = np.full((sz, sz), 2.0, dtype=np.float32)
        stamp[40, 40] = 500.0

        # Bright tier -> SUPERBACK
        bright_img, b_amp = fit_stellar_model(
            stamp, tier="bright", detector="WFI01", position=(2048.0, 2048.0)
        )
        assert bright_img.shape == (sz, sz)
        assert b_amp > 0

        # Medium tier -> STPSF
        med_img, m_amp = fit_stellar_model(
            stamp, tier="medium", detector="WFI01", position=(2048.0, 2048.0)
        )
        assert med_img.shape == (sz, sz)
        assert m_amp > 0

        # Faint tier -> Skipped (zeros)
        faint_img, f_amp = fit_stellar_model(stamp, tier="faint")
        assert np.all(faint_img == 0.0)
        assert f_amp == 0.0

    def test_mask_contaminants_with_physical_models(self):
        sz = 81
        stamp = np.full((sz, sz), 1.0, dtype=np.float32)
        stamp[40, 40] = 1000.0
        # Add off-axis contaminant
        stamp[25, 25] = 200.0

        final_mask, prot_area, res = mask_contaminants_with_spikes_protected(
            stamp,
            tier="bright",
            detector="WFI01",
            target_center_xy=(2048.0, 2048.0),
        )
        assert final_mask.shape == (sz, sz)
        assert prot_area.shape == (sz, sz)
        assert res.shape == (sz, sz)
        # Contaminant should be flagged
        assert final_mask[25, 25]
        # Core is protected
        assert not final_mask[40, 40]


class TestTwoIterationMoffatFitting:
    """Tests for 2-iteration Moffat fitting weighted by var_poisson with updated mask."""

    def test_two_iteration_moffat_with_var_poisson(self):
        sz = 81
        cy, cx = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)

        # True Moffat profile
        moffat_true = 500.0 / (1.0 + (r / 3.0)**2)**1.5 + 2.0
        stamp = moffat_true.copy().astype(np.float32)

        # Add off-axis contaminant
        stamp[20, 20] = 150.0

        # Construct Poisson noise variance array
        var_poisson = np.maximum(stamp, 0.01).astype(np.float32)

        # 2-iteration fit
        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            stamp,
            tier="bright",
            method="moffat",
            var_poisson=var_poisson,
            n_iterations=2,
        )

        assert final_mask.shape == (sz, sz)
        assert prot_area.shape == (sz, sz)
        assert residual.shape == (sz, sz)

        # Off-axis contaminant detected and masked
        assert final_mask[20, 20]
        # Core is strictly protected
        assert not final_mask[40, 40]
        assert prot_area[40, 40]

    def test_faint_tier_bypasses_moffat(self):
        sz = 81
        stamp = np.full((sz, sz), 5.0, dtype=np.float32)
        stamp[40, 40] = 50.0
        stamp[20, 20] = 100.0  # contaminant

        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            stamp,
            tier="faint",
            method="moffat",
        )

        # Faint stars must not have contaminant masking applied
        assert not final_mask[20, 20]
        assert np.array_equal(residual, stamp)


class TestSersicAndCompoundFitting:
    """Tests for Sérsic and compound Sérsic + Moffat profile fitting."""

    def test_fit_sersic_astropy(self):
        sz = 61
        cy, cx = 30.0, 30.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        # Synthetic Sersic (n=2, Re=4)
        bn = 1.9992 * 2.0 - 0.3271
        synthetic = (400.0 * np.exp(-bn * ((r / 4.0)**(1/2.0) - 1.0)) + 3.0).astype(np.float32)

        fitted_img, model = fit_sersic_astropy(synthetic)
        assert fitted_img.shape == (sz, sz)
        assert model is not None
        assert np.all(np.isfinite(fitted_img))
        assert abs(model.amplitude.value - 400.0) < 100.0

    def test_fit_sersic_astrophot(self):
        pytest.importorskip("astrophot")
        sz = 61
        cy, cx = 30.0, 30.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        bn = 1.9992 * 2.0 - 0.3271
        synthetic = (400.0 * np.exp(-bn * ((r / 4.0)**(1/2.0) - 1.0)) + 3.0).astype(np.float32)

        fitted_img, model = fit_sersic_astrophot(synthetic)
        assert fitted_img.shape == (sz, sz)
        assert model is not None
        assert np.all(np.isfinite(fitted_img))

    def test_fit_sersic_moffat_compound(self):
        sz = 61
        cy, cx = 30.0, 30.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        # Combined Moffat + Sersic
        moffat = 300.0 / (1.0 + (r / 2.5)**2)**1.5
        bn = 1.9992 * 2.0 - 0.3271
        sersic = 50.0 * np.exp(-bn * ((r / 10.0)**(1/2.0) - 1.0))
        synthetic = (moffat + sersic + 2.0).astype(np.float32)

        fitted_img, model = fit_sersic_moffat_model(synthetic)
        assert fitted_img.shape == (sz, sz)
        assert model is not None
        assert np.all(np.isfinite(fitted_img))

    def test_fit_stellar_model_sersic_dispatch(self):
        sz = 61
        stamp = np.full((sz, sz), 2.0, dtype=np.float32)
        stamp[30, 30] = 500.0

        sersic_img, s_model = fit_stellar_model(stamp, method="sersic")
        assert sersic_img.shape == (sz, sz)
        assert np.all(np.isfinite(sersic_img))

        comp_img, c_model = fit_stellar_model(stamp, method="sersic_moffat")
        assert comp_img.shape == (sz, sz)
        assert np.all(np.isfinite(comp_img))

    def test_mask_contaminants_with_sersic(self):
        sz = 81
        cy, cx = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        bn = 1.9992 * 2.0 - 0.3271
        synthetic = (400.0 * np.exp(-bn * ((r / 4.0)**(1/2.0) - 1.0)) + 3.0).astype(np.float32)
        # Contaminant off-axis
        synthetic[20, 20] = 200.0

        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            synthetic,
            tier="bright",
            method="sersic",
            n_iterations=2,
        )
        assert final_mask.shape == (sz, sz)
        assert final_mask[20, 20]
        assert not final_mask[40, 40]
        assert prot_area[40, 40]


class TestRadialProfileMaskingAndConnectedComponents:
    """Tests for 2D radial profile model masking, Gaia companion stars, and connected components core protection."""

    def test_build_2d_radial_profile_model_smooth(self):
        sz = 81
        cx, cy = 40.0, 40.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        star = (250.0 / (1.0 + (r / 2.0)**2)**1.1).astype(np.float32)

        model_2d, residual, r_map, std_2d = build_2d_radial_profile_model(
            star, (cx, cy), growth_rate=1.03
        )
        assert model_2d.shape == (sz, sz)
        assert residual.shape == (sz, sz)
        assert r_map.shape == (sz, sz)
        assert std_2d.shape == (sz, sz)
        assert np.all(np.isfinite(model_2d))
        # Smooth star residual should be close to zero
        assert np.nanmean(np.abs(residual[r > 5.0])) < 1.0

    def test_connected_components_eliminates_core_overlap_only(self):
        sz = 61
        cand_mask = np.zeros((sz, sz), dtype=bool)
        # Component 1: touching core (cx=30, cy=30)
        cand_mask[30, 27:35] = True
        # Component 2: isolated companion at (10, 10)
        cand_mask[9:12, 9:12] = True

        gy, gx = np.ogrid[:sz, :sz]
        r_map = np.hypot(gx - 30.0, gy - 30.0)
        core_region = (r_map <= 5.0)

        num_labels, labels = segment_connected_components(cand_mask)
        assert num_labels >= 2
        overlap_ids = np.unique(labels[core_region])
        overlap_ids = overlap_ids[overlap_ids > 0]
        assert len(overlap_ids) > 0

        # Remove overlapping IDs
        cand_mask[np.isin(labels, overlap_ids)] = False
        # Component 1 removed, Component 2 preserved
        assert not np.any(cand_mask[30, 27:35])
        assert np.all(cand_mask[9:12, 9:12])

    def test_radial_profile_masking_with_gaia_companion_and_core_protection(self):
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.2).astype(np.float32)

        # Off-axis companion star at (25, 25)
        comp_r = np.hypot(gx - 25.0, gy - 25.0)
        companion = (40.0 * np.exp(-comp_r**2 / (2 * 1.5**2))).astype(np.float32)
        stamp = star + companion

        # Synthetic Gaia companion table
        gaia_df = pd.DataFrame([{
            "source_id": 999001,
            "mag_lambda": 15.0,
            "x": 25.0,
            "y": 25.0,
        }])

        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            stamp,
            tier="medium",
            method="radial_profile",
            companion_stars=gaia_df,
            target_center_xy=(cx, cy),
        )

        assert final_mask.shape == (sz, sz)
        # Companion star must be masked
        assert final_mask[25, 25]
        # Primary central core must NOT be masked
        assert not final_mask[50, 50]
        # Core region preserved
        assert np.all(~final_mask[r <= 3.0])


class TestDetectSpikePeaksFromProfile:
    """Unit tests for empirical spike detection on the intensity vs theta profile."""

    def test_detect_12_primary_and_secondary_peaks(self):
        """Verify that 12 primary peaks and prominent secondary peaks are detected."""
        angles = np.linspace(0.5, 359.5, 360)
        # Background with small noise
        flx = np.random.RandomState(42).randn(360) * 0.02

        # 12 primary spike angles (Roman 6 opposing pairs)
        prim_true = np.array([13, 49, 74, 111, 134, 168, 193, 229, 254, 291, 314, 348])
        for a in prim_true:
            flx[a] += 2.5

        # 4 secondary peaks
        sec_true = np.array([25, 80, 205, 260])
        for a in sec_true:
            flx[a] += 0.5

        prim_detected, sec_detected = detect_spike_peaks_from_profile(
            bin_centers=angles,
            profile_flx=flx,
            n_primary=12,
            min_distance_deg=5.0,
        )

        assert len(prim_detected) == 12
        # Verify detected primary angles match true injected angles within bin resolution (1 deg)
        for true_a in prim_true:
            assert np.any(np.isclose(prim_detected, angles[true_a], atol=1.5))

        # Verify secondary peaks detected
        assert len(sec_detected) >= 2
        for true_s in sec_true:
            assert np.any(np.isclose(sec_detected, angles[true_s], atol=1.5))

    def test_empty_or_nan_profile_handled_gracefully(self):
        """Verify empty and all-NaN inputs return empty arrays without crashing."""
        p_emp, s_emp = detect_spike_peaks_from_profile(np.array([]), np.array([]))
        assert len(p_emp) == 0 and len(s_emp) == 0

        p_nan, s_nan = detect_spike_peaks_from_profile(np.linspace(0.5, 359.5, 360), np.full(360, np.nan))
        assert len(p_nan) == 0 and len(s_nan) == 0

    def test_mask_contaminants_spike_details_contains_detected_peaks(self):
        """Verify mask_contaminants_with_spikes_protected returns profile peak details."""
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        stamp = (100.0 * np.exp(-r**2 / (2 * 2.0**2))).astype(np.float32)

        # Inject 12 spike rays
        angles = np.radians([15, 50, 75, 110, 135, 170, 195, 230, 255, 290, 315, 350])
        for ang in angles:
            for dist in range(6, 45):
                px = int(round(cx + dist * np.cos(ang)))
                py = int(round(cy + dist * np.sin(ang)))
                if 0 <= px < sz and 0 <= py < sz:
                    stamp[py, px] += 15.0

        mask, prot, res, details = mask_contaminants_with_spikes_protected(
            stamp,
            tier="bright",
            method="radial_profile",
            return_spike_details=True,
        )

        assert "primary_spike_angles" in details
        assert "secondary_spike_angles" in details
        assert len(details["primary_spike_angles"]) > 0
        assert "corrected_spike_mask" in details
        assert np.any(details["corrected_spike_mask"])






