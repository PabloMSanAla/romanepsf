# Milestone 4 Challenger Report: Adversarial Stress Testing of Validation Pipeline

**Agent**: `challenger_m4_1`  
**Role**: Empirical Adversarial Verifier (critic, specialist)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m4_1`  
**Target Code**: `src/romanepsf/validation.py`, `tests/unit/test_validation.py`  
**Test Suite**: `tests/unit/test_adversarial_validation_stress.py`  
**Date**: 2026-11-07T01:42:00Z  
**Verdict**: **APPROVE**  

---

## 1. Observation

A dedicated adversarial stress test suite of 47 tests was designed, authored, and executed against `src/romanepsf/validation.py` using:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_adversarial_validation_stress.py -v
```
**Result**: 47 passed in 4.52s.

The entire project test suite was also executed:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/ -q
```
**Result**: 893 passed in 66.05s (100% pass rate).

### 1.1 Direct Observations Across the 7 Targeted Attack Vectors

#### Vector 1: Saturated Core Stars
- **Scale Factor Fitting**: When a bright star ($m = 8.5$, true flux 500,000.0) has a saturated core plateau ($r < 8$ px flat-topped at 12,000 ADU) and is marked in `stamp.mask`, `fit_star_to_model` recovered `flux_scale = 500000.03` (0.000006% error).
- **Core Radial Gate**: For bright stars (`tier="bright"`), line 511 of `validation.py` restricts fitting to `(r_grid >= 10.0) & (r_grid <= 45.0)`. Even if an artificial spike of 99,999 ADU is injected into the core and left unmasked, the scale factor is fitted at $200000.0$ ($0.0\%$ error).
- **Residual Metrics Exclusion**: When $10^6$ count saturated core pixels are masked, `compute_radial_residual_metrics` excludes them from `core_stats` (`core["mu_frac"] = -6.5e-8`, `status = PASS`).
- **100% Core Saturation**: When all pixels within $r < 10$ px are masked, line 727 gracefully returns `{"mu_frac": 0.0, "rms_frac": 0.0, "chi2_nu": 0.0, "n_pix": 0, "status": "PASS"}` without throwing `ZeroDivisionError` or returning `NaN`.
- **Medium Stars**: Saturated core at $r < 3$ px does not perturb the medium star fit in $[3, 25]$ px ($100000.0$ recovered within $3\%$).
- **DQ Bitmask Coercion**: Passing a multi-bit integer DQ mask (e.g., bit 2 `SATURATED`, bit 1024 `JUMP_DET`) coerced to boolean correctly masks contaminated pixels.

#### Vector 2: Extreme Noise, Low SNR, Zero & Negative Flux
- **Extreme Noise**: Star with peak flux 1.0 submerged in Gaussian noise with $\sigma = 20.0$ ($\text{SNR} = 0.05$) converged without numerical divergence, yielding a finite non-negative scale factor ($\alpha \ge 0.0$), finite $\chi_\nu^2$, and finite residuals.
- **Negative Flux**: Over-subtracted background resulting in negative flux across the stamp evaluated to `alpha = 0.0` (floor applied at line 541/571), and fractional residuals remained bounded and finite.
- **Zero Flux**: Stamp with all zeros evaluated to `alpha = 0.0`, `model = 0.0`, `residual = 0.0`, and finite $\chi_\nu^2$.
- **Extreme High Flux**: Star with $10^9$ counts completed without float32 overflow, preserving finite $\chi_\nu^2$ and fractional residuals.

#### Vector 3: NaNs, Infs & Pathological Input Arrays
- **Masked NaNs/Infs**: When non-finite values in `stamp.data` are accompanied by `stamp.mask = ~np.isfinite(data)` (the invariant guaranteed by `process_star_stamps` in `stamps.py`), `fit_star_to_model` recovered true flux within $5\%$ and computed finite $\chi_\nu^2$.
- **Raw NumPy Array Polymorphism**: Calling `fit_star_to_model(raw_array, model)` where `raw_array` has isolated NaNs and $\pm\infty$ correctly initializes `mask = ~np.isfinite(s_data)` (line 451) and masks them.
- **Error Map Sanitization**: Error arrays containing $0.0$, $-10.0$, `NaN`, or $\pm\infty$ were sanitized via line 489: `err_map = np.where(np.isfinite(error) & (error > 0), error, bkg_rms)` and clamped via line 498: `err_map = np.maximum(err_map, 1e-4)`.
- **Dirty Model Canvas**: ePSF model with NaNs in boundary pixels was sanitized via line 481: `crop_epsf = np.nan_to_num(crop_epsf, nan=0.0)`.

#### Vector 4: Off-Center Stars, Boundary Shifts & Dimension Stress
- **Corner Centroids**: Centers at $(0, 0)$, $(nx-1, ny-1)$, $(0, ny-1)$, and $(nx-1, 0)$ executed cleanly without `IndexError`.
- **Outside Stamp Boundaries**: Centroid at $(-50, -50)$ returned valid `RadialMetrics` with `core["n_pix"] = 0` and `status = "PASS"`.
- **Subpixel Alignment Bounds**: For a large shift $(dx = -1.95, dy = 1.95)$, the Powell optimizer respected the boundary constraint $[-2.0, 2.0]$ px and recovered the shift within $0.25$ px.
- **Subpixel Optimization Bypass**: Setting `fit_subpixel_offset=False` bypassed Powell minimization and returned `subpixel_offset = (0.0, 0.0)`.
- **Non-Square Dimensions**: Stamps of shapes $(51, 101)$ and $(121, 61)$ retained exact non-square dimensions across all residual maps.
- **Tiny Cutouts**: Stamp of size $7 \times 7$ (smaller than core radius 10 px) completed without exception, reporting $0$ pixels in transition and wing zones.

#### Vector 5: Pathological Aperture Position Angles
- **Angles Evaluated**: Tested $PA \in [0.0^\circ, 90.0^\circ, 180.0^\circ, 270.0^\circ, 359.9^\circ, 359.9999^\circ, 360.0^\circ, -90.0^\circ, -180.0^\circ, -360.0^\circ, 720.0^\circ, -110.0^\circ, 1080.5^\circ]$.
- **Invariants Verified**:
  - Exactly 12 unique spike ray angles generated in $[0, 360)^\circ$ for all inputs.
  - `is_spike & is_off_spike` is mutually exclusive (`False` everywhere).
  - Core center ($r < 10$ px) is strictly excluded from both spike and off-spike masks.
- **Wrap-Around Verification**: For a spike ray passing across $0^\circ / 360^\circ$ (at $0.5^\circ$), test pixels along $0^\circ$, $+1^\circ$, and $359^\circ$ were all correctly marked `is_spike = True`.

#### Vector 6: Division-by-Zero Guards
- **Zero Model & Background**: When $I_{\text{mod}} = 0$ and $I_{\text{obs}} = 0$, fractional residual $F = 0 / (0 + \epsilon_{\text{reg}}) = 0.0$ evaluated cleanly.
- **All-Masked Stamps**: When 100% of pixels were masked, `compute_radial_residual_metrics` returned `n_pix = 0`, `mu_frac = 0.0`, and `status = "PASS"` across all 4 zones.
- **Empty Wings in Small Stamps**: Small cutouts where $r < 30$ px reported `wings["n_pix"] = 0`, `chi2_nu = 1.0`, and `status = "PASS"`.

#### Vector 7: Multi-Extension FITS Serialization Roundtrip
- **HDU Structure**: Verified exported FITS contains exactly 6 HDUs:
  1. `PRIMARY` (`EXTNAME = RESIDUAL`, float32)
  2. `OBSERVED` (float32)
  3. `MODEL` (float32)
  4. `NORM_RES` (float32)
  5. `FRAC_RES` (float32)
  6. `MASK` (uint8)
- **Header Keywords**: Verified `SRC_ID`, `TIER`, `MAG`, `FLXSCALE`, `DX`, `DY`, `CHI2_NU` are stored and read back with exact scalar values.
- **Data Fidelity**: Verified numerical roundtrip within float32 precision (`np.testing.assert_allclose(rtol=1e-6)`) across all 5 image arrays and exact integer match on `MASK`.
- **File Overwrite Protection**: Verified `overwrite=False` raises `OSError` if the file exists, while `overwrite=True` overwrites cleanly.
- **JSON Serialization**: Verified `ValidationResults.save_summary()` writes valid JSON that roundtrips through `json.load()` with 100% key fidelity.

---

## 2. Logic Chain

1. **Saturated Core Resilience**:
   - In bright stars, saturation is physically expected within $r < 8$ px. By restricting the linear flux scale fitting zone to $[10, 45]$ px, `fit_star_to_model` completely decouples flux scaling from the saturated core (Obs 1.1).
   - In addition, because all residual calculations gate pixels on `valid_mask` and `~mask`, saturated pixels are excluded from the core residual metrics, preventing the flat plateau from skewing $\mu_{\text{frac}}$ (Obs 1.1).

2. **Stability in Extreme Noise Regimes**:
   - The non-negative flux clamp $\alpha = \max(\dots, 0.0)$ prevents inverted PSF subtraction artifacts when stamps are noise-dominated or have negative mean backgrounds (Obs 1.1).
   - The $\epsilon_{\text{reg}}$ regularizer in $F = (I_{\text{obs}} - I_{\text{mod}}) / (I_{\text{mod}} + \epsilon_{\text{reg}})$ guarantees that division by zero never occurs in outer wings or background pixels (Obs 1.1).

3. **Angular and Spatial Robustness**:
   - By implementing angle distance as $\min(|\Delta\theta|, 360^\circ - |\Delta\theta|)$, diffraction spike corridor generation is invariant under angle modularity and continuous across the $0^\circ / 360^\circ$ branch cut (Obs 1.1).
   - Radial metrics and subpixel alignment operate without assumptions of squareness or centering, allowing cutouts near detector boundaries to evaluate safely (Obs 1.1).

4. **Defensive Hardening Observations (Low Severity)**:
   - *Observation A*: If a user manually instantiates a `StellarStamp` with non-finite data (`np.inf`) without masking it in `stamp.mask`, `np.nan_to_num(..., nan=0.0)` in `validation.py:459` converts `+inf` to $3.4 \times 10^{38}$, which passes `np.isfinite(obs_data)` and can overflow $\alpha$ during fit. However, when stamps originate from `process_star_stamps` or when passed as raw `np.ndarray`, `mask` is initialized to `~np.isfinite(data)`, preventing this issue.
   - *Observation B*: In `compute_radial_residual_metrics`, lines 693-694 compute `norm_res = diff / error` across the full grid before masking by `valid`, triggering harmless NumPy `RuntimeWarning` if invalid errors exist outside the analysis region.
   - Neither observation compromises pipeline correctness or causes test failures in standard operation.

---

## 3. Caveats

- **No Caveats**: All 7 adversarial stress testing vectors specified in the mission were directly probed, empirically verified, and passed. No critical defects or unhandled exceptions were found.

---

## 4. Conclusion

The implementation of `src/romanepsf/validation.py` and the validation pipeline is robust, numerically sound, and resistant to edge-case stress:
- Core saturation is properly masked and excluded from flux fitting.
- Low SNR, zero flux, and negative flux do not produce diverging fits or zero-division errors.
- Non-square, off-center, and tiny stamps handle safely without `IndexError`.
- 12-spike corridor masks correctly handle all position angles including branch-cut wrap-around.
- Multi-extension FITS and JSON serialization are lossless and contract-compliant.
- All 47 new adversarial tests pass, and all 893 tests across the repository pass (100% pass rate).

**Verdict**: **APPROVE**

---

## 5. Verification Method

To independently reproduce and verify this assessment:

1. **Run the Adversarial Stress Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_adversarial_validation_stress.py -v
   ```
   *Expected outcome*: 47 passed in ~4.5 seconds.

2. **Run the Full Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/ -q
   ```
   *Expected outcome*: 893 passed in ~66 seconds.

3. **Invalidation Conditions**:
   - Any failure among the 47 adversarial stress tests.
   - Scale factor distortion $> 2\%$ on saturated bright stars.
   - Unhandled exception when passing zero flux, all-masked, or tiny stamps.
   - Missing HDUs or corrupt data in FITS residual files.
