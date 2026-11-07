"""
Comprehensive verification test runner for unified_m4_it4.patch.
In-memory applies the unified patch and tests:
1. All 23 tests in tests/adversarial_novel_edgecase_stress.py
2. All 11 tests in tests/adversarial_remediated_report_stress.py
3. Unit tests in tests/unit/test_report.py
4. Unit tests in tests/unit/test_validation.py
5. Targeted edge cases for Page 2, Page 4, Page 7, Page 8
"""
import sys
from pathlib import Path
import pytest

# Read modified code from generate_unified_patch output
from generate_unified_patch import src_text_mod

# Dynamically compile and execute the modified module code into romanepsf.report
import romanepsf.report as report_mod
compiled_code = compile(src_text_mod, "<string>", "exec")
exec(compiled_code, report_mod.__dict__)

print("[1/5] Running tests/adversarial_novel_edgecase_stress.py (All 23 tests)...")
ret1 = pytest.main(["tests/adversarial_novel_edgecase_stress.py", "-v", "--no-header"])
assert ret1 == 0, f"Novel stress tests failed with return code {ret1}"

print("\n[2/5] Running tests/adversarial_remediated_report_stress.py (All 11 tests)...")
ret2 = pytest.main(["tests/adversarial_remediated_report_stress.py", "-v", "--no-header"])
assert ret2 == 0, f"Remediated stress tests failed with return code {ret2}"

print("\n[3/5] Running tests/unit/test_report.py...")
ret3 = pytest.main(["tests/unit/test_report.py", "-v", "--no-header"])
assert ret3 == 0, f"Report unit tests failed with return code {ret3}"

print("\n[4/5] Running tests/unit/test_validation.py...")
ret4 = pytest.main(["tests/unit/test_validation.py", "-v", "--no-header"])
assert ret4 == 0, f"Validation unit tests failed with return code {ret4}"

print("\n[5/5] Running targeted edge-case stress assertions for Page 2, Page 4, Page 7, Page 8...")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Targeted Test A: Page 2 missing census columns & NaNs
class MockPage2:
    stars = pd.DataFrame()
    detector_summary = pd.DataFrame({
        "DETECTOR": ["WFI01", None, "WFI03"],
        "N_FAINT": [np.nan, "10", 3],
        "N_MEDIUM": [None, 2, np.nan],
        # N_BRIGHT, N_TOTAL, PA_APER_DEG, PIXSCALE completely missing
    })

fig = plt.figure(figsize=(8.5, 11))
report_mod.plot_page_star_selection(fig, MockPage2())
plt.close(fig)
print("Targeted Test A (Page 2 partial/NaN census): PASSED")

# Targeted Test B: Page 4 missing tier flux & NaN composite
class MockPage4:
    header = {"SCALE_FM": 0.19, "SCALE_MB": 0.02}
    radial_profiles = pd.DataFrame({
        "RADIUS_PX": np.linspace(1, 100, 50),
        "FLUX_COMPOSITE": np.full(50, np.nan),
        # FLUX_FAINT, FLUX_MED_SCALED, FLUX_BRIGHT_SCALED completely missing
    })

fig = plt.figure(figsize=(8.5, 11))
report_mod.plot_page_radial_profiles(fig, MockPage4())
plt.close(fig)
print("Targeted Test B (Page 4 missing tier fluxes & all-NaN composite): PASSED")

# Targeted Test C: Page 7 results_dir=None
class MockPage7:
    results_dir = None
    fits_path = None
    epsf = np.ones((101, 101), dtype=np.float32) * 1e-4
    validation_results = None

fig = plt.figure(figsize=(8.5, 11))
report_mod.plot_page_residual_metrics(fig, MockPage7())
plt.close(fig)
print("Targeted Test C (Page 7 results_dir=None): PASSED")

# Targeted Test D: Page 8 N=25 and N=100 detectors with missing benchmark columns and NaNs
for N in [1, 5, 18, 25, 36, 100]:
    class MockPage8:
        detector_summary = pd.DataFrame({
            "DETECTOR": [f"WFI{i:02d}" for i in range(1, N + 1)],
            "TIME_SEC": [np.nan if i % 2 == 0 else 0.5 for i in range(N)],
            # PEAK_RSS_MB missing
        })
    fig = plt.figure(figsize=(8.5, 11))
    report_mod.plot_page_performance_benchmarks(fig, MockPage8())
    plt.close(fig)
print("Targeted Test D (Page 8 arbitrary N in [1..100] with NaNs): PASSED")

print("\nALL VERIFICATION TESTS COMPLETED WITH 100% PASS RATE!")
