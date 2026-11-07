"""
Adversarial Challenger Verification Suite for Milestone 4 Iteration 3.

Empirically challenges:
1. Binary PDF properties of `output/report.pdf` (strict `%PDF-1.4`, 8 pages, > 2 MB, valid xref table).
2. Exact star census harmonization across all pages (140 stars total: 89 Faint, 39 Medium, 12 Bright).
3. Runtime poison verification: wrap every `numpy.random` attribute in an exception-raising mock and generate a full 8-page PDF report. Confirm zero RNG calls are made.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zlib
from pathlib import Path
from typing import List, Dict, Tuple

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

import romanepsf.cli
from romanepsf.cli import cli
from romanepsf.report import (
    ReportDataBundle,
    generate_publication_pdf_report,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
REPORT_PDF_PATH = OUTPUT_DIR / "report.pdf"
RUN_ALL_DIR = OUTPUT_DIR / "run_all"
COMPOSITE_FITS_PATH = RUN_ALL_DIR / "roman_epsf_composite.fits"
ALL_STARS_CSV_PATH = RUN_ALL_DIR / "all_stars_tiered.csv"


def extract_decompressed_text_streams(pdf_bytes: bytes) -> List[List[str]]:
    """Extract and decompress all text streams from PDF binary."""
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
                    decoded = (
                        b"".join(parts)
                        .replace(rb"\(", b"(")
                        .replace(rb"\)", b")")
                        .decode("latin-1", errors="replace")
                    )
                    lines.append(decoded)
                standalone = re.findall(rb"(?<!\[)\s*\(((?:[^\\)]|\\.)*)\)\s*Tj", block)
                for item in standalone:
                    decoded = (
                        item.replace(rb"\(", b"(")
                        .replace(rb"\)", b")")
                        .decode("latin-1", errors="replace")
                    )
                    lines.append(decoded)
            if lines and any("ROMAN" in line or "romanepsf" in line for line in lines):
                page_texts.append(lines)
        except Exception:
            pass
    return page_texts


# ==============================================================================
# Challenge 1: Binary PDF Properties of output/report.pdf
# ==============================================================================

class TestBinaryPdfCompliance:
    """Empirical challenge of binary PDF compliance."""

    @pytest.fixture(scope="class")
    def pdf_data(self) -> bytes:
        assert REPORT_PDF_PATH.is_file(), f"Target PDF does not exist: {REPORT_PDF_PATH}"
        return REPORT_PDF_PATH.read_bytes()

    def test_strict_pdf14_magic_header(self, pdf_data: bytes):
        """Header must strictly match %PDF-1.4 at offset 0 followed by newline."""
        assert pdf_data.startswith(b"%PDF-1.4\n"), (
            f"Header magic mismatch. Expected b'%PDF-1.4\\n' at byte 0, found: {pdf_data[:16]!r}"
        )
        # Verify binary comment follows
        second_line = pdf_data.splitlines()[1]
        assert second_line.startswith(b"%"), "Second line must be a comment marker '%'"
        assert any(b >= 128 for b in second_line), "Binary comment line should indicate binary PDF format"

    def test_file_size_exceeds_2mb(self, pdf_data: bytes):
        """PDF file size must strictly exceed 2 MB (2,097,152 bytes)."""
        size_bytes = len(pdf_data)
        size_mb = size_bytes / (1024 * 1024)
        min_threshold = 2 * 1024 * 1024
        assert size_bytes > min_threshold, (
            f"PDF file size {size_bytes:,} bytes ({size_mb:.2f} MB) does not exceed 2 MB ceiling ({min_threshold:,} bytes)"
        )
        assert size_mb < 20.0, f"PDF file size {size_mb:.2f} MB is unrealistically bloated"

    def test_page_count_exact_8(self, pdf_data: bytes):
        """PDF must contain exactly 8 pages."""
        # 1. Distinct /Type /Page objects
        page_objs = re.findall(rb"/Type\s*/Page\b(?!\w)", pdf_data)
        assert len(page_objs) == 8, f"Expected exactly 8 distinct /Type /Page objects, found {len(page_objs)}"

        # 2. Document Catalog /Pages /Count 8
        count_matches = re.findall(rb"/Count\s+(\d+)", pdf_data)
        assert b"8" in count_matches, f"Expected /Count 8 in catalog page tree, found {count_matches}"

        # 3. MediaBox declaration on all 8 pages
        mediaboxes = re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+612(?:\.0+)?\s+792(?:\.0+)?\s*\]", pdf_data)
        assert len(mediaboxes) == 8, f"Expected 8 standard US Letter MediaBoxes [0 0 612 792], found {len(mediaboxes)}"

    def test_valid_xref_table_and_object_offsets(self, pdf_data: bytes):
        """Cross-reference (xref) table must be strictly valid and point to exact object offsets."""
        # Locate startxref near end of file
        tail = pdf_data[-1024:]
        match = re.search(rb"startxref[\r\n]+(\d+)[\r\n]+%%EOF", tail)
        assert match is not None, "Valid 'startxref ... %%EOF' trailer not found in last 1024 bytes"
        xref_offset = int(match.group(1))

        assert pdf_data[xref_offset:xref_offset+4] == b"xref", f"'xref' keyword missing at byte offset {xref_offset}"
        xref_str = pdf_data[xref_offset:].decode("latin1")
        lines = xref_str.splitlines()

        assert lines[0] == "xref"
        start_obj, num_objs = map(int, lines[1].split())
        assert start_obj == 0, f"xref section should start at object 0, got {start_obj}"
        assert num_objs > 0, f"Invalid object count: {num_objs}"

        # Parse every xref entry
        entries: Dict[int, Tuple[int, int, str]] = {}
        for i in range(num_objs):
            line = lines[2 + i]
            if line.startswith("trailer"):
                break
            parts = line.split()
            off = int(parts[0])
            gen = int(parts[1])
            status = parts[2]
            entries[start_obj + i] = (off, gen, status)

        assert len(entries) == num_objs, f"Parsed {len(entries)} entries, expected {num_objs}"

        # Entry 0 is free entry
        assert entries[0] == (0, 65535, "f"), f"Entry 0 must be free entry, got {entries[0]}"

        # Validate every in-use object (n)
        for obj_id, (off, gen, status) in entries.items():
            if status == "n":
                assert off < len(pdf_data), f"Offset {off} out of file range for object {obj_id}"
                expected_tag = f"{obj_id} {gen} obj".encode("latin1")
                actual_chunk = pdf_data[off : off + len(expected_tag)]
                assert actual_chunk == expected_tag, (
                    f"Object {obj_id} mismatch at byte offset {off}: expected {expected_tag!r}, got {actual_chunk!r}"
                )

        # Validate Trailer dictionary
        trailer_idx = pdf_data.find(b"trailer", xref_offset)
        assert trailer_idx != -1, "trailer dictionary missing after xref"
        trailer_text = pdf_data[trailer_idx:pdf_data.rfind(b"startxref")].decode("latin1")

        size_m = re.search(r"/Size\s+(\d+)", trailer_text)
        assert size_m and int(size_m.group(1)) == num_objs, "Trailer /Size does not match xref object count"

        root_m = re.search(r"/Root\s+(\d+)\s+(\d+)\s+R", trailer_text)
        assert root_m, "Trailer /Root reference missing"
        root_id = int(root_m.group(1))

        # Check Catalog /Root object
        root_off = entries[root_id][0]
        root_body = pdf_data[root_off : root_off + 400].decode("latin1")
        assert "/Type /Catalog" in root_body or "/Type/Catalog" in root_body, f"Root object {root_id} not Catalog"

        pages_m = re.search(r"/Pages\s+(\d+)\s+(\d+)\s+R", root_body)
        assert pages_m, "Catalog /Pages reference missing"
        pages_id = int(pages_m.group(1))

        # Check Pages tree object
        pages_off = entries[pages_id][0]
        pages_body = pdf_data[pages_off : pages_off + 1000].decode("latin1")
        assert "/Type /Pages" in pages_body or "/Type/Pages" in pages_body, f"Pages object {pages_id} not Pages"

        kids_m = re.search(r"/Kids\s*\[(.*?)\]", pages_body, re.DOTALL)
        assert kids_m, "Pages object missing /Kids array"
        kids_refs = re.findall(r"(\d+)\s+\d+\s+R", kids_m.group(1))
        assert len(kids_refs) == 8, f"Expected 8 page references in /Kids, got {len(kids_refs)}"

    def test_ghostscript_headless_processing(self):
        """Ghostscript headless parser must process all 8 pages without warnings or errors."""
        gs_bin = "/usr/local/bin/gs"
        if not Path(gs_bin).is_file():
            pytest.skip("Ghostscript not installed at /usr/local/bin/gs")

        cmd = [
            gs_bin,
            "-dNODISPLAY",
            "-dBATCH",
            "-dNOPAUSE",
            "-dPDFSTOPONERROR",
            str(REPORT_PDF_PATH),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0, f"Ghostscript verification failed: {proc.stderr}"
        assert "Processing pages 1 through 8." in proc.stdout, f"Unexpected GS output: {proc.stdout}"


# ==============================================================================
# Challenge 2: Exact Star Census Harmonization Across All Pages
# ==============================================================================

class TestStarCensusHarmonization:
    """Empirical verification of 140 stars (89 Faint, 39 Medium, 12 Bright) across report."""

    @pytest.fixture(scope="class")
    def page_texts(self) -> List[str]:
        assert REPORT_PDF_PATH.is_file()
        raw_pages = extract_decompressed_text_streams(REPORT_PDF_PATH.read_bytes())
        assert len(raw_pages) == 8, f"Expected 8 extracted pages, found {len(raw_pages)}"
        return [" ".join(p) for p in raw_pages]

    def test_page1_executive_summary_and_geometry_table(self, page_texts: List[str]):
        """Page 1: Executive Summary and Optical Geometry table census."""
        p1 = page_texts[0]
        assert "89 Faint, 39 Medium, 12 Bright stars" in p1, "P1 executive summary missing tier counts"
        assert "Total Stars Pooled" in p1 and "140 stars" in p1, "P1 optical table missing 140 stars"
        assert "Faint: 89, Medium: 39, Bright: 12" in p1, "P1 optical table missing tier breakdown"

    def test_page2_sky_map_and_magnitude_histogram(self, page_texts: List[str]):
        """Page 2: Celestial scatter plot and magnitude histogram census."""
        p2 = page_texts[1]
        assert "N=89" in p2, "P2 sky map missing Faint N=89"
        assert "N=39" in p2, "P2 sky map missing Medium N=39"
        assert "N=12" in p2, "P2 sky map missing Bright N=12"

        # Check histogram labels
        assert "Bright Tier (m < 11.0)" in p2
        assert "Medium Tier (11" in p2
        assert "Faint Tier (m" in p2

    def test_page2_per_detector_table_and_totals(self, page_texts: List[str]):
        """Page 2: 18-SCA Per-Detector Census Table and TOTAL row."""
        p2 = page_texts[1]
        assert "TOTAL" in p2, "P2 per-detector table missing TOTAL row"
        assert "140" in p2, "P2 per-detector table missing 140 total"

    def test_page5_coverage_uniformity(self, page_texts: List[str]):
        """Page 5: 2D Coverage density caption census."""
        p5 = page_texts[4]
        assert "140 pooled stars" in p5, "P5 coverage caption missing 140 pooled stars"
        assert "N=12" in p5, "P5 coverage caption missing wings N=12"

    def test_page8_system_reproducibility(self, page_texts: List[str]):
        """Page 8: System benchmarks and hardware metrics consistency."""
        p8 = page_texts[7]
        assert "All 18 SCAs" in p8, "P8 benchmarks missing All 18 SCAs"
        assert "WFI01" in p8 and "WFI18" in p8, "P8 missing detector identifiers"

    def test_underlying_data_bundle_census_consistency(self):
        """Underlying FITS data products and catalog CSV must strictly match census."""
        bundle = ReportDataBundle(COMPOSITE_FITS_PATH, results_dir=RUN_ALL_DIR)

        # Header NSTARS
        assert int(bundle.header.get("NSTARS", 0)) == 140, f"HDU 0 NSTARS is {bundle.header.get('NSTARS')}"

        # Stars catalog length and tier breakdown
        assert len(bundle.stars) == 140, f"Stars DataFrame length is {len(bundle.stars)}, expected 140"
        tier_counts = bundle.stars["tier"].value_counts().to_dict()
        expected_tiers = {"faint": 89, "medium": 39, "bright": 12}
        assert tier_counts == expected_tiers, f"Tier counts mismatch: {tier_counts} vs {expected_tiers}"

        # HDU 3 Detector Summary sums
        assert not bundle.detector_summary.empty, "HDU 3 Detector summary table missing"
        assert len(bundle.detector_summary) == 18, f"Expected 18 SCAs in summary, got {len(bundle.detector_summary)}"
        assert bundle.detector_summary["N_FAINT"].sum() == 89, "N_FAINT sum != 89"
        assert bundle.detector_summary["N_MEDIUM"].sum() == 39, "N_MEDIUM sum != 39"
        assert bundle.detector_summary["N_BRIGHT"].sum() == 12, "N_BRIGHT sum != 12"
        assert bundle.detector_summary["N_TOTAL"].sum() == 140, "N_TOTAL sum != 140"


# ==============================================================================
# Challenge 3: Runtime Poison Verification (Zero RNG Invocations)
# ==============================================================================

class TestRuntimePoisonVerification:
    """Empirical challenge with every numpy.random attribute wrapped in exception-raising mock."""

    @pytest.fixture(autouse=True)
    def poison_rng(self):
        """Wrap every attribute on numpy.random, Generator, RandomState, and random module."""
        import random
        import numpy.random as nr

        class PoisonRngError(AssertionError):
            pass

        def poison_func(name: str):
            def _poison(*args, **kwargs):
                raise PoisonRngError(f"POISON: Unauthorized RNG invocation: {name}(args={args}, kwargs={kwargs})")
            return _poison

        # Backup
        orig_nr_attrs = {}
        nr_attrs = [a for a in dir(nr) if not a.startswith("__")]
        for a in nr_attrs:
            orig_nr_attrs[a] = getattr(nr, a)
            try:
                setattr(nr, a, poison_func(f"np.random.{a}"))
            except (TypeError, AttributeError):
                pass

        orig_gen_methods = {}
        for m in dir(np.random.Generator):
            if not m.startswith("__"):
                orig_gen_methods[m] = getattr(np.random.Generator, m)
                try:
                    setattr(np.random.Generator, m, poison_func(f"Generator.{m}"))
                except (TypeError, AttributeError):
                    pass

        orig_rs_methods = {}
        for m in dir(np.random.RandomState):
            if not m.startswith("__"):
                orig_rs_methods[m] = getattr(np.random.RandomState, m)
                try:
                    setattr(np.random.RandomState, m, poison_func(f"RandomState.{m}"))
                except (TypeError, AttributeError):
                    pass

        orig_random_attrs = {}
        for a in dir(random):
            if not a.startswith("__"):
                orig_random_attrs[a] = getattr(random, a)
                try:
                    setattr(random, a, poison_func(f"random.{a}"))
                except (TypeError, AttributeError):
                    pass

        yield

        # Restore
        for a, val in orig_nr_attrs.items():
            try:
                setattr(nr, a, val)
            except (TypeError, AttributeError):
                pass
        for m, val in orig_gen_methods.items():
            try:
                setattr(np.random.Generator, m, val)
            except (TypeError, AttributeError):
                pass
        for m, val in orig_rs_methods.items():
            try:
                setattr(np.random.RandomState, m, val)
            except (TypeError, AttributeError):
                pass
        for a, val in orig_random_attrs.items():
            try:
                setattr(random, a, val)
            except (TypeError, AttributeError):
                pass

    def test_poison_wrap_all_numpy_random_attributes(self, tmp_path: Path):
        """Full 8-page PDF report generation via API must succeed with zero RNG calls."""
        out_pdf = tmp_path / "poisoned_api_report.pdf"
        result_path = generate_publication_pdf_report(RUN_ALL_DIR, out_pdf)

        assert result_path.is_file(), "Report generation failed under poisoned runtime"
        size_bytes = result_path.stat().st_size
        assert size_bytes > 2 * 1024 * 1024, f"Generated PDF size {size_bytes} is not > 2 MB"

        data = result_path.read_bytes()
        assert data.startswith(b"%PDF-1.4\n"), "Generated PDF does not start with %PDF-1.4"
        pages = len(re.findall(rb"/Type\s*/Page\b(?!\w)", data))
        assert pages == 8, f"Expected 8 pages, got {pages}"

    def test_poison_wrap_cli_execution(self, tmp_path: Path):
        """Full 8-page PDF report generation via CLI must succeed with zero RNG calls."""
        out_pdf = tmp_path / "poisoned_cli_report.pdf"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["report", "--results-dir", str(RUN_ALL_DIR), "--output-pdf", str(out_pdf)],
        )

        assert result.exit_code == 0, f"CLI command failed under poisoned runtime: {result.output}"
        assert out_pdf.is_file(), "CLI did not create report PDF"
        size_bytes = out_pdf.stat().st_size
        assert size_bytes > 2 * 1024 * 1024, f"Generated CLI PDF size {size_bytes} is not > 2 MB"

        data = out_pdf.read_bytes()
        assert data.startswith(b"%PDF-1.4\n"), "CLI generated PDF does not start with %PDF-1.4"
        pages = len(re.findall(rb"/Type\s*/Page\b(?!\w)", data))
        assert pages == 8, f"Expected 8 pages, got {pages}"

    def test_poison_mock_efficacy_canary(self):
        """Canary test: verify that poisoned mock raises when RNG is called."""
        import numpy.random as nr
        with pytest.raises(AssertionError, match="POISON: Unauthorized RNG invocation"):
            nr.normal(0.0, 1.0)
