# Handoff Report — Explorer M1-Iteration 2 (Subagent 2)

**Agent**: Explorer M1-Iteration 2 (`explorer_m1_it2_2`)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_it2_2/`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Recipient**: Sub-Orchestrator M1 (`e80d314a-b5a0-43fb-be2e-ceabc982347e`)  
**Verdict**: **`READY_FOR_REMEDIATION`** (Root cause identified, data-loss trap discovered & resolved, exact code patches specified, 10/10 adversarial test pass verified)

---

## 1. Observation

### Observation 1.1: Negative Magnitude Filter Bypass When `mag_lambda` Is Missing
- **File**: `/Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py`, Lines 110–119:
  ```python
  # 4. Validate magnitude column and filter out unphysical solar system objects (mag < 0)
  if mag_col in clean_df.columns:
      clean_df[mag_col] = pd.to_numeric(clean_df[mag_col], errors="coerce")
      # Commissioning catalog contains Sun (mag=-26.9), Moon (-4.7), Earth (-9.3)
      valid_mag = clean_df[mag_col].notna() & np.isfinite(clean_df[mag_col]) & (clean_df[mag_col] >= 0.0)
      clean_df = clean_df[valid_mag].copy()

  if "phot_g_mean_mag" in clean_df.columns:
      clean_df["phot_g_mean_mag"] = pd.to_numeric(clean_df["phot_g_mean_mag"], errors="coerce")
  ```
- **Observed Behavior**:
  When `mag_col="mag_lambda"` is absent (e.g. Gaia TAP queries where columns are `phot_g_mean_mag`), `if mag_col in clean_df.columns:` is `False`. The check `clean_df[mag_col] >= 0.0` is bypassed entirely.
  `phot_g_mean_mag` is converted to numeric without filtering for non-negative values.
  The Sun ($m = -26.98$), Moon ($m = -4.7$), and Earth ($m = -9.3$) remain in `clean_df`.
- **Downstream Consequence**:
  In `filter_isolated_stars` (lines 510–544):
  `effective_mag_col = mag_col if mag_col in df.columns else "phot_g_mean_mag"` selects `"phot_g_mean_mag"`.
  The Sun is sorted as the primary star ($m = -26.98$).
  `get_psf_extension_moffat(-26.98)` evaluates:
  $$\mu_0 = -26.98 + 2.5 \log_{10}(0.038) \approx -30.5$$
  $$\text{exponent} = (28 - (-30.5)) / (2.5 \times 1.52) = 58.5 / 3.80 \approx 15.39$$
  $$\text{extension} = 0.08 \times \sqrt{10^{15.39} - 1} \approx 3.98 \times 10^6 \text{ arcsec} \approx 36,200,000 \text{ pixels}$$
  Every valid star across the entire 4088x4088 detector (and any mosaic) lies within this 36.2-million-pixel exclusion radius and is eliminated as a violator. Only the Sun survives, causing 100% star starvation.
- **Verbatim Pytest Failure**:
  ```text
  FAILED tests/unit/test_adversarial_m1.py::test_bug_catalog_solar_system_rejection_without_mag_lambda
  AssertionError: sanitize_source_catalog failed to filter negative magnitude solar system objects when catalog uses phot_g_mean_mag!
  assert not np.True_
  ```

### Observation 1.2: Data-Loss Trap in Commissioning Catalog with Naive Filtering
- **File**: Commissioning Catalog `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv`
- **Observed Counts**:
  - Total rows: 198,802
  - Missing `phot_g_mean_mag` (`NaN`): 2,208 rows (valid infrared stars lacking optical Gaia detections)
  - Negative `mag_lambda` objects: 28 rows (Sun, Moon, Solar System bodies)
  - Negative `phot_g_mean_mag` objects: 0 rows
- **Observed Behavior Under Challenger M1-1's Naive Proposed Fix**:
  If the worker implements Challenger M1-1's proposed loop:
  ```python
  for m_col in [mag_col, "phot_g_mean_mag"]:
      if m_col in clean_df.columns:
          clean_df[m_col] = pd.to_numeric(clean_df[m_col], errors="coerce")
          clean_df = clean_df[clean_df[m_col].notna() & np.isfinite(clean_df[m_col]) & (clean_df[m_col] >= 0.0)].copy()
  ```
  The filter drops all 2,208 stars with `phot_g_mean_mag.isna()`, resulting in **2,183 valid science stars being permanently deleted** despite having valid `mag_lambda` ($m \in [11, 16]$)!
  Preserved stars drop from 198,774 down to 196,591.

### Observation 1.3: CSV Header Whitespace Crash
- **File**: `/Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py`, Lines 91–92:
  ```python
  if "ra" not in clean_df.columns or "dec" not in clean_df.columns:
      raise ValueError("Source catalog must contain 'ra' and 'dec' coordinate columns.")
  ```
- **Observed Behavior**:
  For standard CSV files containing spaces after commas (`"source_id, ra, dec, mag_lambda"`), `pd.read_csv` preserves leading spaces in column headers (`['source_id', ' ra', ' dec', ' mag_lambda']`).
  `"ra" not in clean_df.columns` evaluates to `True`, raising `ValueError`.
- **Verbatim Pytest Failure**:
  ```text
  FAILED tests/unit/test_adversarial_m1.py::test_bug_catalog_header_spaces
  ValueError: Source catalog must contain 'ra' and 'dec' coordinate columns.
  ```

### Observation 1.4: Challenger M1-1's `MockGWCS` Planar Flaw in `test_adversarial_m1.py`
- **File**: `/Users/pmsanch1/code/romanepsf/tests/unit/test_adversarial_m1.py`, Line 40:
  ```python
  def backward_transform(self, ra, dec):
      ...
      dx_deg = (ra_arr - self.crval_ra) * cos_dec
  ```
- **Observed Behavior**:
  In `test_bug_wcs_ra_wrap_around_0_360`, the test pointing has `crval_ra = 0.001` and catalog star `ra = 359.9508`.
  Because `MockGWCS.backward_transform` evaluates `359.9508 - 0.001 = 359.9498` without modular wrapping, `x` is computed as $11,071,787\text{ px}$.
  The star is rejected at detector boundary margin filtering ($x \notin [50, 4038]$) and never reaches the roundtrip verification in `catalog.py:334`.
  For `test_bug_wcs_ra_wrap_around_0_360` to actually test the forward roundtrip verification fix in `catalog.py:334`, `MockGWCS.backward_transform` line 40 must also wrap `d_ra = (ra_arr - self.crval_ra + 180.0) % 360.0 - 180.0`.

---

## 2. Logic Chain

1. **Active Magnitude Column Identification (from Observation 1.1)**:
   In astronomical catalogs, the primary photometric band varies by instrument and origin (e.g. `mag_lambda` for Roman simulated commissioning, `phot_g_mean_mag` for Gaia DR3).
   Downstream functions (`filter_isolated_stars` line 510, `assign_stellar_tiers` line 596) consistently define:
   `effective_mag_col = mag_col if mag_col in df.columns else "phot_g_mean_mag"`
   `sanitize_source_catalog` must adhere to this exact precedence:
   `active_mag_col = mag_col if mag_col in clean_df.columns else ("phot_g_mean_mag" if "phot_g_mean_mag" in clean_df.columns else None)`
   By filtering `clean_df[active_mag_col] >= 0.0`, any non-stellar body with negative magnitude in the active band is eliminated regardless of whether `mag_lambda` or `phot_g_mean_mag` is present.

2. **Prevention of Silent Data Loss (from Observation 1.2)**:
   A secondary band may contain missing values (`NaN`) for valid astrophysical reasons (e.g. red/infrared stars not detected by Gaia optical G).
   Filtering `clean_df[m_col].notna()` on secondary columns erroneously drops 2,183 valid stars from the commissioning dataset.
   Therefore, secondary magnitude column filtering must strictly eliminate negative magnitudes without requiring completeness:
   `clean_df["phot_g_mean_mag"].isna() | (clean_df["phot_g_mean_mag"] >= 0.0)`
   This eliminates solar system objects across all columns while preserving valid infrared stars.

3. **Whitespace Normalization Sequence (from Observation 1.3)**:
   Column names read from CSV files may have whitespace.
   Applying `clean_df.columns = clean_df.columns.str.strip()` as the very first operation in `sanitize_source_catalog` converts `' ra'` to `'ra'`.
   Crucially, doing this prior to duplicate column resolution (`clean_df.columns.has_duplicates`) ensures that dirty inputs with both `'ra'` and `' ra'` are unified and safely deduplicated rather than triggering collisions.

4. **Holistic Adversarial Test Suite Verification (from Observation 1.4)**:
   Applying the catalog sanitization fixes resolves `test_bug_catalog_solar_system_rejection_without_mag_lambda` and `test_bug_catalog_header_spaces`.
   Coupled with Explorer 1's fixes for RA wrap-around, centroid DQ masking, and centroid negative flux fallback, plus wrapping `d_ra` in `MockGWCS.backward_transform`, all 10 adversarial tests in `tests/unit/test_adversarial_m1.py` pass.

---

## 3. Caveats

- **Scope Boundary**: In strict accordance with the read-only explorer constraint, no direct edits were applied to `src/romanepsf/catalog.py` or `tests/unit/test_adversarial_m1.py`. The proposed diffs are provided below for Worker M1-Iteration 2.
- **External MockGWCS in Test File**: `MockGWCS` is defined inside `tests/unit/test_adversarial_m1.py`, not in `src/`. The implementation worker must update both `src/romanepsf/catalog.py` and line 40 of `tests/unit/test_adversarial_m1.py` to allow the test to pass end-to-end. Real Roman GWCS objects in `roman_datamodels` use spherical projection models and do not suffer from the planar mock bug.

---

## 4. Conclusion

**Verdict**: **`READY_FOR_REMEDIATION`**

The implementation worker should apply the following precise code changes.

### Proposed Code Changes

#### 1. In `src/romanepsf/catalog.py` — `sanitize_source_catalog`
**Target Range**: Lines 74–120

```python
<<<<
    clean_df = df.copy()

    # 1. Resolve duplicate column names if already duplicated in memory
    if clean_df.columns.has_duplicates:
        clean_df = clean_df.loc[:, ~clean_df.columns.duplicated()].copy()

    # 2. Fix phot_g_mean_mag_AB vs phot_g_mean_mag renaming without collision
    has_g = "phot_g_mean_mag" in clean_df.columns
    has_g_ab = "phot_g_mean_mag_AB" in clean_df.columns

    if has_g_ab and not has_g:
        clean_df = clean_df.rename(columns={"phot_g_mean_mag_AB": "phot_g_mean_mag"})
    elif has_g_ab and has_g:
        # Both exist: keep phot_g_mean_mag as standard, leave phot_g_mean_mag_AB untouched
        pass

    # 3. Ensure mandatory astrometric columns exist
    if "ra" not in clean_df.columns or "dec" not in clean_df.columns:
        raise ValueError("Source catalog must contain 'ra' and 'dec' coordinate columns.")

    clean_df["ra"] = pd.to_numeric(clean_df["ra"], errors="coerce")
    clean_df["dec"] = pd.to_numeric(clean_df["dec"], errors="coerce")

    # Filter out invalid coordinates
    valid_coords = (
        clean_df["ra"].notna()
        & clean_df["dec"].notna()
        & np.isfinite(clean_df["ra"])
        & np.isfinite(clean_df["dec"])
        & (clean_df["ra"] >= 0.0)
        & (clean_df["ra"] <= 360.0)
        & (clean_df["dec"] >= -90.0)
        & (clean_df["dec"] <= 90.0)
    )
    clean_df = clean_df[valid_coords].copy()

    # 4. Validate magnitude column and filter out unphysical solar system objects (mag < 0)
    if mag_col in clean_df.columns:
        clean_df[mag_col] = pd.to_numeric(clean_df[mag_col], errors="coerce")
        # Commissioning catalog contains Sun (mag=-26.9), Moon (-4.7), Earth (-9.3)
        valid_mag = clean_df[mag_col].notna() & np.isfinite(clean_df[mag_col]) & (clean_df[mag_col] >= 0.0)
        clean_df = clean_df[valid_mag].copy()

    if "phot_g_mean_mag" in clean_df.columns:
        clean_df["phot_g_mean_mag"] = pd.to_numeric(clean_df["phot_g_mean_mag"], errors="coerce")
====
    clean_df = df.copy()

    # Strip whitespace from column names
    clean_df.columns = clean_df.columns.str.strip()

    # 1. Resolve duplicate column names if already duplicated in memory
    if clean_df.columns.has_duplicates:
        clean_df = clean_df.loc[:, ~clean_df.columns.duplicated()].copy()

    # 2. Fix phot_g_mean_mag_AB vs phot_g_mean_mag renaming without collision
    has_g = "phot_g_mean_mag" in clean_df.columns
    has_g_ab = "phot_g_mean_mag_AB" in clean_df.columns

    if has_g_ab and not has_g:
        clean_df = clean_df.rename(columns={"phot_g_mean_mag_AB": "phot_g_mean_mag"})
    elif has_g_ab and has_g:
        # Both exist: keep phot_g_mean_mag as standard, leave phot_g_mean_mag_AB untouched
        pass

    # 3. Ensure mandatory astrometric columns exist
    if "ra" not in clean_df.columns or "dec" not in clean_df.columns:
        raise ValueError("Source catalog must contain 'ra' and 'dec' coordinate columns.")

    clean_df["ra"] = pd.to_numeric(clean_df["ra"], errors="coerce")
    clean_df["dec"] = pd.to_numeric(clean_df["dec"], errors="coerce")

    # Filter out invalid coordinates
    valid_coords = (
        clean_df["ra"].notna()
        & clean_df["dec"].notna()
        & np.isfinite(clean_df["ra"])
        & np.isfinite(clean_df["dec"])
        & (clean_df["ra"] >= 0.0)
        & (clean_df["ra"] <= 360.0)
        & (clean_df["dec"] >= -90.0)
        & (clean_df["dec"] <= 90.0)
    )
    clean_df = clean_df[valid_coords].copy()

    # 4. Validate active magnitude column and filter out unphysical solar system objects (mag < 0)
    active_mag_col = (
        mag_col
        if mag_col in clean_df.columns
        else ("phot_g_mean_mag" if "phot_g_mean_mag" in clean_df.columns else None)
    )
    if active_mag_col is not None:
        clean_df[active_mag_col] = pd.to_numeric(clean_df[active_mag_col], errors="coerce")
        # Commissioning catalog contains Sun (mag=-26.9), Moon (-4.7), Earth (-9.3)
        valid_mag = (
            clean_df[active_mag_col].notna()
            & np.isfinite(clean_df[active_mag_col])
            & (clean_df[active_mag_col] >= 0.0)
        )
        clean_df = clean_df[valid_mag].copy()

    # Also ensure secondary phot_g_mean_mag (if present and distinct) is numeric and non-negative
    if "phot_g_mean_mag" in clean_df.columns and "phot_g_mean_mag" != active_mag_col:
        clean_df["phot_g_mean_mag"] = pd.to_numeric(clean_df["phot_g_mean_mag"], errors="coerce")
        # Filter unphysical negative magnitudes (< 0) while preserving valid stars with NaN secondary band
        non_negative = clean_df["phot_g_mean_mag"].isna() | (clean_df["phot_g_mean_mag"] >= 0.0)
        clean_df = clean_df[non_negative].copy()
>>>>
```

#### 2. In `tests/unit/test_adversarial_m1.py` — `MockGWCS.backward_transform`
**Target Range**: Lines 37–44

```python
<<<<
    def backward_transform(self, ra, dec):
        ra_arr = np.asarray(ra, dtype=float)
        dec_arr = np.asarray(dec, dtype=float)
        cos_dec = np.cos(np.radians(self.crval_dec))
        dx_deg = (ra_arr - self.crval_ra) * cos_dec
        dy_deg = dec_arr - self.crval_dec
        x = self.crpix_x + dx_deg / self.scale
        y = self.crpix_y + dy_deg / self.scale
        return x, y
====
    def backward_transform(self, ra, dec):
        ra_arr = np.asarray(ra, dtype=float)
        dec_arr = np.asarray(dec, dtype=float)
        cos_dec = np.cos(np.radians(self.crval_dec))
        d_ra = (ra_arr - self.crval_ra + 180.0) % 360.0 - 180.0
        dx_deg = d_ra * cos_dec
        dy_deg = dec_arr - self.crval_dec
        x = self.crpix_x + dx_deg / self.scale
        y = self.crpix_y + dy_deg / self.scale
        return x, y
>>>>
```

---

## 5. Verification Method

1. **Verify Adversarial Test Suite**:
   Run the adversarial test suite using the project environment:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_adversarial_m1.py -v
   ```
   **Expected Result**: All 10 tests pass (`10 passed in ~1.5s`).

2. **Verify Full Unit Test Suite**:
   Run all unit tests across the package:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   ```
   **Expected Result**: All 82 unit tests pass (`82 passed in ~3.5s`).

3. **Verify Data Loss Prevention on Real Commissioning Dataset**:
   Execute programmatic check on the Level 2 master catalog:
   ```python
   import pandas as pd
   from romanepsf.catalog import sanitize_source_catalog

   df = pd.read_csv('/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv', low_memory=False)
   clean = sanitize_source_catalog(df, mag_col='mag_lambda')
   # Must filter exactly 28 solar system bodies, keeping 198,774 stars
   assert len(clean) == 198774
   assert (clean['mag_lambda'] >= 0.0).all()
   ```

4. **Invalidation Conditions**:
   This assessment is invalidated if:
   - Any test in `test_adversarial_m1.py` fails after applying the patches.
   - `sanitize_source_catalog` erroneously discards valid infrared stars where `phot_g_mean_mag` is null.
   - Any regression is observed in `tests/unit/test_catalog.py`.
