"""
Backward-compatibility wrapper re-exporting from romanepsf.report.
"""

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

__all__ = [
    "ReportDataBundle",
    "generate_publication_pdf_report",
    "plot_page_title_executive",
    "plot_page_star_selection",
    "plot_page_spike_protection",
    "plot_page_radial_profiles",
    "plot_page_composite_epsf",
    "plot_page_subtraction_residuals",
    "plot_page_residual_metrics",
    "plot_page_performance_benchmarks",
]
