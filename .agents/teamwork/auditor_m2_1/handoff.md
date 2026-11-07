# Forensic Integrity Audit Report: Milestone 2 (auditor_m2_1)

**Audit Target**: Milestone 2 (Features 9–19: `stamps.py`, `masking.py`, `profile.py`, `assembly.py`)  
**Auditor**: `auditor_m2_1`  
**Date**: 2026-11-06  
**Final Verdict**: **CLEAN**

---

## Forensic Audit Report

**Work Product**: Milestone 2 Implementation (`src/romanepsf/stamps.py`, `masking.py`, `profile.py`, `assembly.py`)  
**Profile**: General Project / Integrity Forensics  
**Verdict**: **CLEAN**

### Phase Results
- **Hardcoded test results**: **PASS** — Zero hardcoded outputs, pre-baked matrices, or lookup tables detected in `src/romanepsf/` or `src/`.
- **Facade implementations**: **PASS** — Every function and class executes real domain logic and mathematical computation; no stub functions, no dummy returns.
- **Fabricated verification outputs**: **PASS** — Workspace search revealed zero pre-populated ePSF result files, pre-baked FITS models, or falsified test logs.
- **Mathematical operations integrity**: **PASS** — Subpixel bicubic spline realignment, 2D Moffat core fitting (`LevMarLSQFitter`), directional ridge filtering (radial span and circular angular dispersion), PyTorch tensor stacking with 2-pass MAD outlier rejection, and $C^1$ smooth raised-cosine partition-of-unity blending are genuine, rigorous mathematical operations.
- **Strict Scientific Integrity**: **PASS** — 1D radial profiles (`src/romanepsf/profile.py`, `src/romanepsf/assembly.py:measure_radial_profile_1d`) are strictly restricted to identifying saturation boundaries and evaluating scalar cross-tier overlap scale factors ($k_{\text{FM}}, k_{\text{MB}}$). Zero azimuthal averaging, radial circularization, or 1D-to-2D projection is performed on the 2D PSF canvas; 2D diffraction spikes and non-circular asymmetries are directly synthesized from stacked 2D cutouts.
- **Test suite authenticity**: **PASS** — Unit tests (`tests/unit/test_masking.py`, `test_stamps.py`, `test_profile.py`, `test_assembly.py`) and E2E scenario tests (`tests/e2e/test_tier4_scenarios.py`) perform genuine assertions against real production code without mocking out core algorithms.

---

## 1. Observation

1. **Static Analysis of Canonical Modules**:
   - `src/romanepsf/stamps.py`:
     - Adaptive sizing (`lines 52–98`): dynamically calculates odd stamp sizes from analytical Moffat extension (`get_psf_extension_moffat(mag, depth=30.0) * 2.2 / pixel_scale`), bounding bright cutouts up to `max_size` (e.g. 1001).
     - Subpixel realignment (`lines 247–300`): applies 3rd-order bicubic spline interpolation via `scipy.ndimage.shift(clean_stamp, [-dy, -dx], order=3, mode="constant", cval=bkg)` with NaN-guarding background filling and synchronous order-0 mask shifting.
     - Background estimation (`lines 157–240`): implements iterative 3-sigma MAD clipping within outer annulus (`0.80` to `0.98` stamp half-width) with percentile fallback.
     - Faint core protection (`lines 431–439`): validates that positive finite flux in core ($r \le 4.0$ px) unflags DQ bit 1 (`SATURATED`), preventing hollow center artifacts.
   - `src/romanepsf/masking.py`:
     - 6-fold pupil geometry (`lines 36–65`): generates 12 spike rays from `ROMAN_BASE_SPIKE_ANGLES_DEG = [23.55, 55.29, 80.25, 118.65, 142.88, 178.07]` rotated by telescope PA and nominal detector clocking offset ($-9.70^\circ$).
     - Geometric corridor protection (`lines 67–124`): constructs 2D boolean mask combining angular wedge cones (`angular_half_width_deg=4.0`) and constant-width corridors (`spike_width_px=4.0`).
     - 2D Moffat fitting (`lines 212–276`): fits 2D circularly symmetric `astropy.modeling.models.Moffat2D` using `astropy.modeling.fitting.LevMarLSQFitter` with inverse-variance weights, safely excluding masked/saturated pixels.
     - Directional ridge filtering (`lines 126–210`): labels contiguous residual features above threshold sigma, discriminates diffraction spikes based on radial extent (`radial_span >= min_length_px`) and narrow circular angular dispersion (`circ_std < 20.0`), rejecting compact companion stars.
     - Strict invariant protection (`lines 428–434`): ensures `contaminants &= (~protected_stellar_area)` so spikes and stellar core pixels are never flagged as contaminants.
   - `src/romanepsf/profile.py`:
     - Elliptical coordinate grid (`lines 24–78`): builds rotated elliptical coordinate tensor using PyTorch (`create_ellipse_meshgrid_torch`).
     - Parallel sigma clipping (`lines 80–126`, `lines 250–265`): digitizes pixels into radius bins via `torch.bucketize`, executing multi-threaded iterative MAD sigma clipping (`_clip_single_bin`).
     - Analytical Moffat extension (`lines 274–315`): analytically inverts Moffat surface brightness profile to compute PSF radius in arcseconds down to detection depth.
     - Purely 1D output: returns strictly 1D numpy arrays (`flux`, `flux_err`); contains no routines that project or circularize 1D profiles into a 2D image.
   - `src/romanepsf/assembly.py`:
     - Multi-tier PyTorch stacking (`lines 24–125`): pads stamps to maximum tier size, computes `torch.nanmedian`, applies 2-pass MAD outlier rejection (`sigma_clip=3.0`), tracks coverage count, and implements hollow-core recovery if central pixel was masked in all inputs.
     - 1D radial profiling for calibration (`lines 127–164`): invokes `elliptical_profile` strictly to produce 1D radius and flux vectors.
     - Dual-radius overlap scale factor (`lines 166–238`): evaluates `r_inner` and `r_outer` independently within `[r_min, r_max]`, resolving the previous `IndexError` at line 152 without hardcoding.
     - Seamless 2D raised-cosine blending (`lines 265–338`): evaluates $C^1$ smooth partition-of-unity annular weights $w(r_{x, y}) = 0.5(1 + \cos(\pi(r - r_0)/(r_1 - r_0)))$ across $[10, 18]$ px and $[30, 48]$ px. Blends 2D arrays directly, completely preserving 2D structure and diffraction spikes.
     - Dual-mode canvas sizing (`lines 443–461`): embeds smaller stamps into larger target canvas or center-crops larger stamps down to target size, permanently fixing the `ValueError` broadcast mismatch.
     - Energy conservation (`lines 470–480`): clips non-finite and negative values to 0.0 and normalizes integrated 2D volume flux to 1.0 ($\sum \text{ePSF} = 1.0$).

2. **Empirical Test Suite Execution Results**:
   - `pytest tests/unit/ -v`:
     ```text
     ============================= 284 passed in 5.15s ==============================
     ```
     100% pass across all 284 unit tests, including 97 newly authored Milestone 2 tests.
   - `pytest tests/e2e/ -v`:
     ```text
     ======================= 298 passed, 4 skipped in 17.30s ========================
     ```
     100% pass across all 298 E2E scenario tests, including real commissioning WFI01 composite assembly (`test_s1_03`) and extreme brightness WFI05 spike preservation (`test_s3_04`, `test_s3_05`).
   - Combined test suite: **582 passed, 4 skipped in 22.45s** with 0 failures, 0 errors, 0 xfails.

3. **Commissioning WFI01 Assembly Smoke Test Execution**:
   - Executing real WFI01 L2 ASDF data and catalog ingestion via `miniforge3/envs/rosalia-dev/bin/python`:
     ```text
     SUCCESS: Real WFI01 ePSF assembled seamlessly! Peak center flux: 0.031139981
     Diagnostics k_fm: 0.12106673080371527 k_mb: 1.0
     ```
     Confirmed shape `(501, 501)`, positive non-hollow peak flux at center `(250, 250)`, and unit total volume flux ($\sum = 1.0$).

4. **Adversarial Stress Testing Execution**:
   - Stress test 1: Raised-Cosine partition-of-unity error $= 0.00\times 10^0 < 10^{-6}$; outer 2D diffraction spike preserved.
   - Stress test 2: Extreme profile length mismatch (10 bins vs 1000 bins) recovered exact scale factor `3.0000`; disjoint radii cleanly returned fallback `1.0`.
   - Stress test 3: Subpixel shift flux conservation under extreme offset $(\Delta x, \Delta y) = (-0.45, 0.45)$ yielded relative difference $= 4.89\times 10^{-8} \ll 0.5\%$.
   - Stress test 4: Morphological ridge filter detected linear spike ($L=45$ px) while cleanly rejecting compact circular companion star ($S/N = 200$).
   - Stress test 5: Stacking 5 stamps with masked center pixel recovered center flux `25.0` via 3x3 neighborhood fallback.

---

## 2. Logic Chain

1. **Evaluation against Prohibited Patterns**:
   - *Hardcoded test results*: Inspection of `stamps.py`, `masking.py`, `profile.py`, and `assembly.py` revealed zero pre-baked numeric constants matching test assertions. Functions compute values dynamically from inputs. (Observation 1)
   - *Facade implementations*: All functions perform real floating-point and tensor operations (`torch.nanmedian`, `scipy.ndimage.shift`, `LevMarLSQFitter`, `binary_dilation`, `np.interp`). No dummy wrappers or placeholders exist. (Observation 1)
   - *Fabricated verification outputs*: No pre-existing FITS or log artifacts existed in `output/` prior to test runs. (Observation 1)
   - *Self-certifying tests*: Unit tests construct synthetic images with known analytical ground truths (e.g. Gaussian peaks, constant disks, injected lines) and verify mathematical invariance independently of production internals. (Observation 1, 2)

2. **Evaluation of Strict Scientific Integrity**:
   - `ORIGINAL_REQUEST.md` mandates:
     > "The model must directly capture the full 2D structure including 2D spikes; radial averaging or circularizing the 2D PSF is prohibited. 1D radial profiles (via src/profile.py) are strictly reserved for identifying saturation boundaries and calculating cross-tier flux scaling factors."
   - In `profile.py`, `elliptical_profile` outputs purely 1D radial flux vectors (`np.ndarray` of shape `(N,)`). It possesses no code to reconstruct or back-project 2D images.
   - In `assembly.py`, `assemble_composite_extended_psf` computes 1D radial profiles solely to evaluate scalar cross-tier scale factors $k_{\text{FM}}$ and $k_{\text{MB}}$. The 2D images `psf_faint`, `psf_medium`, and `psf_bright` are retained in full 2D and blended using spatial weight map $w(r_{x, y})$.
   - The 2D diffraction spikes and non-circular core asymmetries are directly carried through the 2D blending pipeline into the final ePSF canvas without azimuthal averaging. (Observation 1, 4)

3. **Evaluation of Test Authenticity**:
   - Grep search for `mock` across `tests/unit/test_masking.py`, `test_stamps.py`, `test_profile.py`, and `test_assembly.py` confirmed zero mocking of Milestone 2 modules.
   - Tests assert real numpy/torch outputs, array bounds, dtypes, flux conservation, and coordinate transformations. (Observation 2)

---

## 3. Caveats

- **No Caveats**: The entire Milestone 2 scope (Features 9 through 19) was audited. All checks passed with empirical verification and mathematical rigor.

---

## 4. Conclusion

The work product delivered for Milestone 2 is **authentic, scientifically rigorous, and completely free of integrity violations**.
All mathematical algorithms (bicubic spline realignment, 2D Moffat fitting, directional ridge filtering, PyTorch tensor stacking, raised-cosine partition of unity) are genuine implementations.
The strict scientific constraint prohibiting radial circularization of the 2D PSF canvas is strictly enforced.

**Final Verdict**: **CLEAN**

---

## 5. Verification Method

To independently verify this audit:

1. **Execute Unit Tests**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   ```
   *Expected Result*: 284 passed in ~5 seconds.

2. **Execute E2E Scenario Tests**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
   ```
   *Expected Result*: 298 passed, 4 skipped in ~17 seconds.

3. **Execute Real Commissioning WFI01 Assembly Smoke Test**:
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
   assert epsf.shape == (501, 501)
   assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
   assert epsf[250, 250] > 0.0
   print("SUCCESS: Real WFI01 ePSF assembled seamlessly! Peak center flux:", epsf[250, 250])
   '
   ```
   *Expected Output*: `SUCCESS: Real WFI01 ePSF assembled seamlessly! Peak center flux: 0.031139981`.

4. **Verify Absence of Circularization on 2D PSF Canvas**:
   Inspect `src/romanepsf/assembly.py:assemble_composite_extended_psf`:
   Confirm lines 417–428 extract 1D profiles solely for $k_{\text{FM}}$ and $k_{\text{MB}}$, and lines 431–469 blend 2D arrays directly (`blend_2d_annular_profiles`) using 2D spatial weight maps.
