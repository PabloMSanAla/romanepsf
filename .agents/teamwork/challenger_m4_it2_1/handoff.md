# Adversarial Challenge & Stress Report: Remediated Report Generator (Hard Handoff)

**Agent**: `challenger_m4_it2_1`  
**Roles**: Critic, Specialist (Empirical Challenger)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m4_it2_1/`  
**Milestone**: Milestone 4 Iteration 2 — Model Validation, Technical Documentation & PDF Report  
**Date**: 2026-11-07T04:52:00Z  
**Verdict**: **REQUEST_CHANGES** (High Severity: Unhandled Exceptions on Corrupted/Partial Inputs)

---

## Challenge Summary

**Overall risk assessment**: **HIGH**

While the implementation successfully eliminated all `np.random` calls and synthetic facades from report generation (verified via complete function poisoning), adversarial stress-testing revealed that the fallback mechanisms on Pages 6, 7, and 8 lack exception boundaries and input defensive slicing. When residual FITS files are truncated, corrupted, or missing extension HDUs, or when partial detector runs lack `TIME_SEC`, the report generator crashes with unhandled `OSError`, `KeyError`, `ValueError`, and `TypeError` instead of gracefully falling back.

---

## 1. Observation

All tests executed using designated environment `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`.

### 1.1 Stress Test Suite Execution
Created test suite `tests/adversarial_remediated_report_stress.py` containing 11 adversarial test vectors:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/adversarial_remediated_report_stress.py -v
```
**Output**:
```
============================= test session starts ==============================
collected 11 items

tests/adversarial_remediated_report_stress.py::test_adv_vector1_zero_np_random_during_full_report_compilation PASSED [  9%]
tests/adversarial_remediated_report_stress.py::test_adv_vector2a_page6_missing_residual_fits_clean_fallback PASSED [ 18%]
tests/adversarial_remediated_report_stress.py::test_adv_vector2b_page6_corrupted_residual_fits_handling FAILED [ 27%]
tests/adversarial_remediated_report_stress.py::test_adv_vector2c_page6_incomplete_residual_fits_missing_hdus FAILED [ 36%]
tests/adversarial_remediated_report_stress.py::test_adv_vector3a_page7_radial_curves_empty_results PASSED [ 45%]
tests/adversarial_remediated_report_stress.py::test_adv_vector3b_page7_radial_curves_nans_infs_and_masked PASSED [ 54%]
tests/adversarial_remediated_report_stress.py::test_adv_vector3c_page7_corrupted_bright_residual_in_azimuthal_scan FAILED [ 63%]
tests/adversarial_remediated_report_stress.py::test_adv_vector3d_page7_malformed_json_null_metrics FAILED [ 72%]
tests/adversarial_remediated_report_stress.py::test_adv_vector4a_page8_missing_hdu3_fallback PASSED [ 81%]
tests/adversarial_remediated_report_stress.py::test_adv_vector4b_page8_partial_detector_count_missing_time_sec FAILED [ 90%]
tests/adversarial_remediated_report_stress.py::test_adv_vector5_full_report_with_corrupted_residual_fits FAILED [100%]

=================================== FAILURES ===================================
6 failed, 5 passed in 5.42s
```

### 1.2 Verbatim Observations & Failure Details

#### Obs 1.2.1: Page 6 Crashing on Corrupted Residual FITS File (`load_tier_residual_data`)
- **File**: `src/romanepsf/report.py`, line 874
- **Code**:
  ```python
  860:         cand_files = sorted(list(set(cand_files)))
  861:         if cand_files:
  862:             best_f = cand_files[0]
  863:             best_chi2 = float("inf")
  864:             for f in cand_files:
  865:                 try:
  866:                     with fits.open(f) as hd:
  867:                         c2 = float(hd[0].header.get("CHI2_NU", float("inf")))
  868:                         if c2 < best_chi2:
  869:                             best_chi2 = c2
  870:                             best_f = f
  871:                 except Exception:
  872:                     pass
  873: 
  874:             with fits.open(best_f) as hdul:
  ```
- **Error**:
  ```
  src/romanepsf/report.py:874: in load_tier_residual_data
      with fits.open(best_f) as hdul:
  astropy/io/fits/hdu/hdulist.py:1239: in _readfrom
      raise OSError("No SIMPLE card found, this file does not appear to be a valid FITS file.")
  E   OSError: No SIMPLE card found, this file does not appear to be a valid FITS file.
  ```
- **Observation**: If `best_f` (or all candidates) cannot be read, line 874 executes outside the `try...except` block and crashes with `OSError`. Strategy 3 deterministic mock fallback is never reached.

#### Obs 1.2.2: Page 6 Crashing on Missing Residual HDUs (`load_tier_residual_data`)
- **File**: `src/romanepsf/report.py`, lines 876–880
- **Code**:
  ```python
  874:             with fits.open(best_f) as hdul:
  875:                 hdr = hdul[0].header
  876:                 obs = hdul["OBSERVED"].data.astype(np.float32)
  877:                 mod = hdul["MODEL"].data.astype(np.float32)
  878:                 res = hdul["RESIDUAL"].data.astype(np.float32)
  879:                 nres = hdul["NORM_RES"].data.astype(np.float32)
  880:                 fres = hdul["FRAC_RES"].data.astype(np.float32)
  ```
- **Error**:
  ```
  src/romanepsf/report.py:876: in load_tier_residual_data
      obs = hdul["OBSERVED"].data.astype(np.float32)
  astropy/io/fits/hdu/hdulist.py:855: in index_of
      raise KeyError(f"Extension {key!r} not found.")
  E   KeyError: "Extension 'OBSERVED' not found."
  ```
- **Observation**: If a FITS file exists but lacks `"OBSERVED"` (or `"MODEL"`, `"RESIDUAL"`, `"NORM_RES"`, `"FRAC_RES"`), direct indexing raises an unhandled `KeyError`.

#### Obs 1.2.3: Page 7 Azimuthal Profile Crashing on Corrupted Bright Residual FITS
- **File**: `src/romanepsf/report.py`, line 1337
- **Code**:
  ```python
  1336:     if bright_fits is not None and bright_fits.is_file():
  1337:         with fits.open(bright_fits) as hdul:
  1338:             obs = hdul["OBSERVED"].data.astype(np.float32)
  ```
- **Error**:
  ```
  src/romanepsf/report.py:1337: in extract_empirical_azimuthal_profile
      with fits.open(bright_fits) as hdul:
  E   OSError: No SIMPLE card found, this file does not appear to be a valid FITS file.
  ```
- **Observation**: Unlike `extract_empirical_radial_residual_profiles` (which wraps `fits.open` in a `try...except`), `extract_empirical_azimuthal_profile` leaves `fits.open(bright_fits)` completely unprotected.

#### Obs 1.2.4: Page 7 Table Rendering Crashing on Null Metrics (`plot_page_residual_metrics`)
- **File**: `src/romanepsf/report.py`, line 1550
- **Code**:
  ```python
  1546:     core_dict = zs.get("core", {})
  ...
  1550:     core_mu = f"{core_dict.get('mu_frac', 0.0):+.4f}" if core_dict else "-0.0652"
  ```
- **Error**:
  ```
  src/romanepsf/report.py:1550: in plot_page_residual_metrics
      core_mu = f"{core_dict.get('mu_frac', 0.0):+.4f}" if core_dict else "-0.0652"
  E   TypeError: unsupported format string passed to NoneType.__format__
  ```
- **Observation**: When JSON contains `{"core": {"mu_frac": null}}`, `core_dict.get('mu_frac', 0.0)` returns `None` (not `0.0`). Attempting to format `f"{None:+.4f}"` raises `TypeError`.

#### Obs 1.2.5: Page 8 Performance Benchmarks Crashing on Partial SCA Count Missing `TIME_SEC`
- **File**: `src/romanepsf/report.py`, lines 1699 & 1742
- **Code**:
  ```python
  1687:     if not data.detector_summary.empty and "DETECTOR" in data.detector_summary:
  1688:         dets = [str(d) for d in data.detector_summary["DETECTOR"].values]
  ...
  1698:         else:
  1699:             times = np.array([1.24, 0.37, 0.33, 0.60, 0.59, 0.57, 0.65, 0.34, 0.58, 0.64, 0.51, 0.54, 0.35, 0.57, 0.59, 0.72, 0.30, 0.40], dtype=float)
  ...
  1717:             rss_gb = np.array(DEFAULT_MEASURED_RSS_GB[:len(dets)], dtype=float)
  ...
  1742:     ax_time.bar(dets, times, color=COLOR_TEAL, width=0.55, edgecolor=COLOR_NAVY)
  ```
- **Error**:
  ```
  src/romanepsf/report.py:1742: in plot_page_performance_benchmarks
      ax_time.bar(dets, times, color=COLOR_TEAL, width=0.55, edgecolor=COLOR_NAVY)
  numpy/lib/_stride_tricks_impl.py:526: in _broadcast_shape
      b = np.broadcast(*args[:64])
  E   ValueError: shape mismatch: objects cannot be broadcast to a single shape.  Mismatch is between arg 0 with shape (5,) and arg 1 with shape (18,).
  ```
- **Observation**: In line 1717, `rss_gb` is sliced by `[:len(dets)]`. In line 1699, `times` is hardcoded to 18 elements without slicing. For a partial run with $N \ne 18$ detectors (e.g. $N=5$), `ax_time.bar` crashes with `ValueError`.

#### Obs 1.2.6: Zero `np.random` Calls Confirmed
- **Test**: `test_adv_vector1_zero_np_random_during_full_report_compilation`
- **Result**: PASSED cleanly. Poisoning `np.random.normal`, `uniform`, `random`, `rand`, `randn`, `choice`, `seed`, `randint` to raise `AssertionError` did not trigger any assertion. Production report generation is 100% deterministic and free of random noise generation.

---

## 2. Logic Chain

1. **Robustness Requirement**: The mission mandates: "test missing or corrupted residual FITS files, verify fallback logic is deterministic and doesn't crash" and "verify that annular binning computes finite, bounded statistics without NaN / zero division" and "verify graceful fallback to measured constants without KeyError" (Mission Prompt).
2. **Page 6 Failure Chain**:
   - `load_tier_residual_data` intends to provide a 3-strategy fallback (in-memory -> disk FITS -> deterministic mock).
   - When candidate residual files match `residual_*.fits` on disk but are corrupt, line 874 unconditionally executes `fits.open(best_f)`.
   - This raises `OSError` or `KeyError` before Strategy 3 can execute, crashing the report generation (Obs 1.2.1, 1.2.2, 1.2.6).
3. **Page 7 Failure Chain**:
   - `extract_empirical_azimuthal_profile` has fallback logic using `epsf_canvas` (line 1375), but line 1337 executes `fits.open(bright_fits)` without exception handling.
   - Any corruption in `bright_fits` crashes the function before the `epsf_canvas` fallback is reached (Obs 1.2.3).
   - In `plot_page_residual_metrics`, formatting dictionary values with `f"{val:+.4f}"` assumes `val` is numeric. If `val` is `None` (valid JSON `null`), it crashes with `TypeError` (Obs 1.2.4).
4. **Page 8 Failure Chain**:
   - For memory (`rss_gb`), the developer correctly recognized that `len(dets)` may vary and wrote `DEFAULT_MEASURED_RSS_GB[:len(dets)]`.
   - For execution times (`times`), the developer omitted `[:len(dets)]` in lines 1699 and 1701.
   - When $N \ne 18$, `dets` has length $N$ while `times` has length 18, causing matplotlib to crash on shape mismatch (Obs 1.2.5).
5. **Conclusion**: While the core architectural refactoring correctly removed facade noise and hardcoded synthetic profiles, the fallback implementations fail to protect against invalid/corrupt inputs, causing critical pipeline crashes. Therefore, changes must be requested.

---

## 3. Caveats

- **Authentic Data Runs**: When genuine, uncorrupted residual FITS files (`output/validation/residual_*.fits`) and uncorrupted 18-detector summary tables exist, the report generator runs successfully.
- **Zero np.random**: The remediation of random noise / synthetic math formulas in the report generator is verified to be complete and pure.
- **Scope**: The required changes are strictly defensive bounds/exception handling in `src/romanepsf/report.py`.

---

## 4. Conclusion

**Verdict: REQUEST_CHANGES**

### Required Remediations:

1. **Page 6 Defensive FITS Ingestion (`load_tier_residual_data`)**:
   Wrap the FITS loading logic in lines 874–901 in a `try...except (OSError, KeyError, Exception)` block. If reading `best_f` fails or if any required HDU (`"OBSERVED"`, `"MODEL"`, `"RESIDUAL"`, `"NORM_RES"`, `"FRAC_RES"`) is missing, log a warning and fall through to Strategy 3 (deterministic mock fallback).
2. **Page 7 Azimuthal Profile Exception Boundary (`extract_empirical_azimuthal_profile`)**:
   Wrap lines 1336–1374 in a `try...except (OSError, KeyError, Exception)` block so that any corrupted or incomplete `bright_fits` falls through cleanly to the existing `epsf_canvas` scan fallback at line 1375.
3. **Page 7 Null Metric Handling in Dynamic Table (`plot_page_residual_metrics`)**:
   Safely extract metric floats with fallback when value is `None` (e.g. `core_dict.get('mu_frac') if core_dict.get('mu_frac') is not None else -0.0652`) before string formatting.
4. **Page 8 Defensive `times` Slicing (`plot_page_performance_benchmarks`)**:
   In lines 1699 and 1701, slice default times by `[:len(dets)]` (exactly matching line 1717 for `rss_gb`):
   ```python
   DEFAULT_TIMES = [1.24, 0.37, 0.33, 0.60, 0.59, 0.57, 0.65, 0.34, 0.58, 0.64, 0.51, 0.54, 0.35, 0.57, 0.59, 0.72, 0.30, 0.40]
   times = np.array(DEFAULT_TIMES[:len(dets)], dtype=float)
   ```

---

## 5. Verification Method

To verify these remediations:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/adversarial_remediated_report_stress.py -v
```
**Success Condition**:
All 11 adversarial test vectors must pass (11 passed, 0 failed):
- `test_adv_vector1_zero_np_random_during_full_report_compilation`: PASSED
- `test_adv_vector2a_page6_missing_residual_fits_clean_fallback`: PASSED
- `test_adv_vector2b_page6_corrupted_residual_fits_handling`: PASSED
- `test_adv_vector2c_page6_incomplete_residual_fits_missing_hdus`: PASSED
- `test_adv_vector3a_page7_radial_curves_empty_results`: PASSED
- `test_adv_vector3b_page7_radial_curves_nans_infs_and_masked`: PASSED
- `test_adv_vector3c_page7_corrupted_bright_residual_in_azimuthal_scan`: PASSED
- `test_adv_vector3d_page7_malformed_json_null_metrics`: PASSED
- `test_adv_vector4a_page8_missing_hdu3_fallback`: PASSED
- `test_adv_vector4b_page8_partial_detector_count_missing_time_sec`: PASSED
- `test_adv_vector5_full_report_with_corrupted_residual_fits`: PASSED
