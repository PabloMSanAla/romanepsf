import pytest
from romanepsf.report import plot_page_performance_benchmarks
import romanepsf.report as report_mod
from .test_patch import proposed_plot_page_performance_benchmarks


@pytest.fixture(autouse=True)
def apply_page8_patch(monkeypatch):
    monkeypatch.setattr(report_mod, "plot_page_performance_benchmarks", proposed_plot_page_performance_benchmarks)
    # Also patch in the test file where it was directly imported
    import tests.adversarial_novel_edgecase_stress as test_mod
    monkeypatch.setattr(test_mod, "plot_page_performance_benchmarks", proposed_plot_page_performance_benchmarks)
