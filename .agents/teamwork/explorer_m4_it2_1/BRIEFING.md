# BRIEFING — 2026-11-07T01:52:45Z

## Mission
Design an authentic, non-facade remediation blueprint for Page 6 (Subtraction Residuals) in `src/romanepsf/report.py`.

## 🔒 My Identity
- Archetype: explorer
- Roles: explorer, synthesizer
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_1/
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: m4_it2

## 🔒 Key Constraints
- Read-only investigation — do NOT implement directly into `src/` (write blueprint in working directory)
- Must eliminate all `np.random` calls, synthetic noise generation, and hardcoded `tiers_info` numbers from `plot_page_subtraction_residuals`
- Support loading real multi-extension residual FITS files or validation_results.star_results
- Extract and display OBSERVED, MODEL, RESIDUAL, NORM_RES, FRAC_RES, and header cards: MAG, FLXSCALE, DX, DY, CHI2_NU
- Clean deterministic fallback when residual FITS files do not exist
- Deliver tested blueprint script in working directory and write handoff report

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `src/romanepsf/report.py` (lines 735-807 facade implementation, lines 104-178 ReportDataBundle)
  - `src/romanepsf/validation.py` (lines 133-256 StarResidualResult, save_residual_fits)
  - `output/validation/residual_bright_*.fits`, `residual_medium_*.fits`, `residual_faint_*.fits`
  - `output/validation/validation_summary.json`
  - `tests/unit/test_report.py`
- **Key findings**:
  - Authentic multi-extension residual FITS files exist on disk with 6 HDUs: Primary (RESIDUAL), OBSERVED, MODEL, NORM_RES, FRAC_RES, MASK.
  - Header cards contain real fitted parameters: MAG, FLXSCALE, DX, DY, CHI2_NU.
  - Prior implementation in `plot_page_subtraction_residuals` used `np.random.normal` to generate artificial noise over an ePSF cutout with hardcoded chi2 metrics (1.04, 0.98, 1.02).
  - Designed a 5-panel layout (Observed, Model, Residual, Norm Res, Frac Res) with fitted parameters annotation and dual colorbars (Z and F).
  - Built deterministic mock fallback for isolated environments without `np.random`, explicitly labeled as mock.
- **Unexplored areas**: none within the scope of Page 6 remediation.

## Key Decisions Made
- Implemented `load_tier_residual_data` with a 3-tier precedence: (1) in-memory `ValidationResults.star_results`, (2) real FITS files on disk, (3) deterministic mock fallback.
- Structured Page 6 with 5 columns across 3 tiers (total 15 image axes + 2 colorbar axes + 3 header/footer/desc axes = 20 axes).
- Center crop zooming with default sizes (101 bright, 61 medium, 41 faint) to resolve core, transition, and diffraction spike features.
- Generated `blueprint_page6_residuals.py` and unified patch `proposed_page6_remediation.patch` verified with `git apply --check`.

## Artifact Index
- `blueprint_page6_residuals.py` — Self-contained runnable implementation and test suite.
- `proposed_page6_remediation.patch` — Unified git diff ready for application to `src/romanepsf/report.py`.
- `test_blueprint_real.png` — Visual render of Page 6 using authentic Level 2 validation residuals.
- `test_blueprint_mock.png` — Visual render of Page 6 using deterministic mock fallback.
- `handoff.md` — 5-component handoff report.
