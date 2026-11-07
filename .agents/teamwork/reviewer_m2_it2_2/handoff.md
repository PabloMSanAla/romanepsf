# Handoff Report: Reviewer 2 & Adversarial Critic — Milestone 2 Iteration 2 Gate Review

**Agent ID**: `reviewer_m2_it2_2`  
**Parent Orchestrator ID**: `e80d314a-b5a0-43fb-be2e-ceabc982347e`  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_it2_2`  
**Date**: 2026-11-07  
**Status**: REVIEW COMPLETE  
**Gate Verdict**: **APPROVE**  
**Handoff Type**: Hard Handoff  

---

## 1. Observation

### 1.1 Test Suite Execution
1. **Unit Test Suite**:
   Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
   Result: **392 passed in 10.43s** (100% pass across all unit tests, zero failures, zero errors).
2. **End-to-End Test Suite**:
   Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v`
   Result: **298 passed, 4 skipped in 17.45s** (100% pass across all operational tests; 4 skipped tests correspond to Milestone 4 markdown documentation deliverables).
3. **Combined Suite**: **690 passed, 4 skipped, 0 failed** in ~28s.

### 1.2 Integrity Violation Audit
- Audited implementation source files: `src/romanepsf/assembly.py`, `src/romanepsf/masking.py`, `src/romanepsf/stamps.py`, `src/romanepsf/profile.py`, and `src/romanepsf/loader.py`.
- Evaluated against integrity rules:
  1. *Hardcoded test results or expected outputs*: Checked for embedded numerical constants (e.g. `0.0236`, `0.1704`, Gaia source IDs, hardcoded scale factors). Grep and manual AST analysis revealed zero instances.
  2. *Dummy or facade implementations*: Verified genuine numerical implementations:
     - 2D Moffat fitting via `astropy.modeling.fitting.LevMarLSQFitter` (`masking.py:272`).
     - Subpixel bicubic shifting via `scipy.ndimage.shift` with spline order 3 (`stamps.py:339`).
     - PyTorch tensor stacking with MAD outlier rejection (`assembly.py:97-102`).
     - $C^1$ smooth raised-cosine annular partition-of-unity stitching (`assembly.py:331-340`).
  3. *Shortcuts or test bypasses*: Checked for conditional branches keying on test environments (`pytest`, `mock`, `sys._getframe`). Zero found.
  4. *Fabricated verification outputs*: All observations independently executed on raw Level 2 ASDF datasets (`wfi01`, `wfi02`) and precomputed source catalogs.
- **Integrity Assessment Result**: **ZERO integrity violations detected**.

### 1.3 Empirical Verification on Real Commissioning Data

All empirical tests were executed directly using `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_it2_2/verify_empirical.py` on Roman commissioning Level 2 ASDF files located at `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/`.

#### Defect 1: WFI01 $k_{\text{MB}}$ Collapse and Flux Surge Resolution
- **Dataset**: `r0108301001001001001_0001_wfi01_f146_cal.asdf` with catalog `r0108301001001001001_0001_wfi_source_catalog.csv`.
- **Projected Stars**: 7 verified stars (4 faint, 2 medium, 1 bright).
- **Scale Factor Recovery**:
  ```text
  k_fm = 0.170465
  k_mb = 0.023636
  ```
  Verified condition $0.010 < k_{\text{MB}} < 0.100$: **PASS** ($k_{\text{MB}} = 0.023636$).
- **Monotonic Decay across Medium-to-Bright Transition $[30, 48]$ px**:
  Horizontal central slice:
  - $r=30$ px: `epsf[250, 280] = 4.95635413e-06`
  - $r=48$ px: `epsf[250, 298] = 1.04861283e-06`
  - $4.956 \times 10^{-6} > 1.049 \times 10^{-6}$, confirming strict decrease.
  1D Annular Median Profile across $[30, 48]$ px:
  ```text
  r = 30.0 px: flux = 4.85592409e-06
  r = 31.0 px: flux = 4.19133721e-06  (diff: -6.64586878e-07)
  r = 32.0 px: flux = 3.89193428e-06  (diff: -2.99402927e-07)
  r = 33.0 px: flux = 3.50137771e-06  (diff: -3.90556579e-07)
  r = 34.0 px: flux = 3.17638023e-06  (diff: -3.24997472e-07)
  r = 35.0 px: flux = 2.85835222e-06  (diff: -3.18028015e-07)
  r = 36.0 px: flux = 2.61559080e-06  (diff: -2.42761416e-07)
  r = 37.0 px: flux = 2.37576592e-06  (diff: -2.39824885e-07)
  r = 38.0 px: flux = 2.20054153e-06  (diff: -1.75224386e-07)
  r = 39.0 px: flux = 2.05845708e-06  (diff: -1.42084446e-07)
  r = 40.0 px: flux = 1.90931223e-06  (diff: -1.49144853e-07)
  r = 41.0 px: flux = 1.79106144e-06  (diff: -1.18250796e-07)
  r = 42.0 px: flux = 1.68298789e-06  (diff: -1.08073550e-07)
  r = 43.0 px: flux = 1.56199121e-06  (diff: -1.20996674e-07)
  r = 44.0 px: flux = 1.47658534e-06  (diff: -8.54058726e-08)
  r = 45.0 px: flux = 1.39456904e-06  (diff: -8.20162995e-08)
  r = 46.0 px: flux = 1.31848515e-06  (diff: -7.60838930e-08)
  r = 47.0 px: flux = 1.23159941e-06  (diff: -8.68857342e-08)
  r = 48.0 px: flux = 1.16066531e-06  (diff: -7.09341066e-08)
  ```
  Every single adjacent radial step is negative ($\Delta \text{flux} \le 0.0$).
  Flux ratio: $\text{flux}(r=48) / \text{flux}(r=30) = 0.2390$ (a 4.18x decay). The previous 25x (+2377%) step surge is completely eliminated. **PASS**.

#### Defect 2: False Halo Contaminant Over-masking Resolution
- **WFI01 Real Medium Star Stamps**:
  - Stamp 0 (`source_id=6854434484893040896`, $m=11.65$, size $201 \times 201$):
    - Pixels in annulus $[22, 45]$ px: 4,848.
    - Masked pixels: 33.
    - Mask fraction: **0.68%** (< 5% criterion satisfied; previously ~70%).
  - Stamp 1 (`source_id=6866443557049402112`, $m=12.32$, size $201 \times 201$):
    - Pixels in annulus $[22, 45]$ px: 4,848.
    - Masked pixels: 1.
    - Mask fraction: **0.02%** (< 5% criterion satisfied; previously ~70%).
- **Off-Axis Companion Detection**:
  - Injected an off-axis companion (peak flux $15 \text{ MJy/sr}$, $\sigma=1.5$ px) at $r=25$ px ($\theta = 40^\circ$) into real WFI01 medium star stamp 0.
  - Companion peak masked: **True** (`mask_inj[px_y, px_x] == True`).
  - Surrounding stellar halo mask fraction (excluding companion footprint): **0.60%** (< 5%).
  - Result: Genuine contaminants and companion stars remain reliably detected while diffuse stellar halos are preserved. **PASS**.

#### Defect 3: Missing Bright Tier on WFI02 Resolution
- **Dataset**: `r0108301001001001001_0001_wfi02_f146_cal.asdf`.
- **Projected Stars**: 7 verified stars (5 faint, 2 medium, 0 bright).
- **Execution**: `assemble_composite_extended_psf(stamps02, output_size=501)` executed cleanly without exception (no `ValueError: Cannot stack an empty stamp list`).
- **Output Diagnostics**:
  - Shape: `(501, 501)`
  - Total integrated flux: `1.00000000` (normalized to unity)
  - Central peak flux: `3.78959291e-02` (> 0.0, non-hollow core)
  - Cross-tier scale factors: $k_{\text{FM}} = 0.134874$, $k_{\text{MB}} = \text{None}$.
  - Result: Graceful 2-tier synthesis verified. **PASS**.

### 1.4 Adversarial Stress Testing Results
Tested non-standard configurations and edge cases:
1. *All tiers empty*: Correctly raises `ValueError("Cannot assemble composite extended PSF: all tiers are empty.")`.
2. *1-Tier Fallbacks*:
   - Faint-only: Produces normalized $(501, 501)$ canvas, $k_{\text{FM}}=\text{None}, k_{\text{MB}}=\text{None}$.
   - Medium-only: Produces normalized $(501, 501)$ canvas, $k_{\text{FM}}=\text{None}, k_{\text{MB}}=\text{None}$.
   - Bright-only: Produces normalized $(501, 501)$ canvas, $k_{\text{FM}}=\text{None}, k_{\text{MB}}=\text{None}$.
3. *2-Tier Combinations*:
   - Medium + Bright (missing Faint): Blends M+B, produces valid ePSF with $k_{\text{MB}} > 0, k_{\text{FM}}=\text{None}$.
   - Faint + Bright (missing Medium): Blends direct F+B, produces valid ePSF with $k_{\text{FB}} > 0$.
4. *Canvas Dimension Hardening*:
   - Even requested dimension (`output_size=500`): Automatically bumped to odd (`501, 501`).
   - Requested dimension smaller than stamp (`output_size=101`): Symmetrically center-crops cleanly.
5. *Numerical Robustness*:
   - All zero-flux stamps: Returns zero canvas cleanly without `ZeroDivisionError`.
   - Stamps with unobserved/NaN pixels: Properly masked in PyTorch tensor cube.

---

## 2. Logic Chain

1. *From Observation 1.1*: The complete unit test suite (392 tests) and E2E test suite (298 tests) pass with zero failures and zero regressions, demonstrating syntactic and structural conformance.
2. *From Observation 1.2*: No hardcoded outputs, facade logic, or test bypasses exist in the codebase. All algorithms perform real physical and mathematical operations.
3. *From Observation 1.3 (Defect 1)*: Passing `mask=(cov == 0)` to `measure_radial_profile_1d` ensures that unobserved zero-flux pixels in sparse tiers (like WFI01 with 2 medium stars) do not corrupt the annular median. This recovers the physical scale factor $k_{\text{MB}} = 0.023636 \in [0.010, 0.100]$, and establishes strictly monotonic radial decay across $[30, 48]$ px, completely eliminating the previous 25x flux surge.
4. *From Observation 1.3 (Defect 2)*: Combining perimeter background estimation ($r > 0.75 r_{\text{max}}$) with the radially scaled exponential detection threshold $\sigma(r) = \sigma_0(1 + A \exp(-r/r_0))$ lowers the false halo mask fraction from ~70% to $< 0.7\%$ on real medium star stamps, while continuing to reliably detect and mask off-axis companions.
5. *From Observation 1.3 (Defect 3)*: Conditional tier stacking based on available stamp lists and the multi-tier assembly fallback matrix enables robust single-detector processing on detectors that lack bright stars (such as WFI02), producing a normalized 2-tier composite ePSF with $k_{\text{MB}} = \text{None}$.
6. *From Observation 1.4*: Defensive hardening against empty tiers, even canvas sizes, cropping, and non-standard tier combinations is complete and verified.

Therefore, all three defects raised during Milestone 2 are completely and robustly resolved. Milestone 2 satisfies all acceptance criteria.

---

## 3. Caveats

- **No Caveats on Verified Code**: All defect fixes operate on genuine Level 2 data and follow authoritative architectural contracts.
- **Detector Coverage**: While single-detector assembly on WFI01 (3 tiers) and WFI02 (2 tiers) has been verified, full 18-detector execution and multi-detector cross-SCA stamp pooling belong to Milestone 3.

---

## 4. Conclusion

**Verdict: APPROVE**

Milestone 2 Iteration 2 is fully approved to pass Gate Review:
1. **Defect 1 Resolved**: WFI01 physical scaling factor $k_{\text{MB}} = 0.023636$ restored within $[0.010, 0.100]$; strictly monotonic decay verified across $[30, 48]$ px with zero flux surge.
2. **Defect 2 Resolved**: Stellar halo preservation verified (< 1% false masking in $[22, 45]$ px on real WFI01 medium stars); off-axis companion stars remain detected.
3. **Defect 3 Resolved**: 2-tier assembly executes cleanly without `ValueError` on WFI02, yielding a valid normalized $(501, 501)$ ePSF canvas with $k_{\text{MB}} = \text{None}$.
4. **Integrity Verified**: Zero integrity violations, zero hardcoded fixtures.
5. **Test Suite**: 100% pass across 690 unit and E2E tests.

The project is ready to proceed to Milestone 3 (Single-Detector Validation on WFI01 & Full 18-Detector Pipeline Execution).

---

## 5. Verification Method

To independently reproduce all verification results:

1. **Run Full Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
   ```
   *Expected*: 392 passed in unit, 298 passed (4 skipped) in e2e, 0 failed.

2. **Run Empirical Verification Script**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_it2_2/verify_empirical.py
   ```
   *Expected*:
   - WFI01: $0.010 < k_{\text{MB}} < 0.100$ ($k_{\text{MB}} \approx 0.0236$), monotonic decay across $[30, 48]$ px.
   - WFI01 medium stars: mask fraction in $[22, 45]$ px $< 5\%$ ($0.68\%$ and $0.02\%$), off-axis companion masked = True.
   - WFI02: 2-tier clean assembly, shape $(501, 501)$, sum = 1.0, $k_{\text{MB}} = \text{None}$.
   - Exits with return code 0 and `ALL EMPIRICAL TESTS PASSED SUCCESSFULLY!`.

3. **Invalidation Conditions**:
   - Any failure in `pytest tests/unit/` or `pytest tests/e2e/`.
   - $k_{\text{MB}} \ge 0.100$ or flux surge on WFI01.
   - Any unhandled `ValueError` when calling `assemble_composite_extended_psf` on any valid stamp collection.
