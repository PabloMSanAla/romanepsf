"""
Novel Adversarial Stress Test Suite: Report Generator Edge Cases & Scalability.

Author: challenger_m4_it3_1
Target:
  - src/romanepsf/report.py

Edge Case Dimensions Challenged:
  1. Empty input directories & Non-existent paths (clean FileNotFoundError)
  2. Truncated FITS files with 0 bytes (clean fallback to deterministic mocks / canvas)
  3. Corrupted JSON summaries with completely malformed types (syntax error, non-dict, nulls, NaNs, Infs)
  4. Arbitrary detector counts (N = 1, 2, 7, 25) with missing benchmark columns (HDU 3 TIME_SEC / PEAK_RSS_MB)
  5. Missing tier columns in HDU 2 radial profiles (FLUX_FAINT, etc.)
  6. Missing census columns in HDU 3 detector summary (N_FAINT, etc.)
"""

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from astropy.io import fits

from romanepsf.report import (
    ReportDataBundle,
    extract_empirical_azimuthal_profile,
    extract_empirical_radial_residual_profiles,
    generate_publication_pdf_report,
    load_tier_residual_data,
    plot_page_performance_benchmarks,
    plot_page_radial_profiles,
    plot_page_residual_metrics,
    plot_page_star_selection,
    plot_page_subtraction_residuals,
)


# ==============================================================================
# Dimension 1: Empty Input Directories & Non-Existent Paths
# ==============================================================================

def test_adv_empty_input_directory_raises_filenotfound():
    """Verify that passing an empty results directory cleanly raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_dir = Path(tmpdir) / "empty_dir"
        empty_dir.mkdir()
        out_pdf = Path(tmpdir) / "test.pdf"
        with pytest.raises(FileNotFoundError, match="No composite FITS found"):
            generate_publication_pdf_report(input_source=empty_dir, output_pdf_path=out_pdf)


def test_adv_nonexistent_fits_path_raises_filenotfound():
    """Verify that passing a non-existent FITS path cleanly raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent = Path(tmpdir) / "non_existent.fits"
        out_pdf = Path(tmpdir) / "test.pdf"
        with pytest.raises(FileNotFoundError, match="Input source path does not exist"):
            generate_publication_pdf_report(input_source=non_existent, output_pdf_path=out_pdf)


def test_adv_explicit_composite_fits_nonexistent_raises_filenotfound():
    """Verify that passing a non-existent composite_fits_path cleanly raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent = Path(tmpdir) / "missing.fits"
        with pytest.raises(FileNotFoundError, match="Explicit composite FITS model not found"):
            generate_publication_pdf_report(composite_fits_path=non_existent)


# ==============================================================================
# Dimension 2: Truncated FITS Files with 0 Bytes
# ==============================================================================

def test_adv_truncated_zero_byte_residual_fits_clean_fallback():
    """
    Verify that 0-byte truncated residual FITS files in search_dirs do not cause
    unhandled crashes, but are cleanly caught and routed to deterministic mocks.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for t in ["bright", "medium", "faint"]:
            (tmp / f"residual_{t}_0001.fits").touch()  # 0 bytes

        class MockBundle:
            results_dir = tmp
            fits_path = tmp / "dummy.fits"
            epsf = np.ones((101, 101), dtype=np.float32) * 1e-4

        tier_data, any_mock = load_tier_residual_data(MockBundle(), search_dirs=[tmp])
        assert any_mock is True
        for t in ["bright", "medium", "faint"]:
            assert t in tier_data
            assert tier_data[t]["is_mock"] is True

        fig = plt.figure(figsize=(8.5, 11))
        plot_page_subtraction_residuals(fig, MockBundle(), search_dirs=[tmp])
        plt.close(fig)


def test_adv_truncated_zero_byte_azimuthal_scan_fallback():
    """
    Verify that a 0-byte truncated bright residual FITS does not crash
    extract_empirical_azimuthal_profile and cleanly falls back to epsf_canvas.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "residual_bright_0001.fits").touch()  # 0 bytes
        epsf_canvas = np.ones((101, 101), dtype=np.float32) * 1e-4

        data = extract_empirical_azimuthal_profile(tmp, epsf_canvas=epsf_canvas)
        assert data["has_observed"] is False
        assert "theta_deg" in data
        assert len(data["theta_deg"]) == 180


def test_adv_truncated_zero_byte_radial_profiles_handled():
    """Verify that 0-byte truncated FITS files are safely skipped in radial extraction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "residual_bright_0001.fits").touch()  # 0 bytes
        (tmp / "residual_medium_0001.fits").touch()  # 0 bytes
        data = extract_empirical_radial_residual_profiles(tmp)
        assert data["has_data"] is True


# ==============================================================================
# Dimension 3: Corrupted JSON Summaries with Malformed Types
# ==============================================================================

@pytest.mark.parametrize("payload", [
    "{bad_json: 123",  # syntax error
    '"just a raw string"',  # non-dict root
    "[1, 2, 3]",  # list root
    "42",  # int root
    "true",  # bool root
    "null",  # null root
    json.dumps({"zone_summary": "string"}),  # non-dict zone_summary
    json.dumps({"zone_summary": [1, 2, 3]}),  # list zone_summary
    json.dumps({  # malformed metric types
        "zone_summary": {
            "core": "invalid",
            "transition": [1, 2],
            "wings": {"mu_frac": "not_float", "rms_frac": None, "chi2_nu": "nan"},
            "spikes": None,
        }
    }),
    json.dumps({  # extreme and non-finite numbers
        "zone_summary": {
            "core": {"mu_frac": float("inf"), "rms_frac": float("-inf"), "chi2_nu": float("nan")},
            "transition": {"mu_frac": 1e308, "rms_frac": 1e-308, "chi2_nu": 999999999.0},
        }
    }),
])
def test_adv_corrupted_json_summary_extreme_and_malformed_types(payload: str):
    """Verify that plot_page_residual_metrics withstands malformed/corrupted validation JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        val_file = tmp / "validation_summary.json"
        val_file.write_text(payload)

        class MockBundle:
            results_dir = tmp
            fits_path = tmp / "dummy.fits"
            epsf = np.ones((101, 101), dtype=np.float32) * 1e-4
            validation_results = None

        fig = plt.figure(figsize=(8.5, 11))
        plot_page_residual_metrics(fig, MockBundle())
        plt.close(fig)


# ==============================================================================
# Dimension 4: Arbitrary Detector Counts (N = 1, 2, 7, 25)
# ==============================================================================

@pytest.mark.parametrize("N", [1, 2, 7])
def test_adv_arbitrary_detector_counts_subsets_1_2_7_complete(N: int):
    """Verify that detector counts N=1, 2, 7 render cleanly across Page 2 and Page 8."""
    class MockBundle:
        results_dir = Path("output")
        fits_path = Path("output/run_all/roman_epsf_composite.fits")
        epsf = np.ones((101, 101), dtype=np.float32) * 1e-4
        stars = pd.DataFrame()
        detector_summary = pd.DataFrame({
            "DETECTOR": [f"WFI{i:02d}" for i in range(1, N + 1)],
            "N_FAINT": [5] * N,
            "N_MEDIUM": [3] * N,
            "N_BRIGHT": [1] * N,
            "N_TOTAL": [9] * N,
            "PA_APER_DEG": [-110.0] * N,
            "PIXSCALE": [0.11] * N,
        })

    fig2 = plt.figure(figsize=(8.5, 11))
    plot_page_star_selection(fig2, MockBundle())
    plt.close(fig2)

    fig8 = plt.figure(figsize=(8.5, 11))
    plot_page_performance_benchmarks(fig8, MockBundle())
    plt.close(fig8)


def test_adv_arbitrary_detector_counts_n25_complete():
    """Verify that detector count N=25 renders cleanly when all columns are present."""
    N = 25
    class MockBundle:
        results_dir = Path("output")
        fits_path = Path("output/run_all/roman_epsf_composite.fits")
        epsf = np.ones((101, 101), dtype=np.float32) * 1e-4
        stars = pd.DataFrame()
        detector_summary = pd.DataFrame({
            "DETECTOR": [f"WFI{i:02d}" for i in range(1, N + 1)],
            "N_FAINT": [5] * N,
            "N_MEDIUM": [3] * N,
            "N_BRIGHT": [1] * N,
            "N_TOTAL": [9] * N,
            "PA_APER_DEG": [-110.0] * N,
            "PIXSCALE": [0.11] * N,
            "TIME_SEC": [0.5] * N,
            "PEAK_RSS_MB": [1800.0] * N,
        })

    fig2 = plt.figure(figsize=(8.5, 11))
    plot_page_star_selection(fig2, MockBundle())
    plt.close(fig2)

    fig8 = plt.figure(figsize=(8.5, 11))
    plot_page_performance_benchmarks(fig8, MockBundle())
    plt.close(fig8)


def test_adv_arbitrary_detector_count_n25_missing_benchmark_columns():
    """
    Adversarial Challenge: When N=25 detectors are present but TIME_SEC / PEAK_RSS_MB
    are missing from detector_summary, plot_page_performance_benchmarks must not crash
    with a ValueError broadcast shape mismatch between shape (25,) and shape (18,).
    """
    N = 25
    class MockBundle:
        results_dir = Path("output")
        fits_path = Path("output/run_all/roman_epsf_composite.fits")
        epsf = np.ones((101, 101), dtype=np.float32) * 1e-4
        stars = pd.DataFrame()
        detector_summary = pd.DataFrame({
            "DETECTOR": [f"WFI{i:02d}" for i in range(1, N + 1)],
            # Notice TIME_SEC and PEAK_RSS_MB are missing!
        })

    fig = plt.figure(figsize=(8.5, 11))
    plot_page_performance_benchmarks(fig, MockBundle())
    plt.close(fig)


# ==============================================================================
# Dimension 5: Missing Columns in Radial Profiles and Detector Census
# ==============================================================================

def test_adv_radial_profiles_missing_tier_flux_columns():
    """
    Adversarial Challenge: When HDU 2 radial_profiles has RADIUS_PX and FLUX_COMPOSITE,
    but lacks FLUX_FAINT, plot_page_radial_profiles must not crash with an IndexError
    due to length-1 Series boolean mask indexing.
    """
    class MockBundle:
        header = {}
        radial_profiles = pd.DataFrame({
            "RADIUS_PX": np.arange(10, dtype=float),
            "FLUX_COMPOSITE": np.ones(10, dtype=float) * 1e-3,
            # Missing FLUX_FAINT, FLUX_MED_SCALED, FLUX_BRIGHT_SCALED
        })

    fig = plt.figure(figsize=(8.5, 11))
    plot_page_radial_profiles(fig, MockBundle())
    plt.close(fig)


def test_adv_detector_summary_missing_census_columns():
    """
    Adversarial Challenge: When HDU 3 detector_summary has DETECTOR but lacks
    N_FAINT, N_MEDIUM, N_BRIGHT, etc., plot_page_star_selection must not crash
    with KeyError: 'N_FAINT'.
    """
    class MockBundle:
        stars = pd.DataFrame()
        detector_summary = pd.DataFrame({
            "DETECTOR": ["WFI01", "WFI02"],
            "NSTARS": [5, 6],
            # Missing N_FAINT, N_MEDIUM, N_BRIGHT, PA_APER_DEG, PIXSCALE
        })

    fig = plt.figure(figsize=(8.5, 11))
    plot_page_star_selection(fig, MockBundle())
    plt.close(fig)
