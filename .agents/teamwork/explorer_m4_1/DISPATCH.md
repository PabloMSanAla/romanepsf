## 2026-11-07T00:58:35Z
You are explorer_m4_1 (role: Model Validation & Subtraction Residual Explorer).
Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/
You must write your progress to /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/progress.md and your final report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/handoff.md.

MANDATORY INSTRUCTION:
Read the authoritative user request at /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting your investigation.

Python Environment:
Use /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python for all execution and testing.
Local ROSALIA codebase is at /Users/pmsanch1/code/ROSALIA.

Mission:
Investigate and design the Model Validation and Residual Analysis module (`src/romanepsf/validation.py` and backward-compatible `src/validation.py`) to satisfy Requirement R4:
"Validate the synthesized ePSF model by subtracting it from observed star images. Generate 2D residual maps and compute radial residual metrics to assess model accuracy and identify any systematic deviations across core, transition, and spike regions."

Key Investigation & Design Tasks:
1. 2D Subtraction Residual Mapping:
   - Given an observed star stamp $I_{\text{obs}}(x, y)$ (with centroid $(x_0, y_0)$, local background, and error array $\sigma(x, y)$), align and scale the composite ePSF model:
     $I_{\text{model}}(x, y) = \alpha \cdot \text{ePSF}(x - \Delta x, y - \Delta y)$
     where $\alpha$ is the flux scale factor (from aperture/model flux fitting) and $(\Delta x, \Delta y)$ is subpixel centroid alignment.
   - Calculate 2D residual map: $R(x, y) = I_{\text{obs}}(x, y) - I_{\text{model}}(x, y)$
   - Calculate 2D normalized residual map: $Z(x, y) = R(x, y) / \sigma(x, y)$
   - Calculate fractional residual map: $F(x, y) = R(x, y) / I_{\text{model}}(x, y)$ (for $I_{\text{model}} > 0$).
2. Partitioned Radial Residual Metrics:
   - Measure metrics as a function of radial distance $r = \sqrt{(x - x_0)^2 + (y - y_0)^2}$:
     * Mean fractional residual: $\mu_{\text{frac}}(r) = \text{mean}((I_{\text{obs}} - I_{\text{model}}) / I_{\text{model}})$
     * RMS fractional residual: $\text{RMS}_{\text{frac}}(r) = \sqrt{\text{mean}(((I_{\text{obs}} - I_{\text{model}}) / I_{\text{model}})^2)}$
     * Reduced chi-squared: $\chi_\nu^2 = \frac{1}{N_{\text{pix}} - \nu} \sum \frac{(I_{\text{obs}} - I_{\text{model}})^2}{\sigma^2}$
   - Partition into 4 spatial zones:
     1. Core zone ($r < 10$ px)
     2. Transition overlap zone ($10 \le r < 40$ px)
     3. Extended wing zone ($40 \le r < 200$ px)
     4. 6-Fold Diffraction Spike zones (angular sectors of $\pm 2^\circ$ around the 12 theoretical spike rays in detector frame) vs. off-spike background.
3. Data Structures & Functions:
   - Define dataclasses: `StarResidualResult`, `RadialMetrics`, `ValidationResults`.
   - Functions:
     * `fit_star_to_model(stamp: StellarStamp, epsf_model: np.ndarray) -> StarResidualResult`
     * `compute_radial_residual_metrics(observed: np.ndarray, model: np.ndarray, error: np.ndarray, center: Tuple[float, float], pa_aperture: float) -> RadialMetrics`
     * `evaluate_epsf_validation(epsf_model: np.ndarray, test_stamps: List[StellarStamp], cfg: Config) -> ValidationResults`
4. Empirical Prototyping:
   - Prototype and test `validation.py` against actual stars from `output/run_all/roman_epsf_composite.fits` and real Level 2 ASDF stars from WFI01.
   - Author a complete blueprint `blueprint_validation.py` and draft unit tests `test_validation_blueprint.py`.

Deliver your findings, blueprints, and verification method in `handoff.md`.
