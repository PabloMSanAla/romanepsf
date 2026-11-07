# Handoff Report: Blueprint & Unit Test Design for `src/romanepsf/profile.py` & `src/romanepsf/assembly.py`

**Agent ID**: `explorer_m2_3`  
**Parent Orchestrator ID**: `e80d314a-b5a0-43fb-be2e-ceabc982347e`  
**Milestone**: Milestone 2 (Features 15, 16, 17, 18, 19)  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_3`  

---

## 1. Observation

### 1.1 Codebase Layout & Architectural Requirements
1. **User Request & Project Specs**:
   - `ORIGINAL_REQUEST.md` (R1, R2, Acceptance Criteria):
     - Multi-tier ePSF synthesis across Bright ($m < 11.0$), Medium ($11.0 \le m < 13.0$), and Faint ($m \ge 13.0$) stars.
     - **Strict Scientific Constraint**: 1D radial profiles (`profile.py`) are strictly reserved for identifying saturation boundaries ($r_{\text{sat}}$) and calculating scalar cross-tier overlap scaling factors ($k_{\text{FM}}, k_{\text{MB}}$). Azimuthal averaging or circularizing the 2D PSF canvas is strictly prohibited. The synthesized model must directly capture full 2D structure, asymmetries, and 6-fold 2D diffraction spikes.
   - `PROJECT.md` (Features 15–19, lines 43–47 & 89–98):
     - Feature 15: Robust Tier Tensor Stacking via PyTorch tensor acceleration with outlier rejection.
     - Feature 16: 1D Radial Profile Operator strictly for calibration.
     - Feature 17: Dual-Radius Cross-Tier Normalization (`determine_overlap_scale_factor_dual`) to eliminate IndexError.
     - Feature 18: 2D Cosine-Taper Partition-of-Unity Stitching across $[10, 18]$ px (Faint-to-Medium) and $[30, 48]$ px (Medium-to-Bright).
     - Feature 19: Global Energy Conservation Normalization ($\sum \text{ePSF} = 1.0$) with non-negative clipping.
2. **Current Namespace State**:
   - `src/profile.py` (8,064 bytes) and `src/assembly.py` (10,255 bytes) exist at the top level of `src/`, but canonical packaged implementations under `src/romanepsf/profile.py` and `src/romanepsf/assembly.py` are absent.
   - `tests/unit/test_profile.py` and `tests/unit/test_assembly.py` do not yet exist in `tests/unit/`.

### 1.2 Verbatim Root Cause Analysis: IndexError at `src/assembly.py:152`
Executing Scenario 1 integration test `test_s1_03_wfi01_composite_assembly_and_non_hollow_core` reproduced the known defect flagged in `tests/e2e/test_tier4_scenarios.py:97–101`:
```text
pytest tests/e2e/test_tier4_scenarios.py -k "test_s1_03"
XFAIL tests/e2e/test_tier4_scenarios.py::TestScenario1SingleDetectorWFI01::test_s1_03_wfi01_composite_assembly_and_non_hollow_core
Reason: Implementation bug in src/assembly.py:152 (determine_overlap_scale_factor): prof_outer shape mismatch with inner radii boolean mask: boolean index did not match indexed array along dimension 0; dimension is 100 but corresponding boolean dimension is 40
```
- In `src/assembly.py:140–163`:
  ```python
  def determine_overlap_scale_factor(
      prof_inner: np.ndarray,
      prof_outer: np.ndarray,
      radii: np.ndarray,
      r_min: float,
      r_max: float,
  ) -> float:
      idx = (radii >= r_min) & (radii <= r_max)
      v_in = prof_inner[idx]
      v_out = prof_outer[idx]  # <-- BUG at line 152
  ```
- In `assemble_composite_extended_psf`:
  - `psf_faint` is $81 \times 81 \implies r_{\text{max}} = 40 \implies \text{len}(r_{\text{f}}) = 40, \text{len}(prof_{\text{f}}) = 40$.
  - `psf_medium` is $201 \times 201 \implies r_{\text{max}} = 100 \implies \text{len}(r_{\text{m}}) = 100, \text{len}(prof_{\text{m}}) = 100$.
  - `psf_bright` is $1001 \times 1001 \implies r_{\text{max}} = 500 \implies \text{len}(r_{\text{b}}) = 500, \text{len}(prof_{\text{b}}) = 500$.
  - When calling `determine_overlap_scale_factor(prof_f, prof_m, r_f, r_min=8.0, r_max=16.0)`:
    `radii = r_f` has shape `(40,)`. `idx` is boolean of shape `(40,)`.
    `v_out = prof_outer[idx]` evaluates `prof_m[idx]` where `prof_m` has shape `(100,)`.
    Numpy raises verbatim: `IndexError: boolean index did not match indexed array along dimension 0; dimension is 100 but corresponding boolean dimension is 40`.
  - The second overlap `determine_overlap_scale_factor(prof_m_scaled, prof_b, r_m, ...)` similarly crashes because `idx` is shape `(100,)` while `prof_b` is shape `(500,)`.

### 1.3 Hidden Defect Discovered: ValueError at `src/assembly.py:276`
When bypassing the `IndexError`, execution on real WFI01 data with `output_size=501` revealed an immediate secondary crash:
```text
ValueError: could not broadcast input array from shape (1001,1001) into shape (250,250)
  File "/Users/pmsanch1/code/romanepsf/src/assembly.py", line 276, in assemble_composite_extended_psf
    bright_canvas[y0:y0+psf_bright_scaled.shape[0], x0:x0+psf_bright_scaled.shape[1]] = psf_bright_scaled
```
- In `src/assembly.py:265–276`:
  When `output_size = 501` and `psf_bright_scaled.shape = (1001, 1001)`:
  `half_t = (501 - 1) // 2 = 250`
  `half_b = (1001 - 1) // 2 = 500`
  `y0 = half_t - half_b = 250 - 500 = -250`
  `bright_canvas[y0 : y0 + 1001, x0 : x0 + 1001]` uses negative slice start `-250`, wrapping to index $501 - 250 = 251$, capped at 501. Sliced shape is `(250, 250)` instead of `(1001, 1001)`.
- **Finding**: Slicing naively assumes `output_size >= psf_bright_scaled.shape[0]`. When `output_size < psf_bright_scaled.shape[0]`, the bright PSF must be centered and cropped down to `(output_size, output_size)` rather than embedded.

### 1.4 Faint Core Masking & Hollow Core Vulnerability
- Checking WFI01 calibrated data (`r0108301001001001001_0001_wfi01_f146_cal.asdf`) revealed that all 4 faint stars had center pixel DQ values containing bit 1 (`SATURATED`, value 2) or bit 2 (`JUMP_DET`, value 4).
- When DQ saturated pixels are masked without faint core protection, `mask[c, c] == True` for all faint stamps. In `stack_tier_stamps_torch`, `tensor_cube[:, c, c]` became all-NaN, yielding `psf_faint[40, 40] = 0.0` (a hollow core).
- **Finding**: In addition to `stamps.py` Feature 11 faint core protection, `assembly.py` must include a neighborhood fallback in `stack_tier_stamps_torch` to ensure the centroid is never left as a 0.0 void if neighboring pixels are positive.

---

## 2. Logic Chain

### Step 1: Scientific Constraint & 2D Spatial Preservation
1. From Observation 1.1: 1D radial profiles are strictly reserved for finding saturation boundaries ($r_{\text{sat}}$) and computing scalar scaling factors ($k$).
2. The empirical 2D PSF synthesis proceeds purely by operations on 2D arrays:
   - Each tier (Faint, Medium, Bright) is stacked as a 2D tensor cube along dimension 0.
   - The stacked outputs `psf_faint`, `psf_medium`, `psf_bright` are 2D arrays containing real stellar flux distributions.
   - Scale factors $k_{\text{FM}}$ and $k_{\text{MB}}$ are scalar floats computed from 1D radial profiles in unsaturated annuli.
   - Multiplying `psf_medium * k_fm` and `psf_bright * k_mb` scales the entire 2D image uniformly, preserving all non-circular spatial features.
   - Annular blending is performed directly on the 2D pixel grid $(x, y)$ using a 2D scalar weight map $w(r_{x,y})$, preserving 6-fold spikes and core asymmetries without radial averaging.

### Step 2: Dual-Radius Overlap Scale Factor (`determine_overlap_scale_factor_dual`)
1. From Observation 1.2: Inner and outer profiles have independent radius vectors $r_{\text{inner}}$ and $r_{\text{outer}}$ with differing lengths ($N_{\text{inner}} \ne N_{\text{outer}}$).
2. Implementing `determine_overlap_scale_factor_dual(prof_inner, prof_outer, r_inner, r_outer, r_min, r_max)`:
   - Slices independent boolean masks:
     $$M_{\text{inner}} = (r_{\text{inner}} \ge r_{\text{min}}) \land (r_{\text{inner}} \le r_{\text{max}})$$
     $$M_{\text{outer}} = (r_{\text{outer}} \ge r_{\text{min}}) \land (r_{\text{outer}} \le r_{\text{max}})$$
   - When radial sampling steps match ($1.0$ px spacing), $r_{\text{inner}}[M_{\text{inner}}]$ and $r_{\text{outer}}[M_{\text{outer}}]$ identify identical radial coordinate samples.
   - When coordinates match, $v_{\text{in}} = \text{prof}_{\text{inner}}[M_{\text{inner}}]$ and $v_{\text{out}} = \text{prof}_{\text{outer}}[M_{\text{outer}}]$ have identical lengths.
   - For disparate or fractional grids, common radii are matched via `np.intersect1d` or linear interpolation `np.interp(r_in_sel, r_outer, prof_outer)`.
   - Filters out non-finite, zero, and negative fluxes:
     $$\text{valid} = \text{isfinite}(v_{\text{in}}) \land \text{isfinite}(v_{\text{out}}) \land (v_{\text{in}} > 0) \land (v_{\text{out}} > 0)$$
   - Computes robust scalar ratio $k = \text{median}(v_{\text{in}}[\text{valid}] / v_{\text{out}}[\text{valid}])$.
   - Falls back gracefully to $1.0$ if the overlap contains no valid positive flux.
3. Backward compatibility is maintained in `determine_overlap_scale_factor`: if `r_outer` is omitted, it reconstructs $r_{\text{outer}} = r_0 + j \times \Delta r$ from the step of $r_{\text{inner}}$, ensuring legacy test calls never crash.

### Step 3: $C^1$ Smooth Raised-Cosine Partition-of-Unity Blending
1. Annular raised-cosine taper weighting function:
   $$w(r) = \begin{cases} 
   1.0 & r \le r_{\text{start}} \\ 
   0.5 \times \left(1 + \cos\left(\pi \times \frac{r - r_{\text{start}}}{r_{\text{end}} - r_{\text{start}}}\right)\right) & r_{\text{start}} < r < r_{\text{end}} \\ 
   0.0 & r \ge r_{\text{end}} 
   \end{cases}$$
2. Boundary and derivative properties:
   - At $r = r_{\text{start}}$: $w = 1.0$, $w' = 0.0$.
   - At $r = r_{\text{end}}$: $w = 0.0$, $w' = 0.0$.
   - Midpoint $r_{\text{mid}} = (r_{\text{start}} + r_{\text{end}})/2$: $w = 0.5$.
   - Partition of unity: $w(r) + (1.0 - w(r)) \equiv 1.0$ everywhere on the 2D grid.
   - Zero derivative at endpoints guarantees $C^1$ continuity, eliminating sharp edge kinks and Fourier ringing.
3. Canvas Embedding and Cropping:
   - If `inner_image` is smaller than `outer_image`, it is embedded into the center of a matching zero array.
   - If `inner_image` is larger than `outer_image`, it is center-cropped to the shape of `outer_image`.
   - Resolves the Observation 1.3 `ValueError` during final canvas synthesis:
     $$\text{if } S_{\text{bright}} > S_{\text{target}}: \text{crop } psf_{\text{bright}} \text{ to } (S_{\text{target}}, S_{\text{target}})$$
     $$\text{elif } S_{\text{bright}} < S_{\text{target}}: \text{embed } psf_{\text{bright}} \text{ into center of } (S_{\text{target}}, S_{\text{target}})$$

### Step 4: Robust Tier Tensor Stacking & Non-Hollow Core
1. All stamps within a tier are centered and padded to $S_{\text{max}} = \max(S_i)$ (forced odd).
2. Stacking algorithm via PyTorch:
   - First-pass median: $\text{med} = \text{torch.nanmedian}(\text{cube}, \text{dim}=0)$.
   - For $N \ge 3$, robust dispersion is calculated via MAD: $\text{MAD} = 1.4826 \times \text{nanmedian}(|\text{cube} - \text{med}|, \text{dim}=0)$, clamped to $\ge 10^{-6}$. Outliers exceeding $3 \times \text{MAD}$ are set to NaN.
   - For $N < 3$, sigma clipping is bypassed to prevent false rejection of valid stars.
   - Final nanmedian along dim=0 yields stacked 2D flux, and valid non-outlier pixels are counted in coverage map.
3. Hollow Core Recovery:
   - If the exact center pixel `stacked[c, c] == 0.0` due to all stamps having masked cores, it is replaced by the median of positive pixels in its $3 \times 3$ box neighborhood.

### Step 5: Global Unit Flux Normalization
1. Synthesized canvas is cleaned of NaNs and Infs: `np.where(np.isfinite(psf), psf, 0.0)`.
2. Negative noise in far wings is clipped: `psf = np.maximum(psf, 0.0)`.
3. Total volume integral: $F_{\text{tot}} = \sum_{x,y} \text{psf}(x, y)$.
4. Normalization: $\text{ePSF} = \text{psf} / F_{\text{tot}}$ if $F_{\text{tot}} > 0$ else $\text{psf}$, guaranteeing $\sum \text{ePSF} = 1.0$.

---

## 3. Caveats

1. **Read-Only Explorer Scope**: In accordance with the Explorer archetype constraints, no modifications were made directly to `src/romanepsf/profile.py`, `src/romanepsf/assembly.py`, `src/profile.py`, or `src/assembly.py`. Complete, tested drop-in blueprint implementations have been authored in:
   - `proposed_profile.py`
   - `proposed_assembly.py`
   - `proposed_test_profile.py`
   - `proposed_test_assembly.py`
2. **PyTorch MPS Synchronization**: On Apple Silicon (MPS), GPU asynchronous kernel launches can cause race conditions during timing benchmarks. Explicit `torch.mps.synchronize()` calls are placed around meshgrid creation when `device="mps"`.
3. **Dependency on Upstream Stamps & Masking**: Final end-to-end integration across all 18 detectors (`pipeline.py`) relies on `stamps.py` Feature 11 (faint core DQ unmasking) and `masking.py` dual-prior protection (delivered by Explorers 1 and 2).

---

## 4. Conclusion

1. **Authoritative Blueprint Delivered**:
   - `proposed_profile.py` implements high-performance PyTorch meshgrids, MAD-based parallel sigma clipping, Moffat PSF extensions, and strict 1D profile boundaries.
   - `proposed_assembly.py` implements:
     - `determine_overlap_scale_factor_dual` with independent radius vectors, completely eliminating the `IndexError` at `assembly.py:152`.
     - Backward-compatible `determine_overlap_scale_factor` wrapper.
     - Dual-mode canvas sizing fixing the `ValueError` at `assembly.py:276`.
     - $C^1$ smooth raised-cosine partition of unity across $[10, 18]$ px and $[30, 48]$ px.
     - Robust PyTorch tensor stacking with MAD outlier rejection and hollow-core fallback.
     - Non-negative clipping and global unit volume normalization ($\sum \text{ePSF} = 1.0$).
2. **Unit Test Suites Verified**:
   - `proposed_test_profile.py`: **17/17 tests passing (100% pass in 1.30s)**.
   - `proposed_test_assembly.py`: **27/27 tests passing (100% pass in 1.76s)**.
   - Total: **44 comprehensive unit tests** ready for placement into `tests/unit/test_profile.py` and `tests/unit/test_assembly.py`.

---

## 5. Verification Method

### 5.1 Execute Proposed Unit Test Suites
Run both unit test suites with the project's designated Python environment:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest .agents/teamwork/explorer_m2_3/proposed_test_profile.py -v
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest .agents/teamwork/explorer_m2_3/proposed_test_assembly.py -v
```
*Expected Result*: 17 passed in `proposed_test_profile.py`, 27 passed in `proposed_test_assembly.py` (total 44 passed in < 3.5s).

### 5.2 Execute Existing Milestone 1 & 2 Feature Tests
Verify that all existing tests covering Features 15–19 continue to pass:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier1_features.py -k "TestFeature15 or TestFeature16 or TestFeature17 or TestFeature18 or TestFeature19" -v
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier2_boundaries.py -k "TestBoundary13 or TestBoundary14 or TestBoundary15 or TestBoundary16 or TestBoundary17" -v
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier3_combinations.py -k "pair_09 or pair_10 or pair_11 or pair_12 or pair_13 or pair_16" -v
```
*Expected Result*: All 56 tests pass without regression.

### 5.3 Verify Dual-Radius Assembly on Real WFI01 Data
Verify that the `IndexError` and `ValueError` are resolved on real Level 2 commissioning data when integrating with Explorer 1's `proposed_stamps.py`:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c '
import sys
sys.path.insert(0, ".agents/teamwork/explorer_m2_1")
sys.path.insert(0, ".agents/teamwork/explorer_m2_3")
import proposed_stamps as stamps
import proposed_assembly as assembly
import numpy as np, pandas as pd
from romanepsf import loader, catalog

l2 = loader.load_l2_image("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf", calibrate=True)
cat_df = pd.read_csv("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv", low_memory=False)
ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
tier_stamps = stamps.process_star_stamps(l2, tiered)

epsf, diag = assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
assert epsf.shape == (501, 501)
assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
assert epsf[250, 250] > 0.0
print("Verification SUCCESS: ePSF assembled seamlessly with non-hollow core (flux:", epsf[250, 250], ")!")
'
```
*Expected Result*: Prints `Verification SUCCESS: ePSF assembled seamlessly with non-hollow core (flux: 0.048017614)!`.
