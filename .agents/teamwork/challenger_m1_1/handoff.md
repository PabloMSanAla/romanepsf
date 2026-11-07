# Handoff Report — Challenger M1-1: Milestone 1 Adversarial Stress Testing

**Agent**: Challenger M1-1 (Milestone 1 Adversarial Challenger)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m1_1/`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Recipient**: Sub-Orchestrator M1 (`e80d314a-b5a0-43fb-be2e-ceabc982347e`)  
**Verdict**: **`REJECT`** (Critical and High defects discovered in WCS roundtrip verification, catalog sanitization, and centroid refinement)

---

## Challenge Summary

**Overall Risk Assessment**: **`CRITICAL`**

The implementation by Worker M1-1 meets nominal baseline tests (41/41 passing on happy paths), but empirical adversarial testing revealed two critical defects, one high vulnerability, and two medium/low bugs:
1. **Critical Defect 1**: WCS forward roundtrip verification fails to wrap RA differences across the celestial $0^\circ / 360^\circ$ meridian. Any observation field crossing the meridian will reject 100% of stars straddling the boundary ($\Delta\theta \approx 1,300,000''$).
2. **Critical Defect 2**: Catalog sanitization fails to filter negative-magnitude solar system objects (Sun, Moon, Earth) when an input catalog uses `phot_g_mean_mag` without `mag_lambda` (e.g. Gaia TAP queries). In downstream Moffat isolation, the un-sanitized Sun ($m = -26.98$) generates a 30-million-pixel exclusion radius that wipes out 100% of all real stars across the entire detector.
3. **High Vulnerability 3**: Centroid refinement completely ignores `l2_data.dq` (Data Quality) masks. Cosmic rays flagged with `JUMP_DET` within $3\text{ px}$ of stellar cores hijack star centroids by $\sim 2\text{ px}$, introducing systematic centering offsets.
4. **Medium Vulnerability 4**: Centroid refinement computes moment shifts on pure negative background noise (where $\text{peak\_flux} \le 0$), accepting noise shifts up to $2.33\text{ px}$.
5. **Low Defect 5**: Catalog sanitization does not strip whitespace from CSV column names, causing standard CSV headers with spaces after commas (`source_id, ra, dec, mag_lambda`) to crash with `ValueError`.

All defects have been empirically reproduced in an executable test suite: `/Users/pmsanch1/code/romanepsf/tests/unit/test_adversarial_m1.py`.

---

## 1. Observation

Direct observations obtained by executing `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python` against `src/romanepsf/`:

### Observation 1.1: RA Wrap-around $0^\circ / 360^\circ$ Meridian Bug in `catalog.py`
- **File**: `/Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py`, Lines 333–336:
  ```python
  cos_dec = np.cos(np.radians(dec_cand))
  delta_ra_arcsec = (ra_back - ra_cand) * cos_dec * 3600.0
  delta_dec_arcsec = (dec_back - dec_cand) * 3600.0
  delta_theta_arcsec = np.hypot(delta_ra_arcsec, delta_dec_arcsec)
  ```
- **Observed Behavior**:
  For an astronomical pointing near RA $= 0.001^\circ$, a catalog star at $\text{RA} = 359.9508^\circ$ produces `ra_back = -0.0492°` under WCS forward transform.
  The naive difference `ra_back - ra_cand` evaluates to $-360.0^\circ$.
  `delta_ra_arcsec = -360.0 * np.cos(-20 deg) * 3600 = -1,217,908 arcsec`.
  `delta_theta_arcsec` is $1.22 \times 10^6$ arcsec, which exceeds `tolerance_arcsec = 0.5`.
  The star is completely dropped from the catalog.
- **Verbatim Pytest Failure**:
  ```text
  FAILED tests/unit/test_adversarial_m1.py::test_bug_wcs_ra_wrap_around_0_360 - AssertionError: Star crossing RA 0/360 meridian was falsely rejected! ra_catalog=359.9508, expected on detector at x=500, y=2044.
  assert 0 == 1
  ```

### Observation 1.2: Unfiltered Solar System Bodies Eliminating Real Stars in `catalog.py`
- **File**: `/Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py`, Lines 111–119:
  ```python
  if mag_col in clean_df.columns:
      clean_df[mag_col] = pd.to_numeric(clean_df[mag_col], errors="coerce")
      valid_mag = clean_df[mag_col].notna() & np.isfinite(clean_df[mag_col]) & (clean_df[mag_col] >= 0.0)
      clean_df = clean_df[valid_mag].copy()

  if "phot_g_mean_mag" in clean_df.columns:
      clean_df["phot_g_mean_mag"] = pd.to_numeric(clean_df["phot_g_mean_mag"], errors="coerce")
  ```
- **Observed Behavior**:
  When ingesting a catalog without `mag_lambda` (e.g. Gaia DR3 where primary magnitude is `phot_g_mean_mag`), `if mag_col in clean_df.columns:` evaluates to `False`. The filter `clean_df[mag_col] >= 0.0` is completely skipped.
  The Sun ($m = -26.98$), Moon ($m = -4.7$), and Earth ($m = -9.3$) remain in `clean_df`.
  Downstream in `filter_isolated_stars` (lines 510–555):
  `effective_mag_col = mag_col if mag_col in df.columns else "phot_g_mean_mag"` selects `phot_g_mean_mag`.
  The Sun is sorted as the primary star ($m = -26.98$).
  `get_psf_extension_moffat(-26.98)` evaluates:
  $$\mu_0 = -26.98 + 2.5 \log_{10}(\text{term}) \approx -29.98$$
  $$\text{exponent} = (28 - (-29.98)) / 3.8 = 15.25 \implies \text{radius} \approx 3.3 \times 10^6 \text{ arcsec} \approx 30,000,000 \text{ px}$$
  Every valid star on the entire detector is within 30 million pixels of the Sun and is flagged as a violator and eliminated!
  Only the Sun is preserved in the output catalog.
- **Verbatim Pytest Failure**:
  ```text
  FAILED tests/unit/test_adversarial_m1.py::test_bug_catalog_solar_system_rejection_without_mag_lambda - AssertionError: sanitize_source_catalog failed to filter negative magnitude solar system objects when catalog uses phot_g_mean_mag!
  assert not np.True_
  ```

### Observation 1.3: Cosmic Ray Hijacking Centroid Refinement Due to Missing DQ Bitmasking
- **File**: `/Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py`, Lines 395–435:
  `refine_stellar_centroids(l2_data: RomanL2Data, df: pd.DataFrame)` receives `l2_data`, which contains `l2_data.dq` (with Roman standard bit flags `JUMP_DET = 4`, `DO_NOT_USE = 1`), but `l2_data.dq` is never accessed.
- **Observed Behavior**:
  When a true star at $(50.0, 50.0)$ with peak flux $500$ has a cosmic ray at $(52.0, 51.0)$ with flux $50,000$ and DQ bit `JUMP_DET`:
  `refine_stellar_centroids` computes moments on unmasked flux, yielding $\text{cx} = 51.753, \text{cy} = 50.876$.
  The shift is $\text{hypot}(1.753, 0.876) = 1.959\text{ px} \le 3.0\text{ px}$.
  The algorithm accepts the corrupted center, pulling the stellar centroid directly onto the cosmic ray.
- **Verbatim Pytest Failure**:
  ```text
  FAILED tests/unit/test_adversarial_m1.py::test_bug_centroid_cosmic_ray_hijack_dq_ignored - AssertionError: Centroid was hijacked by cosmic ray! refined_x=51.753, true star is at x=50.0, shift=1.959 px
  assert np.float64(1.7525360620025978) < 0.5
  ```

### Observation 1.4: Centroid Refinement Shifting on Negative Noise Fluctuation Cutouts
- **File**: `/Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py`, Lines 424–440:
  ```python
  bkg = float(np.percentile(valid_pix, 10))
  weights = np.maximum(box - bkg, 0.0)
  total_w = np.sum(weights)
  ```
- **Observed Behavior**:
  When all pixels in `box` are negative (e.g. noise gradient from $-100.0$ to $-50.0$, $\text{peak\_flux} = -72.5$):
  `bkg = -95.0`.
  `weights = np.maximum(box - (-95.0), 0.0)` produces positive weights up to $+45.0$.
  `total_w > 0` evaluates to `True`.
  A first moment centroid shift of $2.333\text{ px}$ is calculated on pure noise and accepted because $2.333 \le 3.0\text{ px}$.
- **Verbatim Pytest Failure**:
  ```text
  FAILED tests/unit/test_adversarial_m1.py::test_bug_centroid_negative_flux_noise_shift - AssertionError: Centroid was shifted on pure negative background noise! shift=2.333 px, peak=-72.5
  assert np.float64(2.3333333333333357) == 0.0
  ```

### Observation 1.5: CSV Column Headers with Spaces After Commas Crash `sanitize_source_catalog`
- **File**: `/Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py`, Lines 91–92:
  ```python
  if "ra" not in clean_df.columns or "dec" not in clean_df.columns:
      raise ValueError("Source catalog must contain 'ra' and 'dec' coordinate columns.")
  ```
- **Observed Behavior**:
  A CSV formatted as `source_id, ra, dec, mag_lambda` produces columns `['source_id', ' ra', ' dec', ' mag_lambda']`.
  `"ra" not in clean_df.columns` triggers, throwing `ValueError: Source catalog must contain 'ra' and 'dec' coordinate columns.`
- **Verbatim Pytest Failure**:
  ```text
  FAILED tests/unit/test_adversarial_m1.py::test_bug_catalog_header_spaces - ValueError: Source catalog must contain 'ra' and 'dec' coordinate columns.
  ```

---

## 2. Logic Chain

1. **Step 1 (From Observation 1.1)**:
   In spherical coordinates, angular difference $\Delta \alpha$ between two points on the sphere must be normalized to $(-\pi, +\pi]$ (or $[-180^\circ, +180^\circ]$) before computing arc length: $\Delta \alpha_{\text{wrapped}} = (\Delta \alpha + 180^\circ) \pmod{360^\circ} - 180^\circ$.
   `project_catalog_to_pixels` performs linear subtraction without modular wrapping: `delta_ra_arcsec = (ra_back - ra_cand) * cos_dec * 3600.0`.
   Consequently, whenever an observation field straddles the prime meridian $\alpha = 0^\circ \equiv 360^\circ$, `ra_back - ra_cand \approx \pm 360^\circ`, causing $\Delta \theta \approx 1.2 \times 10^6$ arcseconds.
   Because `delta_theta_arcsec < tolerance_arcsec` ($0.5''$) fails for all stars across the meridian, valid stars are completely discarded.

2. **Step 2 (From Observation 1.2)**:
   A catalog ingestion pipeline must be agnostic to the specific magnitude column name or automatically identify the active magnitude column.
   `sanitize_source_catalog` only filters negative magnitudes if `mag_col` (`"mag_lambda"`) is present in `clean_df.columns`.
   If a user passes a Gaia catalog (where the magnitude column is `phot_g_mean_mag`), negative magnitude solar system bodies (Sun, Moon, Earth) are not removed.
   Downstream in `filter_isolated_stars`, the Sun ($m = -26.98$) is recognized as the brightest star, and its calculated Moffat clearance radius expands to $30,000,000\text{ px}$.
   Because every real star on the detector lies within this $30\text{M-px}$ radius, every star is discarded as a blended contaminant, leaving only the Sun. This causes catastrophic data starvation.

3. **Step 3 (From Observation 1.3)**:
   Level 2 Roman ASDF data products provide a 32-bit Data Quality array (`l2_data.dq`) identifying ramp-fit cosmic rays (`JUMP_DET = 4`).
   `refine_stellar_centroids` receives `l2_data` but never references `l2_data.dq` or calls `l2_data.get_effective_mask()`.
   Because cosmic rays introduce high localized fluxes ($10^4 - 10^5\text{ DN/s}$) within stellar core regions ($r < 3\text{ px}$), the unweighted first moment shifts directly toward the cosmic ray artifact, accepting it whenever $\text{shift} \le 3.0\text{ px}$.
   Postage stamps centered on these refined coordinates will be centered on cosmic ray noise rather than the stellar core.

4. **Step 4 (From Observation 1.4)**:
   Background noise or dead pixels can produce negative fluxes.
   In `refine_stellar_centroids`, `bkg = percentile(10)` creates positive weights from purely negative values (`box - bkg`).
   If $\text{peak\_flux} \le 0$, there is no stellar core in the box; computing a first-moment shift on negative noise produces spurious centroid drifts (up to $2.33\text{ px}$ in our tests) instead of preserving initial catalog coordinates.

5. **Step 5 (From Observation 1.5)**:
   Standard CSV files created by text editors or tools frequently include spaces after commas. Failing to strip whitespace from column names causes brittle crashes on valid catalogs.

6. **Synthesis**:
   These five observations demonstrate that Milestone 1 fails adversarial robustness criteria.
   Because the defects cause data starvation (Observations 1.1 and 1.2) and centroid corruption (Observations 1.3 and 1.4), Milestone 1 cannot be approved in its current state.

---

## 3. Caveats

- **Real Commissioning Dataset (WFI01)**: The precomputed commissioning catalog `r0108301001001001001_0001_wfi_source_catalog.csv` centered on $\text{RA} \approx 303.1^\circ, \text{Dec} \approx -19.9^\circ$ contains `mag_lambda` and does not cross the $\text{RA} = 0^\circ$ meridian. The happy-path test on WFI01 passes (yielding 5 verified stars) because it does not traverse these edge cases.
- **Scope Limitation**: The bugs were identified during adversarial and boundary condition testing; they do not impact purely nominal executions where $\text{RA} \notin [359^\circ, 1^\circ]$, `mag_lambda` is always present, and no cosmic rays hit within $3\text{ px}$ of a star.
- **Review Constraint**: In strict compliance with the Teamwork review constraint ("Review-only — do NOT modify implementation code directly in `src/`"), no fixes have been applied to `src/romanepsf/catalog.py`. All fixes must be implemented by the implementation worker.

---

## 4. Conclusion

**VERDICT**: **`REJECT`**

Milestone 1 is rejected due to two critical algorithmic bugs and two centroid refinement vulnerabilities:
1. **Critical Bug**: RA angle wrap-around failure in `project_catalog_to_pixels` (drops valid stars crossing $0^\circ/360^\circ$).
2. **Critical Bug**: Bypassed solar system object filtering in `sanitize_source_catalog` when `mag_lambda` is absent (wipes out all real stars via $30\text{M-px}$ Moffat exclusion).
3. **High Vulnerability**: Lack of DQ bitmasking in `refine_stellar_centroids` (cosmic rays hijack star centers).
4. **Medium Vulnerability**: Centroid shift calculation on negative noise boxes with $\text{peak\_flux} \le 0$.
5. **Low Defect**: Unstripped whitespace in CSV column headers.

### Required Remediations for Implementation Worker:
1. In `src/romanepsf/catalog.py` (lines 333–336):
   Wrap `delta_ra`:
   ```python
   delta_ra = (ra_back - ra_cand + 180.0) % 360.0 - 180.0
   delta_ra_arcsec = delta_ra * cos_dec * 3600.0
   ```
2. In `src/romanepsf/catalog.py` (lines 76 & 111–119):
   Strip column names:
   ```python
   clean_df.columns = clean_df.columns.str.strip()
   ```
   Filter negative magnitudes across any active magnitude column (`mag_col` or `phot_g_mean_mag`):
   ```python
   for m_col in [mag_col, "phot_g_mean_mag"]:
       if m_col in clean_df.columns:
           clean_df[m_col] = pd.to_numeric(clean_df[m_col], errors="coerce")
           clean_df = clean_df[clean_df[m_col].notna() & np.isfinite(clean_df[m_col]) & (clean_df[m_col] >= 0.0)].copy()
   ```
3. In `src/romanepsf/catalog.py` (lines 415–435):
   Mask bad DQ pixels during centroiding:
   ```python
   dq_box = l2_data.dq[y0:y1, x0:x1] if l2_data.dq is not None else np.zeros_like(box, dtype=np.uint32)
   bad_mask = (dq_box & (DQ_FLAGS["DO_NOT_USE"] | DQ_FLAGS["JUMP_DET"])) > 0
   weights[bad_mask] = 0.0
   ```
   And fall back to catalog position if peak flux is non-positive:
   ```python
   if peak <= 0.0 or total_w <= 0.0:
       x_refined.append(x_init)
       y_refined.append(y_init)
       peak_fluxes.append(peak)
       shifts.append(0.0)
       continue
   ```

---

## 5. Verification Method

To independently verify all reported defects, run the adversarial reproduction test suite:

```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/unit/test_adversarial_m1.py -v
```

**Expected Failure Output**:
- `test_bug_wcs_ra_wrap_around_0_360`: FAILED (`AssertionError: Star crossing RA 0/360 meridian was falsely rejected!`)
- `test_bug_catalog_solar_system_rejection_without_mag_lambda`: FAILED (`AssertionError: sanitize_source_catalog failed to filter negative magnitude solar system objects`)
- `test_bug_catalog_header_spaces`: FAILED (`ValueError: Source catalog must contain 'ra' and 'dec' coordinate columns.`)
- `test_bug_centroid_cosmic_ray_hijack_dq_ignored`: FAILED (`AssertionError: Centroid was hijacked by cosmic ray! refined_x=51.753`)
- `test_bug_centroid_negative_flux_noise_shift`: FAILED (`AssertionError: Centroid was shifted on pure negative background noise! shift=2.333 px`)

**Invalidation Conditions**:
This verdict is invalidated if and only if the implementation worker applies the required remediations and all 10 tests in `test_adversarial_m1.py` as well as all 41 existing unit tests in `tests/unit/` pass with exit code 0.
