# BRIEFING — 2026-11-07T01:08:00Z

## Mission
Investigate and design the Model Validation and Residual Analysis module (`src/romanepsf/validation.py` and `src/validation.py`) to satisfy Requirement R4 (2D subtraction residual mapping, partitioned radial residual metrics across Core, Transition, Wings, and 6-fold Spikes, dataclasses and evaluation functions, empirical prototyping against real data).

## 🔒 My Identity
- Archetype: explorer
- Roles: Model Validation & Subtraction Residual Explorer
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: M4 (Model Validation, Technical Documentation & PDF Report)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement directly in `src/` (create blueprints, prototypes, and tests in agent directory)
- Python environment: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python
- Local ROSALIA codebase: /Users/pmsanch1/code/ROSALIA
- Output progress in `progress.md` and final handoff in `handoff.md`
- Send reports and updates back to parent using `send_message`

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: 2026-11-07T01:08:00Z

## Investigation State
- **Explored paths**:
  - `ORIGINAL_REQUEST.md`, `PROJECT.md`, `configs/default.yaml`
  - `src/romanepsf/config.py`, `src/romanepsf/stamps.py`, `src/romanepsf/pipeline.py`, `src/romanepsf/cli.py`, `src/romanepsf/masking.py`, `src/romanepsf/loader.py`
  - `tests/e2e/test_tier1_features.py` (F22, F23), `tests/e2e/test_tier4_scenarios.py` (Scenario 4)
  - `output/run_all/roman_epsf_composite.fits` and Level 2 ASDF data for WFI01
- **Key findings**:
  - Pure-inverse-variance weighting $1/\sigma_{\text{obs}}^2$ on noisy backgrounds produces strong negative flux bias on faint stars; robust fitting must restrict fitting to SNR-dominated annular apertures (faint: $r \le 12$ px, medium: $3 \le r \le 25$ px, bright: $10 \le r \le 45$ px) or model-weighted least squares.
  - Saturated cores in bright stars are masked in Level 2 DQ and must be strictly excluded from the flux scaling and core residual metrics.
  - 12 theoretical spike angles generated via `get_theoretical_spike_angles(pa_offset_deg, detector_offset_deg=-9.70)` allow direct angular sector filtering ($\pm 2^\circ$). The composite ePSF matches real bright star spikes with median fractional residual of 0.14%!
  - Level 2 ASDF `err` array contains non-finite (`inf`, `nan`) and negative values at flagged pixels; a sanitized error map must enforce $\sigma(x, y) = \max(\sigma_{\text{bkg}}, 10^{-4})$ and incorporate Poisson variance.
  - Complete blueprint authored at `blueprint_validation.py` and validated by 24 passing unit/stress tests in `test_validation_blueprint.py` (100% pass rate in 15.76s).
  - Empirical execution on real WFI01 data yielded `PASS` across all zones with multi-extension residual FITS export and JSON summary.
- **Unexplored areas**: None. All R4 design requirements fully prototyped and verified.

## Key Decisions Made
- Designed 3 dataclasses: `StarResidualResult`, `RadialMetrics`, `ValidationResults`.
- Designed 4 core functions: `compute_spike_ray_mask`, `fit_star_to_model`, `compute_radial_residual_metrics`, `evaluate_epsf_validation`.
- Designed `evaluate_epsf_validation` with polymorphic inputs supporting lists of stamps, dicts of stamps, or on-the-fly extraction from ASDF images.
- Designed dual-access zone dictionary structure supporting both `results.zone_summary["core"]` and `results.to_dict()["core"]` for maximum test compatibility.

## Artifact Index
- `DISPATCH.md` — Ingested dispatch message
- `progress.md` — Liveness heartbeat and milestone tracking
- `blueprint_validation.py` — Complete blueprint implementation for `romanepsf.validation`
- `test_validation_blueprint.py` — 24 comprehensive unit and stress tests (100% pass)
- `empirical_output/` — Real Level 2 validation outputs (5 multi-extension FITS + JSON summary)
- `handoff.md` — Final 5-component handoff report
