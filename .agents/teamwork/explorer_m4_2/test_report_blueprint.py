"""
Unit Tests for Blueprint Publication PDF Report Generation.

Verifies:
- 8-page document contract (Requirement R5, Features 25)
- Standard %PDF- magic bytes header
- Modular figure builders run cleanly and independently
- Flexible input resolution (directory, fits path, kwargs)
- Parent directory creation
- High-DPI publication rendering quality
"""

import re
import pytest
from pathlib import Path
import matplotlib.pyplot as plt

import sys
sys.path.insert(0, str(Path(__file__).parent))

from blueprint_report import (
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


@pytest.fixture(scope="module")
def composite_fits_path() -> Path:
    """Path to verified composite ePSF FITS model."""
    fits_path = Path("output/run_all/roman_epsf_composite.fits")
    if not fits_path.is_file():
        pytest.skip(f"Composite FITS model not found at {fits_path}")
    return fits_path


def count_pdf_pages(pdf_path: Path) -> int:
    """Extract page count directly from PDF binary structure."""
    content = pdf_path.read_bytes()
    count_match = re.search(rb"/Count\s+(\d+)", content)
    if count_match:
        return int(count_match.group(1))
    return len(re.findall(rb"/Type\s*/Page\b", content))


def test_pdf_report_8_page_contract(composite_fits_path: Path, tmp_path: Path):
    """Verify generated PDF document contains exactly 8 pages."""
    pdf_out = tmp_path / "test_report_8pages.pdf"
    res = generate_publication_pdf_report(
        composite_fits_path=composite_fits_path,
        output_pdf_path=pdf_out,
        dpi=150,
    )
    assert res == pdf_out
    assert pdf_out.is_file()
    assert count_pdf_pages(pdf_out) == 8


def test_pdf_magic_header(composite_fits_path: Path, tmp_path: Path):
    """Verify output begins with standard %PDF- magic bytes."""
    pdf_out = tmp_path / "test_magic.pdf"
    generate_publication_pdf_report(
        composite_fits_path=composite_fits_path,
        output_pdf_path=pdf_out,
        dpi=100,
    )
    assert pdf_out.read_bytes()[:5] == b"%PDF-"


def test_pdf_file_size_publication_quality(composite_fits_path: Path, tmp_path: Path):
    """Verify publication document size reflects vector and high-DPI raster elements."""
    pdf_out = tmp_path / "test_pub_quality.pdf"
    generate_publication_pdf_report(
        composite_fits_path=composite_fits_path,
        output_pdf_path=pdf_out,
        dpi=150,
    )
    # 8 full pages should exceed 500 KB
    assert pdf_out.stat().st_size > 500_000


def test_creates_nested_parent_directories(composite_fits_path: Path, tmp_path: Path):
    """Verify PDF writer creates intermediate non-existent directories."""
    nested_pdf = tmp_path / "deeply" / "nested" / "reports" / "commissioning.pdf"
    generate_publication_pdf_report(
        composite_fits_path=composite_fits_path,
        output_pdf_path=nested_pdf,
        dpi=100,
    )
    assert nested_pdf.is_file()


def test_input_source_directory_resolution(composite_fits_path: Path, tmp_path: Path):
    """Verify input_source directory automatically discovers roman_epsf_composite.fits."""
    pdf_out = tmp_path / "test_dir_source.pdf"
    res = generate_publication_pdf_report(
        input_source=composite_fits_path.parent,
        output_pdf_path=pdf_out,
        dpi=100,
    )
    assert res.is_file()
    assert count_pdf_pages(res) == 8


def test_missing_fits_raises_filenotfound(tmp_path: Path):
    """Verify specifying invalid FITS file raises FileNotFoundError."""
    invalid_path = tmp_path / "nonexistent.fits"
    with pytest.raises(FileNotFoundError):
        generate_publication_pdf_report(
            composite_fits_path=invalid_path,
            output_pdf_path=tmp_path / "out.pdf",
        )


@pytest.mark.parametrize("builder_fn, title", [
    (plot_page_title_executive, "Page 1: Title & Executive Summary"),
    (plot_page_star_selection, "Page 2: Star Selection & Census"),
    (plot_page_spike_protection, "Page 3: Dual-Prior Spike Protection"),
    (plot_page_radial_profiles, "Page 4: Cross-Tier Overlap"),
    (plot_page_composite_epsf, "Page 5: Composite 2D ePSF"),
    (plot_page_subtraction_residuals, "Page 6: Subtraction Residuals"),
    (plot_page_residual_metrics, "Page 7: Quantitative Metrics"),
    (plot_page_performance_benchmarks, "Page 8: Performance Benchmarks"),
])
def test_individual_page_builders(composite_fits_path: Path, builder_fn, title):
    """Verify each modular page builder executes cleanly on a standalone figure."""
    data = ReportDataBundle(composite_fits_path)
    fig = plt.figure(figsize=(8.5, 11.0))
    builder_fn(fig, data)
    assert len(fig.axes) > 0, f"{title} must create plot or table axes"
    plt.close(fig)
