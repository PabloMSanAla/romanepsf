"""
Adversarial Stress Test Suite: Remediated Report Generator & Validation Module.

Author: challenger_m4_it2_1
Target:
  - src/romanepsf/report.py
  - src/romanepsf/validation.py

Test Vectors:
  1. np.random isolation / zero-random purity check
  2. Page 6 residual FITS ingestion (missing, truncated, corrupted, missing HDUs)
  3. Page 7 empirical radial curves and azimuthal scan (empty, NaN/Inf, all masked, corrupted bright FITS, null JSON metrics)
  4. Page 8 empirical benchmarks (missing HDU 3, missing TIME_SEC, partial SCA counts N != 18)
  5. Full pipeline stress under adversarial edge conditions
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import matplotlib.pyplot as plt
import numpy as np
import pytest
from astropy.io import fits

from romanepsf.report import (
    ReportDataBundle,
    extract_empirical_azimuthal_profile,
    extract_empirical_radial_residual_profiles,
    generate_publication_pdf_report,
    load_tier_residual_data,
    plot_page_performance_benchmarks,
    plot_page_residual_metrics,
    plot_page_subtraction_residuals,
)


@pytest.fixture(autouse=False)
def poison_random():
    """Monkeypatch numpy.random to fail immediately on any call."""
    def _poison(*args, **kwargs):
        raise AssertionError("VIOLATION: np.random was called during deterministic report generation!")

    orig_funcs = {}
    patch_targets = [
        "normal", "uniform", "random", "rand", "randn", "choice",
        "seed", "randint", "exponential", "standard_normal",
    ]
    for target in patch_targets:
        if hasattr(np.random, target):
            orig_funcs[target] = getattr(np.random, target)
            setattr(np.random, target, _poison)

    yield

    for target, orig in orig_funcs.items():
        setattr(np.random, target, orig)


@pytest.fixture
def sample_fits_bundle():
    """Locate real composite FITS model from previous pipeline runs."""
    cand_paths = [
        Path("output/run_all/roman_epsf_composite.fits"),
        Path("output/roman_epsf_composite.fits"),
        Path("output/single_wfi01/roman_epsf_wfi01.fits"),
    ]
    for p in cand_paths:
        if p.is_file():
            return p, Path("output/run_all") if "run_all" in str(p) else Path("output")
    pytest.skip("No real composite FITS model available in output/ to construct bundle.")


# ==============================================================================
# Vector 1: np.random Isolation (Purity Check)
# ==============================================================================

def test_adv_vector1_zero_np_random_during_full_report_compilation(sample_fits_bundle, poison_random):
    """
    Verify that monkeypatching np.random to raise an AssertionError passes cleanly
    during full 8-page PDF report compilation. Zero np.random calls are permitted.
    """
    fits_path, results_dir = sample_fits_bundle
    with tempfile.TemporaryDirectory() as tmpdir:
        out_pdf = Path(tmpdir) / "adversarial_pure_report.pdf"
        res_path = generate_publication_pdf_report(
            input_source=fits_path,
            output_pdf_path=out_pdf,
            dpi=150,
        )
        assert res_path.is_file()
        assert res_path.stat().st_size > 500_000
        with open(res_path, "rb") as f:
            header = f.read(5)
            assert header == b"%PDF-"


# ==============================================================================
# Vector 2: Page 6 Residual FITS Ingestion & Corrupted Files
# ==============================================================================

def test_adv_vector2a_page6_missing_residual_fits_clean_fallback():
    """
    When no residual FITS files are present in search_dirs,
    verify that load_tier_residual_data falls back to deterministic mock stars
    without crashing or invoking random noise.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        empty_dir = tmp / "empty_val"
        empty_dir.mkdir()

        class MockBundle:
            results_dir = empty_dir
            fits_path = empty_dir / "dummy.fits"
            epsf = np.ones((501, 501), dtype=np.float32) * 1e-4

        tier_data, any_mock = load_tier_residual_data(MockBundle(), search_dirs=[empty_dir])
        assert any_mock is True
        for t in ["bright", "medium", "faint"]:
            assert t in tier_data
            assert tier_data[t]["is_mock"] is True
            assert np.all(np.isfinite(tier_data[t]["observed"]))
            assert np.all(np.isfinite(tier_data[t]["model"]))
            assert tier_data[t]["source_id"] == "MOCK"

        # Verify page 6 renders cleanly on fallback data
        fig = plt.figure(figsize=(8.5, 11))
        plot_page_subtraction_residuals(fig, MockBundle(), search_dirs=[empty_dir])
        plt.close(fig)


def test_adv_vector2b_page6_corrupted_residual_fits_handling():
    """
    Adversarial challenge: Residual FITS file on disk is truncated / corrupted (not a valid FITS).
    Verification check: Does load_tier_residual_data gracefully catch the corruption and fall back,
    or does it crash with an unhandled OSError?
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        corrupt_f = tmp / "residual_bright_9999.fits"
        corrupt_f.write_bytes(b"CORRUPTED_GARBAGE_HEADER_DATA_NOT_A_FITS_FILE\x00\xff" * 50)

        class MockBundle:
            results_dir = tmp
            fits_path = tmp / "dummy.fits"
            epsf = np.ones((501, 501), dtype=np.float32) * 1e-4

        # This should either fall back gracefully or raise an informative handled error.
        tier_data, any_mock = load_tier_residual_data(MockBundle(), search_dirs=[tmp])
        assert "bright" in tier_data


def test_adv_vector2c_page6_incomplete_residual_fits_missing_hdus():
    """
    Adversarial challenge: Residual FITS file exists and opens, but is missing required HDUs
    ('OBSERVED', 'MODEL', 'RESIDUAL', 'NORM_RES', 'FRAC_RES').
    Verification check: Does load_tier_residual_data crash with KeyError or fall back gracefully?
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        bad_f = tmp / "residual_medium_8888.fits"
        # Primary HDU only, missing all image extension HDUs
        phdu = fits.PrimaryHDU(np.zeros((30, 30), dtype=np.float32))
        phdu.header["TIER"] = "medium"
        phdu.header["CHI2_NU"] = 1.05
        fits.HDUList([phdu]).writeto(bad_f)

        class MockBundle:
            results_dir = tmp
            fits_path = tmp / "dummy.fits"
            epsf = np.ones((501, 501), dtype=np.float32) * 1e-4

        tier_data, any_mock = load_tier_residual_data(MockBundle(), search_dirs=[tmp])
        assert "medium" in tier_data


# ==============================================================================
# Vector 3: Page 7 Empirical Radial Curves & Azimuthal Profile Stress
# ==============================================================================

def test_adv_vector3a_page7_radial_curves_empty_results():
    """
    Test extract_empirical_radial_residual_profiles when no residual files exist anywhere.
    Annular binning must return finite bin_centers and composite arrays initialized to NaN
    without raising zero-division errors.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_dir = Path(tmpdir)
        with patch("romanepsf.report.Path.glob", return_value=[]):
            res = extract_empirical_radial_residual_profiles(empty_dir, r_max=180.0, n_bins=90)
            assert res["has_data"] is False
            assert len(res["bin_centers"]) == 90
            assert np.all(np.isnan(res["composite_mu"]))
            assert np.all(np.isnan(res["composite_rms"]))


def test_adv_vector3b_page7_radial_curves_nans_infs_and_masked():
    """
    Adversarial challenge: Residual FITS contains NaNs, Infs, negative flux values,
    and all pixels masked.
    Verify that annular binning computes finite statistics or clean NaNs without unhandled exceptions.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        bad_f = tmp / "residual_faint_7777.fits"
        shape = (101, 101)
        obs = np.full(shape, np.nan, dtype=np.float32)
        mod = np.full(shape, np.inf, dtype=np.float32)
        frac = np.full(shape, -999.0, dtype=np.float32)
        mask = np.ones(shape, dtype=np.uint8)  # all pixels masked

        hdul = fits.HDUList([
            fits.PrimaryHDU(),
            fits.ImageHDU(obs, name="OBSERVED"),
            fits.ImageHDU(mod, name="MODEL"),
            fits.ImageHDU(frac, name="FRAC_RES"),
            fits.ImageHDU(mask, name="MASK"),
        ])
        hdul[0].header["TIER"] = "faint"
        hdul.writeto(bad_f)

        res = extract_empirical_radial_residual_profiles(tmp, r_max=180.0, n_bins=90)
        assert res["has_data"] is True
        # Since all pixels are masked/invalid, profiles must be NaNs without division by zero crash
        assert np.all(np.isnan(res["composite_mu"]))
        assert np.all(np.isnan(res["composite_rms"]))


def test_adv_vector3c_page7_corrupted_bright_residual_in_azimuthal_scan():
    """
    Adversarial challenge: Bright residual FITS file is corrupted on disk.
    Verification check: Does extract_empirical_azimuthal_profile fall back to epsf_canvas
    or crash with unhandled OSError/KeyError?
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        corrupt_bright = tmp / "residual_bright_corrupted.fits"
        corrupt_bright.write_bytes(b"BAD_FITS_HEADER\x00")

        epsf_canvas = np.ones((501, 501), dtype=np.float32) * 1e-4

        data = extract_empirical_azimuthal_profile(tmp, epsf_canvas=epsf_canvas)
        assert "theta_deg" in data
        assert len(data["theta_deg"]) == 180


def test_adv_vector3d_page7_malformed_json_null_metrics():
    """
    Adversarial challenge: validation_summary.json contains null / None values for zone metrics.
    Verification check: Does plot_page_residual_metrics handle None metrics without
    TypeError: unsupported format string passed to NoneType.__format__?
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        val_json = tmp / "validation_summary.json"
        val_json.write_text(json.dumps({
            "zone_summary": {
                "core": {"mu_frac": None, "rms_frac": None, "chi2_nu": None, "status": "PASS"},
                "transition": {"mu_frac": 0.01, "rms_frac": 0.05, "chi2_nu": 1.1, "status": "PASS"},
            }
        }))

        class MockBundle:
            results_dir = tmp
            fits_path = tmp / "dummy.fits"
            epsf = np.ones((501, 501), dtype=np.float32) * 1e-4
            validation_results = None

        fig = plt.figure(figsize=(8.5, 11))
        plot_page_residual_metrics(fig, MockBundle())
        plt.close(fig)


# ==============================================================================
# Vector 4: Page 8 Empirical Benchmarks & HDU 3 Resilience
# ==============================================================================

def test_adv_vector4a_page8_missing_hdu3_fallback():
    """
    When HDU 3 (detector summary) is completely missing from the FITS file,
    verify that plot_page_performance_benchmarks falls back cleanly to
    standard 18-detector benchmark constants without KeyError.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        fits_path = tmp / "epsf_no_hdu3.fits"
        # Only HDU 0, 1, 2 (no HDU 3)
        h0 = fits.PrimaryHDU(np.zeros((101, 101), dtype=np.float32))
        h1 = fits.ImageHDU(np.ones((101, 101), dtype=np.int32))
        h2 = fits.BinTableHDU(fits.FITS_rec.from_columns([
            fits.Column(name="RADIUS", format="D", array=np.arange(10)),
        ]))
        fits.HDUList([h0, h1, h2]).writeto(fits_path)

        bundle = ReportDataBundle(fits_path, results_dir=tmp)
        fig = plt.figure(figsize=(8.5, 11))
        plot_page_performance_benchmarks(fig, bundle)
        plt.close(fig)


def test_adv_vector4b_page8_partial_detector_count_missing_time_sec():
    """
    Adversarial challenge: HDU 3 is present for a partial run (e.g. N = 5 detectors),
    but TIME_SEC is missing from the table.
    Verification check: Does ax_time.bar(dets, times) raise a shape mismatch ValueError
    between 5 detectors and 18 times?
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        fits_path = tmp / "epsf_5det.fits"
        h0 = fits.PrimaryHDU(np.zeros((101, 101), dtype=np.float32))
        h1 = fits.ImageHDU(np.ones((101, 101), dtype=np.int32))
        h2 = fits.BinTableHDU(fits.FITS_rec.from_columns([
            fits.Column(name="RADIUS", format="D", array=np.arange(10)),
        ]))
        # 5 detectors table, NO TIME_SEC or EXEC_SEC column
        cols = [
            fits.Column(name="DETECTOR", format="5A", array=["WFI01", "WFI02", "WFI03", "WFI04", "WFI05"]),
            fits.Column(name="NSTARS", format="J", array=[1, 2, 3, 4, 5]),
        ]
        h3 = fits.BinTableHDU.from_columns(cols)
        fits.HDUList([h0, h1, h2, h3]).writeto(fits_path)

        bundle = ReportDataBundle(fits_path, results_dir=tmp)
        fig = plt.figure(figsize=(8.5, 11))
        plot_page_performance_benchmarks(fig, bundle)
        plt.close(fig)


# ==============================================================================
# Vector 5: End-to-End Report Compilation under Corrupted Environment
# ==============================================================================

def test_adv_vector5_full_report_with_corrupted_residual_fits(sample_fits_bundle):
    """
    Adversarial challenge: Full report compilation executed in a results directory
    where a corrupted residual FITS file is present.
    Verification check: Does generate_publication_pdf_report crash with OSError or fall back cleanly?
    """
    import shutil
    fits_path, _ = sample_fits_bundle
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Copy valid composite FITS model to tmp
        shutil.copy(fits_path, tmp / "roman_epsf_composite.fits")
        # Place a corrupted residual FITS in the results dir
        corrupt_f = tmp / "residual_bright_corrupted.fits"
        corrupt_f.write_text("CORRUPTED NOT FITS FILE")

        out_pdf = tmp / "output_report.pdf"
        res_path = generate_publication_pdf_report(
            input_source=tmp,
            output_pdf_path=out_pdf,
            dpi=150,
        )
        assert res_path.is_file()

