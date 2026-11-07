# Handoff Report: Reviewer 2 & Adversarial Critic — Milestone 2 Gate Review

**Agent ID**: `reviewer_m2_2`  
**Parent Orchestrator ID**: `e80d314a-b5a0-43fb-be2e-ceabc982347e`  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_2`  
**Date**: 2026-11-06  
**Status**: REVIEW COMPLETE  
**Gate Verdict**: **REQUEST_CHANGES**

---

## 1. Observation

1. **Test Suite Execution**:
   - `pytest tests/unit/ -v`: **284 passed in 5.16s** (100% pass across all unit tests).
   - `pytest tests/e2e/ -v`: **298 passed, 4 skipped in 17.14s** (100% pass across all E2E tests; 4 skipped tests correspond to Milestone 4 markdown documentation).
   - Combined test suite: **582 passed, 4 skipped in ~22.3s**, zero test failures, zero xfails.

2. **Integrity Violation Assessment**:
   - Audited `src/romanepsf/masking.py`, `src/romanepsf/stamps.py`, `src/romanepsf/profile.py`, and `src/romanepsf/assembly.py`.
   - Grep search for hardcoded test fixtures, expected outputs, fake bypasses, or test branch conditions in source code returned **zero integrity violations**.
   - Implementations contain genuine algorithmic logic: 2D Moffat fitting via `astropy.modeling.fitting.LevMarLSQFitter`, subpixel bicubic shifting via `scipy.ndimage.shift`, PyTorch tensor stacking with MAD outlier rejection, and 2D cosine-taper partition-of-unity blending.

3. **Core Requirement Verifications**:
   - **6-fold spike angle base angles**: Base angles `[23.55, 55.29, 80.25, 118.65, 142.88, 178.07]` degrees are established in `masking.py:32`. `get_theoretical_spike_angles` correctly expands these 6 base angles into 12 radial directions in $[0, 360)$ degrees, and adjusts for telescope roll angle (`pa_aperture`) and nominal detector clocking offset (`NOMINAL_DETECTOR_OFFSET_DEG = -9.70` deg).
   - **Directional morphological line filtering**: In `masking.py:382-402`, 2D Moffat fitting is performed on the stellar core, and `detect_morphological_spikes` operates on `residual = stamp - moffat_img`, rejecting compact companion stars via radial extent (`ptp(r) >= 15` px) and circular standard deviation (`circ_std < 20` deg).
   - **Dual-prior protection mask fusion**: In `masking.py:404-428`, geometric cones and empirical ridges are fused into `protected_stellar_area = geom_spike_mask | morph_spike_mask | core_protection`. Contaminants are strictly constrained by `contaminants &= (~protected_stellar_area)`.
   - **Dual-radius overlap scaling (no IndexError)**: In `assembly.py:166-238`, `determine_overlap_scale_factor_dual` accepts independent `r_inner` and `r_outer` coordinates, eliminating the previous `IndexError` on differing stamp dimensions.
   - **2D cosine-taper partition-of-unity blending**: In `assembly.py:265-338`, annular blending uses a $C^1$ smooth raised-cosine weight $w(r)$ where $w + (1 - w) \equiv 1.0$, operating directly on the 2D image without circular or azimuthal averaging.
   - **Unit flux normalization and non-hollow core**: `np.isclose(np.sum(epsf), 1.0, atol=1e-5)` is satisfied, and faint core DQ bit 1 protection prevents center-pixel zeroing.

4. **Adversarial Defect Discoveries on Real Commissioning Data**:
   - **Finding 1 (Critical Defect: `assembly.py:417-419`)**: When executing `assemble_composite_extended_psf` on real commissioning detector `wfi01`, radial profiling omits the coverage mask `cov`:
     ```python
     # src/romanepsf/assembly.py:417-419
     r_f, prof_f, _ = measure_radial_profile_1d(psf_faint, device=device)
     r_m, prof_m, _ = measure_radial_profile_1d(psf_medium, device=device)
     r_b, prof_b, _ = measure_radial_profile_1d(psf_bright, device=device)
     ```
     Because `stack_tier_stamps_torch` replaces unobserved pixels (pixels masked across all stamps in a tier) with `0.0` at line 114 (`stack_np = np.nan_to_num(stack_np, nan=0.0)`), and `cov_medium` is omitted from `measure_radial_profile_1d`, unobserved pixels are profiled as real `0.0` flux.
     On `wfi01`, which contains only 2 medium stars, more than 50% of the pixels in the outer annulus $[22, 45]$ px are unobserved (`cov_medium == 0`). Consequently, the median profile `prof_m` collapses to `0.0` for all $r \ge 19$ px:
     ```text
     prof_m in [22, 45]: [0. 0. 0. 0. 0. 0. 0. 0. 0. 0.]
     ```
     When `determine_overlap_scale_factor_dual` evaluates `k_mb`, there are zero valid positive bins in `prof_m_scaled`. It silently falls back to `k_mb = 1.000000`:
     ```text
     DEFECT 1 CONFIRMATION: k_fm = 0.121067, k_mb = 1.000000
     ```
     Because `k_mb = 1.0`, the bright star PSF (unscaled flux level $\sim 1000 - 50000$) is blended directly with the faint/medium composite (faint-scaled flux level $\sim 1$). This produces a catastrophic **25x artificial flux surge (step discontinuity)** in the composite ePSF between $r = 30$ and $r = 48$ px:
     ```text
     r=29 px: mean_epsf = 0.00000149
     r=30 px: mean_epsf = 0.00000120
     r=35 px: mean_epsf = 0.00001020
     r=40 px: mean_epsf = 0.00002582
     r=45 px: mean_epsf = 0.00002917
     r=48 px: mean_epsf = 0.00002973  (Flux rises by +2377%!)
     r=50 px: mean_epsf = 0.00002355
     r=60 px: mean_epsf = 0.00001463
     ```
     When passing `mask = (cov_m == 0)` to `measure_radial_profile_1d`, `prof_m` evaluates to valid positive flux (`1.62` down to `0.51`), `k_mb` accurately recovers `0.017904` (a factor of 56x lower than `1.0`), and the composite ePSF becomes smoothly, strictly monotonically decreasing without the 25x surge:
     ```text
     With mask: k_mb = 0.017904
     r=30 px: mean_epsf = 0.00000226
     r=35 px: mean_epsf = 0.00000100
     r=40 px: mean_epsf = 0.00000110
     r=48 px: mean_epsf = 0.00000099
     r=60 px: mean_epsf = 0.00000049
     ```
   - **Finding 2 (Major Defect: `masking.py:414-424`)**:
     In `mask_contaminants_with_spikes_protected`, `res_std` is estimated on `clean_area = ~protected_stellar_area` via MAD. Because `clean_area` is dominated by distant sky background where $\sigma \approx 0.03$ MJy/sr, the detection threshold `res_med + 3 * res_std` is only $\sim 0.1$ MJy/sr above background. Legitimate stellar halo flux ($0.5 - 2.0$ MJy/sr at $r = 15..45$ px) that deviates from an idealized circular Moffat fit is falsely flagged as "contaminants". Dilating this mask wipes out up to 70% of annular pixels in medium star wings, directly causing the sparse coverage that triggers Finding 1.
   - **Finding 3 (Major Defect: `assembly.py:412-414`)**:
     `assemble_composite_extended_psf` unconditionally stacks all three tiers:
     ```python
     psf_faint, cov_faint = stack_tier_stamps_torch(tier_stamps["faint"], ...)
     psf_medium, cov_medium = stack_tier_stamps_torch(tier_stamps["medium"], ...)
     psf_bright, cov_bright = stack_tier_stamps_torch(tier_stamps["bright"], ...)
     ```
     When executed on a detector that lacks stars in one of the tiers (such as `wfi02`, which contains 0 bright stars in the commissioning catalog), `stack_tier_stamps_torch([])` immediately raises:
     ```text
     ValueError: Cannot stack an empty stamp list.
     ```
     There is no graceful fallback for single-detector execution when a tier has 0 stars.

---

## 2. Logic Chain

1. **Why Finding 1 Invalidates Milestone 2 Gate Approval**:
   - *From Observation 4 (Finding 1)*: The fundamental scientific requirement of Milestone 2 (Tenet 1, Tenet 2, Feature 17, and Requirement R2) is cross-tier flux calibration via scalar scale factors $k_{\text{FM}}$ and $k_{\text{MB}}$ in the unsaturated overlap annuli.
   - When `measure_radial_profile_1d(psf_medium)` is called without `mask=(cov_medium == 0)`, all unobserved pixels (set to 0.0 by `nan_to_num`) are included in the median.
   - In sparse tiers (such as WFI01 with 2 medium stars), unobserved pixels comprise $> 50\%$ of the outer annulus, forcing the annular median to 0.0.
   - This causes `determine_overlap_scale_factor_dual` to fail silently and return `k_mb = 1.0`.
   - The resulting composite ePSF on WFI01 suffers a 25x unphysical flux surge (+2377%) across the Medium-to-Bright blending annulus $[30, 48]$ px. This is a severe defect in the core scientific deliverable.

2. **Why the Existing Test Suite Missed This Defect**:
   - In `tests/unit/test_assembly.py`, `synthetic_tier_stamps` generates dense synthetic stamps where all pixels in all tiers are 100% valid (`cov > 0` everywhere), so unobserved 0.0 pixels never existed in the unit test data.
   - In `tests/e2e/test_tier4_scenarios.py`, `test_s1_03` only verified `assert epsf.shape == (501, 501)`, `assert epsf[250, 250] > 0.0`, and `assert np.isclose(np.sum(epsf), 1.0)`. It never asserted `k_mb < 1.0` or tested radial monotonicity across the transition annuli.
   - In `tests/e2e/test_tier4_scenarios.py`, `test_s4_02` tested `blend_2d_annular_profiles` using two flat images of constant value 50.0 rather than testing the synthesized ePSF model.

3. **Why Finding 3 Must Be Resolved Before Milestone 3**:
   - Milestone 3 requires executing the pipeline across all 18 WFI detectors (`wfi01`..`wfi18`).
   - Several detectors (including `wfi02`) have zero stars in the bright tier ($m < 11.0$).
   - Calling `assemble_composite_extended_psf` on single detectors or partitioned sets will crash with `ValueError: Cannot stack an empty stamp list.` unless graceful tier handling is implemented.

---

## 3. Caveats

- **No Caveats on Verified Code**: The mathematical foundations of the 6-fold spike geometry, subpixel bicubic shifting, PyTorch tensor acceleration, and raised-cosine blending are verified to be high quality, correct, and free of cheating or facade code.
- **Root Cause is Well-Isolated**: Finding 1 is completely resolved by passing `mask = (cov == 0)` to `measure_radial_profile_1d` inside `assemble_composite_extended_psf`. Finding 2 is resolved by radius-dependent clipping or raising `detection_sigma` in the inner halo. Finding 3 is resolved by checking `if len(tier_stamps[tier]) > 0` before stacking.

---

## 4. Conclusion

**Verdict: REQUEST_CHANGES**

Milestone 2 implementation cannot be approved in its current state due to one Critical Defect and two Major Defects:

1. **[CRITICAL] Flawed Assembly Radial Profiling (`src/romanepsf/assembly.py:417-419`)**:
   - *Problem*: `measure_radial_profile_1d` does not receive the coverage mask `cov`. Unobserved pixels (`cov == 0`, filled with 0.0) dominate the median in sparse tiers, causing `prof_m` to collapse to 0.0 in $[22, 45]$ px, which forces `k_mb` to fall back to `1.0`, creating a 25x (+2377%) unphysical flux surge at $r = 30..48$ px on WFI01.
   - *Required Fix*: Pass `mask = (cov_faint == 0)`, `mask = (cov_medium == 0)`, and `mask = (cov_bright == 0)` into `measure_radial_profile_1d` in `assemble_composite_extended_psf`. Also add an assertion or test verifying `k_mb < 0.1` and monotonic radial decay in the assembled WFI01 ePSF.

2. **[MAJOR] False Contaminant Masking of Stellar Halo (`src/romanepsf/masking.py:414-424`)**:
   - *Problem*: Fixed $3\sigma$ threshold above sky noise on `~protected_stellar_area` falsely flags genuine stellar wings as contaminants, masking up to 70% of annular pixels at $r \in [15, 45]$ px.
   - *Required Fix*: Either scale `detection_sigma` radially (e.g. higher threshold near center, e.g. $\sigma(r) = 3.0 + 5.0 \cdot \exp(-r / 15.0)$) or restrict contaminant detection to isolated compact objects via morphological aspect ratio / minimum area thresholds.

3. **[MAJOR] Crash on Detectors with Missing Tiers (`src/romanepsf/assembly.py:412-414`)**:
   - *Problem*: `assemble_composite_extended_psf` crashes with `ValueError: Cannot stack an empty stamp list` when a tier contains zero stars (e.g. WFI02).
   - *Required Fix*: Support 2-tier fallback (e.g. faint + medium when bright is empty, or pooling across detectors).

---

## 5. Verification Method

To independently reproduce all observations and verify the defects:

1. **Reproduce Defect 1 (WFI01 `k_mb = 1.0` and 25x flux surge)**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c '
   from romanepsf import loader, catalog, stamps, assembly
   import numpy as np, pandas as pd

   l2 = loader.load_l2_image("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf", calibrate=True)
   cat_df = pd.read_csv("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv", low_memory=False)
   ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
   cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
   cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
   proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
   tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
   tier_stamps = stamps.process_star_stamps(l2, tiered)

   epsf, diag = assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
   print("Observed k_fm:", diag["k_fm"], "Observed k_mb:", diag["k_mb"])
   c = 250
   print("Flux at r=30 px:", epsf[c, c+30], "Flux at r=48 px:", epsf[c, c+48])
   '
   ```
   *Expected Output*: Shows `k_mb = 1.0000` and `epsf[c, c+48] >> epsf[c, c+30]`.

2. **Reproduce Proof of Fix for Defect 1**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c '
   from romanepsf import loader, catalog, stamps, assembly
   import numpy as np, pandas as pd

   l2 = loader.load_l2_image("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf", calibrate=True)
   cat_df = pd.read_csv("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv", low_memory=False)
   ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
   cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
   cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
   proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
   tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
   tier_stamps = stamps.process_star_stamps(l2, tiered)

   _, diag = assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
   r_m, prof_m_masked, _ = assembly.measure_radial_profile_1d(diag["psf_medium"], mask=(diag["cov_medium"] == 0))
   r_b, prof_b_masked, _ = assembly.measure_radial_profile_1d(diag["psf_bright"], mask=(diag["cov_bright"] == 0))
   k_mb_corrected = assembly.determine_overlap_scale_factor_dual(prof_m_masked * diag["k_fm"], prof_b_masked, r_m, r_b, 22.0, 45.0)
   print("Corrected k_mb:", k_mb_corrected)
   assert 0.015 < k_mb_corrected < 0.025
   print("SUCCESS: Passing mask restores correct physical scaling!")
   '
   ```

3. **Reproduce Defect 3 (WFI02 Empty Tier Crash)**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c '
   from romanepsf import loader, catalog, stamps, assembly
   import numpy as np, pandas as pd

   l2 = loader.load_l2_image("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi02_f146_cal.asdf", calibrate=True)
   cat_df = pd.read_csv("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv", low_memory=False)
   ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
   cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
   cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
   proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
   tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
   tier_stamps = stamps.process_star_stamps(l2, tiered)
   assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
   '
   ```
   *Expected Output*: Raises `ValueError: Cannot stack an empty stamp list.`
