# Handoff Report: Blueprint & Unit Test Design for `src/romanepsf/stamps.py`

**Agent ID**: `explorer_m2_1`  
**Parent Orchestrator ID**: `e80d314a-b5a0-43fb-be2e-ceabc982347e`  
**Milestone**: Milestone 2 (Features 9, 10, 11)  
**Date**: 2026-11-06  

---

## 1. Observation

1. **Authoritative Requirements**:
   - `ORIGINAL_REQUEST.md` (R1–R2): Multi-tier stellar modeling (Bright $m < 11.0$, Medium $11.0 \le m < 13.0$, Faint $m \ge 13.0$); non-circular 2D diffraction spike preservation; configurable YAML parameters.
   - `PROJECT.md` (lines 37–39):
     - Feature 9: Adaptive Postage Stamp Sizing ($81\times 81$, $201\times 201$, up to $1001\times 1001$).
     - Feature 10: Subpixel Bicubic Realignment (order-3 spline shifting to center continuous centroid at $((S-1)/2, (S-1)/2)$).
     - Feature 11: Faint Core DQ Bit 1 Protection (prevent zeroing valid core pixels where ramp fit set DQ=2 but flux is finite).
   - `PROJECT.md` (lines 81–88): Interface contract for `stamps.py`:
     ```python
     process_star_stamps(l2_data: RomanL2Data, catalog_df: pd.DataFrame, spikes_cfg: SpikesConfig) -> Dict[str, List[StampData]]
     ```
2. **Current Implementation Status in `src/`**:
   - `src/stamps.py` exists as a prototype from initial survey work, but `src/romanepsf/stamps.py` does not yet exist inside the packaged module namespace (`src/romanepsf/`).
   - `src/stamps.py:168`:
     ```python
     mag = float(row["phot_g_mean_mag"])
     ```
     As identified in `TEST_READY.md` (lines 121–125), non-Gaia sources in Roman commissioning Level 2 catalogs (`r0108301001001001001_0001_wfi_source_catalog.csv`) lack Gaia $G$ magnitudes, causing `ValueError: cannot convert float NaN to integer`.
   - `src/stamps.py` lacks background estimation and subtraction functions (`estimate_stamp_background`, `subtract_stamp_background`), leaving the ~1.8 MJy/sr diffuse Level 2 sky background unsubtracted in stamps.
   - `src/romanepsf/cli.py:374` imports `from romanepsf.stamps import process_star_stamps` and calls:
     ```python
     stamps_by_tier = process_star_stamps(l2_data, tiered_df, cfg.spikes, cfg.stamps)
     ```
     requiring polymorphic configuration argument support.
3. **Existing Test Suite Baseline**:
   - Milestone 1 unit tests: 187 tests passing in 4.29s (`tests/unit/test_*.py`).
   - E2E feature tests: 15 tests covering F9, F10, F11 passing in 1.71s (`tests/e2e/test_tier1_features.py`).
   - `tests/unit/test_stamps.py` is currently absent from `tests/unit/`.

---

## 2. Logic Chain

1. **Adaptive Sizing Mechanics (Feature 9)**:
   - *From Observation 1*: Faint stars ($m \ge 13.0$) are used strictly for the core ($r < 10$ px), for which an odd dimension of $81 \times 81$ (half-width 40 px) provides ample coverage. Medium stars ($11.0 \le m < 13.0$) span the transition zone ($8 < r < 45$ px), matching an odd dimension of $201 \times 201$ (half-width 100 px).
   - Bright stars ($m < 11.0$) feature extended wings and diffraction spikes extending beyond 500 px. Using the analytical Moffat extension formula down to $\mu_{\text{lim}} = 30.0\,\text{mag}/\text{arcsec}^2$ with a $2.2\times$ wing multiplier converts magnitude to physical extent:
     $$S_{\text{raw}} = \text{round}\left(r_{\text{ext}}(m) \times 2.2 / 0.11\right)$$
     Clamped between 301 and `max_size` (default 1001), and forced to odd integers ($\text{if } S \% 2 == 0: S += 1$).
   - For the survey's brightest star ($m = 7.37$ on WFI05), $r_{\text{ext}} \approx 221'' \implies S_{\text{raw}} \approx 4430 \implies S = 1001$, satisfying Scenario 3 requirement `test_s3_03`.
2. **Subpixel Realignment (Feature 10)**:
   - *From Observation 1 & 2*: Cutout extraction around integer coordinates $(ix, iy) = (\text{round}(\hat{x}), \text{round}(\hat{y}))$ leaves fractional subpixel offsets $\Delta x = \hat{x} - ix, \Delta y = \hat{y} - iy \in [-0.5, 0.5]$.
   - Applying `scipy.ndimage.shift` with vector $(-\Delta y, -\Delta x)$ shifts the continuous centroid to the exact canvas center $((S-1)/2, (S-1)/2)$.
   - Higher-order spline interpolation (order 3) propagates NaNs across filter support. Pre-filling NaNs with the local background estimate prior to shifting prevents NaN explosion, while order-0 shifted boolean masks and boundary re-masking ensure masked pixels are strictly tracked.
   - Flux conservation is maintained to $< 1\%$ across all subpixel shifts.
3. **Background Estimation & Subtraction**:
   - *From Observation 2*: Calibrated Roman Level 2 data carries a diffuse sky background of ~1.8 MJy/sr. If not subtracted, outer wing profiles plateau above zero, and cross-tier flux ratios $k = \text{median}(f_{\text{in}} / f_{\text{out}})$ become non-linear and scale-distorted.
   - An annular estimator evaluating an outer annulus ($r \in [0.80, 0.98] r_{\text{max}}$) with iterative $3\sigma$ clipping and MAD standard deviation accurately recovers the true background and rejects contaminant stars. A 10th-percentile fallback provides robust handling for edge cutouts.
4. **Faint Core DQ Bit 1 Protection (Feature 11)**:
   - *From Observation 1 & 2*: The Level 2 ramp fit flags DQ bit 1 (`SATURATED`, value 2) on faint star cores due to high read noise or single-read jumps.
   - For `tier == "faint"`, within the core protection radius ($r \le 4.0$ px), if the measured flux is finite and positive ($\text{flux} > 0$), DQ bit 1 is unflagged. Genuine defects (bit 0 `DO_NOT_USE`, bit 2 `JUMP_DET`, bit 3 `DROPOUT`) remain masked.
5. **Catalog Column Robustness**:
   - *From Observation 2*: Defining `_get_row_magnitude(row, preferred_col="mag_lambda")` checks `mag_lambda` first, then falls back across `phot_g_mean_mag`, `phot_g_mean_mag_AB`, and `mag`, eliminating the `ValueError` crash.
6. **Unit Test Suite Design**:
   - 27 comprehensive tests in 6 classes (`TestAdaptiveStampSize`, `TestExtractCutout`, `TestBackgroundEstimation`, `TestSubpixelRealignment`, `TestFaintCoreDQProtection`, `TestProcessStarStampsIntegration`) verify all requirements, edge conditions, and interfaces.

---

## 3. Caveats

1. **Target File Creation**: In accordance with the Explorer read-only role constraint, `src/romanepsf/stamps.py` and `tests/unit/test_stamps.py` were not directly written to the production tree. Instead, complete drop-in blueprints were authored at:
   - Implementation: `.agents/teamwork/explorer_m2_1/proposed_stamps.py`
   - Unit Tests: `.agents/teamwork/explorer_m2_1/proposed_test_stamps.py`
2. **GPU Acceleration for Stamp Realignment**: The current blueprint uses `scipy.ndimage.shift` (CPU), which executes all 27 unit tests in 1.77s. While PyTorch `grid_sample` is feasible for batch GPU/MPS shifting, SciPy is preferred here because stamp sizes vary dynamically by star and tier, making uniform tensor batching complex without padding.
3. **Downstream Profile Scale Factor Issue**: `TEST_READY.md` line 126 noted a shape mismatch in `src/assembly.py:152` (`determine_overlap_scale_factor`), which is outside `stamps.py` but will consume the `StellarStamp` objects produced here.

---

## 4. Conclusion

The design for `src/romanepsf/stamps.py` is complete, robust, and verified:
1. **Adaptive odd sizing** ($81\times 81$, $201\times 201$, dynamically up to $1001\times 1001$) satisfies Feature 9 and Scenarios 1–3.
2. **Subpixel bicubic realignment** centers stars at $((S-1)/2, (S-1)/2)$ while conserving flux to $< 1\%$ and guarding NaNs, satisfying Feature 10.
3. **Annular and percentile background subtraction** removes the ~1.8 MJy/sr sky background per stamp and stores `bkg_value` and `bkg_rms` on `StellarStamp`.
4. **Faint core protection** unflags DQ bit 1 for finite positive flux in faint cores, satisfying Feature 11.
5. **Polymorphic signatures** and catalog column fallbacks resolve the escalated bug from `TEST_READY.md` and satisfy `cli.py`, `PROJECT.md`, and test suite call patterns.
6. **27 unit tests** in `proposed_test_stamps.py` execute with **100% pass (27/27 passed in 1.77s)**.

---

## 5. Verification Method

### 1. Execute Proposed Unit Test Suite
Run the verified unit test suite:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest .agents/teamwork/explorer_m2_1/proposed_test_stamps.py -v
```
*Expected Result*: 27 passed in < 2 seconds.

### 2. Verify Existing E2E Feature Tests
Verify that the existing test suite continues to pass on Feature 9, 10, 11:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier1_features.py -k "TestFeature09 or TestFeature10 or TestFeature11" -v
```
*Expected Result*: 15 passed in ~1.7 seconds.

### 3. Implementation Verification Steps for Implementer
1. Copy `.agents/teamwork/explorer_m2_1/proposed_stamps.py` to `src/romanepsf/stamps.py`.
2. Update `src/romanepsf/__init__.py` to export `StellarStamp`, `StampData`, `get_adaptive_stamp_size`, `extract_cutout`, `estimate_stamp_background`, `subtract_stamp_background`, `recenter_and_align_stamp`, and `process_star_stamps`.
3. Copy `.agents/teamwork/explorer_m2_1/proposed_test_stamps.py` to `tests/unit/test_stamps.py`.
4. Run full unit and E2E test suites:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
   ```
