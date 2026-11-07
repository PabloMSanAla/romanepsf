# Handoff Report: Milestone 2 Iteration 2 Review (reviewer_m2_it2_1)

**Agent ID**: `reviewer_m2_it2_1`  
**Parent Orchestrator ID**: `e80d314a-b5a0-43fb-be2e-ceabc982347e`  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_it2_1`  
**Date**: 2026-11-07  
**Verdict**: **APPROVE**  
**Handoff Type**: Hard Handoff  

---

## 1. Observation

### 1.1 Source Code and Architecture Inspection
1. **`src/romanepsf/assembly.py` & `src/assembly.py`**:
   - **Defect 1 Resolution**: Lines 468–483 explicitly pass `mask=(cov == 0)` to `measure_radial_profile_1d` for faint, medium, and bright tiers:
     ```python
     r_f, prof_f = measure_radial_profile_1d(psf_faint, mask=(cov_faint == 0), device=device)[:2] if has_f else (None, None)
     r_m, prof_m = measure_radial_profile_1d(psf_medium, mask=(cov_medium == 0), device=device)[:2] if has_m else (None, None)
     r_b, prof_b = measure_radial_profile_1d(psf_bright, mask=(cov_bright == 0), device=device)[:2] if has_b else (None, None)
     ```
     This ensures unobserved zero-flux pixels in sparse outer regions do not corrupt the median radial profile.
   - **Defect 3 Resolution**: Lines 440–567 introduce complete multi-tier assembly resilience:
     * Validates that at least one tier is populated, raising `ValueError("Cannot assemble composite extended PSF: all tiers are empty.")` if and only if all tiers are empty.
     * Stacks available tiers conditionally (`if has_... else (None, None)`).
     * Implements full synthesis matrix:
       - 3-tier ($F + M + B$): stitches $F \to M$ using $k_{\text{FM}}$, $M \to B$ using $k_{\text{MB}}$ with annular blending.
       - 2-tier ($F + M$, e.g. WFI02 with 0 bright stars): scales $M$ by $k_{\text{FM}}$, blends $F+M$, embeds into target canvas, diagnostics sets `k_mb = None`.
       - 2-tier ($M + B$): scales $B$ by $k_{\text{MB}}$, blends $M+B$, sets `k_fm = None`.
       - 2-tier ($F + B$): scales $B$ by $k_{\text{FB}}$, blends $F+B$ across $[12, 22]$ px.
       - 1-tier ($F$, $M$, or $B$): directly embeds single available tier into target canvas with `k_fm = None, k_mb = None`.
   - **Challenger Hardening Items**:
     * Line 64: Explicit `d = np.asarray(s.data, dtype=np.float32).copy()` eliminates integer dtype NaN assignment failure.
     * Line 84: Mask construction `(~m_pad) & np.isfinite(d_pad)` prevents unmasked NaNs from corrupting coverage counting.
     * Lines 220–236: Coordinate length matching check `if len(v_in_cand) == len(v_out_cand) and len(v_in_cand) >= 1:` with robust linear interpolation fallback (`np.interp(r_in_sel, r_out, p_out)`) resolves coordinate rounding collisions.
     * Lines 313–329 & 344–366: Symmetrical floating-point center-aligned slice calculation handles mismatched aspect ratios, even-dimensioned canvases, and inner images larger than outer targets without broadcast errors.
     * `_embed_or_crop_canvas` correctly re-exported in `src/romanepsf/assembly.py` and `src/assembly.py`.

2. **`src/romanepsf/masking.py` & `src/masking.py`**:
   - **Defect 2 Resolution**:
     * Lines 248–253 in `fit_moffat_model`: Background pedestal is evaluated strictly on the outer perimeter (`outer_cutout = np.isfinite(stamp) & (r > 0.75 * np.nanmax(r))`), preventing inner halo flux from inflating background estimates.
     * Lines 426–440 in `mask_contaminants_with_spikes_protected`: Tiered radial exponential scaling:
       $$\sigma(r) = \sigma_0 \cdot \left(1 + A \cdot \exp\left(-\frac{r}{r_0}\right)\right)$$
       with $A=200.0, r_0=15.0$ for medium; $A=200.0, r_0=20.0$ for bright; $A=50.0, r_0=15.0$ for faint.
     * Backward-compatibility wrapper `src/masking.py` re-exports all symbols identically.

3. **`src/romanepsf/stamps.py` & `src/stamps.py`**:
   - Correctly integrates `mask_contaminants_with_spikes_protected` passing `tier=tier` and `pa_aperture=roll_ref`.
   - Top-level wrapper `src/stamps.py` re-exports all stamps symbols identically.

4. **`src/romanepsf/profile.py` & `src/profile.py`**:
   - Preserves 1D profile extraction strictly for calibration without radial circularization of 2D canvases.
   - Top-level wrapper `src/profile.py` re-exports all profile symbols identically.

### 1.2 Independent Test Suite Execution
- **Unit test suite**:
  `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
  **Result**: 392 passed in 11.87s (100% pass, 0 failures, 0 errors).
- **E2E test suite**:
  `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v`
  **Result**: 298 passed, 4 skipped in 18.01s (100% pass, 0 failures, 0 errors).
- **Combined total**: 690 passed, 4 skipped, 0 failures.

### 1.3 Independent Verification of Physical Scaling and Edge Cases
1. **WFI01 Physical Scaling and Radial Monotonicity**:
   - Executed live pipeline on real simulated commissioning ASDF (`wfi01`) and catalog:
     * $k_{\text{FM}} = 0.17046$
     * $k_{\text{MB}} = 0.023636$ (strictly within physical expected range $[0.010, 0.100]$)
     * Flux at $r=30$ px: $4.956 \times 10^{-6}$
     * Flux at $r=48$ px: $1.049 \times 10^{-6}$
     * Strict monotonic radial decay confirmed ($\text{flux}(r=48) < \text{flux}(r=30)$); 25x flux surge is completely eliminated.
2. **WFI02 2-Tier Assembly**:
   - Executed live pipeline on WFI02 (which has 0 bright stars):
     * Tier counts: Bright=0, Medium=2, Faint=5.
     * Successfully assembled without errors into a (501, 501) canvas.
     * Total integrated flux = 1.0, central peak > 0, $k_{\text{FM}} = 0.13487$, $k_{\text{MB}} = \text{None}$.
3. **WFI01 Medium Star Halo Preservation**:
   - Stamp 0: masked fraction in $[22, 45]$ px = 0.6807% (dropped from 69.8%).
   - Stamp 1: masked fraction in $[22, 45]$ px = 0.0206% (dropped from 68.4%).
   - Stellar halos preserved (< 1% masked) while genuine off-axis companion stars at $r=25$ px and $r=18$ px are detected and masked.
4. **Adversarial Edge Cases**:
   - 1-tier fallback (Faint only, Medium only, Bright only): verified, normalized unit flux.
   - 2-tier fallback ($F + B$ direct): verified, $k_{\text{MB}} = k_{\text{FB}} = 0.020$.
   - All tiers empty: verified raises `ValueError("Cannot assemble composite extended PSF: all tiers are empty.")`.
   - Small canvas crop (`output_size=31` with `81x81` stamps): verified, centered and normalized to 1.0.
   - Integer stamp dtype with masked pixels: verified casting to float32 succeeds without NaN assignment error.
   - Non-square mismatched aspect ratio images: verified symmetrical canvas embedding succeeds.

### 1.4 Integrity Audit
- No hardcoded test results, fixed constants masquerading as calculations, or star/detector cheat tables exist in source code.
- No dummy or facade implementations.
- No shortcuts or bypassed logic.
- Full independent verification succeeded across all metrics.

---

## 2. Logic Chain

1. *From Observation 1.1*:
   Unobserved pixels in sparse outer regions of stamps are assigned `0.0`. In M2 It1, omitting `cov == 0` allowed unobserved pixels to depress the median profile `prof_m` to 0.0 across $[22, 45]$ px, forcing fallback to $k_{\text{MB}} = 1.0$ and causing a 25x flux surge.
2. *From Observations 1.1 & 1.3*:
   Passing `mask=(cov == 0)` ensures only valid observed pixels enter the median profile calculation. In testing on actual WFI01 commissioning data, this reliably recovers physical scaling $k_{\text{MB}} = 0.0236$ and enforces monotonic radial decay across $[30, 48]$ px.
3. *From Observations 1.1 & 1.3*:
   Estimating background on the outer perimeter ($r > 0.75 \cdot r_{\text{max}}$) in `fit_moffat_model` avoids pedestal bias, and tiered radial exponential scaling elevated the contaminant detection threshold in stellar wings, reducing false contaminant masking on WFI01 from $\approx 70\%$ to $< 1\%$ without compromising companion star detection.
4. *From Observations 1.1 & 1.3*:
   Conditioning stacking on `has_...` and implementing the multi-tier fallback matrix resolves crashes on detectors lacking bright stars (such as WFI02), enabling end-to-end assembly across all single-detector configurations.
5. *From Observations 1.1, 1.2, 1.3 & 1.4*:
   All 5 challenger hardening items are verified, all 690 tests pass with 0 failures, and no integrity violations exist.
6. *Conclusion*: The deliverables for Milestone 2 Iteration 2 are complete, robust, scientifically sound, and ready for approval.

---

## 3. Caveats

No caveats. All investigated components, defect resolutions, adversarial corner cases, and test suites have been verified on synthetic fixtures and real Level 2 simulated commissioning datasets (`wfi01`, `wfi02`).

---

## 4. Conclusion

**Verdict: APPROVE**

Milestone 2 Iteration 2 fully resolves all reported defects and challenger hardening requirements:
- **Defect 1**: Resolved. Radial profiling now passes coverage masks `mask=(cov == 0)`, restoring physical $k_{\text{MB}} = 0.0236$ and monotonic radial flux decay on WFI01.
- **Defect 2**: Resolved. Outer-cutout background estimation and tiered radial exponential thresholding reduce false halo masking on WFI01 medium stars from $\approx 70\%$ to $< 1\%$ while preserving companion detection.
- **Defect 3**: Resolved. Graceful multi-tier fallback handles 3-tier, 2-tier ($F+M$, $M+B$, $F+B$), 1-tier, and empty catalogs cleanly, verified on WFI02.
- **Challenger Hardening**: All 5 defensive edge cases (float32 casting, unmasked NaN guard, coordinate mismatch interpolation fallback, symmetrical annular blending canvas alignment, `_embed_or_crop_canvas`) are implemented and pass adversarial tests.
- **Test Suite**: 100% pass across 392 unit tests and 298 e2e tests (total 690 passed, 4 skipped, 0 failed).
- **Integrity**: Zero integrity violations, zero facades, zero hardcoded values.

---

## 5. Verification Method

To independently reproduce this verification:

1. **Run Full Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
   ```
   *Expected*: 392 passed in unit, 298 passed (4 skipped) in e2e, 0 failures.

2. **Verify WFI01 Scaling and Monotonic Decay**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   from romanepsf import loader, catalog, stamps, assembly
   import numpy as np, pandas as pd

   l2 = loader.load_l2_image('/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf', calibrate=True)
   cat_df = pd.read_csv('/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv', low_memory=False)
   ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
   cand = cat_df[(np.abs(cat_df['ra'] - ra_c) < rad) & (np.abs(cat_df['dec'] - dec_c) < rad)].copy()
   cand['phot_g_mean_mag'] = cand['phot_g_mean_mag'].fillna(cand['mag_lambda'])
   proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
   tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
   tier_stamps = stamps.process_star_stamps(l2, tiered)

   epsf, diag = assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
   assert 0.010 < diag['k_mb'] < 0.100, f'Unphysical k_mb: {diag[\"k_mb\"]}'
   c = 250
   assert epsf[c, c+48] < epsf[c, c+30], 'Flux surge detected across [30, 48] px'
   print('SUCCESS: WFI01 physical scaling verified! k_mb =', diag['k_mb'])
   "
   ```

3. **Verify WFI02 2-Tier Clean Assembly**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   from romanepsf import loader, catalog, stamps, assembly
   import numpy as np, pandas as pd

   l2 = loader.load_l2_image('/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi02_f146_cal.asdf', calibrate=True)
   cat_df = pd.read_csv('/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv', low_memory=False)
   ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
   cand = cat_df[(np.abs(cat_df['ra'] - ra_c) < rad) & (np.abs(cat_df['dec'] - dec_c) < rad)].copy()
   cand['phot_g_mean_mag'] = cand['phot_g_mean_mag'].fillna(cand['mag_lambda'])
   proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
   tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
   tier_stamps = stamps.process_star_stamps(l2, tiered)

   epsf, diag = assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
   assert epsf.shape == (501, 501)
   assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
   assert epsf[250, 250] > 0.0
   assert diag['k_fm'] > 0.0
   assert diag['k_mb'] is None
   print('SUCCESS: WFI02 2-tier ePSF assembled cleanly!')
   "
   ```

4. **Invalidation Conditions**:
   - Any failure in `pytest tests/unit/` or `pytest tests/e2e/`.
   - $k_{\text{MB}} \ge 0.100$ or flux surge on WFI01.
   - Any unhandled crash when calling `assemble_composite_extended_psf` on datasets with missing tiers.
