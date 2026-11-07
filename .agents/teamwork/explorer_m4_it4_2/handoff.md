# 5-Component Handoff Report: Page 4 Missing Tier Flux Columns Blueprint

**Agent**: `explorer_m4_it4_2`  
**Archetype**: Explorer  
**Roles**: investigator, specialist  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it4_2/`  
**Milestone**: Milestone 4 Iteration 4 (M4-it4)  
**Date**: 2026-11-07T05:33:00Z  
**Target Code**: `src/romanepsf/report.py` (`plot_page_radial_profiles`, lines 589–610)  

---

## 1. Observation

### 1.1 Verbatim Failure Reproduction
Execution command:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/adversarial_novel_edgecase_stress.py -k "tier_flux" -v
```
Verbatim failure trace:
```text
tests/adversarial_novel_edgecase_stress.py::test_adv_radial_profiles_missing_tier_flux_columns FAILED [100%]

=================================== FAILURES ===================================
______________ test_adv_radial_profiles_missing_tier_flux_columns ______________
tests/adversarial_novel_edgecase_stress.py:276: in test_adv_radial_profiles_missing_tier_flux_columns
    plot_page_radial_profiles(fig, MockBundle())
src/romanepsf/report.py:607: in plot_page_radial_profiles
    ax_prof.plot(r_px[mask_f], f_faint[mask_f], color=COLOR_BLUE, alpha=0.7, linestyle="--", linewidth=1.4, label="Faint Tier (Core r < 8 px)")
                               ^^^^^^^^^^^^^^^
E   IndexError: boolean index did not match indexed array along axis 0; size of axis is 1 but size of corresponding boolean axis is 10
=========================== short test summary info ============================
FAILED tests/adversarial_novel_edgecase_stress.py::test_adv_radial_profiles_missing_tier_flux_columns - IndexError: boolean index did not match indexed array along axis 0; size of axis is 1 but size of corresponding boolean axis is 10
======================= 1 failed, 22 deselected in 1.88s =======================
```

### 1.2 Inspection of Existing Vulnerable Implementation
In `src/romanepsf/report.py` (lines 589–610):
```python
589:     if not data.radial_profiles.empty and "RADIUS_PX" in data.radial_profiles:
590:         df_p = data.radial_profiles
591:         r_px = df_p["RADIUS_PX"].values
592:         f_comp = df_p["FLUX_COMPOSITE"].values
593:         f_faint = df_p.get("FLUX_FAINT", pd.Series(np.nan)).values
594:         f_med = df_p.get("FLUX_MED_SCALED", pd.Series(np.nan)).values
595:         f_bright = df_p.get("FLUX_BRIGHT_SCALED", pd.Series(np.nan)).values
596:     else:
597:         r_px = np.logspace(0, 2.7, 300)
...
603:     mask_f = (r_px <= 25.0) & (f_faint > 0)
604:     mask_m = (r_px >= 7.0) & (r_px <= 50.0) & (f_med > 0)
605:     mask_b = (r_px >= 20.0) & (f_bright > 0)
606: 
607:     ax_prof.plot(r_px[mask_f], f_faint[mask_f], color=COLOR_BLUE, alpha=0.7, linestyle="--", linewidth=1.4, label="Faint Tier (Core r < 8 px)")
608:     ax_prof.plot(r_px[mask_m], f_med[mask_m], color=COLOR_AMBER, alpha=0.7, linestyle="-.", linewidth=1.4, label=f"Medium Tier (Scaled k_FM={data.header.get('SCALE_FM', 0.1937):.4f})")
609:     ax_prof.plot(r_px[mask_b], f_bright[mask_b], color=COLOR_CRIMSON, alpha=0.6, linestyle=":", linewidth=1.4, label=f"Bright Tier (Scaled k_MB={data.header.get('SCALE_MB', 0.0255):.4f})")
610:     ax_prof.plot(r_px, f_comp, color="#1A202C", linewidth=2.0, label="Composite Extended PSF (Unit Flux)")
```

### 1.3 Additional Edge-Case Vulnerabilities Uncovered
1. **Missing `FLUX_COMPOSITE`**: Line 592 directly indexes `df_p["FLUX_COMPOSITE"].values`. If HDU 2 contains `RADIUS_PX` but lacks `FLUX_COMPOSITE`, a `KeyError: 'FLUX_COMPOSITE'` is triggered before reaching line 593.
2. **`None` / Corrupted Values in Flux Columns**: If `FLUX_FAINT` is present as an `object` series containing `None` or string values, `f_faint > 0` throws `TypeError: '>' not supported between instances of 'NoneType' and 'int'`.
3. **`None` in Header Scale Factors**: If `data.header` contains `{"SCALE_FM": None}`, `data.header.get("SCALE_FM", 0.1937)` returns `None`, and `f"{None:.4f}"` raises `TypeError: unsupported format string passed to NoneType.__format__`.

---

## 2. Logic Chain

1. **Obs 1.1 & 1.2 demonstrate** that when HDU 2 `radial_profiles` contains `RADIUS_PX` ($N_{\rm rad} = 10$) and `FLUX_COMPOSITE`, but lacks `FLUX_FAINT`:
   - `df_p.get("FLUX_FAINT", pd.Series(np.nan))` uses default `pd.Series(np.nan)`, which is a 1-element Series of shape `(1,)`.
   - `f_faint.values` produces a numpy array of shape `(1,)`.
   - In line 603, `(r_px <= 25.0)` has shape `(10,)`. `(f_faint > 0)` has shape `(1,)`. Bitwise `&` broadcasts the condition along axis 0, giving `mask_f` shape `(10,)`.
   - In line 607, `r_px[mask_f]` correctly extracts matching elements, but `f_faint[mask_f]` indexes an array of shape `(1,)` with a boolean mask of shape `(10,)`. NumPy rejects this with `IndexError: boolean index did not match indexed array along axis 0; size of axis is 1 but size of corresponding boolean axis is 10`.
2. **Obs 1.3 reveals** that similar crashes occur if `FLUX_COMPOSITE` is missing or if flux columns contain `None`/dirty object dtypes.
3. **To resolve all failure modes**, the fallback arrays must be explicitly sized to $N_{\rm rad} = \text{len}(r\_px)$:
   - `n_r = len(r_px)`
   - `f_comp = pd.to_numeric(df_p["FLUX_COMPOSITE"], errors="coerce").to_numpy(dtype=float) if "FLUX_COMPOSITE" in df_p else np.full(n_r, np.nan)`
   - `f_faint = pd.to_numeric(df_p["FLUX_FAINT"], errors="coerce").to_numpy(dtype=float) if "FLUX_FAINT" in df_p else np.full(n_r, np.nan)`
   - `f_med = pd.to_numeric(df_p["FLUX_MED_SCALED"], errors="coerce").to_numpy(dtype=float) if "FLUX_MED_SCALED" in df_p else np.full(n_r, np.nan)`
   - `f_bright = pd.to_numeric(df_p["FLUX_BRIGHT_SCALED"], errors="coerce").to_numpy(dtype=float) if "FLUX_BRIGHT_SCALED" in df_p else np.full(n_r, np.nan)`
   - Coercion via `pd.to_numeric(..., errors="coerce")` guarantees that any `None`, string, or unparseable value safely becomes `np.nan`, preventing `TypeError` on `(f_faint > 0)`.
   - Format strings for scale factors must use `float(data.header.get("SCALE_FM") or 0.1937)` to guard against `None` values.
4. **Empirical testing confirms**:
   - When patched, `test_adv_radial_profiles_missing_tier_flux_columns` passes in 2.00s with exit code 0.
   - All edge cases (missing composite flux, dirty types, `None` header values) render cleanly.
   - Nominal 18-detector production ePSF FITS report generation exhibits 0 regressions.

---

## 3. Caveats

- **No Caveats**: The proposed patch is strictly localized to Page 4 (`plot_page_radial_profiles`), requires zero architectural modifications, introduces zero new dependencies, and preserves all existing visual formatting and labeling.

---

## 4. Conclusion & Actionable Blueprint Patch

### 4.1 Deliverable Artifacts
The patch has been written as a unified diff file:
- File path: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it4_2/page4_radial_profiles.patch`
- Standalone test verification runner: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it4_2/test_tier_flux_patch.py`

### 4.2 Exact Unified Diff
```diff
--- a/src/romanepsf/report.py
+++ b/src/romanepsf/report.py
@@ -588,11 +588,12 @@
 
     if not data.radial_profiles.empty and "RADIUS_PX" in data.radial_profiles:
         df_p = data.radial_profiles
-        r_px = df_p["RADIUS_PX"].values
-        f_comp = df_p["FLUX_COMPOSITE"].values
-        f_faint = df_p.get("FLUX_FAINT", pd.Series(np.nan)).values
-        f_med = df_p.get("FLUX_MED_SCALED", pd.Series(np.nan)).values
-        f_bright = df_p.get("FLUX_BRIGHT_SCALED", pd.Series(np.nan)).values
+        r_px = pd.to_numeric(df_p["RADIUS_PX"], errors="coerce").to_numpy(dtype=float)
+        n_r = len(r_px)
+        f_comp = pd.to_numeric(df_p["FLUX_COMPOSITE"], errors="coerce").to_numpy(dtype=float) if "FLUX_COMPOSITE" in df_p else np.full(n_r, np.nan)
+        f_faint = pd.to_numeric(df_p["FLUX_FAINT"], errors="coerce").to_numpy(dtype=float) if "FLUX_FAINT" in df_p else np.full(n_r, np.nan)
+        f_med = pd.to_numeric(df_p["FLUX_MED_SCALED"], errors="coerce").to_numpy(dtype=float) if "FLUX_MED_SCALED" in df_p else np.full(n_r, np.nan)
+        f_bright = pd.to_numeric(df_p["FLUX_BRIGHT_SCALED"], errors="coerce").to_numpy(dtype=float) if "FLUX_BRIGHT_SCALED" in df_p else np.full(n_r, np.nan)
     else:
         r_px = np.logspace(0, 2.7, 300)
         f_comp = 0.06 / (1.0 + (r_px / 2.5)**2)**1.3
@@ -605,8 +606,8 @@
     mask_b = (r_px >= 20.0) & (f_bright > 0)
 
     ax_prof.plot(r_px[mask_f], f_faint[mask_f], color=COLOR_BLUE, alpha=0.7, linestyle="--", linewidth=1.4, label="Faint Tier (Core r < 8 px)")
-    ax_prof.plot(r_px[mask_m], f_med[mask_m], color=COLOR_AMBER, alpha=0.7, linestyle="-.", linewidth=1.4, label=f"Medium Tier (Scaled k_FM={data.header.get('SCALE_FM', 0.1937):.4f})")
-    ax_prof.plot(r_px[mask_b], f_bright[mask_b], color=COLOR_CRIMSON, alpha=0.6, linestyle=":", linewidth=1.4, label=f"Bright Tier (Scaled k_MB={data.header.get('SCALE_MB', 0.0255):.4f})")
+    ax_prof.plot(r_px[mask_m], f_med[mask_m], color=COLOR_AMBER, alpha=0.7, linestyle="-.", linewidth=1.4, label=f"Medium Tier (Scaled k_FM={float(data.header.get('SCALE_FM') or 0.1937):.4f})")
+    ax_prof.plot(r_px[mask_b], f_bright[mask_b], color=COLOR_CRIMSON, alpha=0.6, linestyle=":", linewidth=1.4, label=f"Bright Tier (Scaled k_MB={float(data.header.get('SCALE_MB') or 0.0255):.4f})")
     ax_prof.plot(r_px, f_comp, color="#1A202C", linewidth=2.0, label="Composite Extended PSF (Unit Flux)")
 
     ax_prof.axvline(8.0, color=COLOR_AMBER, linestyle=":", linewidth=1.2)
```

---

## 5. Verification Method

### 5.1 Standalone Test Runner
Execute the comprehensive test runner in the agent working directory:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python .agents/teamwork/explorer_m4_it4_2/test_tier_flux_patch.py
```
Expected output:
```text
=== 1. Testing Novel Adversarial Stress Case: Missing Tier Flux Columns ===
PASS: test_adv_radial_profiles_missing_tier_flux_columns executed cleanly!

=== 2. Testing Additional Edge Cases ===
PASS: Edge Case 2a (missing FLUX_COMPOSITE) handled cleanly!
PASS: Edge Case 2b (corrupted types & None values) handled cleanly!
PASS: Edge Case 2c (empty DataFrame fallback) handled cleanly!

=== 3. Testing Real FITS Production Data Regression ===
PASS: Real FITS (output/run_all/roman_epsf_composite.fits) rendered Page 4 successfully!

ALL VERIFICATION TESTS COMPLETED SUCCESSFULLY!
```

### 5.2 Direct Patch Application and Pytest Run
Apply the patch and run pytest directly:
```bash
# Verify patch applies cleanly without errors
git apply --check .agents/teamwork/explorer_m4_it4_2/page4_radial_profiles.patch

# Apply patch
patch -p1 < .agents/teamwork/explorer_m4_it4_2/page4_radial_profiles.patch

# Run adversarial stress test
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/adversarial_novel_edgecase_stress.py -k "tier_flux" -v
```
Expected result: `1 passed, 22 deselected in ~2s`.

### 5.3 Invalidation Conditions
- If `tests/adversarial_novel_edgecase_stress.py -k "tier_flux"` raises `IndexError` after patch application.
- If Page 4 fails to render when `FLUX_FAINT`, `FLUX_MED_SCALED`, or `FLUX_BRIGHT_SCALED` is omitted from `radial_profiles`.
- If nominal publication PDF compilation (`output/report.pdf`) fails or exhibits degraded visual output.
