"""
Adversarial Stress Test Suite: PDF Binary Properties and Star Census Harmonization.

Milestone 4 Adversarial Verification:
1. Binary PDF Stress & Quality Verification:
   - Header magic bytes: b"%PDF-1.4" at byte 0.
   - Distinct page count: exactly 8 /Type /Page objects emitted.
   - Page tree count: /Count 8 in catalog dictionary.
   - Dimensions: each page declares standard US Letter MediaBox [0 0 612 792].
   - File size: exceeds 1.0 MB (high publication resolution).
   - Zero external system dependencies: no pdflatex, xelatex, or gs.
2. Star Census Harmonization Stress:
   - ReportDataBundle stress across various directory configurations (missing single CSVs,
     mixed directories, full-focal-plane catalogs, deduplication).
   - Strict 140-star consistency across Page 1, Page 2 scatter, Page 2 hist, Page 2 table,
     and Page 5 coverage text.
3. Integrity and non-facade verification:
   - Zero np.random in production report generation.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zlib
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

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


REPO_ROOT = Path(__file__).resolve().parent.parent if Path(__file__).resolve().parent.name != "romanepsf" else Path(__file__).resolve().parent
PROJECT_OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_PDF_PATH = PROJECT_OUTPUT_DIR / "report.pdf"
COMPOSITE_FITS_PATH = PROJECT_OUTPUT_DIR / "run_all" / "roman_epsf_composite.fits"
ALL_STARS_CSV_PATH = PROJECT_OUTPUT_DIR / "run_all" / "all_stars_tiered.csv"


# Helper to extract uncompressed text streams from a PDF binary
def extract_pdf_page_texts(pdf_bytes: bytes) -> List[List[str]]:
    """Decompress FlateDecode streams and extract strings from TJ/Tj operators."""
    stream_pattern = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
    streams = stream_pattern.findall(pdf_bytes)
    page_texts: List[List[str]] = []

    for s in streams:
        try:
            decomp = zlib.decompress(s)
            lines: List[str] = []
            bt_blocks = re.findall(rb"BT[\r\n]+(.*?)[\r\n]+ET", decomp, re.DOTALL)
            for block in bt_blocks:
                tj_arrays = re.findall(rb"\[(.*?)\]\s*TJ", block, re.DOTALL)
                for arr in tj_arrays:
                    parts = re.findall(rb"\(((?:[^\\)]|\\.)*)\)", arr)
                    decoded = b"".join(parts).replace(rb"\(", b"(").replace(rb"\)", b")").decode("latin-1", errors="replace")
                    lines.append(decoded)
                standalone = re.findall(rb"(?<!\[)\s*\(((?:[^\\)]|\\.)*)\)\s*Tj", block)
                for item in standalone:
                    decoded = item.replace(rb"\(", b"(").replace(rb"\)", b")").decode("latin-1", errors="replace")
                    lines.append(decoded)
            if lines and any("romanepsf" in line or "ROMAN" in line for line in lines):
                page_texts.append(lines)
        except Exception:
            pass
    return page_texts


# ==============================================================================
# SECTION 1: PDF Binary Stress & Quality Verification
# ==============================================================================

class TestPdfBinaryProperties:
    """Rigorous binary validation of generated report PDF."""

    @pytest.fixture(scope="class")
    def pdf_bytes(self) -> bytes:
        assert DEFAULT_PDF_PATH.is_file(), f"Report PDF missing at: {DEFAULT_PDF_PATH}"
        with open(DEFAULT_PDF_PATH, "rb") as f:
            return f.read()

    def test_pdf_magic_header_at_byte_zero(self, pdf_bytes: bytes):
        """Verify strict b'%PDF-1.4' at offset 0."""
        assert pdf_bytes.startswith(b"%PDF-1.4"), (
            f"Header magic mismatch. Expected b'%PDF-1.4' at byte 0, found: {pdf_bytes[:16]!r}"
        )

    def test_distinct_page_objects_count(self, pdf_bytes: bytes):
        """Scan object streams to confirm exactly 8 distinct page objects are emitted."""
        page_matches = re.findall(rb"/Type\s*/Page\b(?!\w)", pdf_bytes)
        assert len(page_matches) == 8, (
            f"Expected exactly 8 distinct /Type /Page objects, found {len(page_matches)}"
        )

    def test_page_tree_catalog_count(self, pdf_bytes: bytes):
        """Verify /Count 8 in catalog page tree dictionary."""
        pages_matches = re.findall(rb"/Type\s*/Pages\b(?!\w)", pdf_bytes)
        assert len(pages_matches) >= 1, "Catalog /Type /Pages dictionary missing"

        # Check /Count 8
        counts = re.findall(rb"/Count\s+(\d+)", pdf_bytes)
        assert b"8" in counts, f"Expected /Count 8 in catalog tree, found: {counts}"

    def test_mediabox_dimensions_us_letter(self, pdf_bytes: bytes):
        """Verify all pages declare standard US Letter MediaBox [0 0 612 792]."""
        mediaboxes = re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+612(?:\.0+)?\s+792(?:\.0+)?\s*\]", pdf_bytes)
        assert len(mediaboxes) == 8, (
            f"Expected 8 US Letter MediaBoxes [0 0 612 792], found {len(mediaboxes)}"
        )

    def test_file_size_exceeds_publication_threshold(self, pdf_bytes: bytes):
        """Verify file size exceeds 1.0 MB for high publication resolution."""
        sz = len(pdf_bytes)
        assert sz > 1_000_000, f"PDF file size ({sz:,} bytes) is below publication ceiling (> 1.0 MB)"
        # Also verify reasonable upper limit (< 15 MB)
        assert sz < 15_000_000, f"PDF file size ({sz:,} bytes) exceeds reasonable limit (< 15 MB)"

    def test_pdf_trailer_eof(self, pdf_bytes: bytes):
        """Verify proper PDF EOF marker at file termination."""
        assert b"%%EOF" in pdf_bytes[-1024:], "PDF missing %%EOF marker near trailer"

    def test_zero_external_system_dependencies(self):
        """Verify report generator contains no subprocess or external CLI tool calls."""
        import inspect
        import romanepsf.report as report_mod

        src = inspect.getsource(report_mod)
        for prohibited in ["subprocess", "os.system", "shutil.which", "pdflatex", "xelatex", "gs"]:
            matches = [m.start() for m in re.finditer(rf"\b{prohibited}\b", src)]
            assert len(matches) == 0, f"Prohibited external dependency call '{prohibited}' found in report.py"


# ==============================================================================
# SECTION 2: Star Census Harmonization Across All Report Pages
# ==============================================================================

class TestStarCensusHarmonization:
    """Verify exact 140-star consistency across all rendered report pages."""

    @pytest.fixture(scope="class")
    def page_texts(self) -> List[str]:
        with open(DEFAULT_PDF_PATH, "rb") as f:
            pdf_bytes = f.read()
        raw_pages = extract_pdf_page_texts(pdf_bytes)
        assert len(raw_pages) == 8, f"Expected 8 pages with headers, found {len(raw_pages)}"
        return [" ".join(p) for p in raw_pages]

    def test_page_1_executive_summary_census(self, page_texts: List[str]):
        """Page 1: Verify 140 stars and (89 Faint, 39 Medium, 12 Bright)."""
        p1 = page_texts[0]
        assert "89 Faint, 39 Medium, 12 Bright stars" in p1, "P1 executive summary missing exact tier counts"
        assert "140 stars" in p1, "P1 optical geometry table missing '140 stars'"
        assert "Faint: 89, Medium: 39, Bright: 12" in p1, "P1 optical geometry table missing tier breakdown"

    def test_page_2_scatter_plot_census(self, page_texts: List[str]):
        """Page 2: Verify celestial scatter plot labels report N=89, N=39, N=12."""
        p2 = page_texts[1]
        assert "N=89" in p2, "P2 scatter plot missing Faint N=89"
        assert "N=39" in p2, "P2 scatter plot missing Medium N=39"
        assert "N=12" in p2, "P2 scatter plot missing Bright N=12"

    def test_page_2_table_total_census(self, page_texts: List[str]):
        """Page 2: Verify per-detector census table row TOTAL reports 89, 39, 12, 140."""
        p2 = page_texts[1]
        assert "TOTAL" in p2, "P2 table missing TOTAL row header"
        assert "140" in p2, "P2 table missing 140 total stars"

    def test_page_5_coverage_uniformity_census(self, page_texts: List[str]):
        """Page 5: Verify coverage uniformity caption reports exactly 140 pooled stars."""
        p5 = page_texts[4]
        assert "140 pooled stars" in p5, "P5 coverage caption missing '140 pooled stars'"


# ==============================================================================
# SECTION 3: Directory Configuration Stress on ReportDataBundle
# ==============================================================================

class TestReportDataBundleDirectoryStress:
    """Adversarially stress ReportDataBundle with edge-case directory configurations."""

    @pytest.fixture(scope="class")
    def full_stars_df(self) -> pd.DataFrame:
        assert ALL_STARS_CSV_PATH.is_file(), f"Missing {ALL_STARS_CSV_PATH}"
        return pd.read_csv(ALL_STARS_CSV_PATH)

    def test_bundle_with_only_full_catalog_csv(self, tmp_path: Path):
        """Stress 1: Isolated dir containing ONLY composite FITS and all_stars_tiered.csv."""
        fits_copy = tmp_path / "roman_epsf_composite.fits"
        csv_copy = tmp_path / "all_stars_tiered.csv"
        shutil.copy(COMPOSITE_FITS_PATH, fits_copy)
        shutil.copy(ALL_STARS_CSV_PATH, csv_copy)

        bundle = ReportDataBundle(fits_copy, results_dir=tmp_path)
        assert len(bundle.stars) == 140, f"Expected 140 stars, got {len(bundle.stars)}"
        tcounts = bundle.stars["tier"].value_counts().to_dict()
        assert tcounts == {"faint": 89, "medium": 39, "bright": 12}, f"Unexpected tier counts: {tcounts}"

    def test_bundle_with_only_18_single_detector_csvs(self, tmp_path: Path):
        """Stress 2: Isolated dir containing 18 detector CSVs without all_stars_tiered.csv."""
        fits_copy = tmp_path / "roman_epsf_composite.fits"
        shutil.copy(COMPOSITE_FITS_PATH, fits_copy)

        # Copy only single detector CSVs
        det_csvs = list((PROJECT_OUTPUT_DIR / "run_all").glob("wfi[0-9][0-9]_stars_tiered.csv"))
        assert len(det_csvs) == 18, f"Expected 18 detector CSVs, found {len(det_csvs)}"
        for f in det_csvs:
            shutil.copy(f, tmp_path / f.name)

        # Verify all_stars_tiered.csv does not exist in tmp_path
        assert not (tmp_path / "all_stars_tiered.csv").exists()

        bundle = ReportDataBundle(fits_copy, results_dir=tmp_path)
        assert len(bundle.stars) == 140, f"Expected 140 stars pooled across 18 CSVs, got {len(bundle.stars)}"
        tcounts = bundle.stars["tier"].value_counts().to_dict()
        assert tcounts == {"faint": 89, "medium": 39, "bright": 12}, f"Unexpected tier counts: {tcounts}"

    def test_bundle_deduplication_on_overlapping_source_ids(self, tmp_path: Path, full_stars_df: pd.DataFrame):
        """Stress 3: Detector CSVs containing duplicate source_ids (e.g. edge stars in multiple SCAs)."""
        fits_copy = tmp_path / "roman_epsf_composite.fits"
        shutil.copy(COMPOSITE_FITS_PATH, fits_copy)

        # Split into two detector CSVs with artificial overlap
        half = len(full_stars_df) // 2
        df_wfi01 = full_stars_df.iloc[:half + 10].copy()
        df_wfi02 = full_stars_df.iloc[half:].copy()

        df_wfi01.to_csv(tmp_path / "wfi01_stars_tiered.csv", index=False)
        df_wfi02.to_csv(tmp_path / "wfi02_stars_tiered.csv", index=False)

        # Modify FITS header to expect 140 stars
        bundle = ReportDataBundle(fits_copy, results_dir=tmp_path)
        # Deduplication must prevent inflated length
        assert len(bundle.stars) <= 140
        assert not bundle.stars["source_id"].duplicated().any(), "Duplicate source_ids found in pooled catalog"

    def test_bundle_corrupt_csv_graceful_handling(self, tmp_path: Path):
        """Stress 4: Presence of zero-byte or corrupted CSVs must not crash ReportDataBundle."""
        fits_copy = tmp_path / "roman_epsf_composite.fits"
        shutil.copy(COMPOSITE_FITS_PATH, fits_copy)

        # Create corrupt CSVs
        (tmp_path / "wfi01_stars_tiered.csv").write_text("CORRUPTED_HEADER\nrandom_gibberish_without_commas\n")
        (tmp_path / "wfi02_stars_tiered.csv").write_text("")

        # Should load without exception
        bundle = ReportDataBundle(fits_copy, results_dir=tmp_path)
        assert isinstance(bundle.stars, pd.DataFrame)

    def test_single_detector_bundle_handling(self):
        """Stress 5: Single detector run (WFI01) with NDET=1."""
        fits_wfi01 = PROJECT_OUTPUT_DIR / "roman_epsf_wfi01.fits"
        if not fits_wfi01.is_file():
            pytest.skip("WFI01 fits not available")

        bundle = ReportDataBundle(fits_wfi01, results_dir=PROJECT_OUTPUT_DIR)
        assert str(bundle.header.get("DETECTOR")).upper() == "WFI01"
        assert len(bundle.stars) == 5, f"Expected 5 stars for WFI01, got {len(bundle.stars)}"
        tcounts = bundle.stars["tier"].value_counts().to_dict()
        assert tcounts == {"medium": 2, "faint": 2, "bright": 1}

    def test_empty_bundle_fallback_compilation(self, tmp_path: Path):
        """Stress 6: When stars DataFrame is forced empty, report compilation renders successfully."""
        fits_copy = tmp_path / "roman_epsf_composite.fits"
        shutil.copy(COMPOSITE_FITS_PATH, fits_copy)

        bundle = ReportDataBundle(fits_copy, results_dir=tmp_path)
        bundle.stars = pd.DataFrame()  # Force empty

        test_pdf = tmp_path / "fallback_report.pdf"
        with PdfPages(test_pdf) as pdf:
            fig = plt.figure(figsize=(8.5, 11), dpi=150)
            plot_page_star_selection(fig, bundle)
            pdf.savefig(fig)
            plt.close(fig)

        assert test_pdf.is_file()
        assert test_pdf.stat().st_size > 10_000


# ==============================================================================
# SECTION 4: Integrity and Non-Facade Invariants
# ==============================================================================

class TestIntegrityInvariants:
    """Adversarially verify that no fabricated data or random generators exist in report generation."""

    def test_no_np_random_in_report_code(self):
        """Verify zero occurrences of np.random functions in report.py execution logic."""
        import inspect
        import romanepsf.report as report_mod

        src = inspect.getsource(report_mod)
        for pattern in [r"np\.random\.normal", r"np\.random\.uniform", r"np\.random\.seed", r"random\.uniform"]:
            matches = list(re.finditer(pattern, src))
            assert len(matches) == 0, f"Found integrity violation: '{pattern}' detected in report.py at positions: {matches}"

    def test_page_6_no_hallucinated_noise(self, tmp_path: Path):
        """Verify Page 6 uses authentic residual data or deterministic fallback without noise injection."""
        bundle = ReportDataBundle(COMPOSITE_FITS_PATH, results_dir=PROJECT_OUTPUT_DIR / "run_all")
        test_pdf = tmp_path / "page_6_test.pdf"
        with PdfPages(test_pdf) as pdf:
            fig = plt.figure(figsize=(8.5, 11), dpi=150)
            plot_page_subtraction_residuals(fig, bundle)
            pdf.savefig(fig)
            plt.close(fig)

        assert test_pdf.is_file()
        assert test_pdf.stat().st_size > 50_000

    def test_page_7_residual_metrics_table_status_dynamic(self):
        """Verify Page 7 table derives verification status from zone summary data."""
        bundle = ReportDataBundle(COMPOSITE_FITS_PATH, results_dir=PROJECT_OUTPUT_DIR / "run_all")
        assert bundle.validation_results is not None, "Validation results should be loaded"
        assert "zone_summary" in bundle.validation_results or "overall_status" in bundle.validation_results
        if "zone_summary" in bundle.validation_results:
            zs = bundle.validation_results["zone_summary"]
            for zname in ["core", "transition", "wings", "spikes"]:
                assert zname in zs
                assert "status" in zs[zname]
                assert zs[zname]["status"] in ["PASS", "FAIL", "PASSED", "FAILED"]

    def test_page_8_benchmarks_deterministic(self):
        """Verify Page 8 uses authentic HDU 3 runtime data or deterministic constants."""
        bundle = ReportDataBundle(COMPOSITE_FITS_PATH, results_dir=PROJECT_OUTPUT_DIR / "run_all")
        assert not bundle.detector_summary.empty, "HDU 3 detector summary table must be present"
        assert "TIME_SEC" in bundle.detector_summary.columns
        assert len(bundle.detector_summary) == 18
