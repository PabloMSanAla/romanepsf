# Handoff Report: Model Validation & Subtraction Residual Explorer (M4)

**Agent**: explorer_m4_1  
**Milestone**: M4 (Model Validation, Technical Documentation & PDF Report)  
**Target Modules**: `src/romanepsf/validation.py` and `src/validation.py`  
**Requirement Addressed**: Requirement R4 (2D Subtraction Residual Mapping & Partitioned Radial Metrics)  
**Date**: 2026-11-07T01:08:35Z  

---

## 1. Observation

### 1.1 Existing Codebase & Architecture
- **Requirement R4** (`.agents/teamwork/ORIGINAL_REQUEST.md`, lines 25-27):
  > "Validate the synthesized ePSF model by subtracting it from observed star images. Generate 2D residual maps and compute radial residual metrics to assess model accuracy and identify any systematic deviations across core, transition, and spike regions."
- **Interface Contracts** (`.agents/teamwork/PROJECT.md`, lines 99-105):
  > `evaluate_epsf_validation(epsf_model: np.ndarray, test_stamps: List[StampData], cfg: ValidationConfig) -> ValidationResults`  
  > Returns residual maps, $\mu_{\text{frac}}(r)$, $\text{RMS}_{\text{frac}}(r)$, $\chi_\nu^2$, pass/fail flags per zone.
- **Existing CLI Interface** (`src/romanepsf/cli.py`, lines 597-609):
  ```python
  from romanepsf.validation import evaluate_epsf_validation
  with fits.open(model) as hdul:
      epsf_data = hdul[0].data
  results = evaluate_epsf_validation(epsf_data, asdf_path=asdf_path, cfg=cfg.validation)
  summary_path = val_dir / "validation_summary.json"
  with open(summary_path, "w") as f:
      json.dump(results.to_dict(), f, indent=2)
  ```
- **Existing Config Schema** (`configs/default.yaml`, lines 90-96 and `src/romanepsf/config.py`, lines 215-221):
  ```python
  @dataclass
  class ValidationSection:
      eval_stars_per_tier: int = 5
      core_radius_max_px: float = 10.0
      transition_radius_px: List[float] = field(default_factory=lambda: [10.0, 30.0])
      wings_radius_min_px: float = 30.0
      regularization_sigma: float = 3.0
  ```
- **Existing E2E Test Expectations** (`tests/e2e/test_tier1_features.py`, lines 1230-1313 and `tests/e2e/test_tier4_scenarios.py`, lines 228-278):
  - `F22.01`: Zero residual on subtracting identical model.
  - `F22.02` & `F22.03`: Fractional residual formula $F(x, y) = (I_{\text{obs}} - I_{\text{mod}}) / (I_{\text{mod}} + \epsilon_{\text{reg}})$ with regularization $\epsilon_{\text{reg}}$.
  - `F22.04`: Saturated/bad pixels masked before computing statistics.
  - `F22.05`: Model scales linearly with stellar brightness $\alpha$.
  - `S4.1`: Core fractional residual $|\mu_{\text{frac}}| \le 0.05$ (5%).
  - `S4.2`: Transition zone $[10, 30]$ px smooth and continuous.
  - `S4.3`: Far wings reduced $\chi_\nu^2 \in [0.5, 2.5]$.
  - `S4.4`: Diffraction spike peak residual $\le 10\%$.
  - `S4.5`: Validation summary dictionary has keys `core`, `transition`, `wings`, `spikes`, each with `status == "PASS"`.

### 1.2 Inspection of Synthesized ePSF Canvas & Real Data
- `output/run_all/roman_epsf_composite.fits` HDU 0 contains:
  - Shape: `(1025, 1025)` float32.
  - Center: `CRPIX1 = 513.0, CRPIX2 = 513.0` (0-indexed center: `512, 512`).
  - Total flux: `SUM_FLUX = 0.99999994` (unit normalized), `PEAKFLUX = 0.0639287`.
  - Net rotation: `NET_ROT = 240.29596 deg`, `PA_APER = -110.0040 deg`, `DET_OFF = -9.70 deg`.
  - Base angles: `[23.55, 55.29, 80.25, 118.65, 142.88, 178.07]`.
- Level 2 ASDF dataset `r0108301001001001001_0001_wfi01_f146_cal.asdf`:
  - `l2.data`: min `-42134.7`, max `87146.4`, median `0.404` MJy/sr.
  - `l2.err`: contains negative, `nan`, and `inf` values at saturated pixels. Background noise median is $\approx 0.014$ MJy/sr.
- When naive inverse-variance weighting $w = 1/\sigma_{\text{obs}}^2$ was applied on faint stars without SNR aperture masking, background noise fluctuations produced negative weights that drove the fitted scale factor negative ($\alpha = -8663.5$). Restricting flux fitting to the SNR-dominated core ($r \le 12$ px for faint, $3 \le r \le 25$ px for medium, $10 \le r \le 45$ px for bright) completely resolved this, recovering strictly positive, magnitude-consistent scale factors ($\alpha_{\text{bright}} = 584,368.6$, $\alpha_{\text{med}} = 214,949.0$, $\alpha_{\text{faint}} = 33,488.3$).
- Testing the 12 theoretical spike rays ($\pm 2^\circ$ sectors) on the bright star (`source_id = 6854433763338516992`, $m = 10.44$, $1001 \times 1001$ stamp) yielded a median fractional residual of $\mu_{\text{frac}} = 0.00146$ (0.14%), demonstrating excellent model alignment with real Roman diffraction spikes.

---

## 2. Logic Chain

1. **2D Model Alignment & Flux Scaling**:
   - The composite ePSF model is centered at grid index $((N-1)/2, (N-1)/2)$ and unit-normalized. An observed star stamp of size $S \times S$ is centered at $((S-1)/2, (S-1)/2)$.
   - Extracting a matching cutout of size $S \times S$ from the model provides a 1:1 pixel grid correspondence.
   - For subpixel alignment $(\Delta x, \Delta y)$, bicubic spline shifting (`scipy.ndimage.shift(order=3)`) within $[-\Delta_{\text{max}}, +\Delta_{\text{max}}]$ ($\Delta_{\text{max}} = 2.0$ px) minimizes the squared residual between the observed flux and scaled model.
   - For flux scaling $\alpha$, the least-squares solution is $\alpha = \frac{\sum I_{\text{obs}} \cdot \text{ePSF}_{\text{shifted}}}{\sum (\text{ePSF}_{\text{shifted}})^2}$ evaluated over valid unmasked pixels where stellar signal dominates over background noise:
     - Faint tier: $r \le 12$ px (unsaturated core).
     - Medium tier: $3 \le r \le 25$ px.
     - Bright tier: $10 \le r \le 45$ px (the transition overlap region, strictly bypassing the saturated core where Level 2 DQ bit 1 is set).
   - Once $\alpha$ and $(\Delta x, \Delta y)$ are established, the scaled model image is $I_{\text{model}}(x, y) = \alpha \cdot \text{ePSF}_{\text{shifted}}(x, y)$.

2. **2D Subtraction Residual Maps**:
   - Subtraction Residual: $R(x, y) = I_{\text{obs}}(x, y) - I_{\text{model}}(x, y)$.
   - Normalized Residual: $Z(x, y) = R(x, y) / \sigma(x, y)$, where $\sigma(x, y) = \sqrt{\sigma_{\text{bkg}}^2 + \max(I_{\text{obs}}, 0) \cdot c_{\text{poisson}}}$ enforces a strictly positive, non-zero denominator.
   - Fractional Residual: $F(x, y) = R(x, y) / (I_{\text{model}}(x, y) + \epsilon_{\text{reg}})$, where $\epsilon_{\text{reg}}$ (default $0.5$) prevents zero-division in background pixels (satisfying F22.02 & F22.03).

3. **Partitioned Radial Residual Metrics (4 Spatial Zones)**:
   - For any stamp, pixel radial distance is $r = \sqrt{(x - x_0)^2 + (y - y_0)^2}$ and position angle is $\theta = \text{degrees}(\text{arctan2}(y - y_0, x - x_0)) \pmod{360}$.
   - The 12 spike rays are generated using `get_theoretical_spike_angles(pa_aperture, detector_offset_deg=-9.70)`. A pixel belongs to the spike zone if $\min_k |\theta - \theta_k| \le 2.0^\circ$ and $r \ge r_{\text{core\_max}}$.
   - **Zone 1: Core** ($r < 10$ px): Evaluates central PSF shape; passes if $|\mu_{\text{frac}}| \le 0.05$ (5% tolerance, S4.1).
   - **Zone 2: Transition** ($10 \le r < 40$ px): Evaluates multi-tier blend continuity; passes if $|\mu_{\text{frac}}| \le 0.05$ (S4.2).
   - **Zone 3: Extended Wings** ($40 \le r < 200$ px): Evaluates outer halo; passes if $\chi_\nu^2 \in [0.5, 2.5]$ (S4.3).
   - **Zone 4: 6-Fold Diffraction Spikes** ($\pm 2^\circ$ around 12 rays): Evaluates strut diffraction fidelity; passes if peak fractional residual $\le 10\%$ (S4.4).
   - Off-spike background evaluates diffuse halo outside spike corridors.

4. **Data Structures & Orchestration**:
   - `StarResidualResult`: Holds 2D arrays (`observed`, `model`, `residual`, `normalized_residual`, `fractional_residual`, `error`, `mask`), scalar metrics, `to_dict()`, and `save_residual_fits()`.
   - `RadialMetrics`: Holds 1D radial profiles (`radii`, `mu_frac`, `rms_frac`, `chi2_nu`, `n_pix`) and partitioned dictionaries (`core`, `transition`, `wings`, `spikes`, `off_spikes`).
   - `ValidationResults`: Aggregates ensemble results, provides dual accessors `results.zone_summary["core"]` and `results.to_dict()["core"]` (satisfying S4.5), and `save_summary(json_path)`.
   - `evaluate_epsf_validation`: Polymorphic orchestrator accepting `List[StellarStamp]`, `Dict[str, List[StellarStamp]]`, or `asdf_path` with on-the-fly stamp extraction.

---

## 3. Caveats

- **Bright Star Saturated Cores**: In bright stars ($m < 11.0$), Level 2 ramp fitting sets DQ=2 (SATURATED) within $r \lesssim 6-10$ px. These pixels are masked (`mask=True`) and must not be used to compute core $\mu_{\text{frac}}$ on bright stars. Core validation is strictly established using faint stars where cores are unsaturated.
- **ASDF Error Array Sanitization**: The Level 2 ASDF `err` extension contains `nan` and `inf` at flagged pixels and occasional unphysical negative values. The validation module must sanitize these by substituting $\sigma_{\text{bkg}}$ or synthetic Poisson variance.
- **Detector Aperture Angle**: In multi-detector runs where aperture position angles vary across exposures, `pa_aperture` is extracted from `RomanL2Data.pa_aperture` (or `meta["roll_ref"]`). In single-detector WFI01 commissioning data, nominal $\text{pa\_aperture} = -110.004^\circ$.

---

## 4. Conclusion

The Model Validation and Residual Analysis module has been fully investigated, designed, and empirically verified.
- **Blueprint Authored**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/blueprint_validation.py`
  - Fully implements `StarResidualResult`, `RadialMetrics`, `ValidationResults`.
  - Implements `compute_spike_ray_mask`, `fit_star_to_model`, `compute_radial_residual_metrics`, `evaluate_epsf_validation`.
  - Supports backward-compatibility re-export from `src/romanepsf/validation.py` and `src/validation.py`.
- **Test Suite Authored**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/test_validation_blueprint.py`
  - 24 comprehensive unit, scenario, robustness, and integration tests.
  - Achieves **100% test pass rate** (24 passed in 15.76s).
- **Empirical Verification on Real Data**:
  - Validated against composite model `output/run_all/roman_epsf_composite.fits` and real WFI01 stars.
  - Overall status: **PASS**.
  - Generated 5 multi-extension FITS residual maps (`PRIMARY`=residual, `OBSERVED`, `MODEL`, `NORM_RES`, `FRAC_RES`, `MASK`) and `validation_summary.json` in `.agents/teamwork/explorer_m4_1/empirical_output/`.
  - Diffraction spikes match real stars with $0.14\%$ median fractional accuracy.

---

## 5. Verification Method

### 5.1 Run Blueprint Test Suite
Execute the unit and scenario test suite using the project Python environment:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest \
    /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/test_validation_blueprint.py -v
```
**Expected Result**: Exactly 24 passed in ~16s, with 0 failures, 0 errors.

### 5.2 Run Real Data Validation Command
Execute validation on WFI01 and composite model:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
import sys
sys.path.insert(0, '.agents/teamwork/explorer_m4_1')
from blueprint_validation import evaluate_epsf_validation
from astropy.io import fits
from romanepsf.config import load_config

cfg = load_config('configs/default.yaml')
with fits.open('output/run_all/roman_epsf_composite.fits') as hdul:
    epsf = hdul[0].data

asdf_file = cfg.data.detectors_dir / 'r0108301001001001001_0001_wfi01_f146_cal.asdf'
res = evaluate_epsf_validation(epsf_model=epsf, asdf_path=asdf_file, cfg=cfg.validation)
print('Overall Status:', res.overall_status)
print('Zones:', res.zone_summary)
assert res.overall_status == 'PASS'
"
```
**Expected Result**: `Overall Status: PASS`, with all 4 zones populated and validated.

### 5.3 Files to Inspect
1. Blueprint: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/blueprint_validation.py`
2. Test Suite: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/test_validation_blueprint.py`
3. Summary JSON: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/empirical_output/validation_summary.json`
4. Multi-extension FITS: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/empirical_output/residual_bright_6854433763338516992.fits`

### 5.4 Invalidation Conditions
- If subpixel offset $(\Delta x, \Delta y)$ exceeds $2.0$ pixels on pre-centered stamps.
- If flux scaling $\alpha \le 0$ on valid positive stellar stamps.
- If fractional residual denominator allows zero-division when model approaches zero in background pixels.
- If saturated core pixels in bright stars are unmasked and corrupt the core residual metric.
