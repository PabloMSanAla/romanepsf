# Handoff Report — Explorer M1-Iteration 2: Remediation Strategy for M1 Adversarial Defects

**Agent**: Explorer M1-Iteration 2 (Subagent 1)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_it2_1/`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Recipient**: Parent Orchestrator (`e80d314a-b5a0-43fb-be2e-ceabc982347e`) / Implementation Worker  

---

## 1. Observation

Direct observations obtained by executing pytest and code analysis against `src/romanepsf/` and `tests/unit/test_adversarial_m1.py` using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:

### Baseline Reproduction
Running `pytest tests/unit/test_adversarial_m1.py` reproduces exactly 5 failures out of 10 tests (5 passed, 5 failed):
```text
=================================== FAILURES ===================================
FAILED tests/unit/test_adversarial_m1.py::test_bug_wcs_ra_wrap_around_0_360
FAILED tests/unit/test_adversarial_m1.py::test_bug_catalog_solar_system_rejection_without_mag_lambda
FAILED tests/unit/test_adversarial_m1.py::test_bug_catalog_header_spaces
FAILED tests/unit/test_adversarial_m1.py::test_bug_centroid_cosmic_ray_hijack_dq_ignored
FAILED tests/unit/test_adversarial_m1.py::test_bug_centroid_negative_flux_noise_shift
========================= 5 failed, 5 passed in 1.38s ==========================
```

### Observation 1.1: Astrometric WCS Meridian Wrap-around in `project_catalog_to_pixels`
- **File**: `src/romanepsf/catalog.py`, Lines 297–305 & 333–336
- **Current Code**:
  ```python
  # Line 297
  if hasattr(wcs, "backward_transform"):
      x_cand, y_cand = wcs.backward_transform(ra_vals, dec_vals)
  ...
  # Line 333
  cos_dec = np.cos(np.radians(dec_cand))
  delta_ra_arcsec = (ra_back - ra_cand) * cos_dec * 3600.0
  delta_dec_arcsec = (dec_back - dec_cand) * 3600.0
  delta_theta_arcsec = np.hypot(delta_ra_arcsec, delta_dec_arcsec)
  ```
- **Observed Behavior**:
  1. For an astronomical pointing centered near $\text{RA} = 0.001^\circ$, a catalog star physically on the detector at $(x=500, y=2044)$ has celestial $\text{RA} = 359.9508^\circ$.
  2. In `wcs.backward_transform(ra_vals, dec_vals)`, passing $359.9508^\circ$ directly to tangent-plane backward projection without centering causes $\Delta\alpha = 359.9508 - 0.001 = 359.9498^\circ$, yielding $x_{\text{cand}} \approx 11,071,787\text{ px}$. This immediately fails boundary check `x_cand <= (nx - margin_px)`.
  3. When forward verified, $ra_{\text{back}} \approx -0.0492^\circ$ while $ra_{\text{cand}} = 359.9508^\circ$. The naive difference $ra_{\text{back}} - ra_{\text{cand}} = -360.0^\circ$ evaluates to $\Delta\theta \approx 1.22 \times 10^6\text{ arcsec} \gg 0.5''$, causing 100% false rejection of stars crossing the prime meridian.
- **Verbatim Error**:
  ```text
  AssertionError: Star crossing RA 0/360 meridian was falsely rejected! ra_catalog=359.9508, expected on detector at x=500, y=2044.
  assert 0 == 1
  ```

### Observation 1.2: Centroid Refinement Missing DQ Bitmasking (`DO_NOT_USE` & `JUMP_DET`)
- **File**: `src/romanepsf/catalog.py`, Lines 395–435
- **Current Code**:
  `RomanL2Data` includes `l2_data.dq`, but `refine_stellar_centroids` never reads `l2_data.dq` or filters bad data quality pixels.
- **Observed Behavior**:
  When a cosmic ray flagged with `JUMP_DET = 4` (or `DO_NOT_USE = 1`) occurs at $(52, 51)$ with high flux ($50,000\text{ DN/s}$) adjacent to a real star at $(50, 50)$ with peak $500\text{ DN/s}$, the unmasked moments shift the stellar centroid to $(51.753, 50.876)$ (shift $= 1.959\text{ px} \le 3.0\text{ px}$), hijacking the star center onto the cosmic ray.
- **Verbatim Error**:
  ```text
  AssertionError: Centroid was hijacked by cosmic ray! refined_x=51.753, true star is at x=50.0, shift=1.959 px
  assert np.float64(1.7525360620025978) < 0.5
  ```

### Observation 1.3: Centroid Moment Shifts on Non-Positive / Negative Flux Noise
- **File**: `src/romanepsf/catalog.py`, Lines 424–440
- **Current Code**:
  ```python
  bkg = float(np.percentile(valid_pix, 10))
  weights = np.maximum(box - bkg, 0.0)
  total_w = np.sum(weights)
  ```
- **Observed Behavior**:
  When all pixels in `box` are negative noise (e.g. gradient from $-100$ to $-50$, $\text{peak} = -72.5$), $bkg = -95.0$ and $weights = \max(box - (-95), 0) > 0$. The routine computes a spurious moment shift of $2.333\text{ px}$ on pure noise and accepts it because $2.333 \le 3.0\text{ px}$.
- **Verbatim Error**:
  ```text
  AssertionError: Centroid was shifted on pure negative background noise! shift=2.333 px, peak=-72.5
  assert np.float64(2.3333333333333357) == 0.0
  ```

### Observation 1.4: Solar System Objects Bypassing Sanitization when `mag_lambda` is Absent
- **File**: `src/romanepsf/catalog.py`, Lines 111–119
- **Current Code**:
  ```python
  if mag_col in clean_df.columns:
      clean_df[mag_col] = pd.to_numeric(clean_df[mag_col], errors="coerce")
      valid_mag = clean_df[mag_col].notna() & np.isfinite(clean_df[mag_col]) & (clean_df[mag_col] >= 0.0)
      clean_df = clean_df[valid_mag].copy()
  if "phot_g_mean_mag" in clean_df.columns:
      clean_df["phot_g_mean_mag"] = pd.to_numeric(clean_df["phot_g_mean_mag"], errors="coerce")
  ```
- **Observed Behavior**:
  If a catalog uses `phot_g_mean_mag` without `mag_lambda` (e.g. Gaia TAP query), `mag_col in clean_df.columns` is False. The negative magnitude filter (`>= 0.0`) is skipped, leaving the Sun ($m = -26.98$). Downstream in `filter_isolated_stars`, the Sun generates a 30M-pixel Moffat exclusion radius that eliminates 100% of real stars.
- **Verbatim Error**:
  ```text
  AssertionError: sanitize_source_catalog failed to filter negative magnitude solar system objects when catalog uses phot_g_mean_mag!
  assert not np.True_
  ```

### Observation 1.5: Unstripped Whitespace in CSV Headers
- **File**: `src/romanepsf/catalog.py`, Lines 91–92
- **Current Code**:
  `clean_df.columns` retains raw CSV header strings without `.str.strip()`.
- **Observed Behavior**:
  Headers formatted with spaces after commas (`source_id, ra, dec, mag_lambda`) yield `['source_id', ' ra', ' dec', ' mag_lambda']`. `"ra" not in clean_df.columns` raises `ValueError: Source catalog must contain 'ra' and 'dec' coordinate columns.`
- **Verbatim Error**:
  ```text
  ValueError: Source catalog must contain 'ra' and 'dec' coordinate columns.
  ```

---

## 2. Logic Chain

1. **Astrometric Projection and Roundtrip Spherical Topology**:
   - Celestial RA is a circular angle with topology $S^1$, period $360^\circ$.
   - Any difference $\Delta\alpha = \alpha_1 - \alpha_2$ must be mapped to the principal branch $(-\pi, +\pi]$ (or $[-180^\circ, +180^\circ]$):
     $$\Delta\alpha_{\text{wrapped}} = (\Delta\alpha + 180^\circ) \pmod{360^\circ} - 180^\circ$$
   - For `wcs.backward_transform`, tangent-plane projection algorithms require coordinates close to the pointing reference center $\alpha_0$. Ingested catalog $\alpha$ values in $[0, 360)$ straddling $\alpha_0 \approx 0^\circ$ must be expressed relative to $\alpha_0$:
     $$\alpha_{\text{transform}} = \alpha_0 + ((\alpha - \alpha_0 + 180^\circ) \pmod{360^\circ} - 180^\circ)$$
   - In forward roundtrip verification:
     $$\Delta\alpha_{\text{arcsec}} = ((\alpha_{\text{back}} - \alpha_{\text{cand}} + 180^\circ) \pmod{360^\circ} - 180^\circ) \times \cos(\delta_{\text{cand}}) \times 3600''$$
   - Applying both transformations ensures stars crossing $0^\circ / 360^\circ$ project to correct detector coordinates $(x \in [50, 4038])$ and pass the $\Delta\theta < 0.5''$ tolerance check.

2. **Cosmic Ray Rejection in Centroid Moments**:
   - Roman Level 2 data flags single-pixel and multi-pixel energy deposits (cosmic rays) with bit flags:
     - `DO_NOT_USE` $= 1$ (Bit 0)
     - `JUMP_DET` $= 4$ (Bit 2)
   - When extracting a stellar cutout `box = data[y0:y1, x0:x1]`, reading `dq_box = l2_data.dq[y0:y1, x0:x1]` and identifying:
     `bad_mask = (dq_box & (DQ_FLAGS["DO_NOT_USE"] | DQ_FLAGS["JUMP_DET"])) > 0`
     allows constructing `valid_mask = np.isfinite(box) & (~bad_mask)`.
   - Setting `weights[~valid_mask] = 0.0` completely zeros out the flux contribution from cosmic rays. The computed first-order moments $(\sum x_i w_i / \sum w_i, \sum y_i w_i / \sum w_i)$ then faithfully reflect only the astronomical stellar PSF core.

3. **Peak Flux Guard and Pure Noise Gradient Protection**:
   - A real star on an astronomical image must exhibit positive peak flux above local background ($peak > 0$).
   - If all pixels in `valid_pix` are non-positive ($peak \le 0.0$), or if the cutout is completely flat ($total\_w \le 0.0$), the region contains no astronomical source.
   - Guard condition:
     ```python
     if peak <= 0.0 or total_w <= 0.0:
         x_refined.append(x_init)
         y_refined.append(y_init)
         peak_fluxes.append(peak)
         shifts.append(0.0)
         continue
     ```
   - This prevents moment calculations on noise gradients, cleanly maintaining initial catalog coordinates with `shift = 0.0`.

4. **Catalog Ingestion Resilience**:
   - Cleaning `clean_df.columns = clean_df.columns.astype(str).str.strip()` normalizes any spaces following commas.
   - Enforcing $mag \ge 0.0$ on both `mag_col` (when present) and `phot_g_mean_mag` (when `mag_col` is absent or when present) removes unphysical solar system objects (Sun, Moon, Earth) regardless of catalog format.

---

## 3. Caveats

1. **Non-Planar WCS Projections**: The RA transformation wraps coordinates relative to the detector center `wcs(nx/2, ny/2)`. For WFI detectors, the field of view is $\sim 0.28^\circ \times 0.28^\circ$, which is well within the $[-180^\circ, +180^\circ]$ branch.
2. **Missing DQ Array in Mocks**: Synthetic test datasets may have `l2_data.dq = None`. The code guards with `hasattr(l2_data, "dq") and l2_data.dq is not None`, creating an all-False mask when absent.
3. **Saturated Stellar Cores**: Note that `DQ_FLAGS["SATURATED"]` ($2$) is intentionally NOT masked in `refine_stellar_centroids`. For bright stars, masking saturation would hollow out the core; saturation handling is handled downstream during multi-tier profile normalization.

---

## 4. Conclusion

All 5 defects identified by Challenger M1-1 have been analyzed and an exact, regression-free remediation strategy designed and verified.

A clean, machine-applicable unified git patch has been generated and validated:
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_it2_1/catalog_fix.patch`

### Required Code Modifications in `src/romanepsf/catalog.py`:

#### 1. Import `DQ_FLAGS` (Line 18)
```python
# Before:
from romanepsf.loader import RomanL2Data

# After:
from romanepsf.loader import RomanL2Data, DQ_FLAGS
```

#### 2. Column Stripping & Negative Magnitude Filtering in `sanitize_source_catalog` (Lines 76 & 111–120)
```python
# In sanitize_source_catalog:
    clean_df = df.copy()

    # Strip whitespace from column names
    clean_df.columns = clean_df.columns.astype(str).str.strip()

    # 1. Resolve duplicate column names if already duplicated in memory
    if clean_df.columns.has_duplicates:
        clean_df = clean_df.loc[:, ~clean_df.columns.duplicated()].copy()
...
    if mag_col in clean_df.columns:
        clean_df[mag_col] = pd.to_numeric(clean_df[mag_col], errors="coerce")
        # Commissioning catalog contains Sun (mag=-26.9), Moon (-4.7), Earth (-9.3)
        valid_mag = clean_df[mag_col].notna() & np.isfinite(clean_df[mag_col]) & (clean_df[mag_col] >= 0.0)
        clean_df = clean_df[valid_mag].copy()

    if "phot_g_mean_mag" in clean_df.columns:
        clean_df["phot_g_mean_mag"] = pd.to_numeric(clean_df["phot_g_mean_mag"], errors="coerce")
        if mag_col not in clean_df.columns:
            valid_g = clean_df["phot_g_mean_mag"].notna() & np.isfinite(clean_df["phot_g_mean_mag"]) & (clean_df["phot_g_mean_mag"] >= 0.0)
            clean_df = clean_df[valid_g].copy()
        else:
            clean_df = clean_df[clean_df["phot_g_mean_mag"].isna() | (clean_df["phot_g_mean_mag"] >= 0.0)].copy()
```

#### 3. RA Wrap-around in `project_catalog_to_pixels` (Lines 293–305 & 333–337)
```python
    ra_vals = catalog_df["ra"].to_numpy(dtype=float)
    dec_vals = catalog_df["dec"].to_numpy(dtype=float)

    # Wrap RA relative to detector center to handle 0/360 boundary in backward transform
    try:
        center_ra, _ = wcs(nx / 2.0, ny / 2.0)
        center_ra = float(np.asarray(center_ra).flat[0])
        ra_for_transform = center_ra + ((ra_vals - center_ra + 180.0) % 360.0 - 180.0)
    except Exception:
        ra_for_transform = ra_vals

    # 1. Vectorized backward transform (sky -> detector pixels)
    if hasattr(wcs, "backward_transform"):
        x_cand, y_cand = wcs.backward_transform(ra_for_transform, dec_vals)
    elif hasattr(wcs, "invert"):
        x_cand, y_cand = wcs.invert(ra_for_transform, dec_vals)
    else:
        raise AttributeError("WCS object does not provide backward_transform or invert method.")
...
    # 3. Mandatory forward roundtrip verification (pixels -> sky)
    ra_back, dec_back = wcs(x_sub, y_sub)
    ra_back = np.asarray(ra_back, dtype=float)
    dec_back = np.asarray(dec_back, dtype=float)

    cos_dec = np.cos(np.radians(dec_cand))
    delta_ra = (ra_back - ra_cand + 180.0) % 360.0 - 180.0
    delta_ra_arcsec = delta_ra * cos_dec * 3600.0
    delta_dec_arcsec = (dec_back - dec_cand) * 3600.0
    delta_theta_arcsec = np.hypot(delta_ra_arcsec, delta_dec_arcsec)
```

#### 4. Centroid Refinement DQ Masking & Fallback Guard in `refine_stellar_centroids` (Lines 413–455)
```python
        box = data[y0:y1, x0:x1]

        if box.size == 0 or np.all(np.isnan(box)):
            x_refined.append(x_init)
            y_refined.append(y_init)
            peak_fluxes.append(0.0)
            shifts.append(0.0)
            continue

        # Mask bad DQ pixels (e.g. DO_NOT_USE=1, JUMP_DET=4 cosmic rays)
        if hasattr(l2_data, "dq") and l2_data.dq is not None:
            dq_box = l2_data.dq[y0:y1, x0:x1]
            bad_mask = (dq_box & (DQ_FLAGS.get("DO_NOT_USE", 1) | DQ_FLAGS.get("JUMP_DET", 4))) > 0
        else:
            bad_mask = np.zeros(box.shape, dtype=bool)

        valid_mask = np.isfinite(box) & (~bad_mask)
        valid_pix = box[valid_mask]

        if len(valid_pix) == 0:
            x_refined.append(x_init)
            y_refined.append(y_init)
            peak_fluxes.append(0.0)
            shifts.append(0.0)
            continue

        peak = float(np.max(valid_pix))

        # Robust local background (10th percentile of valid pixels)
        bkg = float(np.percentile(valid_pix, 10))

        weights = np.maximum(box - bkg, 0.0)
        weights[~valid_mask] = 0.0
        total_w = float(np.sum(weights))

        # Fallback to catalog position when peak flux is non-positive or total weight is zero
        if peak <= 0.0 or total_w <= 0.0:
            x_refined.append(x_init)
            y_refined.append(y_init)
            peak_fluxes.append(peak)
            shifts.append(0.0)
            continue

        grid_y, grid_x = np.indices(box.shape)
        cx = x0 + (np.sum(grid_x * weights) / total_w)
        cy = y0 + (np.sum(grid_y * weights) / total_w)

        shift = float(np.hypot(cx - x_init, cy - y_init))
        # Guard against divergent centroid shifts
        if np.isfinite(cx) and np.isfinite(cy) and (shift <= max_shift_px):
            x_refined.append(float(cx))
            y_refined.append(float(cy))
            shifts.append(shift)
        else:
            x_refined.append(x_init)
            y_refined.append(y_init)
            shifts.append(0.0)

        peak_fluxes.append(peak)
```

---

## 5. Verification Method

### 1. Patch Application Check
The implementation worker can apply the unified patch directly:
```bash
cd /Users/pmsanch1/code/romanepsf
git apply .agents/teamwork/explorer_m1_it2_1/catalog_fix.patch
```

### 2. Test Verification Commands
Run adversarial test suite:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_adversarial_m1.py -v
```
**Expected Result**: `10 passed in 0.09s` (Exit code 0).

Run full project unit test suite:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
```
**Expected Result**: `82 passed in 2.32s` (Exit code 0, zero regressions).

### 3. Invalidation Conditions
This remediation plan is invalidated if any of the 82 unit tests fail, or if applying `catalog_fix.patch` produces merge conflicts or warnings.
