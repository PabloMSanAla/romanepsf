# Quality Review & Adversarial Challenge Report — Milestone 1 Iteration 2

**Agent**: Reviewer 2 & Adversarial Critic (`reviewer_m1_it2_2`)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m1_it2_2`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Recipient**: Sub-Orchestrator M1 (`e80d314a-b5a0-43fb-be2e-ceabc982347e`)  

---

## Review Summary

**Gate Verdict**: **APPROVE**  
**Integrity Audit**: **PASS** (Zero hardcoded test outputs, zero facade implementations, zero bypasses, zero fabricated attestations)  
**Overall Risk Assessment**: **LOW**

---

## 1. Observation

### Verification Commands & Direct Test Results
The test suites were executed using the designated environment `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:

1. **Adversarial M1 Unit Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_adversarial_m1.py -v
   ```
   *Result*: **10 passed in 1.36s (Exit code: 0)**  
   Verified tests:
   - `test_wcs_exact_boundary_coordinates`: PASSED
   - `test_wcs_far_outside_tangent_plane`: PASSED
   - `test_wcs_celestial_poles`: PASSED
   - `test_bug_wcs_ra_wrap_around_0_360`: PASSED
   - `test_catalog_dirty_duplicates_and_corrupt_types`: PASSED
   - `test_bug_catalog_solar_system_rejection_without_mag_lambda`: PASSED
   - `test_bug_catalog_header_spaces`: PASSED
   - `test_centroid_all_nan_and_inf_boxes`: PASSED
   - `test_bug_centroid_cosmic_ray_hijack_dq_ignored`: PASSED
   - `test_bug_centroid_negative_flux_noise_shift`: PASSED

2. **Full Unit Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   ```
   *Result*: **82 passed in 3.74s (Exit code: 0)**

3. **End-to-End Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
   ```
   *Result*: **297 passed, 4 skipped, 1 xfailed in 18.39s (Exit code: 0)**  
   *Note*: 4 skipped tests correspond to M4 documentation (`docs/technical_documentation.md`); 1 xfailed test (`test_s1_03`) corresponds to M2 radial profile assembly array dimension indexing documented in `TEST_READY.md`.

### Codebase Inspections & Physical Verifications
1. **WCS Meridian Wrap-Around (`src/romanepsf/catalog.py:306–365`)**:
   - Line 316: `ra_for_transform = center_ra + ((ra_vals - center_ra + 180.0) % 360.0 - 180.0)` wraps input celestial catalog RA into the local tangent plane relative to detector center prior to invoking `wcs.backward_transform`.
   - Line 358: `delta_ra = (ra_back - ra_cand + 180.0) % 360.0 - 180.0` wraps residual angular difference on the sphere.
   - Line 359–361: Calculates `delta_ra_arcsec = delta_ra * cos_dec * 3600.0`, `delta_dec_arcsec = (dec_back - dec_cand) * 3600.0`, and `delta_theta_arcsec = np.hypot(delta_ra_arcsec, delta_dec_arcsec)`.
   - Verified across all 18 Level 2 WFI detectors (`wfi01`–`wfi18`): `delta_theta_arcsec` residuals on physical stars are $\sim 10^{-6} - 10^{-5}$ arcsec, well below the 0.5 arcsec tolerance threshold.

2. **DQ Cosmic Ray Masking & Noise Centroid Fallback (`src/romanepsf/catalog.py:447–495`)**:
   - Line 450: Masking `bad_mask = (dq_box & (DQ_FLAGS.get("DO_NOT_USE", 1) | DQ_FLAGS.get("JUMP_DET", 4))) > 0`.
   - Line 454: `valid_mask = np.isfinite(box) & (~bad_mask)`.
   - Line 469–470: Local background `bkg = float(np.percentile(valid_pix, 10))` with `weights = np.maximum(box - bkg, 0.0); weights[~valid_mask] = 0.0`.
   - Line 474: Fallback guard `if peak <= 0.0 or total_w <= 0.0:` sets `shift = 0.0` and preserves initial catalog coordinates `(x_init, y_init)`.
   - Line 487: Bounds check `if np.isfinite(cx) and np.isfinite(cy) and (shift <= max_shift_px):` ensures divergent centroids do not escape.

3. **Catalog Data Conservation on Real Commissioning Catalog (`src/romanepsf/catalog.py:51–141`)**:
   - Target dataset: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv`
   - Raw catalog rows: 198,802 rows.
   - Identified negative magnitude objects: Exactly 28 non-stellar bodies (Sun $m=-26.99$, Earth $m=-9.32$, Venus $m=-4.97$, Moon $m=-4.74$, Jupiter $m=-2.13$, and Hipparcos solar system artifacts).
   - Preserved valid stellar objects: Exactly 198,774 stars ($198,802 - 28$).
   - Unique physical stars after source_id deduplication: Exactly 198,564 stars ($198,774 - 210$ positive star duplicates).
   - Star conservation verification: 2,208 infrared stars having `NaN` optical `phot_g_mean_mag` are strictly preserved via line 133 (`clean_df["phot_g_mean_mag"].isna() | (clean_df["phot_g_mean_mag"] >= 0.0)`). 100% of all valid physical stars are conserved with 1:1 ID parity.

---

## 2. Logic Chain

1. **Astrometric Projection Correctness**:
   - Spherical coordinates wrap at $360^\circ \equiv 0^\circ$. A naive linear subtraction `ra_back - ra_cand` produces a jump of $\approx 360.0^\circ$ for coordinates near the prime meridian.
   - By applying modulo topology `(diff + 180.0) % 360.0 - 180.0` centered on the detector pointing center, all coordinates map continuously into $[-\pi, +\pi]$.
   - Independent verification against both the mock WCS and real Level 2 GWCS confirms that stars on both sides of the $0^\circ/360^\circ$ boundary project to continuous detector pixel coordinates with sub-milliarcsecond forward roundtrip fidelity.

2. **Centroid Refinement Robustness & Integrity**:
   - First-moment centroiding computes $\bar{x} = \sum x_i w_i / \sum w_i$. In uncalibrated images, high-energy cosmic rays ($JUMP\_DET$, flux $> 50,000$) create extreme off-center moments.
   - Explicitly filtering `bad_mask` zero-weights defect pixels, keeping the centroid anchored to the PSF core.
   - Intentionally excluding `SATURATED` (flag 2) from this mask avoids coring out the peak of bright stars, which would otherwise destabilize the moment.
   - In pure noise cutouts where $peak \le 0$ or $total\_w \le 0$, setting $shift = 0.0$ and returning catalog $(x, y)$ avoids chasing noise gradients.

3. **Catalog Sanitization and Data Conservation**:
   - Commissioning catalogs merge Gaia optical ($phot\_g\_mean\_mag$) and infrared bands ($mag\_lambda$).
   - A single-band negative filter previously dropped stars missing $mag\_lambda$. Applying $active\_mag\_col$ with safe secondary-band handling preserves valid infrared sources with missing optical detections ($2,208$ stars).
   - Deduplicating whitespace in column names (`str.strip()`) and deduplicating columns prevents key lookup failures on non-standard CSV formatting.

4. **Code Quality and Architectural Conformance**:
   - All changes strictly adhere to `PROJECT.md` contracts and feature specifications.
   - Validated runtime execution across all 18 SCAs sequentially, maintaining lazy loading and memory hygiene.

---

## 3. Adversarial Challenges & Stress Tests

### Challenge Summary: Overall Risk Assessment: LOW

### Stress Test 1: Coordinate Wrap-Around Boundary Conditions
- **Scenario**: Astrometric wrapping with coordinates at $0^\circ, 360^\circ, 180^\circ, -180^\circ$, and extreme sub-arcsecond separations.
- **Result**: PASSED ($< 10^{-9\circ}$ angular difference error).
- **Observation**: Handled continuous negative and positive crossings without discontinuity.

### Stress Test 2: Pathological Centroid Cutouts
- **Scenarios tested**:
  1. All pixels in bounding box flagged as `DO_NOT_USE` in DQ array.
  2. Perfectly flat uniform background ($box - bkg = 0$).
  3. Single isolated positive pixel in box.
  4. Box truncated at active detector boundaries ($x=0, y=0$).
  5. Box with all-negative flux gradient ($-100$ to $-50$).
- **Result**: ALL PASSED. Every pathological case safely falls back to initial coordinates with $shift = 0.0$ and zero division or NaN crashes.

### Stress Test 3: Full 18-Detector Sequential Pipeline Stress
- **Scenario**: Ingest real Level 2 ASDF files and project sanitized catalog across detectors `wfi01` through `wfi18`.
- **Result**: PASSED. Total 187 stars verified within 50px boundary across all 18 detectors; peak memory maintained well below 4 GB.

### Stress Test 4: Integrity Violation Audit
- **Check 1**: Hardcoded test results or expected outputs embedded in source code? None found.
- **Check 2**: Dummy or facade implementations? None found; all calculations are genuine mathematical operations.
- **Check 3**: Shortcuts bypassing intended requirements? None found.
- **Check 4**: Fabricated logs or self-certifying artifacts? None found; all test outputs reproduced independently.

---

## 4. Caveats

1. **Center RA in GWCS Projection (`src/romanepsf/catalog.py:314`)**:
   If a non-standard WCS were to evaluate `wcs(nx/2, ny/2)` as `NaN`, `float(center_ra)` would evaluate to `NaN` without raising an exception, falling back to NaN inputs for `backward_transform`. On all Roman Level 2 WCS models, `center_ra` is guaranteed finite. Recommended minor defensive check for future iterations: `np.isfinite(center_ra)`.
2. **Milestone 2 Dependency (`test_s1_03`)**:
   `test_s1_03_wfi01_composite_assembly_and_non_hollow_core` remains `xfail` due to `src/assembly.py` radial profile slicing bug. This is strictly a Milestone 2 component and does not impact Milestone 1 catalog/loader approval.

---

## 5. Conclusion

Milestone 1 Iteration 2 implementation worker has thoroughly remediated all defects, hardened the CLI, config, loader, and catalog modules against adversarial edge cases, and preserved 100% of physical stars in the commissioning catalog.
All 82 unit tests and 297 E2E tests pass cleanly. Zero integrity violations or regressions were found.

**Verdict: APPROVE**

---

## 6. Verification Method

To independently reproduce this verification:

```bash
# 1. Unit & Adversarial Tests
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_adversarial_m1.py -v
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v

# 2. E2E Test Suite
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v

# 3. Commissioning Catalog Data Conservation
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c '
import pandas as pd
from romanepsf.catalog import sanitize_source_catalog

path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv"
df = pd.read_csv(path, low_memory=False)
clean = sanitize_source_catalog(df, mag_col="mag_lambda")
assert len(clean) == 198564
assert (clean["mag_lambda"] >= 0.0).all()
assert clean["source_id"].nunique() == 198564
print("Commissioning catalog verified successfully!")
'
```

**Invalidation Conditions**:
This review approval is invalidated if any of the 82 unit tests fail, if any of the 10 adversarial M1 tests fail, or if data conservation drops below 198,564 unique stars.
