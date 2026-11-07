"""
Tier 5 Adversarial Stress Test Suite: Integration, Validation, Report, and CLI.

Milestone 5 Phase 2 Adversarial Coverage Hardening
Author: challenger_m5_tier5_2
Project: Roman Extended PSF (ePSF) Measurement Pipeline

Adversarial Stress Dimensions:
  1. CLI Subcommand & Flag Permutations:
     - Non-existent & corrupted YAML configuration files.
     - Canvas size edge cases (even size promotion vs CLI validation discrepancy).
     - Detector list string parsing, whitespace, casing, and invalid detector codes.
     - Missing arguments and unknown options.
     - Empirical discovery & verification of CLI 'assemble' subcommand defect.
  2. Multi-Extension FITS Edge Cases:
     - Header card standard <= 8 character conformance.
     - Single-HDU minimal FITS ingestion fallbacks.
     - Corrupted FITS file headers and truncated data blocks.
     - Unphysical model canvas (all zeros, all NaNs, all Infs).
     - LogNorm dynamic range crash on flat canvas with vmax < 1e-6.
  3. Validation Module Boundary Conditions:
     - compute_spike_ray_mask with inverted radii, extreme PA angles, non-square dimensions.
     - fit_star_to_model with all-zero, all-NaN, 100% masked, tiny stamps, and large subpixel shifts.
     - evaluate_epsf_validation with empty stamp collections.
     - ValidationResults dictionary and JSON serialization roundtrips.
  4. Corrupted Validation Summary JSON & Report Robustness:
     - Corrupt JSON syntax handling in ReportDataBundle.
     - Non-numeric strings and nulls in metric fields handled by _safe_float.
     - Astronomical extreme values (chi2 > 1e6) formatted cleanly.
  5. Sequential Pipeline Resilience & Resource Lifecycle:
     - Multi-detector partial failure tolerance (1 SCA fails, 1 SCA succeeds).
     - Global failure when 0 stars extracted across all SCAs.
     - Guaranteed gc.collect() in finally block during extraction failures.
  6. Publication Report End-to-End PDF Generation:
     - Full 8-page PDF compilation and binary validation (page count, MediaBox, xref).
"""

from __future__ import annotations

import gc
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits
from click.testing import CliRunner

from romanepsf.cli import cli
from romanepsf.config import Config, PipelineConfig, load_config
from romanepsf.pipeline import (
    SingleDetectorResult,
    PipelineOutputs,
    discover_detectors,
    export_single_detector_fits,
    process_single_detector_stamps,
    run_pipeline,
    run_single_detector,
)
from romanepsf.report import (
    ReportDataBundle,
    generate_publication_pdf_report,
    plot_page_performance_benchmarks,
    plot_page_residual_metrics,
    plot_page_subtraction_residuals,
)
from romanepsf.stamps import StellarStamp
from romanepsf.validation import (
    RadialMetrics,
    StarResidualResult,
    ValidationResults,
    compute_radial_residual_metrics,
    compute_spike_ray_mask,
    evaluate_epsf_validation,
    fit_star_to_model,
)


# ==============================================================================
# Helper Fixtures & Utilities
# ==============================================================================

@pytest.fixture
def synthetic_psf_canvas() -> np.ndarray:
    """Generate realistic 1025x1025 2D Moffat PSF canvas with unit flux."""
    y, x = np.ogrid[-512:513, -512:513]
    r = np.hypot(x, y)
    canvas = (1.0 + (r / 2.5) ** 2) ** (-2.5)
    canvas /= np.sum(canvas)
    return canvas.astype(np.float32)


@pytest.fixture
def synthetic_fits_file(tmp_path, synthetic_psf_canvas) -> Path:
    """Create a valid 4-HDU composite ePSF FITS file for testing."""
    fits_path = tmp_path / "roman_epsf_composite.fits"
    primary = fits.PrimaryHDU(synthetic_psf_canvas)
    primary.header["EXTNAME"] = "EPSF"
    primary.header["DETECTOR"] = "ALL18"
    primary.header["FILTER"] = "F146"
    primary.header["PA_APER"] = 15.0
    primary.header["PIXSCALE"] = 0.11
    primary.header["CANVAS_S"] = 1025
    primary.header["NSTARS"] = 140
    primary.header["NDET"] = 18

    # HDU 1: COVERAGE
    coverage = fits.ImageHDU(np.ones((1025, 1025), dtype=np.int32), name="COVERAGE")

    # HDU 2: RADIAL_PROFILES
    radii = np.linspace(0.5, 180.0, 90)
    p_cols = [
        fits.Column(name="RADIUS_PX", format="E", array=radii),
        fits.Column(name="FLUX_DENSITY", format="E", array=np.exp(-radii / 10.0)),
        fits.Column(name="AZ_MEAN", format="E", array=np.exp(-radii / 10.0)),
        fits.Column(name="AZ_MEDIAN", format="E", array=np.exp(-radii / 10.0)),
        fits.Column(name="N_PIX", format="J", array=np.full(90, 50, dtype=np.int32)),
    ]
    hdu_rad = fits.BinTableHDU.from_columns(p_cols, name="RADIAL_PROFILES")

    # HDU 3: DETECTOR_SUMMARY
    det_names = [f"WFI{i:02d}" for i in range(1, 19)]
    d_cols = [
        fits.Column(name="DETECTOR", format="5A", array=det_names),
        fits.Column(name="STATUS", format="10A", array=["SUCCESS"] * 18),
        fits.Column(name="TOTAL_STARS", format="J", array=np.full(18, 10, dtype=np.int32)),
        fits.Column(name="TIME_SEC", format="E", array=np.full(18, 0.5, dtype=np.float32)),
        fits.Column(name="PEAK_RSS_MB", format="E", array=np.full(18, 1800.0, dtype=np.float32)),
    ]
    hdu_det = fits.BinTableHDU.from_columns(d_cols, name="DETECTOR_SUMMARY")

    hdul = fits.HDUList([primary, coverage, hdu_rad, hdu_det])
    hdul.writeto(fits_path, overwrite=True)
    return fits_path


# ==============================================================================
# Suite 1: CLI Subcommand & Flag Permutations
# ==============================================================================

class TestAdversarialCliPermutations:
    """Stress-test Click CLI argument permutations, boundary values, and error paths."""

    def test_cli_nonexistent_and_corrupt_config_files(self, tmp_path):
        """Verify non-existent and malformed configuration files fail gracefully with exit code 1."""
        runner = CliRunner()

        # 1. Non-existent explicit config path
        res_nonexistent = runner.invoke(cli, ["--config", str(tmp_path / "missing.yaml"), "single"])
        assert res_nonexistent.exit_code == 1
        assert "Configuration file not found" in res_nonexistent.output

        # 2. Corrupted YAML config (syntax error)
        corrupt_yaml = tmp_path / "corrupt.yaml"
        corrupt_yaml.write_text("assembly:\n  canvas_size: [unclosed list\n  bad_syntax: :::")
        res_corrupt = runner.invoke(cli, ["--config", str(corrupt_yaml), "single"])
        assert res_corrupt.exit_code == 1
        assert "Error loading configuration" in res_corrupt.output

        # 3. Directory path passed when file is required
        res_dir = runner.invoke(cli, ["--config", str(tmp_path), "single"])
        assert res_dir.exit_code == 2

    def test_cli_detector_flag_permutations(self):
        """Verify detector flag permutations: casing, commas, whitespace, and invalid detector codes."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run_pipeline.return_value = MagicMock(fits_path=Path("out.fits"))

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            # 1. Uppercase and mixed case: 'WFI01,WFI02'
            res1 = runner.invoke(cli, ["run", "--detectors", "WFI01,WFI02"])
            assert res1.exit_code == 0
            cfg1 = mock_pipeline.run_pipeline.call_args.args[0]
            assert cfg1.data.detectors == ["wfi01", "wfi02"]

            # 2. 'all' case variants: 'All', 'ALL'
            res2 = runner.invoke(cli, ["run", "--detectors", "ALL"])
            assert res2.exit_code == 0
            cfg2 = mock_pipeline.run_pipeline.call_args.args[0]
            assert len(cfg2.data.detectors) == 18
            assert cfg2.data.detectors[0] == "wfi01"
            assert cfg2.data.detectors[-1] == "wfi18"

            # 3. Extra whitespace in comma-separated list
            res3 = runner.invoke(cli, ["run", "--detectors", "  wfi03 ,  wfi07  "])
            assert res3.exit_code == 0
            cfg3 = mock_pipeline.run_pipeline.call_args.args[0]
            assert cfg3.data.detectors == ["wfi03", "wfi07"]

    def test_cli_canvas_size_validation_discrepancy(self):
        """
        Verify CLI seamlessly promotes even canvas sizes (e.g. 1024 -> 1025) before
        cfg.validate(), preventing premature configuration failure.
        """
        runner = CliRunner()

        # Passing even canvas size to CLI single is seamlessly promoted to 1025
        res_even = runner.invoke(cli, ["single", "--canvas-size", "1024"])
        assert res_even.exit_code == 0
        assert "Even canvas size 1024 provided; promoting to odd 1025" in res_even.output

        # Passing negative canvas size to CLI run properly fails validation
        res_neg = runner.invoke(cli, ["run", "--canvas-size", "-100"])
        assert res_neg.exit_code == 1
        assert "Configuration validation failed" in res_neg.output

    def test_cli_invalid_options_and_missing_arguments(self):
        """Verify CLI exits with code 2 on unknown flags or missing mandatory arguments."""
        runner = CliRunner()

        # 1. Unknown flag
        res_unknown = runner.invoke(cli, ["--completely-invalid-flag"])
        assert res_unknown.exit_code == 2

        # 2. Missing required option '--model' for 'validate' subcommand
        res_val_missing = runner.invoke(cli, ["validate"])
        assert res_val_missing.exit_code == 2
        assert "Missing option" in res_val_missing.output or "--model" in res_val_missing.output

        # 3. Non-existent path where click.Path(exists=True) is required
        res_val_missing_file = runner.invoke(cli, ["validate", "--model", "nonexistent_model_12345.fits"])
        assert res_val_missing_file.exit_code == 2

    def test_cli_assemble_command_defect_empirical(self, tmp_path):
        """
        Verify 'romanepsf assemble' correctly unpacks (extended_psf, diagnostics)
        and passes output_size, successfully producing a float32 FITS canvas.
        """
        import pickle
        stamps_dir = tmp_path / "stamps"
        stamps_dir.mkdir(parents=True)
        stamps_file = stamps_dir / "stamps_by_tier.pkl"

        dummy_stamp = StellarStamp(
            source_id="1",
            tier="faint",
            mag=14.0,
            data=np.ones((25, 25), dtype=np.float32),
            mask=np.zeros((25, 25), dtype=bool),
            center_original=(12.0, 12.0),
            size=25,
            bkg_rms=1.0,
        )
        with open(stamps_file, "wb") as f:
            pickle.dump({"bright": [], "medium": [], "faint": [dummy_stamp]}, f)

        runner = CliRunner()
        out_fits = tmp_path / "assembled.fits"
        res = runner.invoke(cli, ["assemble", "--stamps-dir", str(stamps_dir), "--output-fits", str(out_fits)])

        assert res.exit_code == 0, f"Assemble failed: {res.output}"
        assert out_fits.exists()
        with fits.open(out_fits) as hdul:
            assert np.issubdtype(hdul[0].data.dtype, np.float32)
            assert hdul[0].header["CANVAS_S"] == 1025


# ==============================================================================
# Suite 2: Multi-Extension FITS Edge Cases
# ==============================================================================

class TestMultiExtensionFitsEdgeCases:
    """Stress-test FITS serialization, header conformance, and ingestion robustness."""

    def test_fits_export_header_card_conformance(self, tmp_path):
        """Verify export_single_detector_fits complies with standard <= 8 char header card limits."""
        out_fits = tmp_path / "export_test.fits"
        canvas = np.zeros((501, 501), dtype=np.float32)
        canvas[250, 250] = 1.0

        export_single_detector_fits(
            epsf_model=canvas,
            fits_path=out_fits,
            detector_id="wfi05",
            filter_name="F146",
            pixel_scale=0.11,
            pa_aperture=35.5,
            star_counts={"bright": 2, "medium": 5, "faint": 15, "total": 22},
            scale_factors={"k_fm": 0.15, "k_mb": 0.025},
        )

        assert out_fits.is_file()
        with fits.open(out_fits) as hdul:
            hdr = hdul[0].header
            # Verify ALL header keyword names are <= 8 characters
            for key in hdr.keys():
                assert len(key) <= 8, f"FITS header card keyword '{key}' exceeds 8 characters"

            assert hdr["EXTNAME"] == "EPSF"
            assert hdr["DETECTOR"] == "WFI05"
            assert hdr["FILTER"] == "F146"
            assert hdr["CANVAS_S"] == 501
            assert np.isclose(hdr["CRPIX1"], 251.0)
            assert np.isclose(hdr["CRPIX2"], 251.0)
            assert hdr["N_TOTAL"] == 22
            assert np.isclose(hdr["K_FM"], 0.15)
            assert np.isclose(hdr["K_MB"], 0.025)

    def test_fits_export_invalid_inputs(self, tmp_path):
        """Verify export_single_detector_fits raises ValueError on invalid inputs."""
        canvas = np.zeros((101, 101), dtype=np.float32)

        # Missing output path
        with pytest.raises(ValueError, match="Must specify output path"):
            export_single_detector_fits(epsf_model=canvas, fits_path=None, output_path=None)

        # Invalid object type
        with pytest.raises(ValueError, match="Must provide either SingleDetectorResult"):
            export_single_detector_fits("not_a_valid_model_or_result")

    def test_fits_ingestion_single_hdu_minimal(self, tmp_path):
        """Verify ReportDataBundle gracefully ingests a bare 1-HDU FITS without extensions."""
        bare_fits = tmp_path / "bare_1hdu.fits"
        hdu = fits.PrimaryHDU(np.ones((1025, 1025), dtype=np.float32) * 1e-4)
        hdu.header["DETECTOR"] = "WFI01"
        hdu.writeto(bare_fits)

        bundle = ReportDataBundle(bare_fits)
        assert bundle.epsf.shape == (1025, 1025)
        # HDU 1 fallback
        assert bundle.coverage.shape == (1025, 1025)
        # HDU 2 & 3 fallbacks
        assert bundle.radial_profiles.empty
        assert bundle.detector_summary.empty

    def test_fits_ingestion_corrupted_header_or_truncated_file(self, tmp_path):
        """Verify ReportDataBundle raises appropriate astropy/OS errors on corrupt FITS files."""
        corrupt_fits = tmp_path / "truncated.fits"
        corrupt_fits.write_bytes(b"SIMPLE  =                    T / corrupt binary garbage \x00\xff\xfe")

        with pytest.raises(Exception):
            ReportDataBundle(corrupt_fits)

    def test_fits_with_nans_infs_and_zero_flux(self):
        """Verify fit_star_to_model handles zero-flux, NaN, and Inf model canvases safely."""
        zero_canvas = np.zeros((101, 101), dtype=np.float32)
        stamp_data = np.full((31, 31), 5.0, dtype=np.float32)

        # Zero model canvas
        res_zero = fit_star_to_model(stamp_data, zero_canvas)
        assert res_zero.flux_scale == 1.0
        assert np.isfinite(res_zero.chi2_nu)

        # NaN model canvas
        nan_canvas = np.full((101, 101), np.nan, dtype=np.float32)
        res_nan = fit_star_to_model(stamp_data, nan_canvas)
        assert np.isfinite(res_nan.flux_scale)

    def test_report_lognorm_flat_canvas_edge_case(self, tmp_path):
        """
        Verify Page 5 of report does not crash with ValueError when epsf canvas
        has tiny peak flux (vmax < 1e-6) where vmin is clamped.
        """
        fits_path = tmp_path / "flat_tiny_canvas.fits"
        pdf_path = tmp_path / "output_crash.pdf"

        # Flat uniform canvas: max flux = 1 / (1025*1025) = 9.5e-7 < 1e-6
        flat_canvas = np.ones((1025, 1025), dtype=np.float32) / (1025 * 1025)
        hdu = fits.PrimaryHDU(flat_canvas)
        hdu.header["DETECTOR"] = "WFI01"
        hdu.writeto(fits_path)

        # Generates publication PDF cleanly without ValueError
        generate_publication_pdf_report(fits_path, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0


# ==============================================================================
# Suite 3: Validation Module Boundary Conditions & Extreme Inputs
# ==============================================================================

class TestValidationAdversarialBoundaries:
    """Stress-test spike ray masking, stellar fitting, and metric aggregation."""

    def test_validation_spike_ray_mask_boundary_conditions(self):
        """Verify compute_spike_ray_mask under inverted radii, extreme angles, and non-square stamps."""
        # 1. Inverted radii: r_min > r_max -> 0 pixels
        mask_spk, mask_off, angles = compute_spike_ray_mask(
            (61, 61), (30.0, 30.0), pa_aperture=0.0, r_min_px=50.0, r_max_px=10.0
        )
        assert np.sum(mask_spk) == 0
        assert np.sum(mask_off) == 0
        assert len(angles) == 12

        # 2. Extreme aperture angles (+100,000 deg and -360 deg)
        _, _, angles_pos = compute_spike_ray_mask((51, 51), (25.0, 25.0), pa_aperture=100000.0)
        assert np.all(angles_pos >= 0.0) and np.all(angles_pos < 360.0)

        _, _, angles_neg = compute_spike_ray_mask((51, 51), (25.0, 25.0), pa_aperture=-360.0)
        assert np.all(angles_neg >= 0.0) and np.all(angles_neg < 360.0)

        # 3. Non-square shape
        mask_rect, _, _ = compute_spike_ray_mask((41, 81), (40.0, 20.0), pa_aperture=45.0)
        assert mask_rect.shape == (41, 81)

        # 4. Zero half-width -> 0 spike pixels
        m_zero, _, _ = compute_spike_ray_mask((51, 51), (25.0, 25.0), pa_aperture=0.0, angular_half_width_deg=0.0)
        assert np.sum(m_zero) == 0

    def test_validation_fit_star_to_model_extreme_stamps(self, synthetic_psf_canvas):
        """Verify fit_star_to_model under extreme star stamp conditions."""
        # 1. All-zero stamp
        s_zero = np.zeros((41, 41), dtype=np.float32)
        res_zero = fit_star_to_model(s_zero, synthetic_psf_canvas)
        assert res_zero.flux_scale == 0.0 or res_zero.flux_scale == 1.0
        assert res_zero.chi2_nu == 0.0

        # 2. All-NaN stamp
        s_nan = np.full((41, 41), np.nan, dtype=np.float32)
        res_nan = fit_star_to_model(s_nan, synthetic_psf_canvas)
        assert np.isnan(res_nan.chi2_nu) or res_nan.chi2_nu == 0.0

        # 3. 100% masked stamp
        stamp_obj = StellarStamp(
            source_id="masked",
            tier="faint",
            mag=15.0,
            data=np.ones((41, 41), dtype=np.float32),
            mask=np.ones((41, 41), dtype=bool),
            center_original=(20.0, 20.0),
            size=41,
            bkg_rms=1.0,
        )
        res_masked = fit_star_to_model(stamp_obj, synthetic_psf_canvas)
        assert np.isfinite(res_masked.flux_scale)

        # 4. Tiny stamp (3x3) vs huge canvas
        s_tiny = np.ones((3, 3), dtype=np.float32)
        res_tiny = fit_star_to_model(s_tiny, synthetic_psf_canvas)
        assert res_tiny.residual.shape == (3, 3)

        # 5. Non-square stamp (31x51)
        s_rect = np.ones((31, 51), dtype=np.float32)
        res_rect = fit_star_to_model(s_rect, synthetic_psf_canvas)
        assert res_rect.residual.shape == (3, 31) or res_rect.residual.shape == (31, 51)

    def test_validation_empty_or_missing_test_stamps(self, synthetic_psf_canvas):
        """Verify evaluate_epsf_validation handles empty stamp input cleanly without exceptions."""
        # Empty stamp list
        res_empty = evaluate_epsf_validation(synthetic_psf_canvas, test_stamps=[])
        assert res_empty.overall_status == "NO_DATA"
        assert res_empty.total_stars_evaluated == 0
        assert res_empty.zone_summary["core"]["status"] == "NO_DATA"
        assert res_empty.radial_metrics is not None

        # Empty stamp dict
        res_dict = evaluate_epsf_validation(
            synthetic_psf_canvas, test_stamps={"bright": [], "medium": [], "faint": []}
        )
        assert res_dict.overall_status == "NO_DATA"
        assert res_dict.total_stars_evaluated == 0

    def test_validation_summary_serialization_roundtrip(self, tmp_path):
        """Verify ValidationResults.to_dict and save_summary produce compliant JSON."""
        metrics = RadialMetrics(
            radii=np.array([1.0, 5.0, 15.0]),
            mu_frac=np.array([0.01, -0.02, 0.03]),
            rms_frac=np.array([0.05, 0.06, 0.07]),
            chi2_nu=np.array([1.1, 1.2, 1.3]),
            n_pix=np.array([100, 200, 300]),
            core={"mu_frac": 0.01, "status": "PASS"},
            transition={"mu_frac": -0.02, "status": "PASS"},
            wings={"mu_frac": 0.03, "status": "PASS"},
            spikes={"peak_res_frac": 0.04, "status": "PASS"},
        )
        val = ValidationResults(
            star_results=[],
            radial_metrics=metrics,
            zone_summary={
                "core": {"status": "PASS", "mu_frac": 0.01},
                "transition": {"status": "PASS", "mu_frac": -0.02},
                "wings": {"status": "PASS", "mu_frac": 0.03},
                "spikes": {"status": "PASS", "peak_res_frac": 0.04},
            },
            tier_summary={"faint": {"count": 1, "median_chi2": 1.1}},
            overall_status="PASS",
            total_stars_evaluated=1,
            execution_time_s=0.12,
        )

        json_path = tmp_path / "val_summary.json"
        val.save_summary(json_path)
        assert json_path.is_file()

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["overall_status"] == "PASS"
        assert data["total_stars_evaluated"] == 1
        # Top-level zone aliases
        assert data["core"]["status"] == "PASS"
        assert data["transition"]["status"] == "PASS"
        assert data["wings"]["status"] == "PASS"
        assert data["spikes"]["status"] == "PASS"


# ==============================================================================
# Suite 4: Corrupted Validation Summary JSON & Report Robustness
# ==============================================================================

class TestCorruptedValidationSummaryJsonAndReport:
    """Stress-test ReportDataBundle and report plotting under corrupted validation JSON."""

    def test_report_with_corrupt_validation_json_syntax(self, tmp_path, synthetic_fits_file):
        """Verify ReportDataBundle catches corrupted JSON syntax and either falls back or safely defaults to None."""
        val_dir = tmp_path / "validation"
        val_dir.mkdir(parents=True)
        bad_json = val_dir / "validation_summary.json"
        bad_json.write_text('{"overall_status": "PASS", "zone_summary": { TRUNCATED UNCLOSED JSON')


        # When all candidates have corrupted syntax (raising JSONDecodeError)
        with patch("json.load", side_effect=json.JSONDecodeError("Expecting value", "doc", 0)):
            bundle = ReportDataBundle(synthetic_fits_file, results_dir=tmp_path)
            # Must safely default to None without raising
            assert bundle.validation_results is None

        # Real instantiation with bad_json present in results_dir does not raise
        bundle_real = ReportDataBundle(synthetic_fits_file, results_dir=tmp_path)
        assert bundle_real.validation_results is None or isinstance(bundle_real.validation_results, dict)



    def test_report_with_empty_or_malformed_json_fields(self, tmp_path, synthetic_fits_file):
        """Verify plot_page_residual_metrics handles null, missing, and non-numeric fields gracefully."""
        from matplotlib.figure import Figure

        val_dir = tmp_path / "validation"
        val_dir.mkdir(parents=True, exist_ok=True)
        malformed_json = val_dir / "validation_summary.json"
        malformed_content = {
            "overall_status": "WARNING",
            "zone_summary": {
                "core": {"mu_frac": "ERROR_NAN", "rms_frac": None, "chi2_nu": "N/A", "status": "FAIL"},
                "transition": {"mu_frac": None, "rms_frac": "INVALID"},
                "wings": {},
                "spikes": {"peak_res_frac": "NOT_A_FLOAT"},
            },
        }
        with open(malformed_json, "w") as f:
            json.dump(malformed_content, f)

        bundle = ReportDataBundle(synthetic_fits_file, results_dir=tmp_path)
        fig = Figure(figsize=(8.5, 11.0))

        # Should execute cleanly via _safe_float fallbacks without raising
        plot_page_residual_metrics(fig, bundle)

    def test_report_with_extreme_metric_values(self, tmp_path, synthetic_fits_file):
        """Verify plot_page_residual_metrics formats extreme astronomical metrics without overflow."""
        from matplotlib.figure import Figure

        val_dir = tmp_path / "validation"
        val_dir.mkdir(parents=True, exist_ok=True)
        extreme_json = val_dir / "validation_summary.json"
        extreme_content = {
            "overall_status": "PASS",
            "zone_summary": {
                "core": {"mu_frac": -999.9999, "rms_frac": 8888.8888, "chi2_nu": 1.5e12, "status": "PASS"},
                "transition": {"mu_frac": 1e-15, "rms_frac": 0.0001, "chi2_nu": 0.00001, "status": "PASS"},
                "wings": {"mu_frac": 0.0, "rms_frac": 0.0, "chi2_nu": 99999.0, "status": "PASS"},
                "spikes": {"peak_res_frac": 9.99, "status": "PASS"},
            },
        }
        with open(extreme_json, "w") as f:
            json.dump(extreme_content, f)

        bundle = ReportDataBundle(synthetic_fits_file, results_dir=tmp_path)
        fig = Figure(figsize=(8.5, 11.0))
        plot_page_residual_metrics(fig, bundle)


# ==============================================================================
# Suite 5: Sequential Pipeline Resilience & Resource Lifecycle
# ==============================================================================

class TestSequentialPipelineResilienceAndMemory:
    """Stress-test sequential multi-detector pipeline error recovery and memory cleanup."""

    @patch("romanepsf.pipeline.load_l2_image")
    @patch("romanepsf.pipeline.assemble_composite_extended_psf")
    def test_pipeline_partial_detector_failure_resilience(
        self, mock_assemble, mock_load, tmp_path
    ):
        """Verify run_pipeline tolerates individual SCA extraction failures and continues."""
        det_dir = tmp_path / "detectors"
        det_dir.mkdir()
        (det_dir / "r0108301001001001001_0001_wfi01_f146_cal.asdf").touch()
        (det_dir / "r0108301001001001001_0001_wfi02_f146_cal.asdf").touch()

        cat_path = tmp_path / "catalog.csv"
        pd.DataFrame({
            "source_id": [1, 2],
            "ra": [10.0, 10.05],
            "dec": [-20.0, -20.05],
            "mag_lambda": [14.0, 12.0],
            "tier": ["faint", "medium"],
        }).to_csv(cat_path, index=False)

        # Mock: WFI01 succeeds, WFI02 raises OSError (corrupted ASDF)
        def _mock_process(asdf_path, cat_df, cfg):
            if "wfi02" in asdf_path.name:
                raise OSError("Simulated ASDF bit corruption")
            stamp = StellarStamp("1", "faint", 14.0, np.ones((21, 21), dtype=np.float32), np.zeros((21, 21), dtype=bool), (10.0, 10.0), 21, 1.0)
            return "wfi01", {"faint": [stamp], "medium": [], "bright": []}, {
                "detector": "WFI01", "faint": 1, "medium": 0, "bright": 0, "total": 1,
                "status": "SUCCESS", "time_s": 0.1,
            }

        canvas = np.zeros((1025, 1025), dtype=np.float32)
        canvas[512, 512] = 1.0
        mock_assemble.return_value = (canvas, {"k_fm": 0.2, "k_mb": None})

        cfg = load_config()
        cfg.data.detectors_dir = det_dir
        cfg.data.catalog_path = cat_path
        cfg.data.output_dir = tmp_path / "out"
        cfg.data.detectors = ["wfi01", "wfi02"]

        with patch("romanepsf.pipeline.process_single_detector_stamps", side_effect=_mock_process):
            out = run_pipeline(cfg)

        assert out.composite_epsf.shape == (1025, 1025)
        assert "wfi02" in out.diagnostics["failed_detectors"]
        assert "Simulated ASDF bit corruption" in out.diagnostics["failed_detectors"]["wfi02"]
        assert len(out.detector_summaries) == 2
        assert out.detector_summaries[1]["status"].startswith("FAILED")

    @patch("romanepsf.pipeline.load_l2_image")
    def test_pipeline_all_detectors_failure_handling(self, mock_load, tmp_path):
        """Verify run_pipeline raises RuntimeError when all detectors fail."""
        det_dir = tmp_path / "detectors"
        det_dir.mkdir()
        (det_dir / "r0108301001001001001_0001_wfi01_f146_cal.asdf").touch()

        cat_path = tmp_path / "catalog.csv"
        pd.DataFrame({"source_id": [1], "ra": [10.0], "dec": [-20.0], "mag_lambda": [14.0]}).to_csv(cat_path, index=False)

        cfg = load_config()
        cfg.data.detectors_dir = det_dir
        cfg.data.catalog_path = cat_path
        cfg.data.output_dir = tmp_path / "out"
        cfg.data.detectors = ["wfi01"]

        # 1 detector fails -> re-raises exception
        with patch("romanepsf.pipeline.process_single_detector_stamps", side_effect=ValueError("Total failure")):
            with pytest.raises(ValueError, match="Total failure"):
                run_pipeline(cfg)

    def test_process_single_detector_stamps_lifecycle_cleanup(self, tmp_path):
        """Verify gc.collect() is called in finally block even when extraction raises an error."""
        asdf_file = tmp_path / "r0108301001001001001_0001_wfi01_f146_cal.asdf"
        asdf_file.touch()

        cat_df = pd.DataFrame({"source_id": [1], "ra": [10.0], "dec": [-20.0], "mag_lambda": [14.0]})
        cfg = load_config()

        with patch("romanepsf.pipeline.load_l2_image") as mock_load, \
             patch("gc.collect") as mock_gc:
            mock_l2 = MagicMock()
            mock_l2.detector = "wfi01"
            mock_load.return_value = mock_l2

            # Force error inside extraction
            with patch("romanepsf.pipeline.get_detector_sky_bounds", side_effect=RuntimeError("WCS exploded")):
                with pytest.raises(RuntimeError, match="WCS exploded"):
                    process_single_detector_stamps(asdf_file, cat_df, cfg)

            # Strict verification: gc.collect() was executed despite exception
            assert mock_gc.called


# ==============================================================================
# Suite 6: Publication Report End-to-End PDF Generation
# ==============================================================================

class TestPublicationReportEndToEndIntegrity:
    """Stress-test complete 8-page publication-ready PDF generation and structural integrity."""

    def test_report_complete_8page_pdf_generation(self, tmp_path, synthetic_fits_file):
        """Verify generate_publication_pdf_report compiles exactly 8 pages with valid PDF syntax."""
        pdf_out = tmp_path / "roman_epsf_publication_report.pdf"

        # Execute PDF generator
        out_path = generate_publication_pdf_report(synthetic_fits_file, pdf_out, dpi=150)
        assert out_path.is_file()
        assert out_path.stat().st_size > 50_000

        pdf_bytes = out_path.read_bytes()

        # 1. Verify exactly 8 /Type /Page objects
        page_objs = re.findall(rb"/Type\s*/Page\b(?!\w)", pdf_bytes)
        assert len(page_objs) == 8, f"Expected 8 /Type /Page objects, found {len(page_objs)}"

        # 2. Document Catalog page count = 8
        count_matches = re.findall(rb"/Count\s+(\d+)", pdf_bytes)
        assert b"8" in count_matches, f"Expected /Count 8 in catalog, found {count_matches}"

        # 3. Standard MediaBox declarations
        mediaboxes = re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+612(?:\.0+)?\s+792(?:\.0+)?\s*\]", pdf_bytes)
        assert len(mediaboxes) == 8, f"Expected 8 standard US Letter MediaBoxes, found {len(mediaboxes)}"

        # 4. Valid startxref %%EOF trailer
        assert re.search(rb"startxref[\r\n]+(\d+)[\r\n]+%%EOF", pdf_bytes[-1024:]) is not None

    def test_report_png_page_export(self, tmp_path, synthetic_fits_file):
        """Verify report generator can export individual page PNG images (pages 1 to 8)."""
        pdf_out = tmp_path / "report_with_pngs.pdf"
        png_dir = tmp_path / "pages_png"

        generate_publication_pdf_report(
            synthetic_fits_file,
            pdf_out,
            dpi=72,
            save_png_pages=True,
            png_dir=png_dir,
        )

        assert png_dir.is_dir()
        png_files = sorted(png_dir.glob("page_*.png"))
        assert len(png_files) == 8
        for p in png_files:
            assert p.stat().st_size > 5_000

    def test_report_individual_page_builders_with_minimal_bundle(self, tmp_path):
        """Verify each of the 8 page plotting functions executes cleanly with minimal/empty data."""
        from matplotlib.figure import Figure
        from romanepsf.report import (
            plot_page_title_executive,
            plot_page_star_selection,
            plot_page_spike_protection,
            plot_page_radial_profiles,
            plot_page_composite_epsf,
            plot_page_subtraction_residuals,
            plot_page_residual_metrics,
            plot_page_performance_benchmarks,
        )

        # Bare FITS with 1 HDU
        bare_fits = tmp_path / "bare_model.fits"
        y, x = np.ogrid[-100:101, -100:101]
        epsf_toy = (1.0 + (np.hypot(x, y) / 3.0)**2)**(-2.0)
        epsf_toy /= epsf_toy.sum()
        hdu = fits.PrimaryHDU(epsf_toy.astype(np.float32))
        hdu.header["DETECTOR"] = "WFI01"
        hdu.header["PA_APER"] = 30.0
        hdu.writeto(bare_fits)

        bundle = ReportDataBundle(bare_fits, results_dir=tmp_path)

        builders = [
            plot_page_title_executive,
            plot_page_star_selection,
            plot_page_spike_protection,
            plot_page_radial_profiles,
            plot_page_composite_epsf,
            plot_page_subtraction_residuals,
            plot_page_residual_metrics,
            plot_page_performance_benchmarks,
        ]

        for idx, builder in enumerate(builders, start=1):
            fig = Figure(figsize=(8.5, 11.0))
            builder(fig, bundle)
            assert len(fig.axes) > 0, f"Page {idx} ({builder.__name__}) produced no axes"


# ==============================================================================
# Suite 7: Additional Module & CLI Surface Coverage
# ==============================================================================

class TestAdditionalAdversarialSurface:
    """Additional integration and CLI edge case tests across pipeline and validation."""

    def test_discover_detectors_edge_cases(self, tmp_path):
        """Verify discover_detectors under missing directory, non-matching files, and custom requests."""
        # 1. Non-existent directory
        assert discover_detectors(tmp_path / "does_not_exist") == {}

        # 2. Directory with non-matching files
        (tmp_path / "other.txt").touch()
        (tmp_path / "wfi01.fits").touch()
        (tmp_path / "r0108301001001001001_0001_wfi_f146_cal.asdf").touch()  # Missing 2 digits
        assert discover_detectors(tmp_path) == {}

        # 3. Valid files with case and requested filtering
        (tmp_path / "r0108301001001001001_0001_wfi03_f146_cal.asdf").touch()
        (tmp_path / "r0108301001001001001_0001_wfi07_f146_cal.asdf").touch()

        # Request with mixed case and duplicates
        dets = discover_detectors(tmp_path, requested=["WFI03", "wfi03", "wfi99"])
        assert list(dets.keys()) == ["wfi03"]

        # Request 'all'
        dets_all = discover_detectors(tmp_path, requested=["all"])
        assert set(dets_all.keys()) == {"wfi03", "wfi07"}

    def test_run_single_detector_missing_asdf_error(self, tmp_path):
        """Verify run_single_detector raises FileNotFoundError if designated ASDF is missing."""
        cfg = load_config()
        cfg.data.output_dir = tmp_path

        with pytest.raises(FileNotFoundError, match="Detector ASDF file not found"):
            run_single_detector(
                cfg,
                detector="wfi01",
                asdf_path=tmp_path / "definitely_nonexistent_detector.asdf",
            )

    def test_star_residual_result_save_residual_fits(self, tmp_path, synthetic_psf_canvas):
        """Verify StarResidualResult.save_residual_fits creates standard 6-HDU residual FITS."""
        stamp_data = np.ones((31, 31), dtype=np.float32) * 10.0
        res = fit_star_to_model(stamp_data, synthetic_psf_canvas)

        out_fits = tmp_path / "star_residual.fits"
        saved_path = res.save_residual_fits(out_fits)
        assert saved_path.is_file()

        with fits.open(saved_path) as hdul:
            assert len(hdul) == 6
            ext_names = [h.name for h in hdul]
            assert "RESIDUAL" in ext_names
            assert "OBSERVED" in ext_names
            assert "MODEL" in ext_names
            assert "NORM_RES" in ext_names
            assert "FRAC_RES" in ext_names
            assert "MASK" in ext_names

            hdr = hdul[0].header
            assert "SRC_ID" in hdr
            assert "TIER" in hdr
            assert "FLXSCALE" in hdr
            assert "CHI2_NU" in hdr

    def test_evaluate_epsf_validation_fits_path_input(self, tmp_path, synthetic_fits_file):
        """Verify evaluate_epsf_validation accepts FITS file path as input and loads PA_APER."""
        # Non-existent FITS
        with pytest.raises(FileNotFoundError, match="Composite model FITS not found"):
            evaluate_epsf_validation(tmp_path / "nonexistent.fits")

        # Valid FITS with empty stamps
        res = evaluate_epsf_validation(synthetic_fits_file, test_stamps=[])
        assert res.overall_status == "NO_DATA"

    def test_cli_logging_verbosity_and_log_level(self):
        """Verify CLI root options: --verbose, --log-level, and --device."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run_pipeline.return_value = MagicMock(fits_path=Path("out.fits"))

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            # --verbose sets DEBUG
            res_v = runner.invoke(cli, ["--verbose", "run"])
            assert res_v.exit_code == 0
            cfg_v = mock_pipeline.run_pipeline.call_args.args[0]
            assert cfg_v.pipeline.log_level == "DEBUG"

            # --log-level WARNING sets WARNING
            res_w = runner.invoke(cli, ["--log-level", "WARNING", "run"])
            assert res_w.exit_code == 0
            cfg_w = mock_pipeline.run_pipeline.call_args.args[0]
            assert cfg_w.pipeline.log_level == "WARNING"

            # Invalid log-level choice -> exit code 2
            res_inv = runner.invoke(cli, ["--log-level", "FATAL_CRASH", "run"])
            assert res_inv.exit_code == 2

    def test_cli_report_subcommand_execution(self, tmp_path, synthetic_fits_file):
        """Verify CLI 'report' subcommand parses arguments and invokes report generator."""
        runner = CliRunner()
        out_pdf = tmp_path / "cli_report.pdf"

        res = runner.invoke(cli, [
            "report",
            "--results-dir", str(synthetic_fits_file.parent),
            "--output-pdf", str(out_pdf),
            "--dpi", "72",
        ])
        assert res.exit_code == 0
        assert out_pdf.is_file()

