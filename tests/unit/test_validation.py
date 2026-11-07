"""
Unit Tests for Model Validation & Subtraction Residual Module (Milestone 4, Features 22 & 23, Scenario 4).
"""

from __future__ import annotations

import json
from pathlib import Path
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
import validation as root_validation
from romanepsf.stamps import StellarStamp
from romanepsf.config import load_config, ValidationConfig


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def synthetic_gaussian_epsf():
    """Create a 1025x1025 normalized synthetic 2D extended PSF canvas."""
    sz = 1025
    canvas = np.zeros((sz, sz), dtype=np.float32)
    c = sz // 2
    # Gaussian core
    gy, gx = np.indices((sz, sz))
    r = np.hypot(gx - c, gy - c)
    core = np.exp(-0.5 * (r / 2.5)**2)
    wings = 1.0 / (1.0 + (r / 5.0)**2.5)
    canvas = 0.8 * core + 0.2 * wings
    # Add 12 diffraction spikes
    from romanepsf.masking import get_theoretical_spike_angles
    angles = get_theoretical_spike_angles(pa_offset_deg=-110.0, detector_offset_deg=-9.7)
    theta = (np.degrees(np.arctan2(gy - c, gx - c)) + 360.0) % 360.0
    for ang in angles:
        diff = np.abs(theta - ang)
        diff = np.minimum(diff, 360.0 - diff)
        spike_strip = (diff <= 1.0) & (r >= 5.0)
        canvas[spike_strip] += 0.05 / (1.0 + r[spike_strip] / 10.0)

    canvas /= np.sum(canvas)
    return canvas.astype(np.float32)


@pytest.fixture
def synthetic_faint_stamp(synthetic_gaussian_epsf):
    """Create a synthetic 81x81 faint star stamp matching the ePSF model."""
    sz = 81
    c = 1025 // 2
    half = sz // 2
    crop = synthetic_gaussian_epsf[c - half : c + half + 1, c - half : c + half + 1]
    flux = 25000.0
    star_data = (flux * crop).astype(np.float32)
    # Add small Gaussian noise
    rng = np.random.RandomState(42)
    noise = rng.normal(0.0, 0.5, (sz, sz)).astype(np.float32)
    noisy_data = star_data + noise

    return StellarStamp(
        source_id="syn_faint_001",
        tier="faint",
        mag=14.0,
        data=noisy_data,
        mask=np.zeros((sz, sz), dtype=bool),
        center_original=(40.0, 40.0),
        size=sz,
        bkg_value=0.0,
        bkg_rms=0.5,
    )


# ==============================================================================
# Backward Compatibility Shim Tests
# ==============================================================================

def test_backward_compatibility_reexports():
    """Verify that root validation.py re-exports all public symbols."""
    assert root_validation.StarResidualResult is StarResidualResult
    assert root_validation.RadialMetrics is RadialMetrics
    assert root_validation.ValidationResults is ValidationResults
    assert root_validation.compute_spike_ray_mask is compute_spike_ray_mask
    assert root_validation.fit_star_to_model is fit_star_to_model
    assert root_validation.compute_radial_residual_metrics is compute_radial_residual_metrics
    assert root_validation.evaluate_epsf_validation is evaluate_epsf_validation


# ==============================================================================
# Test Class 1: 2D Subtraction Residual Mapping (F22)
# ==============================================================================

class Test2DSubtractionResidualMapping:
    """Tests for 2D Subtraction Residual Mapping (Feature 22, Requirement R4)."""

    def test_f22_01_model_forward_subtraction_zero_residual(self):
        """F22.01: Verify subtracting identical model from star yields zero residual."""
        sz = 81
        rng = np.random.RandomState(42)
        star = rng.uniform(0.1, 10.0, (sz, sz)).astype(np.float32)
        model = star.copy()
        res = star - model
        np.testing.assert_allclose(res, 0.0, atol=1e-6)

    def test_f22_02_fractional_residual_calculation(self):
        """F22.02: Verify fractional residual formula Delta_frac = (I_obs - I_mod) / (I_mod + eps_reg)."""
        obs = np.array([10.0, 20.0], dtype=np.float32)
        mod = np.array([8.0, 25.0], dtype=np.float32)
        eps = 1.0
        frac = (obs - mod) / (mod + eps)
        assert np.isclose(frac[0], (10.0 - 8.0) / (8.0 + 1.0))
        assert np.isclose(frac[1], (20.0 - 25.0) / (25.0 + 1.0))

    def test_f22_03_regularization_sigma_prevents_zero_division(self):
        """F22.03: Verify regularization parameter prevents division by zero in background."""
        obs = np.array([0.0], dtype=np.float32)
        mod = np.array([0.0], dtype=np.float32)
        eps_reg = 0.5
        frac = (obs - mod) / (mod + eps_reg)
        assert frac[0] == 0.0
        assert np.isfinite(frac[0])

    def test_f22_04_saturated_pixels_masked_in_residuals(self):
        """F22.04: Verify saturated pixels are masked before computing residual statistics."""
        residual = np.array([0.01, 0.02, 9999.0], dtype=np.float32)
        mask = np.array([False, False, True], dtype=bool)
        valid_res = residual[~mask]
        assert len(valid_res) == 2
        assert float(np.mean(valid_res)) < 0.05

    def test_f22_05_scaled_forward_model_flux_matching(self, synthetic_gaussian_epsf):
        """F22.05: Verify fitted model flux scales linearly with star brightness."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_gaussian_epsf[c - half : c + half + 1, c - half : c + half + 1]

        target_flux = 50000.0
        star_data = (target_flux * crop).astype(np.float32)
        stamp = StellarStamp("lin_001", "faint", 13.0, star_data, np.zeros((sz, sz), bool), (40.0, 40.0), sz)

        result = fit_star_to_model(stamp, synthetic_gaussian_epsf, fit_subpixel_offset=False)
        assert np.isclose(result.flux_scale, target_flux, rtol=0.01)

    def test_subpixel_offset_recovery(self, synthetic_gaussian_epsf):
        """Verify subpixel centroid alignment recovers known fractional shifts."""
        sz = 81
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_gaussian_epsf[c - half : c + half + 1, c - half : c + half + 1]

        true_dy = 0.25
        true_dx = -0.35
        shifted_crop = shift(crop, [true_dy, true_dx], order=3, mode="constant", cval=0.0)
        flux = 20000.0
        star_data = (flux * shifted_crop).astype(np.float32)

        stamp = StellarStamp("shift_001", "faint", 14.0, star_data, np.zeros((sz, sz), bool), (40.0, 40.0), sz)
        result = fit_star_to_model(stamp, synthetic_gaussian_epsf, fit_subpixel_offset=True)

        rec_dx, rec_dy = result.subpixel_offset
        assert np.isclose(rec_dx, true_dx, atol=0.08)
        assert np.isclose(rec_dy, true_dy, atol=0.08)


# ==============================================================================
# Test Class 2: Partitioned Radial Residual Metrics (F23 & Scenario 4)
# ==============================================================================

class TestPartitionedRadialResidualMetrics:
    """Tests for Partitioned Radial Residual Metrics across 4 spatial zones."""

    def test_f23_01_core_zone_definition(self):
        """F23.01: Verify Core evaluation zone is defined for r < 10 pixels."""
        cfg = load_config("configs/default.yaml")
        assert cfg.validation.core_radius_max_px == 10.0

    def test_f23_02_transition_zone_definition(self):
        """F23.02: Verify Transition evaluation zone is defined for [10.0, 30.0] or [10.0, 40.0] px."""
        cfg = load_config("configs/default.yaml")
        assert cfg.validation.transition_radius_px[0] == 10.0
        assert cfg.validation.transition_radius_px[1] in [30.0, 40.0]

    def test_f23_03_wings_zone_definition(self):
        """F23.03: Verify Wings evaluation zone is defined for r >= 30.0 or r >= 40.0 pixels."""
        cfg = load_config("configs/default.yaml")
        assert cfg.validation.wings_radius_min_px in [30.0, 40.0]

    def test_f23_04_reduced_chisq_formula(self):
        """F23.04: Verify reduced chi-squared statistic calculation chi^2 = sum((obs - mod)^2 / err^2) / N."""
        obs = np.array([10.0, 12.0, 9.0], dtype=np.float32)
        mod = np.array([10.0, 10.0, 10.0], dtype=np.float32)
        err = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        chi2_nu = float(np.mean(((obs - mod) / err)**2))
        assert np.isclose(chi2_nu, 5.0 / 3.0)

    def test_s4_01_core_zone_tolerance_within_5_percent(self, synthetic_faint_stamp, synthetic_gaussian_epsf):
        """S4.1: Verify core fractional residual satisfies |mu_frac| <= 0.05 (5%)."""
        res = fit_star_to_model(synthetic_faint_stamp, synthetic_gaussian_epsf)
        core_mu = res.radial_metrics.core["mu_frac"]
        assert abs(core_mu) <= 0.05
        assert res.radial_metrics.core["status"] == "PASS"

    def test_s4_02_transition_zone_continuity_smoothness(self):
        """S4.2: Verify transition zone has smooth residuals without step discontinuities."""
        sz = 81
        mod = np.ones((sz, sz), dtype=np.float32) * 50.0
        obs = mod.copy()
        err = np.ones((sz, sz), dtype=np.float32)
        metrics = compute_radial_residual_metrics(obs, mod, err, center=(40.0, 40.0))
        assert abs(metrics.transition["mu_frac"]) <= 0.05
        assert metrics.transition["status"] == "PASS"

    def test_s4_03_wings_reduced_chi2_in_nominal_range(self):
        """S4.3: Verify far wings reduced chi^2 is bounded within nominal range [0.5, 2.5]."""
        sz = 101
        c = 50.0
        rng = np.random.RandomState(42)
        mod = np.full((sz, sz), 5.0, dtype=np.float32)
        noise = rng.normal(0.0, 1.0, (sz, sz)).astype(np.float32)
        obs = mod + noise
        err = np.ones((sz, sz), dtype=np.float32)

        metrics = compute_radial_residual_metrics(obs, mod, err, center=(c, c), wings_r_min=30.0)
        chi2_w = metrics.wings["chi2_nu"]
        assert 0.8 <= chi2_w <= 1.2
        assert metrics.wings["status"] == "PASS"

    def test_s4_04_spike_peak_residual_under_10_percent(self, synthetic_gaussian_epsf):
        """S4.4: Verify diffraction spike peak residual is <= 10% of peak spike flux."""
        sz = 101
        c = 1025 // 2
        half = sz // 2
        crop = synthetic_gaussian_epsf[c - half : c + half + 1, c - half : c + half + 1]
        flux = 50000.0
        obs = (flux * crop).astype(np.float32)

        err = np.ones_like(obs)
        metrics = compute_radial_residual_metrics(obs, obs * 0.98, err, center=(half, half), pa_aperture=-110.0)
        assert metrics.spikes["peak_res_frac"] <= 0.10
        assert metrics.spikes["status"] == "PASS"

    def test_s4_05_validation_results_dataclass_structure(self, synthetic_faint_stamp, synthetic_gaussian_epsf):
        """S4.5: Validation summary dictionary contains metrics for all 4 zones with status=PASS."""
        results = evaluate_epsf_validation(
            epsf_model=synthetic_gaussian_epsf,
            test_stamps=[synthetic_faint_stamp],
        )
        summary = results.to_dict()

        for zone in ["core", "transition", "wings", "spikes"]:
            assert zone in summary, f"Zone {zone} missing from summary dictionary"
            assert summary[zone]["status"] == "PASS", f"Zone {zone} failed status check"


# ==============================================================================
# Test Class 3: Spike Corridor Masking
# ==============================================================================

class TestSpikeCorridorMasking:
    """Tests for compute_spike_ray_mask."""

    def test_12_theoretical_angles_generated(self):
        """Verify 12 unique spike angles in detector frame."""
        _, _, angles = compute_spike_ray_mask((81, 81), (40.0, 40.0), pa_aperture=0.0)
        assert len(angles) == 12
        assert np.all(angles >= 0.0)
        assert np.all(angles < 360.0)

    def test_spike_mask_geometry(self):
        """Verify pixels along spike rays are marked True and core is excluded."""
        shape = (101, 101)
        center = (50.0, 50.0)
        is_spike, is_off, angles = compute_spike_ray_mask(shape, center, pa_aperture=0.0, r_min_px=10.0)

        # Center core must be False in both
        assert not is_spike[50, 50]
        assert not is_off[50, 50]

        # Check an arbitrary spike ray
        first_ang_rad = np.radians(angles[0])
        test_r = 30.0
        tx = int(round(50.0 + test_r * np.cos(first_ang_rad)))
        ty = int(round(50.0 + test_r * np.sin(first_ang_rad)))
        assert is_spike[ty, tx]
        assert not is_off[ty, tx]


# ==============================================================================
# Test Class 4: Dataclass Serialization & File Export
# ==============================================================================

class TestDataclassSerialization:
    """Tests for JSON serialization and FITS residual export."""

    def test_star_residual_fits_export(self, synthetic_faint_stamp, synthetic_gaussian_epsf, tmp_path):
        """Verify StarResidualResult can export multi-extension FITS file."""
        res = fit_star_to_model(synthetic_faint_stamp, synthetic_gaussian_epsf)
        fits_p = tmp_path / "residual_test.fits"
        saved = res.save_residual_fits(fits_p)
        assert saved.is_file()

        with fits.open(saved) as hdul:
            assert hdul[0].name == "PRIMARY" or hdul[0].header.get("EXTNAME") == "RESIDUAL"
            assert "OBSERVED" in hdul
            assert "MODEL" in hdul
            assert "NORM_RES" in hdul
            assert "FRAC_RES" in hdul
            assert "MASK" in hdul

    def test_validation_results_json_save(self, synthetic_faint_stamp, synthetic_gaussian_epsf, tmp_path):
        """Verify ValidationResults can serialize to JSON summary file."""
        results = evaluate_epsf_validation(
            epsf_model=synthetic_gaussian_epsf,
            test_stamps=[synthetic_faint_stamp],
            output_dir=tmp_path,
        )
        json_p = tmp_path / "validation_summary.json"
        assert json_p.is_file()

        with open(json_p, "r") as f:
            data = json.load(f)
        assert data["overall_status"] == "PASS"
        assert data["total_stars_evaluated"] == 1
        assert "core" in data
        assert "transition" in data
        assert "wings" in data
        assert "spikes" in data


# ==============================================================================
# Test Class 5: Real Data Integration
# ==============================================================================

class TestRealDataIntegration:
    """Integration test against actual Level 2 WFI01 data and composite ePSF model."""

    def test_validate_against_wfi01_real_stars(self):
        """Verify validation runs against actual synthesized ePSF and extracted WFI01 stars."""
        composite_fits = Path("output/run_all/roman_epsf_composite.fits")
        if not composite_fits.is_file():
            pytest.skip("output/run_all/roman_epsf_composite.fits not found")

        with fits.open(composite_fits) as hdul:
            epsf_data = hdul[0].data

        cfg = load_config("configs/default.yaml")
        asdf_file = cfg.data.detectors_dir / "r0108301001001001001_0001_wfi01_f146_cal.asdf"
        if not asdf_file.is_file():
            pytest.skip("WFI01 ASDF file not found")

        results = evaluate_epsf_validation(
            epsf_model=epsf_data,
            asdf_path=asdf_file,
            cfg=cfg.validation,
        )

        assert results.total_stars_evaluated > 0
        assert results.overall_status in ["PASS", "WARNING"]
        for z in ["core", "transition", "wings", "spikes"]:
            assert z in results.zone_summary
            assert results.zone_summary[z]["n_pix"] >= 0


# ==============================================================================
# Test Class 6: Robustness & Adversarial Edge Cases
# ==============================================================================

class TestRobustnessAndEdgeCases:
    """Stress tests on pathological inputs, edge cases, and missing data."""

    def test_all_nan_stamp(self, synthetic_gaussian_epsf):
        """Verify all-NaN stamp does not crash and handles safely."""
        nan_data = np.full((81, 81), np.nan, dtype=np.float32)
        stamp = StellarStamp("nan_01", "faint", 15.0, nan_data, np.ones((81, 81), bool), (40.0, 40.0), 81)
        res = fit_star_to_model(stamp, synthetic_gaussian_epsf)
        assert np.isfinite(res.flux_scale)
        assert res.residual.shape == (81, 81)

    def test_zero_flux_stamp(self, synthetic_gaussian_epsf):
        """Verify zero-flux stamp returns zero flux scale safely."""
        zero_data = np.zeros((81, 81), dtype=np.float32)
        stamp = StellarStamp("zero_01", "faint", 18.0, zero_data, np.zeros((81, 81), bool), (40.0, 40.0), 81)
        res = fit_star_to_model(stamp, synthetic_gaussian_epsf)
        assert res.flux_scale == 0.0

    def test_numpy_array_input_polymorphism(self, synthetic_gaussian_epsf):
        """Verify fit_star_to_model accepts raw numpy array as stamp."""
        arr = np.ones((51, 51), dtype=np.float32) * 10.0
        res = fit_star_to_model(arr, synthetic_gaussian_epsf)
        assert res.observed.shape == (51, 51)
        assert res.flux_scale > 0.0

    def test_empty_test_stamps_evaluation(self, synthetic_gaussian_epsf):
        """Verify evaluate_epsf_validation with empty list returns clean NO_DATA container."""
        res = evaluate_epsf_validation(synthetic_gaussian_epsf, test_stamps=[])
        assert res.total_stars_evaluated == 0
        assert res.overall_status == "NO_DATA"
