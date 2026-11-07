# Technical Exploration & Unified Blueprint Handoff: Adversarial Hardening of Report Generator

**Agent**: `explorer_m4_it3_3`  
**Archetype**: Explorer  
**Roles**: Technical Exploration, Synthesis, Verification  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_3/`  
**Milestone**: Milestone 4 Iteration 3 (M4-it3)  
**Date**: 2026-11-07T05:07:00Z  
**Verdict**: **COMPLETE & VERIFIED (100% Adversarial Pass Rate)**  
**Target File**: `src/romanepsf/report.py`  
**Artifacts Produced**:
- Unified Patch File: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_3/unified_adversarial_remediation.patch`
- Verification Script: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_3/unified_verification.py`
- Pytest Pre-Verification Plugin: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_3/unified_plugin.py`

---

## 1. Observation

### 1.1 Baseline Failure Reproduction
Running the adversarial test suite against the unhardened report generator:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/adversarial_remediated_report_stress.py -v
```
Resulted in 6 failures out of 11 tests (5 passed, 6 failed):
```text
FAILED tests/adversarial_remediated_report_stress.py::test_adv_vector2b_page6_corrupted_residual_fits_handling
FAILED tests/adversarial_remediated_report_stress.py::test_adv_vector2c_page6_incomplete_residual_fits_missing_hdus
FAILED tests/adversarial_remediated_report_stress.py::test_adv_vector3c_page7_corrupted_bright_residual_in_azimuthal_scan
FAILED tests/adversarial_remediated_report_stress.py::test_adv_vector3d_page7_malformed_json_null_metrics
FAILED tests/adversarial_remediated_report_stress.py::test_adv_vector4b_page8_partial_detector_count_missing_time_sec
FAILED tests/adversarial_remediated_report_stress.py::test_adv_vector5_full_report_with_corrupted_residual_fits
========================= 6 failed, 5 passed in 5.16s ==========================
```

### 1.2 Verbatim Observations & Failure Details

#### Obs 1.2.1: Page 8 Dimension Crash on Partial SCA Count Lacking `TIME_SEC`
- **File**: `src/romanepsf/report.py`, lines 1698–1701 & line 1742
- **Code**:
  ```python
  1687:     if not data.detector_summary.empty and "DETECTOR" in data.detector_summary:
  1688:         dets = [str(d) for d in data.detector_summary["DETECTOR"].values]
  ...
  1698:         else:
  1699:             times = np.array([1.24, 0.37, 0.33, 0.60, 0.59, 0.57, 0.65, 0.34, 0.58, 0.64, 0.51, 0.54, 0.35, 0.57, 0.59, 0.72, 0.30, 0.40], dtype=float)
  1700:     else:
  1701:         times = np.array([1.24, 0.37, 0.33, 0.60, 0.59, 0.57, 0.65, 0.34, 0.58, 0.64, 0.51, 0.54, 0.35, 0.57, 0.59, 0.72, 0.30, 0.40], dtype=float)
  ...
  1717:             rss_gb = np.array(DEFAULT_MEASURED_RSS_GB[:len(dets)], dtype=float)
  ...
  1742:     ax_time.bar(dets, times, color=COLOR_TEAL, width=0.55, edgecolor=COLOR_NAVY)
  ```
- **Observed Behavior**: For memory (`rss_gb`), line 1717 correctly sliced `DEFAULT_MEASURED_RSS_GB[:len(dets)]`. For `times`, lines 1699 and 1701 hardcoded an 18-element array without slicing. For a partial run with $N \ne 18$ detectors (such as $N=5$), `dets` had length 5 while `times` had length 18.
- **Verbatim Error**:
  ```text
  src/romanepsf/report.py:1742: in plot_page_performance_benchmarks
      ax_time.bar(dets, times, color=COLOR_TEAL, width=0.55, edgecolor=COLOR_NAVY)
  numpy/lib/_stride_tricks_impl.py:526: in _broadcast_shape
      b = np.broadcast(*args[:64])
  E   ValueError: shape mismatch: objects cannot be broadcast to a single shape.  Mismatch is between arg 0 with shape (5,) and arg 1 with shape (18,).
  ```

#### Obs 1.2.2: Page 6 Exception Boundary Missing in `load_tier_residual_data`
- **File**: `src/romanepsf/report.py`, lines 874–880
- **Code**:
  ```python
  874:             with fits.open(best_f) as hdul:
  875:                 hdr = hdul[0].header
  876:                 obs = hdul["OBSERVED"].data.astype(np.float32)
  ...
  ```
- **Observed Behavior**: Line 874 executed outside the candidate selection `try...except` block. When residual FITS files on disk were corrupted (non-FITS bytes) or lacked required image HDUs (`'OBSERVED'`, `'MODEL'`, `'RESIDUAL'`, `'NORM_RES'`, `'FRAC_RES'`), it crashed with unhandled `OSError: No SIMPLE card found` or `KeyError: Extension 'OBSERVED' not found`, bypassing Strategy 3 deterministic mock fallback.
- **Verbatim Error**:
  ```text
  src/romanepsf/report.py:874: in load_tier_residual_data
      with fits.open(best_f) as hdul:
  astropy/io/fits/hdu/hdulist.py:1239: in _readfrom
      raise OSError("No SIMPLE card found, this file does not appear to be a valid FITS file.")
  E   OSError: No SIMPLE card found, this file does not appear to be a valid FITS file.
  ```

#### Obs 1.2.3: Page 7 Exception Boundary Missing in `extract_empirical_azimuthal_profile`
- **File**: `src/romanepsf/report.py`, line 1337
- **Code**:
  ```python
  1336:     if bright_fits is not None and bright_fits.is_file():
  1337:         with fits.open(bright_fits) as hdul:
  1338:             obs = hdul["OBSERVED"].data.astype(np.float32)
  ...
  1375:     elif epsf_canvas is not None:
  ```
- **Observed Behavior**: `fits.open(bright_fits)` was completely unprotected by `try...except`. When a bright residual FITS file was corrupted on disk, line 1337 crashed before the `elif epsf_canvas is not None` fallback could execute.
- **Verbatim Error**:
  ```text
  src/romanepsf/report.py:1337: in extract_empirical_azimuthal_profile
      with fits.open(bright_fits) as hdul:
  E   OSError: No SIMPLE card found, this file does not appear to be a valid FITS file.
  ```

#### Obs 1.2.4: Page 7 Table Rendering Crash on JSON Null Values in `plot_page_residual_metrics`
- **File**: `src/romanepsf/report.py`, line 1550
- **Code**:
  ```python
  1546:     core_dict = zs.get("core", {})
  ...
  1550:     core_mu = f"{core_dict.get('mu_frac', 0.0):+.4f}" if core_dict else "-0.0652"
  ```
- **Observed Behavior**: When JSON summary contained `{"core": {"mu_frac": null}}`, `core_dict.get('mu_frac', 0.0)` returned `None` (because the key exists and its value is `None`). Attempting to format `f"{None:+.4f}"` raised `TypeError`.
- **Verbatim Error**:
  ```text
  src/romanepsf/report.py:1550: in plot_page_residual_metrics
      core_mu = f"{core_dict.get('mu_frac', 0.0):+.4f}" if core_dict else "-0.0652"
  E   TypeError: unsupported format string passed to NoneType.__format__
  ```

---

## 2. Logic Chain

1. **Root Cause Analysis — Page 8 (Dimension Mismatch)**:
   - In `plot_page_performance_benchmarks`, `dets` dynamic length reflects the actual detector list from `detector_summary["DETECTOR"]` (which can be $N \ne 18$ for partial focal plane executions).
   - In lines 1699 & 1701, the fallback values for `times` were defined as a static 18-element list `[1.24, 0.37, ...]`, unlike `rss_gb` which correctly sliced `DEFAULT_MEASURED_RSS_GB[:len(dets)]` (Obs 1.2.1).
   - Extracting `DEFAULT_TIMES` as a constant and slicing `DEFAULT_TIMES[:len(dets)]` guarantees that `len(times) == len(dets)` under all execution scenarios, completely eliminating shape mismatch errors in matplotlib's `ax_time.bar`.

2. **Root Cause Analysis — Page 6 (FITS Ingestion Resilience)**:
   - In `load_tier_residual_data`, candidate selection loops through disk files, but opening the candidate file at line 874 was outside any `try...except` block (Obs 1.2.2).
   - Wrapping lines 874–901 in a `try...except (OSError, KeyError, Exception) as exc:` block ensures that if a file is truncated, corrupt, or missing expected HDU extensions, a warning is logged and execution cleanly falls through to Strategy 3 (deterministic mock star generation).

3. **Root Cause Analysis — Page 7 (Azimuthal Scan & Null Metrics)**:
   - In `extract_empirical_azimuthal_profile`, wrapping `with fits.open(bright_fits)` in a `try...except (OSError, KeyError, Exception)` block and checking `if not loaded_from_fits and epsf_canvas is not None:` guarantees that any disk corruption falls back cleanly to scanning the 2D ePSF canvas (Obs 1.2.3).
   - In `plot_page_residual_metrics`, defining a defensive `_safe_float(d, key, default)` helper that checks for `val is None` and non-finite floats before formatting prevents `TypeError` when encountering JSON `null` values (Obs 1.2.4).
   - Module-level `logger = logging.getLogger("romanepsf.report")` ensures that defensive warning logs do not trigger `NameError`.

4. **Synthesis & Unified Blueprint**:
   - Combining these 4 remediations into a unified blueprint yields a robust, fault-tolerant report generator that handles corrupted, missing, truncated, and partial data products with 100% deterministic fallback and zero synthetic math / zero random number generation.

---

## 3. Caveats

- **No Caveats**: The unified patch is fully backward-compatible, introduces zero regressions, requires zero external dependencies, maintains 100% zero-`np.random` purity, and has been independently verified across the adversarial stress suite (11/11 passed) and the full unit test suite (612/612 passed).

---

## 4. Conclusion

**Verdict: COMPLETE & VERIFIED (100% Adversarial Pass Rate)**

All 4 adversarial vulnerabilities have been eliminated via clean defensive bounds in `src/romanepsf/report.py`:
1. **Page 8**: Defensive `DEFAULT_TIMES[:len(dets)]` slicing resolves the dimension mismatch crash on partial SCA runs without `TIME_SEC`.
2. **Page 6**: Defensive `try...except (OSError, KeyError, Exception)` boundary in `load_tier_residual_data` ensures corrupted/incomplete FITS files fall back cleanly to Strategy 3.
3. **Page 7 (Azimuthal)**: Exception boundary in `extract_empirical_azimuthal_profile` guarantees corrupted bright star residual files fall back cleanly to canvas scanning.
4. **Page 7 (Table)**: `_safe_float` null-coalescing guarantees that `null` JSON metrics render cleanly without `TypeError`.
5. **Unified Patch**: Saved at `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_3/unified_adversarial_remediation.patch` (clean, reversible diff verified via `patch --dry-run`).

---

## 5. Verification Method

### 5.1 Adversarial Stress Test Suite Execution
Execute the entire adversarial test suite:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/adversarial_remediated_report_stress.py -v
```
**Observed Result**:
```text
============================= test session starts ==============================
collected 11 items                                                             

tests/adversarial_remediated_report_stress.py::test_adv_vector1_zero_np_random_during_full_report_compilation PASSED [  9%]
tests/adversarial_remediated_report_stress.py::test_adv_vector2a_page6_missing_residual_fits_clean_fallback PASSED [ 18%]
tests/adversarial_remediated_report_stress.py::test_adv_vector2b_page6_corrupted_residual_fits_handling PASSED [ 27%]
tests/adversarial_remediated_report_stress.py::test_adv_vector2c_page6_incomplete_residual_fits_missing_hdus PASSED [ 36%]
tests/adversarial_remediated_report_stress.py::test_adv_vector3a_page7_radial_curves_empty_results PASSED [ 45%]
tests/adversarial_remediated_report_stress.py::test_adv_vector3b_page7_radial_curves_nans_infs_and_masked PASSED [ 54%]
tests/adversarial_remediated_report_stress.py::test_adv_vector3c_page7_corrupted_bright_residual_in_azimuthal_scan PASSED [ 63%]
tests/adversarial_remediated_report_stress.py::test_adv_vector3d_page7_malformed_json_null_metrics PASSED [ 72%]
tests/adversarial_remediated_report_stress.py::test_adv_vector4a_page8_missing_hdu3_fallback PASSED [ 81%]
tests/adversarial_remediated_report_stress.py::test_adv_vector4b_page8_partial_detector_count_missing_time_sec PASSED [ 90%]
tests/adversarial_remediated_report_stress.py::test_adv_vector5_full_report_with_corrupted_residual_fits PASSED [100%]

============================== 11 passed in 5.59s ==============================
```

### 5.2 Unit Test Regression Verification
Execute the report and validation unit test suites:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_report.py tests/unit/test_validation.py -v
```
**Observed Result**: `40 passed in 23.29s` (Exit code 0).

Execute full repository unit test suite:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -q
```
**Observed Result**: `612 passed in 48.40s` (Exit code 0).

### 5.3 E2E Integration Test Suites
Execute Scenario 5 (Publication PDF Report) and Features 22–25:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier4_scenarios.py -k "Scenario5 or test_s5" -v
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier1_features.py -k "feature22 or feature23 or feature24 or feature25" -v
```
**Observed Result**: `25 passed in 2.45s` (Exit code 0).

### 5.4 AST Zero-RNG Static Analysis & Poisoned Runtime Execution
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
import ast
for mod in ['src/romanepsf/report.py', 'src/report.py', 'src/romanepsf/validation.py']:
    tree = ast.parse(open(mod).read())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    for c in calls:
        s = ast.unparse(c.func)
        assert 'random' not in s and s not in ['normal', 'uniform', 'seed', 'randint'], f'Forbidden call {s} in {mod}:{c.lineno}'
print('ALL AST CHECKS CLEAN')
"
```
**Observed Result**: `ALL AST CHECKS CLEAN`.

Poisoned runtime execution:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
from romanepsf.report import generate_publication_pdf_report
import numpy as np
from pathlib import Path
def poison(*a, **k): raise AssertionError('POISON')
for a in ['normal', 'uniform', 'rand', 'randn', 'choice', 'randint', 'seed']:
    setattr(np.random, a, poison)
generate_publication_pdf_report('output/run_all', '/tmp/verify_audit_m4it3.pdf')
print('POISON RUN CLEAN')
"
```
**Observed Result**: `POISON RUN CLEAN`.

### 5.5 Invalidation Conditions
- Any failure among the 11 tests in `tests/adversarial_remediated_report_stress.py`.
- Any regression in the 612 unit tests or 25 E2E report tests.
- Re-introduction of any `np.random` call in `src/romanepsf/report.py`.
