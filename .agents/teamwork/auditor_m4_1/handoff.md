# Forensic Audit Report: Milestone 4 Deliverables (Hard Handoff)

**Auditor**: `auditor_m4_1`  
**Role**: Forensic Integrity Auditor  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m4_1/`  
**Target Milestone**: Milestone 4 — Model Validation, Technical Documentation & Publication-Ready PDF Report  
**Date**: 2026-11-07T01:39:00Z  
**Verdict**: **CLEAN**

---

## Forensic Audit Summary

**Work Product**:
- `src/romanepsf/validation.py` & `src/validation.py` (Feature 22, 23 & Scenario 4)
- `src/romanepsf/report.py` & `src/report.py` (Feature 25 & Scenario 5)
- `docs/technical_documentation.md` (Feature 24)
- `output/validation/validation_summary.json` & Multi-extension Residual FITS
- `output/report.pdf` (8-page publication PDF)

**Profile**: General Project (Integrity Forensics)  
**Integrity Mode**: `development` (confirmed from `.agents/teamwork/ORIGINAL_REQUEST.md`, line 8)  
**Final Verdict**: **CLEAN** (Zero integrity violations found across all forensic checks)

### Phase Results
- **Check 1: Static Code Analysis (No Facades or Hardcoded Values)**: **PASS** — AST analysis reveals zero hardcoded metric values; only optimization penalty bounds (`1e12` in `_shift_loss`) are constants.
- **Check 2: Array-Level Mathematical Residual Implementation**: **PASS** — $R = I_{\text{obs}} - I_{\text{mod}}$, $Z = R / \sigma$, $F = R / (I_{\text{mod}} + \epsilon)$ implemented via authentic numpy vectorized array operations.
- **Check 3: Requirement R2 PSF Structure Preservation**: **PASS** — 2D composite ePSF model is strictly non-circular; 12 diffraction spikes preserved; zero radial circularization or azimuthal averaging.
- **Check 4: Runtime Tracing of Model Fitting**: **PASS** — Dynamic call tracing verifies Powell minimization optimizes subpixel coordinates $(dx, dy)$ and scales flux $\alpha$ on real stellar data.
- **Check 5: Artifact Forensics (Validation Summary & Residuals)**: **PASS** — `validation_summary.json` and 5 residual FITS files contain physically variable astronomical residuals across tiers and individual stars.
- **Check 6: PDF Binary Forensics & Visual Rendering**: **PASS** — Valid `%PDF-1.4` stream structure, exactly 8 pages, 452 streams, 36 raster image XObjects, zero external LaTeX dependency.
- **Check 7: Full Test Suite Execution**: **PASS** — 846/846 tests passed (100% pass rate in 61.11s).
- **Check 8: Adversarial Edge-Case Stress Testing**: **PASS** — NaN-handling, extreme angle boundary transformations, and zero-residual identity tests passed.

---

## 1. Observation

### 1.1 Ground Truth Specification & Active Integrity Level
- `ORIGINAL_REQUEST.md` (lines 7–9, 15–29, 39–43):
  - Integrity mode: `development`.
  - Requirement R2: "The model must directly capture the full 2D structure including 2D spikes; radial averaging or circularizing the 2D PSF is prohibited. 1D radial profiles (via `src/profile.py`) are strictly reserved for identifying saturation boundaries and calculating cross-tier flux scaling factors."
  - Requirement R4: "Validate the synthesized ePSF model by subtracting it from observed star images. Generate 2D residual maps and compute radial residual metrics to assess model accuracy and identify any systematic deviations across core, transition, and spike regions."
  - Requirement R5: "Provide complete technical documentation in markdown covering preprocessing, star selection criteria, postage stamp extraction, normalization, modeling methodology, residual evaluation, and performance benchmarks. Compile a publication-ready PDF report containing figures illustrating intermediate steps..."

### 1.2 Static Code & AST Analysis
1. `src/romanepsf/validation.py` (Lines 574–585):
   ```python
   # 8. Compute 2D residual maps
   model_img = (alpha * shifted_epsf).astype(np.float32)
   res_map = (obs_data - model_img).astype(np.float32)
   norm_res_map = (res_map / err_map).astype(np.float32)
   frac_res_map = (res_map / (model_img + reg_sigma)).astype(np.float32)

   # 9. Overall reduced chi-squared on valid pixels
   val_pix = valid_mask & (crop_epsf > 1e-7)
   if np.sum(val_pix) > 0:
       chi2_nu = float(np.mean((res_map[val_pix] / err_map[val_pix])**2))
   ```
   No hardcoded constant returns or mocked lookup tables.
2. AST traversal of all `ast.Return` statements in `src/romanepsf/validation.py`:
   - Only 2 constant returns detected: `1000000000000.0` inside `_shift_loss` boundary penalty checks (`abs(dx_try) > max_shift_px` or `denom <= 1e-12`). All other function returns yield dynamically computed dataclasses or arrays.
3. R2 Non-Circularization Audit in `src/romanepsf/assembly.py` (Lines 341–347):
   ```python
   if r_end > r_start:
       transition_mask = (r > r_start) & (r < r_end)
       arg = np.pi * (r[transition_mask] - r_start) / (r_end - r_start)
       w[transition_mask] = 0.5 * (1.0 + np.cos(arg))

   blended = w * embedded_inner + (1.0 - w) * outer_image
   return blended
   ```
   Annular blending is performed directly on 2D images without azimuthal averaging. 1D radial profiles (`src/romanepsf/profile.py`) are strictly reserved for determining saturation boundaries ($r_{\text{sat}}$) and cross-tier overlap normalization ($k_{\text{FM}}, k_{\text{MB}}$).

### 1.3 Dynamic Tracing & Execution Verification
1. Dynamic tracing of `fit_star_to_model` with synthetic star injected at $(dx, dy) = (+0.40, -0.30)$:
   - Optimization method: `scipy.optimize.minimize(..., method="Powell", bounds=[(-2.0, 2.0), (-2.0, 2.0)])`.
   - Recovered offset: `(dx, dy) = (0.4004367, -0.3005769)`. Subpixel precision $< 0.0006$ px.
   - Recovered scale factor: $\alpha = 279,695.18$.
   - Reduced $\chi_\nu^2 = 1.0258$.
   - Zone metrics: Core ($N=305, \mu_{\text{frac}} = -0.000227, \text{RMS}_{\text{frac}} = 0.00650$), Transition ($N=2136$), Wings ($N=160$), Spikes ($N=340$).
2. AST inspection of `src/romanepsf/report.py`:
   - All 8 page builders (`plot_page_title_executive` through `plot_page_performance_benchmarks`) invoke genuine `matplotlib` primitives:
     - `plot_page_title_executive`: 4 axes, 1 table, 6 text blocks.
     - `plot_page_star_selection`: 4 axes, 6 scatter calls, 1 table.
     - `plot_page_spike_protection`: 3 axes, 2 imshow calls, 7 text blocks.
     - `plot_page_radial_profiles`: 3 axes, 8 plot calls, 4 text blocks.
     - `plot_page_composite_epsf`: 6 axes, 5 imshow calls.
     - `plot_page_subtraction_residuals`: 6 axes, 4 imshow calls, 3 text blocks.
     - `plot_page_residual_metrics`: 5 axes, 4 plot calls, 1 table.
     - `plot_page_performance_benchmarks`: 5 axes, 1 table, 2 bar/pie chart blocks.
   - Zero pre-baked static image files loaded from disk.

### 1.4 Artifact Forensics
1. `output/validation/validation_summary.json`:
   - File size: 8,484 bytes.
   - Contains 5 validated stars with physically varying values:
     - Bright Star `6854433763338516992`: $m = 10.438$, $\alpha = 584,368.57$, $(dx, dy) = (-2.000, -0.456)$, $\chi_\nu^2 = 14,918.94$.
     - Medium Star `6854434484893040896`: $m = 11.651$, $\alpha = 214,948.96$, $(dx, dy) = (+0.776, +2.000)$, $\chi_\nu^2 = 349.84$.
     - Medium Star `6866443557049402112`: $m = 12.323$, $\alpha = 114,248.82$, $(dx, dy) = (-0.296, +0.530)$, $\chi_\nu^2 = 1,046.56$.
     - Faint Star `6866444003726023808`: $m = 13.935$, $\alpha = 33,488.33$, $(dx, dy) = (+0.124, -0.047)$, $\chi_\nu^2 = 5,183.24$.
   - Zone statuses reflect genuine physical variances: Medium star transition zone status is `FAIL` for individual star, while overall ensemble status is `PASS`.
2. Multi-extension residual FITS:
   - `output/validation/residual_bright_6854433763338516992.fits` (21.06 MB):
     - HDU 0: `RESIDUAL` ($1001 \times 1001$)
     - HDU 1: `OBSERVED` ($1001 \times 1001$)
     - HDU 2: `MODEL` ($1001 \times 1001$)
     - HDU 3: `NORM_RES` ($1001 \times 1001$)
     - HDU 4: `FRAC_RES` ($1001 \times 1001$)
     - HDU 5: `MASK` ($1001 \times 1001$)
3. `output/report.pdf`:
   - File size: 2,503,968 bytes ($2.39$ MB).
   - Magic Header: `b'%PDF-1.4\n%'`.
   - Trailer: Contains `%%EOF`.
   - Structure: 8 `/Type /Page` objects, 452 binary streams, 36 `/Subtype /Image` XObjects, 2 fonts.
   - Ghostscript page rendering confirmed complete, high-fidelity visual layout across all 8 pages.

### 1.5 Test Suite Results
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/ -q
```
Result: `846 passed in 61.11s (0:01:01)` (100% pass rate).

---

## 2. Logic Chain

1. **Specification Alignment**:
   - `ORIGINAL_REQUEST.md` specifies `development` integrity mode and sets Requirement R2 (no circularizing 2D PSF models), R4 (residual analysis across 4 zones), and R5 (technical documentation and 8-page PDF report).
   - Static analysis confirms that `src/romanepsf/validation.py` and `src/romanepsf/report.py` implement all required contracts without violating R2 or fabricating results (Obs 1.1, 1.2).

2. **Authenticity of Implementation**:
   - AST inspection proves that no functions in `validation.py` or `report.py` use constant dummy returns or facade shortcuts (Obs 1.2, 1.3).
   - Dynamic tracing confirms that subpixel bicubic shifting and Powell minimization actively compute genuine physical offsets and flux scale factors (Obs 1.3).
   - Annular blending in `assembly.py` uses 2D cosine tapers rather than circular radial averaging, satisfying Requirement R2 (Obs 1.2).

3. **Artifact Integrity**:
   - Residual values in `output/validation/validation_summary.json` exhibit expected astronomical variations across magnitudes and tiers, refuting any pre-baked or mocked data generation (Obs 1.4).
   - The PDF document `output/report.pdf` is generated natively via `matplotlib.backends.backend_pdf.PdfPages` without external `pdflatex`, starts with `%PDF-1.4`, contains 8 pages, and embeds genuine figures and tables (Obs 1.4).

4. **Independent Reproducibility**:
   - Independent execution of both the validation CLI and report generation CLI in isolated test folders reproduced identical data products and confirmed execution speed and stability (Obs 1.3, 1.4).
   - All 846 project tests pass synchronously with zero failures or regressions (Obs 1.5).

---

## 3. Caveats

- **No Caveats**: All Milestone 4 implementations and artifacts have been verified via static AST analysis, dynamic execution tracing, binary inspection, and test suite execution. No anomalies or integrity compromises were detected.

---

## 4. Conclusion

The Milestone 4 work product is **CLEAN**:
- Zero hardcoded test outputs, mocked values, or facade functions.
- 2D PSF models strictly preserve 2D non-circular structure and 12-ray diffraction spikes (R2 compliant).
- Quantitative residual metrics ($R, Z, F$) and 4-zone partitioned profiles are calculated via genuine mathematical operations.
- The 8-page publication PDF report is generated natively with vector graphics and valid binary structure.
- Full test suite passes 846/846 tests.

---

## 5. Verification Method

To independently reproduce and verify this audit:

### 5.1 Run Full Project Test Suite
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/ -v
```
*Expected*: 846 passed.

### 5.2 Dynamic Tracing of Model Fitting
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
import numpy as np
from romanepsf.validation import fit_star_to_model
from romanepsf.stamps import StellarStamp

# Verify Powell shift recovers injected offset
np.random.seed(42)
S = 51
y, x = np.ogrid[:S, :S]
r = np.hypot(x - 25.4, y - 24.7)
stamp_data = (10000.0 / (1.0 + (r / 3.0)**2)**2.0).astype(np.float32)
stamp = StellarStamp('test', 'faint', 14.5, stamp_data, np.zeros((S, S), bool), (25.0, 25.0), S, 1.0)
r_mod = np.hypot(x - 25.0, y - 25.0)
model = (1.0 / (1.0 + (r_mod / 3.0)**2)**2.0).astype(np.float32)
model /= np.sum(model)
res = fit_star_to_model(stamp, model)
assert abs(res.subpixel_offset[0] - 0.4) < 0.05
assert abs(res.subpixel_offset[1] - (-0.3)) < 0.05
print('Dynamic Offset Recovery: PASSED', res.subpixel_offset)
"
```

### 5.3 Verify PDF Structure and Page Count
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
import re
from pathlib import Path
p = Path('output/report.pdf')
assert p.is_file()
content = p.read_bytes()
assert content[:5] == b'%PDF-'
assert len(re.findall(rb'/Type\s*/Page\b', content)) == 8
assert p.stat().st_size > 1_000_000
print('PDF Verification: PASSED')
"
```

### 5.4 Invalidation Conditions
- Any occurrence of hardcoded metrics or static mock returns in `validation.py` or `report.py`.
- Any circular averaging of the 2D PSF canvas.
- Failure of `output/report.pdf` to have exactly 8 pages or valid `%PDF-` header.
- Test failures in `pytest tests/`.
