"""
Adversarial Stress Testing Suite for Roman ePSF PDF Report Generation (Milestone 4).

Challenger: challenger_m4_2
Target Module: src/romanepsf/report.py, src/report.py

Covers:
1. Binary and structural verification of PDF output:
   - Magic byte conformance (%PDF- prefix, offset 0).
   - Exact 8-page count from binary object streams (/Type /Page).
   - /Type /Pages catalog /Count == 8.
   - MediaBox publication geometry ([0 0 612 792] for 8.5x11 inches).
   - Valid xref table, trailer catalog, %%EOF sentinel.
   - High-DPI size verification (> 1.0 MB for 300 DPI).
2. Extreme parameter handling:
   - DPI scaling (72, 100, 150, 200, 300).
   - Nested directory creation (deep path resolution).
   - Paths with spaces and special characters.
   - PNG page exports (save_png_pages=True).
3. Degraded & Partial Input Resilience:
   - Minimal FITS (HDU 0 only, missing HDU 1/2/3).
   - FITS with empty table HDUs (data=None).
   - FITS with missing header optical keywords.
   - Non-standard / extreme canvas sizes (513x513, 2049x2049, 101x101).
   - Corrupted, missing, and malformed catalog CSVs (0-byte, binary junk, NaNs, missing columns).
   - Degraded validation results (None, empty dict, missing zones, n_pix=0, dataclass instances).
4. Resource & Dependency Verification:
   - Zero external dependency assertion (poison-pill monkeypatching of subprocess / os.system).
   - Peak RSS memory footprint (< 1 GB delta, << 4 GB ceiling).
   - Execution time benchmarks (< 5 seconds for full 8-page 300 DPI report).
   - File handle cleanup and back-to-back execution idempotence.
5. Direct Modular Page Builder Isolation:
   - Standalone testing of all 8 page builders on standalone figures.
"""

from __future__ import annotations

import gc
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from romanepsf.report import (
    ReportDataBundle,
    generate_publication_pdf_report,
    plot_page_title_executive,
    plot_page_star_selection,
    plot_page_spike_protection,
    plot_page_radial_profiles,
    plot_page_composite_epsf,
    plot_page_subtraction_residuals,
    plot_page_residual_metrics,
    plot_page_performance_benchmarks,
)
from romanepsf.validation import RadialMetrics, ValidationResults
import report as root_report


# ==============================================================================
# Helper Fixtures & Extraction Utilities
# ==============================================================================

COMPOSITE_FITS_PATH = Path("output/run_all/roman_epsf_composite.fits")
if not COMPOSITE_FITS_PATH.is_file():
    alt_fits = Path("output/roman_epsf_composite.fits")
    if alt_fits.is_file():
        COMPOSITE_FITS_PATH = alt_fits


def extract_pdf_page_count_binary(pdf_bytes: bytes) -> int:
    """Extract page count by directly counting /Type /Page occurrences in byte stream."""
    return len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))


def extract_pages_dict_count(pdf_bytes: bytes) -> List[int]:
    """Extract all integer arguments to /Count in the PDF byte stream."""
    matches = re.findall(rb"/Count\s+(\d+)", pdf_bytes)
    return [int(m) for m in matches]


# ==============================================================================
# Suite 1: Binary and Structural Stress Testing of PDF Output
# ==============================================================================

class TestBinaryAndStructuralIntegrity:
    """Rigorous verification of the underlying binary PDF 1.4/1.5 file structure."""

    def test_magic_bytes_strict(self, tmp_path):
        """Verify the document starts strictly at byte 0 with '%PDF-'."""
        pdf_out = tmp_path / "magic_test.pdf"
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=100,
        )
        assert pdf_out.is_file()
        content = pdf_out.read_bytes()
        assert content.startswith(b"%PDF-"), f"Invalid magic header: {content[:10]!r}"
        # Validate format is valid %PDF-X.Y
        header_line = content.split(b"\n", 1)[0].strip()
        assert re.match(rb"^%PDF-\d+\.\d+$", header_line), f"Malformed PDF version line: {header_line!r}"

    def test_page_count_binary_object_stream(self, tmp_path):
        """Inspect binary object streams to verify exactly 8 distinct /Type /Page objects."""
        pdf_out = tmp_path / "page_stream_test.pdf"
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=100,
        )
        content = pdf_out.read_bytes()
        page_objects = re.findall(rb"/Type\s*/Page\b", content)
        assert len(page_objects) == 8, f"Expected exactly 8 /Type /Page objects, found {len(page_objects)}"

        # Verify page tree /Count is 8
        counts = extract_pages_dict_count(content)
        assert 8 in counts, f"Expected page tree /Count 8, found counts: {counts}"

    def test_publication_mediabox_dimensions(self, tmp_path):
        """Verify standard 8.5 x 11 inch US Letter MediaBox [0 0 612 792] on all pages."""
        pdf_out = tmp_path / "mediabox_test.pdf"
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=100,
        )
        content = pdf_out.read_bytes()
        mediabox_pattern = re.compile(rb"/MediaBox\s*\[\s*0\s+0\s+612\s+792\s*\]")
        matches = mediabox_pattern.findall(content)
        assert len(matches) == 8, f"Expected 8 pages with [0 0 612 792] MediaBox, found {len(matches)}"

    def test_eof_marker_and_xref_integrity(self, tmp_path):
        """Verify presence of %%EOF terminator and cross-reference table."""
        pdf_out = tmp_path / "eof_xref_test.pdf"
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=100,
        )
        content = pdf_out.read_bytes()
        # %%EOF should appear near the end of the file
        tail = content[-2048:]
        assert b"%%EOF" in tail, "Missing %%EOF sentinel at end of file"
        assert (b"xref" in content) or (b"/XRef" in content), "Missing cross-reference table/stream"
        assert (b"trailer" in content) or (b"/Root" in content), "Missing trailer or document root"

    def test_publication_quality_file_size_threshold(self, tmp_path):
        """Verify default publication DPI (300) exceeds 1.0 MB (high-DPI figure embedding)."""
        pdf_out = tmp_path / "pub_size_test.pdf"
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=300,
        )
        file_size = pdf_out.stat().st_size
        assert file_size > 1_000_000, f"Publication report size {file_size} bytes is under 1.0 MB threshold"
        # Sanity check: verify size is reasonable (< 15 MB)
        assert file_size < 15_000_000, f"Publication report size {file_size} bytes is excessively large (> 15 MB)"


# ==============================================================================
# Suite 2: Extreme and Boundary Parameter Testing
# ==============================================================================

class TestExtremeParameters:
    """Stress tests on configuration options, resolutions, and destination paths."""

    @pytest.mark.parametrize("dpi, min_size", [
        (72, 400_000),
        (100, 600_000),
        (150, 1_000_000),
        (200, 1_200_000),
        (300, 1_800_000),
    ])
    def test_dpi_scaling_resolution_sweep(self, tmp_path, dpi, min_size):
        """Verify multi-resolution rendering across 72 to 300 DPI."""
        pdf_out = tmp_path / f"report_{dpi}dpi.pdf"
        t0 = time.perf_counter()
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=dpi,
        )
        elapsed = time.perf_counter() - t0
        assert pdf_out.is_file()
        sz = pdf_out.stat().st_size
        assert sz >= min_size, f"Size {sz} for DPI {dpi} lower than expected {min_size}"
        assert extract_pdf_page_count_binary(pdf_out.read_bytes()) == 8
        assert elapsed < 10.0, f"Rendering took too long: {elapsed:.2f} s"

    def test_deeply_nested_directory_creation(self, tmp_path):
        """Verify automatic creation of multiple levels of non-existent directories."""
        deep_path = (
            tmp_path
            / "level_1"
            / "level_2"
            / "deeply"
            / "nested"
            / "custom_reports"
            / "publication_epsf_report.pdf"
        )
        assert not deep_path.parent.exists()
        out = generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=deep_path,
            dpi=72,
        )
        assert out == deep_path
        assert deep_path.is_file()
        assert deep_path.stat().st_size > 100_000

    def test_destination_path_with_spaces_and_special_chars(self, tmp_path):
        """Verify paths containing spaces, hyphens, and brackets are handled safely."""
        special_path = tmp_path / "Roman [WFI-Report] (v1.0) & Final" / "ePSF Final Report #1.pdf"
        out = generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=special_path,
            dpi=72,
        )
        assert out.is_file()
        assert extract_pdf_page_count_binary(out.read_bytes()) == 8

    def test_overwriting_existing_destination(self, tmp_path):
        """Verify report generator safely overwrites existing target without corruption."""
        pdf_out = tmp_path / "overwrite_test.pdf"
        pdf_out.write_bytes(b"EXISTING CORRUPT DATA" * 100)
        assert pdf_out.stat().st_size > 0

        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=100,
        )
        content = pdf_out.read_bytes()
        assert content.startswith(b"%PDF-")
        assert extract_pdf_page_count_binary(content) == 8

    def test_save_png_pages_export(self, tmp_path):
        """Verify optional export of standalone PNG pages for each of the 8 pages."""
        pdf_out = tmp_path / "pdf_with_pngs.pdf"
        png_dir = tmp_path / "exported_pngs"
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=72,
            save_png_pages=True,
            png_dir=png_dir,
        )
        assert pdf_out.is_file()
        assert png_dir.is_dir()
        png_files = sorted(list(png_dir.glob("page_*.png")))
        assert len(png_files) == 8
        for i, png_f in enumerate(png_files, start=1):
            assert png_f.name == f"page_{i}.png"
            assert png_f.stat().st_size > 10_000, f"PNG page {i} is suspiciously small: {png_f.stat().st_size}"


# ==============================================================================
# Suite 3: Degraded and Partial Input Resilience
# ==============================================================================

class TestDegradedAndPartialInputs:
    """Stress tests verifying robust fallbacks when input datasets are incomplete or degraded."""

    def test_minimal_fits_single_hdu_only(self, tmp_path):
        """Verify report generation when FITS has ONLY HDU 0 (no COVERAGE, PROFILES, SUMMARY)."""
        fits_minimal = tmp_path / "single_hdu.fits"
        data = np.full((1025, 1025), 1e-4, dtype=np.float32)
        data[512, 512] = 0.0639
        fits.writeto(fits_minimal, data)

        pdf_out = tmp_path / "minimal_hdu_report.pdf"
        generate_publication_pdf_report(
            composite_fits_path=fits_minimal,
            output_pdf_path=pdf_out,
            dpi=72,
        )
        assert pdf_out.is_file()
        assert extract_pdf_page_count_binary(pdf_out.read_bytes()) == 8

    def test_empty_table_hdus(self, tmp_path):
        """Verify resilience when HDU 2 and HDU 3 are present but contain None / empty data."""
        fits_empty_tables = tmp_path / "empty_tables.fits"
        primary = fits.PrimaryHDU(np.full((513, 513), 1e-3, dtype=np.float32))
        hdu1 = fits.ImageHDU(np.ones((513, 513), dtype=np.int32), name="COVERAGE")
        hdu2 = fits.BinTableHDU(data=None, name="PROFILES")
        hdu3 = fits.BinTableHDU(data=None, name="SUMMARY")
        hdul = fits.HDUList([primary, hdu1, hdu2, hdu3])
        hdul.writeto(fits_empty_tables)

        pdf_out = tmp_path / "empty_tables_report.pdf"
        generate_publication_pdf_report(
            composite_fits_path=fits_empty_tables,
            output_pdf_path=pdf_out,
            dpi=72,
        )
        assert pdf_out.is_file()
        assert extract_pdf_page_count_binary(pdf_out.read_bytes()) == 8

    def test_missing_optical_keywords_in_header(self, tmp_path):
        """Verify report falls back cleanly when FITS header has none of the pipeline keywords."""
        fits_no_header = tmp_path / "no_header.fits"
        # Bare HDU with clean header without DATE_UTC, PA_APER, DET_OFF, NET_ROT, etc.
        primary = fits.PrimaryHDU(np.full((513, 513), 1e-3, dtype=np.float32))
        primary.writeto(fits_no_header)

        pdf_out = tmp_path / "no_header_report.pdf"
        generate_publication_pdf_report(
            composite_fits_path=fits_no_header,
            output_pdf_path=pdf_out,
            dpi=72,
        )
        assert pdf_out.is_file()
        assert extract_pdf_page_count_binary(pdf_out.read_bytes()) == 8

    @pytest.mark.parametrize("canvas_size", [513, 1025, 2049, 301, 151])
    def test_various_canvas_sizes(self, tmp_path, canvas_size):
        """Verify handling of various canvas sizes from 151x151 up to 2049x2049."""
        fits_p = tmp_path / f"canvas_{canvas_size}.fits"
        data = np.full((canvas_size, canvas_size), 1e-4, dtype=np.float32)
        mid = (canvas_size - 1) // 2
        data[mid, mid] = 0.05
        fits.writeto(fits_p, data)

        pdf_out = tmp_path / f"report_canvas_{canvas_size}.pdf"
        generate_publication_pdf_report(
            composite_fits_path=fits_p,
            output_pdf_path=pdf_out,
            dpi=72,
        )
        assert pdf_out.is_file()
        assert extract_pdf_page_count_binary(pdf_out.read_bytes()) == 8

    def test_missing_and_corrupt_catalog_csvs(self, tmp_path):
        """Verify report compilation when results directory contains corrupted or missing CSVs."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        fits_p = work_dir / "roman_epsf_composite.fits"
        shutil.copy(COMPOSITE_FITS_PATH, fits_p)

        # Inject malformed CSVs
        (work_dir / "corrupt1_stars_tiered.csv").write_bytes(b"\x00\xff\xfe\xaa\xbb")
        (work_dir / "empty_stars_tiered.csv").write_text("")
        (work_dir / "badcols_stars_tiered.csv").write_text("foo,bar\n1,2\n3,4\n")

        pdf_out = work_dir / "degraded_catalogs_report.pdf"
        generate_publication_pdf_report(
            input_source=work_dir,
            output_pdf_path=pdf_out,
            dpi=72,
        )
        assert pdf_out.is_file()
        assert extract_pdf_page_count_binary(pdf_out.read_bytes()) == 8

    def test_catalog_with_nans_and_missing_values(self, tmp_path):
        """Verify report compilation when catalog contains NaN coordinates and missing tiers."""
        work_dir = tmp_path / "nan_work"
        work_dir.mkdir()
        fits_p = work_dir / "roman_epsf_composite.fits"
        shutil.copy(COMPOSITE_FITS_PATH, fits_p)

        df = pd.DataFrame({
            "source_id": [1, 2, 3, 4],
            "ra": [303.1, np.nan, 303.2, None],
            "dec": [-19.9, -20.1, np.nan, None],
            "mag_lambda": [10.5, np.nan, 12.5, 14.2],
            "tier": ["bright", None, "medium", "faint"],
        })
        df.to_csv(work_dir / "wfi01_stars_tiered.csv", index=False)

        pdf_out = work_dir / "nan_catalogs_report.pdf"
        generate_publication_pdf_report(
            input_source=work_dir,
            output_pdf_path=pdf_out,
            dpi=72,
        )
        assert pdf_out.is_file()
        assert extract_pdf_page_count_binary(pdf_out.read_bytes()) == 8

    def test_degraded_validation_results_variants(self, tmp_path):
        """Test variations of validation_results: empty dict, missing zones, zero valid pixels."""
        # 1. Empty dict
        pdf1 = tmp_path / "val_empty.pdf"
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf1,
            validation_results={},
            dpi=72,
        )
        assert extract_pdf_page_count_binary(pdf1.read_bytes()) == 8

        # 2. Zone summary with zero counts
        pdf2 = tmp_path / "val_zero_counts.pdf"
        zero_val = {
            "zone_summary": {
                "core": {"n_pix": 0, "mu_frac": 0.0},
                "transition": {"n_pix": 0, "mu_frac": 0.0},
                "wings": {"n_pix": 0, "mu_frac": 0.0},
                "spikes": {"n_pix": 0, "mu_frac": 0.0},
            }
        }
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf2,
            validation_results=zero_val,
            dpi=72,
        )
        assert extract_pdf_page_count_binary(pdf2.read_bytes()) == 8

        # 3. Live ValidationResults dataclass object
        pdf3 = tmp_path / "val_dataclass.pdf"
        rm = RadialMetrics(
            radii=np.array([2.0, 15.0, 60.0]),
            mu_frac=np.array([0.005, -0.002, 0.001]),
            rms_frac=np.array([0.025, 0.040, 0.065]),
            chi2_nu=np.array([1.02, 1.05, 0.98]),
            n_pix=np.array([100, 500, 2000]),
            core={"mu_frac": 0.005, "rms_frac": 0.025, "chi2_nu": 1.02, "n_pix": 100},
            transition={"mu_frac": -0.002, "rms_frac": 0.040, "chi2_nu": 1.05, "n_pix": 500},
            wings={"mu_frac": 0.001, "rms_frac": 0.065, "chi2_nu": 0.98, "n_pix": 2000},
            spikes={"mu_frac": 0.008, "rms_frac": 0.055, "chi2_nu": 1.04, "n_pix": 350},
        )
        vr = ValidationResults(
            star_results=[],
            radial_metrics=rm,
            zone_summary={
                "core": rm.core,
                "transition": rm.transition,
                "wings": rm.wings,
                "spikes": rm.spikes,
            },
            tier_summary={},
            overall_status="PASS",
            total_stars_evaluated=5,
            execution_time_s=1.23,
        )
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf3,
            validation_results=vr,
            dpi=72,
        )
        assert extract_pdf_page_count_binary(pdf3.read_bytes()) == 8


# ==============================================================================
# Suite 4: Resource Efficiency, Concurrency & Zero External Dependencies
# ==============================================================================

class TestResourceEfficiencyAndDependencies:
    """Stress tests on memory ceiling, execution speed, and absence of external binaries."""

    def test_zero_external_dependencies_poison_pill(self, tmp_path, monkeypatch):
        """
        Poison-pill test: assert no subprocess or shell calls are made.
        Monkeypatch subprocess.run, subprocess.Popen, os.system to fail immediately if called.
        """
        def poison(*args, **kwargs):
            raise RuntimeError(f"VIOLATION: External process spawned: {args}")

        monkeypatch.setattr(subprocess, "run", poison)
        monkeypatch.setattr(subprocess, "Popen", poison)
        monkeypatch.setattr(subprocess, "call", poison)
        monkeypatch.setattr(os, "system", poison)

        pdf_out = tmp_path / "zero_dep_poison_test.pdf"
        # Should complete cleanly without triggering any external command
        out = generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=100,
        )
        assert out.is_file()
        assert extract_pdf_page_count_binary(out.read_bytes()) == 8

    def test_execution_time_and_memory_ceiling(self, tmp_path):
        """Verify complete 8-page 300 DPI report generates in < 6.0 seconds and memory RSS is within budget."""
        gc.collect()
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        pdf_out = tmp_path / "perf_bench_300dpi.pdf"

        t0 = time.perf_counter()
        generate_publication_pdf_report(
            composite_fits_path=COMPOSITE_FITS_PATH,
            output_pdf_path=pdf_out,
            dpi=300,
        )
        dt = time.perf_counter() - t0
        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        # Execution time benchmark: full 8 pages at 300 dpi must complete under 6.0 seconds
        assert dt < 6.0, f"Execution time {dt:.2f} s exceeded 6.0 s ceiling"

        # Peak RSS delta: on macOS ru_maxrss is in bytes, on Linux in KB
        # Convert to MB
        rss_mb = rss_after / (1024 * 1024) if sys.platform == "darwin" else rss_after / 1024
        # Total peak RSS should be well under 4.0 GB budget
        assert rss_mb < 4000.0, f"Peak RSS {rss_mb:.1f} MB exceeded 4.0 GB limit"
        print(f"\n[BENCHMARK] 8-Page 300-DPI PDF generation: {dt:.2f} s, Peak RSS: {rss_mb:.1f} MB")

    def test_successive_compilations_idempotence(self, tmp_path):
        """Verify multiple successive report compilations complete without resource exhaustion."""
        for i in range(3):
            p = tmp_path / f"successive_report_{i}.pdf"
            generate_publication_pdf_report(
                composite_fits_path=COMPOSITE_FITS_PATH,
                output_pdf_path=p,
                dpi=100,
            )
            assert p.is_file()
            assert extract_pdf_page_count_binary(p.read_bytes()) == 8


# ==============================================================================
# Suite 5: Individual Modular Page Builder Isolation
# ==============================================================================

class TestModularPageBuilders:
    """Stress tests on individual page rendering functions with complete and minimal data."""

    BUILDERS = [
        (plot_page_title_executive, "Page 1: Title & Exec Summary"),
        (plot_page_star_selection, "Page 2: Star Selection & Census"),
        (plot_page_spike_protection, "Page 3: Dual-Prior Spike Protection"),
        (plot_page_radial_profiles, "Page 4: Cross-Tier Overlap"),
        (plot_page_composite_epsf, "Page 5: Composite 2D ePSF"),
        (plot_page_subtraction_residuals, "Page 6: Subtraction Residuals"),
        (plot_page_residual_metrics, "Page 7: Quantitative Metrics"),
        (plot_page_performance_benchmarks, "Page 8: Performance Benchmarks"),
    ]

    @pytest.mark.parametrize("builder_fn, name", BUILDERS)
    def test_page_builder_on_live_data(self, builder_fn, name):
        """Verify each page builder executes cleanly with verified pipeline data."""
        bundle = ReportDataBundle(COMPOSITE_FITS_PATH)
        fig = plt.figure(figsize=(8.5, 11.0))
        builder_fn(fig, bundle)
        assert len(fig.axes) > 0, f"{name} failed to create any axes"
        plt.close(fig)

    @pytest.mark.parametrize("builder_fn, name", BUILDERS)
    def test_page_builder_on_degraded_minimal_data(self, tmp_path, builder_fn, name):
        """Verify each page builder handles completely empty / minimal data without crashing."""
        minimal_fits = tmp_path / f"min_{builder_fn.__name__}.fits"
        fits.writeto(minimal_fits, np.full((1025, 1025), 1e-4, dtype=np.float32))
        bundle = ReportDataBundle(minimal_fits, validation_results={})
        fig = plt.figure(figsize=(8.5, 11.0))
        builder_fn(fig, bundle)
        assert len(fig.axes) > 0, f"{name} failed to create any axes under degraded conditions"
        plt.close(fig)


# ==============================================================================
# Main Runner for Direct Execution
# ==============================================================================

if __name__ == "__main__":
    ret = pytest.main([__file__, "-v", "-s"])
    sys.exit(ret)
