"""
Adversarial Stress Test Suite for Roman Extended PSF (ePSF) Validation Pipeline.

Challenger M4.1 — Empirical Adversarial Verification:
1. Saturated core stars: DQ mask handling, scale factor fitting resilience, core residual bias exclusion.
2. Extreme Poisson/Gaussian noise, faint stars near background limit, negative or zero flux estimates.
3. NaNs, Infs, or negative values in input data, error, and model arrays.
4. Off-center stars near stamp boundaries, coordinate shifts outside boundaries, non-square and tiny stamps.
5. Pathological aperture position angles (0°, 90°, 180°, 359.9°, 360°, negative, multi-revolution, 0/360 wrap-around).
6. Division-by-zero guards in chi2_nu, mu_frac, and fractional residuals F.
7. Multi-extension FITS serialization roundtrip and JSON validation summary integrity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np
import pytest
from scipy.ndimage import shift
from astropy.io import fits

from romanepsf.validation import (
    StarResidualResult,
    RadialMetrics,
    ValidationResults,
    compute_spike_ray_mask,
    fit_star_to_model,
    compute_radial_residual_metrics,
    evaluate_epsf_validation,
)
from romanepsf.stamps import StellarStamp
from romanepsf.masking import get_theoretical_spike_angles


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def synthetic_epsf_model() -> np.ndarray:
    """Create a realistic unit-flux normalized 1025x1025 extended PSF canvas."""
    sz = 1025
    canvas = np.zeros((sz, sz), dtype=np.float32)
    c = sz // 2
    gy, gx = np.indices((sz, sz))
    r = np.hypot(gx - c, gy - c)

    # Core + Moffat-like wings
    core = np.exp(-0.5 * (r / 2.5)**2)
    wings = 1.0 / (1.0 + (r / 6.0)**2.5)
    canvas = (0.75 * core + 0.25 * wings).astype(np.float32)

    # Add 12 diffraction spikes matching Roman geometry
    angles = get_theoretical_spike_angles(pa_offset_deg=-110.0, detector_offset_deg=-9.70)
    theta = (np.degrees(np.arctan2(gy - c, gx - c)) + 360.0) % 360.0
    for ang in angles:
        diff = np.abs(theta - ang)
        diff = np.minimum(diff, 360.0 - diff)
        spike_strip = (diff <= 1.0) & (r >= 5.0)
        canvas[spike_strip] += 0.05 / (1.0 + r[spike_strip] / 10.0)

    canvas /= float(np.sum(canvas))
    return canvas.astype(np.float32)


# ==============================================================================
# 1. Saturated Core Stars Stress Tests
# ==============================================================================

class TestSaturatedCoreStress:
    """Stress tests for saturated core handling, scale factor fitting, and metric bias exclusion."""

    def test_saturated_bright_star_scale_factor_resilience(self, synthetic_epsf_model):
        """Verify saturated core pixels do not distort linear flux scale factor fitting."""
        sz = 101
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]

        true_flux = 500000.0
        obs = (true_flux * crop).astype(np.float32)

        # Apply flat saturation plateau in the core (r < 8 px)
        gy, gx = np.indices((sz, sz))
        r = np.hypot(gx - half, gy - half)
        sat_mask = r < 8.0
        obs[sat_mask] = 12000.0  # severely truncated saturated plateau

        stamp = StellarStamp(
            source_id="sat_bright_001",
            tier="bright",
            mag=8.5,
            data=obs,
            mask=sat_mask,
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=False)

        # Scale factor must match true flux within 2% despite severely saturated core
        assert np.isclose(res.flux_scale, true_flux, rtol=0.02), (
            f"Fitted flux scale {res.flux_scale} distorted by saturated core; expected {true_flux}"
        )

    def test_saturated_bright_star_unmasked_core_exclusion(self, synthetic_epsf_model):
        """Verify bright star fitting zone inherently excludes r < 10 px even if unmasked in mask."""
        sz = 101
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]

        true_flux = 200000.0
        obs = (true_flux * crop).astype(np.float32)

        # Severely corrupt core pixels without marking them in mask
        gy, gx = np.indices((sz, sz))
        r = np.hypot(gx - half, gy - half)
        obs[r < 8.0] = 99999.0  # artificial huge spike in core

        # mask is entirely False
        stamp = StellarStamp(
            source_id="unmasked_sat_bright",
            tier="bright",
            mag=9.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=False)

        # Because tier='bright', fit_zone is [10, 45] px, so corrupted core is excluded
        assert np.isclose(res.flux_scale, true_flux, rtol=0.02)

    def test_saturated_core_residual_metrics_exclusion(self, synthetic_epsf_model):
        """Verify core metrics strictly exclude masked saturated pixels and do not bias mu_frac."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]
        obs = (50000.0 * crop).astype(np.float32)

        gy, gx = np.indices((sz, sz))
        r = np.hypot(gx - half, gy - half)

        # Mask innermost 4 pixels and inject 1e6 into them
        sat_mask = r < 4.0
        obs[sat_mask] = 1_000_000.0

        stamp = StellarStamp(
            source_id="sat_core_metrics",
            tier="bright",
            mag=10.0,
            data=obs,
            mask=sat_mask,
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=False)
        core_stats = res.radial_metrics.core

        # Total unmasked pixels in core (4 <= r < 10) must be positive
        assert core_stats["n_pix"] > 0
        # The 1e6 saturated values must NOT contaminate mu_frac
        assert abs(core_stats["mu_frac"]) < 0.05
        assert core_stats["status"] == "PASS"

    def test_fully_saturated_core_handling(self, synthetic_epsf_model):
        """Verify 100% saturated core (all r < 10 px masked) handles cleanly without NaN or crash."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]
        obs = (50000.0 * crop).astype(np.float32)

        gy, gx = np.indices((sz, sz))
        r = np.hypot(gx - half, gy - half)
        sat_mask = r < 10.0  # 100% of core masked
        obs[sat_mask] = 1_000_000.0

        stamp = StellarStamp(
            source_id="fully_sat_core",
            tier="bright",
            mag=9.5,
            data=obs,
            mask=sat_mask,
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=False)
        core_stats = res.radial_metrics.core

        assert core_stats["n_pix"] == 0
        assert core_stats["mu_frac"] == 0.0
        assert core_stats["status"] == "PASS"
        assert np.isfinite(res.chi2_nu)

    def test_medium_star_saturated_core_guard(self, synthetic_epsf_model):
        """Verify medium star with core saturation at r < 3 px fits cleanly in [3, 25] px."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]

        true_flux = 100000.0
        obs = (true_flux * crop).astype(np.float32)

        gy, gx = np.indices((sz, sz))
        r = np.hypot(gx - half, gy - half)
        sat_mask = r < 3.0
        obs[sat_mask] = 5000.0  # saturated core

        stamp = StellarStamp(
            source_id="med_sat_01",
            tier="medium",
            mag=11.5,
            data=obs,
            mask=sat_mask,
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=False)
        assert np.isclose(res.flux_scale, true_flux, rtol=0.03)

    def test_dq_bitmask_coercion_to_boolean_mask(self, synthetic_epsf_model):
        """Verify passing uint8/int DQ bitmask as mask is safely coerced to boolean."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]
        obs = (20000.0 * crop).astype(np.float32)

        # Integer DQ mask where 2=SATURATED, 1024=JUMP_DET, 0=GOOD
        dq_int = np.zeros((sz, sz), dtype=np.uint16)
        dq_int[40, 40] = 2
        dq_int[10, 10] = 1024

        stamp = StellarStamp(
            source_id="dq_coercion",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=dq_int > 0,  # coerced to bool
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)
        assert res.mask[40, 40] == True
        assert res.mask[10, 10] == True
        assert res.mask[20, 20] == False


# ==============================================================================
# 2. Extreme Noise, Low SNR & Negative Flux Stress Tests
# ==============================================================================

class TestExtremeNoiseAndFluxStress:
    """Stress tests on low-SNR regimes, extreme noise distributions, and pathological flux levels."""

    def test_extreme_low_snr_poisson_gaussian_noise(self, synthetic_epsf_model):
        """Verify fitting on low SNR (SNR ~ 0.1) does not diverge and produces finite parameters."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]

        # Weak star peak = 1.0, noise sigma = 20.0 (SNR = 0.05)
        star = (100.0 * crop).astype(np.float32)
        rng = np.random.RandomState(42)
        noise = rng.normal(0.0, 20.0, (sz, sz)).astype(np.float32)
        obs = star + noise

        stamp = StellarStamp(
            source_id="low_snr_01",
            tier="faint",
            mag=19.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=20.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=True)

        assert np.isfinite(res.flux_scale)
        assert res.flux_scale >= 0.0
        assert np.isfinite(res.chi2_nu)
        assert np.all(np.isfinite(res.residual))
        assert np.all(np.isfinite(res.fractional_residual))

    def test_negative_flux_over_subtracted_stamp(self, synthetic_epsf_model):
        """Verify negative flux star clamps flux_scale to 0.0 and computes finite residuals."""
        sz = 81
        half = sz // 2
        obs_neg = np.full((sz, sz), -50.0, dtype=np.float32)

        stamp = StellarStamp(
            source_id="neg_flux_01",
            tier="faint",
            mag=20.0,
            data=obs_neg,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=5.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)

        assert res.flux_scale == 0.0
        assert np.all(np.isfinite(res.residual))
        assert np.all(np.isfinite(res.normalized_residual))
        assert np.all(np.isfinite(res.fractional_residual))

    def test_identically_zero_flux_stamp(self, synthetic_epsf_model):
        """Verify identically zero flux stamp produces flux_scale == 0.0 without errors."""
        sz = 81
        half = sz // 2
        obs_zero = np.zeros((sz, sz), dtype=np.float32)

        stamp = StellarStamp(
            source_id="zero_flux_01",
            tier="faint",
            mag=22.0,
            data=obs_zero,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)

        assert res.flux_scale == 0.0
        assert np.allclose(res.model, 0.0)
        assert np.allclose(res.residual, 0.0)
        assert np.allclose(res.fractional_residual, 0.0)
        assert np.isfinite(res.chi2_nu)

    def test_very_faint_star_near_detection_limit(self, synthetic_epsf_model):
        """Verify faint star near detection limit (flux=1.0) converges smoothly."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]

        obs = (1.0 * crop).astype(np.float32)
        stamp = StellarStamp(
            source_id="detection_limit_01",
            tier="faint",
            mag=21.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=0.01,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=False)
        assert np.isclose(res.flux_scale, 1.0, rtol=0.01)

    def test_astronomical_flux_star_no_overflow(self, synthetic_epsf_model):
        """Verify very bright star (10^9 counts) does not overflow in float32 arithmetic."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]

        huge_flux = 1e9
        obs = (huge_flux * crop).astype(np.float32)
        stamp = StellarStamp(
            source_id="huge_flux_01",
            tier="bright",
            mag=4.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=10.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=False)
        assert np.isclose(res.flux_scale, huge_flux, rtol=0.02)
        assert np.all(np.isfinite(res.residual))
        assert np.all(np.isfinite(res.normalized_residual))
        assert np.all(np.isfinite(res.fractional_residual))


# ==============================================================================
# 3. NaNs, Infs & Pathological Input Arrays Stress Tests
# ==============================================================================

class TestNaNInfAndPathologicalArrayStress:
    """Stress tests on non-finite, corrupt, or missing data across input arrays."""

    def test_isolated_nan_and_inf_in_observed_stamp(self, synthetic_epsf_model):
        """Verify NaNs and Infs properly masked in stamp.mask produce valid, finite results."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]
        obs = (25000.0 * crop).astype(np.float32)

        # Inject NaNs and Infs
        obs[40, 40] = np.nan
        obs[10, 10] = np.inf
        obs[70, 70] = -np.inf

        # Properly mask non-finite values
        mask = ~np.isfinite(obs)

        stamp = StellarStamp(
            source_id="nan_inf_masked",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=mask,
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)
        assert np.isfinite(res.flux_scale)
        assert np.isclose(res.flux_scale, 25000.0, rtol=0.05)
        assert np.isfinite(res.chi2_nu)
        assert np.all(np.isfinite(res.residual))

    def test_raw_numpy_array_with_nans_and_infs(self, synthetic_epsf_model):
        """Verify raw numpy array containing NaNs and Infs is safely polymorphic and masked."""
        sz = 61
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0
        obs[30, 30] = np.nan
        obs[5, 5] = np.inf
        obs[55, 55] = -np.inf

        res = fit_star_to_model(obs, synthetic_epsf_model)
        assert np.isfinite(res.flux_scale)
        assert res.mask[30, 30] == True
        assert res.mask[5, 5] == True
        assert res.mask[55, 55] == True
        assert np.all(np.isfinite(res.residual))

    def test_pathological_error_array_zeros_negatives_and_nans(self, synthetic_epsf_model):
        """Verify error array containing 0, negative values, and NaNs is sanitized to positive values."""
        sz = 81
        half = sz // 2
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0

        bad_err = np.ones((sz, sz), dtype=np.float32)
        bad_err[0, 0] = 0.0
        bad_err[1, 1] = -10.0
        bad_err[2, 2] = np.nan
        bad_err[3, 3] = np.inf
        bad_err[4, 4] = -np.inf

        stamp = StellarStamp(
            source_id="bad_err_01",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.5,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, error=bad_err)

        assert np.all(res.error > 0.0)
        assert np.all(np.isfinite(res.error))
        assert np.all(res.error >= 1e-4)
        assert np.isfinite(res.chi2_nu)

    def test_compute_radial_residual_metrics_with_zero_and_nan_errors(self):
        """Verify compute_radial_residual_metrics handles invalid error entries safely."""
        sz = 81
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0
        mod = np.ones((sz, sz), dtype=np.float32) * 10.0
        err = np.ones((sz, sz), dtype=np.float32)

        err[0, 0] = 0.0
        err[1, 1] = -5.0
        err[2, 2] = np.nan

        metrics = compute_radial_residual_metrics(obs, mod, err)
        assert metrics.core["status"] == "PASS"
        assert metrics.transition["status"] == "PASS"
        assert metrics.wings["status"] == "PASS"

    def test_model_canvas_with_nans_in_outer_pixels(self, synthetic_epsf_model):
        """Verify ePSF model with NaNs in outer pixels is sanitized without propagating NaNs."""
        dirty_model = synthetic_epsf_model.copy()
        dirty_model[0, 0] = np.nan
        dirty_model[10, 10] = np.nan

        sz = 81
        half = sz // 2
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0

        stamp = StellarStamp(
            source_id="dirty_mod_01",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, dirty_model)
        assert np.isfinite(res.flux_scale)
        assert np.all(np.isfinite(res.model))


# ==============================================================================
# 4. Off-Center Stars, Boundary Shifts & Dimension Stress Tests
# ==============================================================================

class TestBoundaryAndCoordinateShiftStress:
    """Stress tests on stars located at stamp edges, outside boundaries, and non-square cutouts."""

    def test_star_centered_at_stamp_corner(self, synthetic_epsf_model):
        """Verify star centroid placed at (0, 0) or stamp corner does not cause IndexError."""
        sz = 81
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0
        mod = np.ones((sz, sz), dtype=np.float32) * 10.0
        err = np.ones((sz, sz), dtype=np.float32)

        for corner in [(0.0, 0.0), (80.0, 80.0), (0.0, 80.0), (80.0, 0.0)]:
            metrics = compute_radial_residual_metrics(obs, mod, err, center=corner)
            assert metrics.core["status"] == "PASS"
            assert metrics.transition["status"] == "PASS"
            assert metrics.wings["status"] == "PASS"
            assert metrics.spikes["status"] == "PASS"

    def test_star_centroid_outside_stamp_boundaries(self):
        """Verify star centroid far outside stamp boundaries (-50, -50) handles safely."""
        sz = 81
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0
        mod = np.ones((sz, sz), dtype=np.float32) * 10.0
        err = np.ones((sz, sz), dtype=np.float32)

        metrics = compute_radial_residual_metrics(obs, mod, err, center=(-50.0, -50.0))
        # Core zone is at distance > 50 px, so core has 0 pixels
        assert metrics.core["n_pix"] == 0
        assert metrics.core["status"] == "PASS"

    def test_subpixel_offset_optimization_at_bounds(self, synthetic_epsf_model):
        """Verify subpixel offset optimization respects [-max_shift_px, max_shift_px] boundary."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]

        # Shift by nearly 2.0 pixels
        large_dy, large_dx = 1.95, -1.95
        shifted = shift(crop, [large_dy, large_dx], order=3, mode="constant", cval=0.0)
        obs = (20000.0 * shifted).astype(np.float32)

        stamp = StellarStamp(
            source_id="bound_shift_01",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=0.5,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=True, max_shift_px=2.0)
        rec_dx, rec_dy = res.subpixel_offset

        assert abs(rec_dx) <= 2.0
        assert abs(rec_dy) <= 2.0
        assert np.isclose(rec_dx, large_dx, atol=0.25)
        assert np.isclose(rec_dy, large_dy, atol=0.25)

    def test_subpixel_offset_optimization_disabled(self, synthetic_epsf_model):
        """Verify fit_subpixel_offset=False strictly skips optimization and leaves dx=dy=0.0."""
        sz = 81
        half = sz // 2
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0

        stamp = StellarStamp(
            source_id="no_shift_01",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model, fit_subpixel_offset=False)
        assert res.subpixel_offset == (0.0, 0.0)

    def test_non_square_stamps(self, synthetic_epsf_model):
        """Verify non-square stamp shapes (51x101, 121x61) retain exact output dimensions."""
        for shape in [(51, 101), (121, 61)]:
            obs_rect = np.ones(shape, dtype=np.float32) * 10.0
            res = fit_star_to_model(obs_rect, synthetic_epsf_model)

            assert res.observed.shape == shape
            assert res.model.shape == shape
            assert res.residual.shape == shape
            assert res.normalized_residual.shape == shape
            assert res.fractional_residual.shape == shape
            assert res.mask.shape == shape

    def test_tiny_stamp_smaller_than_core(self, synthetic_epsf_model):
        """Verify tiny stamp (7x7) smaller than core radius (10 px) handles gracefully without crashing."""
        obs_tiny = np.ones((7, 7), dtype=np.float32) * 10.0
        res = fit_star_to_model(obs_tiny, synthetic_epsf_model)

        assert res.observed.shape == (7, 7)
        assert res.radial_metrics.core["status"] in ["PASS", "FAIL"]
        assert res.radial_metrics.transition["n_pix"] == 0
        assert res.radial_metrics.wings["n_pix"] == 0
        assert np.isfinite(res.flux_scale)


# ==============================================================================
# 5. Pathological Aperture Position Angles Stress Tests
# ==============================================================================

class TestPathologicalAperturePositionAngles:
    """Stress tests on aperture position angles: wrap-around, negative, and extreme rotations."""

    @pytest.mark.parametrize("pa", [
        0.0, 90.0, 180.0, 270.0, 359.9, 359.9999, 360.0,
        -90.0, -180.0, -360.0, 720.0, -110.0, 1080.5
    ])
    def test_angles_generate_12_unique_valid_rays(self, pa):
        """Verify all aperture angles yield exactly 12 unique sorted spike rays in [0, 360)."""
        is_spike, is_off, angles = compute_spike_ray_mask((81, 81), (40.0, 40.0), pa_aperture=pa)

        assert len(angles) == 12
        assert np.all(angles >= 0.0)
        assert np.all(angles <= 360.0)
        # Spike and off-spike must be mutually exclusive
        assert np.all(~(is_spike & is_off))
        # Core center must be excluded
        assert not is_spike[40, 40]
        assert not is_off[40, 40]
        # Pixels must be allocated to both zones
        assert np.sum(is_spike) > 0
        assert np.sum(is_off) > 0

    def test_spike_sector_wraparound_across_zero(self):
        """Verify spike rays passing across 0° / 360° boundary correctly capture pixels on both sides."""
        # Find pa that places a spike ray near 0.5 deg
        # Base angle 178.07 deg: if net offset = 182.43 -> angle = 0.50 deg
        pa = 182.43 - (-9.70)
        shape = (101, 101)
        center = (50.0, 50.0)
        is_spike, _, angles = compute_spike_ray_mask(
            shape, center, pa_aperture=pa, angular_half_width_deg=2.0, r_min_px=10.0
        )

        # Check if one angle is close to 0.0 deg
        min_ang = float(np.min(angles))
        assert min_ang < 2.0 or (360.0 - float(np.max(angles))) < 2.0

        # Pixel along +X axis (theta = 0.0 deg, r = 25 px)
        px_0deg = (50, 75)
        # Pixel at slightly positive angle (theta ~ 1.0 deg, r = 25 px)
        px_pos = (50 + int(25 * np.sin(np.radians(1.0))), 50 + int(25 * np.cos(np.radians(1.0))))
        # Pixel at slightly negative angle (theta ~ 359.0 deg, r = 25 px)
        px_neg = (50 + int(25 * np.sin(np.radians(-1.0))), 50 + int(25 * np.cos(np.radians(-1.0))))

        assert is_spike[px_0deg], "Pixel along 0° axis was missed by spike sector wrap-around"
        assert is_spike[px_pos], "Pixel at +1° was missed by spike sector wrap-around"
        assert is_spike[px_neg], "Pixel at 359° was missed by spike sector wrap-around"

    def test_core_radial_gate_exclusion_in_spikes(self):
        """Verify r < r_min_px is strictly excluded from diffraction spike masks."""
        shape = (101, 101)
        center = (50.0, 50.0)
        is_spike, is_off, _ = compute_spike_ray_mask(shape, center, pa_aperture=0.0, r_min_px=15.0)

        gy, gx = np.indices(shape)
        r = np.hypot(gx - 50.0, gy - 50.0)

        # No pixels with r < 15.0 can be marked True in either mask
        assert np.all(~is_spike[r < 15.0])
        assert np.all(~is_off[r < 15.0])


# ==============================================================================
# 6. Division-by-Zero & Regularization Guards Stress Tests
# ==============================================================================

class TestDivisionByZeroGuards:
    """Stress tests verifying numerical stability against division by zero."""

    def test_fractional_residual_zero_model_and_zero_obs(self):
        """Verify background pixels where model=0 and obs=0 evaluate to F=0.0 via eps_reg."""
        obs = np.zeros((51, 51), dtype=np.float32)
        mod = np.zeros((51, 51), dtype=np.float32)
        err = np.ones((51, 51), dtype=np.float32)
        reg_sigma = 0.5

        metrics = compute_radial_residual_metrics(obs, mod, err, reg_sigma=reg_sigma)
        assert metrics.core["mu_frac"] == 0.0
        assert metrics.core["rms_frac"] == 0.0
        assert np.isfinite(metrics.core["mu_frac"])

    def test_all_masked_stamp_radial_metrics(self):
        """Verify completely masked stamp returns safe container with n_pix=0 and no crash."""
        sz = 51
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0
        mod = np.ones((sz, sz), dtype=np.float32) * 10.0
        err = np.ones((sz, sz), dtype=np.float32)
        all_mask = np.ones((sz, sz), dtype=bool)

        metrics = compute_radial_residual_metrics(obs, mod, err, mask=all_mask)

        for zone in ["core", "transition", "wings", "spikes", "off_spikes"]:
            z_dict = getattr(metrics, zone)
            assert z_dict["n_pix"] == 0
            assert z_dict["mu_frac"] == 0.0
            assert z_dict["status"] == "PASS"

    def test_empty_outer_zones_small_stamp(self):
        """Verify small stamp (15x15) where wings has 0 pixels reports n_pix=0 and status=PASS."""
        sz = 15
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0
        mod = np.ones((sz, sz), dtype=np.float32) * 10.0
        err = np.ones((sz, sz), dtype=np.float32)

        metrics = compute_radial_residual_metrics(obs, mod, err, wings_r_min=30.0)
        assert metrics.wings["n_pix"] == 0
        assert metrics.wings["status"] == "PASS"
        assert metrics.wings["chi2_nu"] == 1.0


# ==============================================================================
# 7. Multi-Extension FITS Serialization Roundtrip & JSON Integrity
# ==============================================================================

class TestMultiExtensionFitsRoundtrip:
    """Stress tests verifying lossless FITS export/roundtrip and JSON summary serialization."""

    def test_fits_export_hdu_list_structure(self, synthetic_epsf_model, tmp_path):
        """Verify exported FITS contains exactly 6 HDUs with expected extension names and dtypes."""
        sz = 81
        half = sz // 2
        obs = np.ones((sz, sz), dtype=np.float32) * 25.0
        stamp = StellarStamp(
            source_id="fits_struct_01",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)
        fits_file = tmp_path / "test_struct.fits"
        res.save_residual_fits(fits_file)

        assert fits_file.is_file()
        with fits.open(fits_file) as hdul:
            assert len(hdul) == 6
            ext_names = [h.name for h in hdul]
            assert "RESIDUAL" in ext_names or hdul[0].name == "PRIMARY"
            assert "OBSERVED" in ext_names
            assert "MODEL" in ext_names
            assert "NORM_RES" in ext_names
            assert "FRAC_RES" in ext_names
            assert "MASK" in ext_names

            # Dtype verification (FITS standard stores big-endian float32 >f4)
            for name in ["RESIDUAL", "OBSERVED", "MODEL", "NORM_RES", "FRAC_RES"]:
                arr = hdul[name].data if name in hdul else hdul[0].data
                assert np.issubdtype(arr.dtype, np.floating)
                assert arr.dtype.itemsize == 4
            assert hdul["MASK"].data.dtype.itemsize == 1

    def test_fits_export_header_keywords(self, synthetic_epsf_model, tmp_path):
        """Verify all primary header metadata keywords are correctly populated and typed."""
        sz = 81
        half = sz // 2
        obs = np.ones((sz, sz), dtype=np.float32) * 25.0
        stamp = StellarStamp(
            source_id="star_hdr_test",
            tier="medium",
            mag=12.34,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)
        fits_file = tmp_path / "test_headers.fits"
        res.save_residual_fits(fits_file)

        with fits.open(fits_file) as hdul:
            hdr = hdul[0].header
            assert hdr["SRC_ID"] == "star_hdr_test"
            assert hdr["TIER"] == "MEDIUM"
            assert np.isclose(hdr["MAG"], 12.34, atol=1e-4)
            assert np.isclose(hdr["FLXSCALE"], res.flux_scale)
            assert np.isclose(hdr["DX"], res.subpixel_offset[0])
            assert np.isclose(hdr["DY"], res.subpixel_offset[1])
            assert np.isclose(hdr["CHI2_NU"], res.chi2_nu)

    def test_fits_export_data_roundtrip_fidelity(self, synthetic_epsf_model, tmp_path):
        """Verify numerical roundtrip: data arrays loaded from FITS exactly match in-memory arrays."""
        sz = 81
        half = sz // 2
        rng = np.random.RandomState(42)
        obs = rng.uniform(5.0, 50.0, (sz, sz)).astype(np.float32)
        mask = (rng.uniform(0, 1, (sz, sz)) > 0.8)

        stamp = StellarStamp(
            source_id="fidelity_01",
            tier="faint",
            mag=14.5,
            data=obs,
            mask=mask,
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)
        fits_file = tmp_path / "test_fidelity.fits"
        res.save_residual_fits(fits_file)

        with fits.open(fits_file) as hdul:
            np.testing.assert_allclose(hdul[0].data, res.residual, rtol=1e-6)
            np.testing.assert_allclose(hdul["OBSERVED"].data, res.observed, rtol=1e-6)
            np.testing.assert_allclose(hdul["MODEL"].data, res.model, rtol=1e-6)
            np.testing.assert_allclose(hdul["NORM_RES"].data, res.normalized_residual, rtol=1e-6)
            np.testing.assert_allclose(hdul["FRAC_RES"].data, res.fractional_residual, rtol=1e-6)
            np.testing.assert_array_equal(hdul["MASK"].data, res.mask.astype(np.uint8))

    def test_fits_export_overwrite_behavior(self, synthetic_epsf_model, tmp_path):
        """Verify overwrite=False protects existing files and overwrite=True allows replacement."""
        sz = 51
        half = sz // 2
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0
        stamp = StellarStamp(
            source_id="overwrite_test",
            tier="faint",
            mag=15.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)
        fits_file = tmp_path / "overwrite_target.fits"

        # First write
        res.save_residual_fits(fits_file)
        assert fits_file.is_file()

        # Second write with overwrite=False must raise OSError
        with pytest.raises(OSError):
            res.save_residual_fits(fits_file, overwrite=False)

        # Third write with overwrite=True must succeed
        res.save_residual_fits(fits_file, overwrite=True)
        assert fits_file.is_file()

    def test_fits_export_nested_directory_creation(self, synthetic_epsf_model, tmp_path):
        """Verify save_residual_fits creates nested parent directories automatically."""
        sz = 51
        half = sz // 2
        obs = np.ones((sz, sz), dtype=np.float32) * 10.0
        stamp = StellarStamp(
            source_id="nested_dir_test",
            tier="faint",
            mag=15.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        res = fit_star_to_model(stamp, synthetic_epsf_model)
        nested_file = tmp_path / "sub1" / "sub2" / "deep_residual.fits"
        res.save_residual_fits(nested_file)

        assert nested_file.is_file()

    def test_validation_results_json_serialization_roundtrip(self, synthetic_epsf_model, tmp_path):
        """Verify ValidationResults serializes cleanly to JSON and can be read back with full fidelity."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]
        obs = (25000.0 * crop).astype(np.float32)
        stamp = StellarStamp(
            source_id="json_test_01",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        results = evaluate_epsf_validation(
            epsf_model=synthetic_epsf_model,
            test_stamps=[stamp],
            output_dir=tmp_path,
        )

        json_file = tmp_path / "validation_summary.json"
        assert json_file.is_file()

        with open(json_file, "r") as f:
            data = json.load(f)

        assert data["overall_status"] == "PASS"
        assert data["total_stars_evaluated"] == 1
        assert "zone_summary" in data
        assert "core" in data["zone_summary"]
        assert "transition" in data["zone_summary"]
        assert "wings" in data["zone_summary"]
        assert "spikes" in data["zone_summary"]
        assert len(data["stars"]) == 1
        assert data["stars"][0]["source_id"] == "json_test_01"

    def test_evaluate_epsf_validation_with_fits_export(self, synthetic_epsf_model, tmp_path):
        """Verify evaluate_epsf_validation saves individual star residual FITS when requested."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_epsf_model[c - half : c + half + 1, c - half : c + half + 1]
        obs = (25000.0 * crop).astype(np.float32)
        stamp = StellarStamp(
            source_id="eval_fits_01",
            tier="faint",
            mag=14.0,
            data=obs,
            mask=np.zeros((sz, sz), dtype=bool),
            center_original=(float(half), float(half)),
            size=sz,
            bkg_rms=1.0,
        )

        results = evaluate_epsf_validation(
            epsf_model=synthetic_epsf_model,
            test_stamps=[stamp],
            output_dir=tmp_path,
            save_residual_fits=True,
        )

        expected_fits = tmp_path / "residual_faint_eval_fits_01.fits"
        assert expected_fits.is_file()
        assert results.overall_status == "PASS"
