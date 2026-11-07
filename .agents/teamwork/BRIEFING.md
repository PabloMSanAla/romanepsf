# BRIEFING — 2026-11-06T08:52:00Z

## Mission
Orchestrate and monitor the Roman extended PSF pipeline development across all 18 WFI detectors, validation, and PDF report delivery.

## 🔒 My Identity
- Archetype: sentinel
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/
- Orchestrator: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Victory Auditor: cffd5447-20d9-4e36-b1ec-c628f84ee010

## 🔒 Key Constraints
- No technical decisions — relay only
- Victory Audit is MANDATORY before reporting completion
- Route: General -> teamwork_orchestrator
- Model directly captures full 2D structure including 2D spikes; radial averaging or circularizing 2D PSF is prohibited.
- 1D radial profiles are strictly reserved for saturation boundaries & cross-tier scaling.
- Spike angles: theoretical 6-fold pupil geometry priors [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] adjusted for aperture PA + morphological filtering on Moffat residuals.
- Single detector (wfi01) first, then all 18 detectors (wfi01-wfi18).
- Canvas size 1024x1024 to 2048x2048.
- Deliverables: modular codebase under src/, programmatic validation, technical documentation, PDF report with figures.
- Use Python environment /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python.
- Working directory: /Users/pmsanch1/code/romanepsf.

## User Context
- **Last user request**: Approved task prompt received.
- **Pending clarifications**: none
- **Delivered results**: Task interview concluded; execution launched.

## Project Status
- **Phase**: complete
- **Route Rationale**: Multi-part software engineering, scientific pipeline implementation, data processing across 18 detectors, CLI, documentation, validation, and PDF report generation.

## Victory Audit Status
- **Triggered**: yes
- **Verdict**: VICTORY CONFIRMED
- **Retry count**: 0

## Artifact Index
- .agents/teamwork/ORIGINAL_REQUEST.md — Authoritative user task prompt
- output/run_all/composite_epsf_wfi_1025.fits — Synthesized 18-detector composite 2D extended PSF model
- output/single_wfi01/epsf_wfi01_1025.fits — Single detector (WFI01) ePSF model
- output/validation/ — Subtraction residual maps and quantitative metrics
- output/report.pdf — Publication-ready 8-page PDF report with complete figures
- docs/technical_documentation.md — Full technical documentation markdown
- .agents/teamwork/victory_auditor/handoff.md — Independent Victory Audit report (VICTORY CONFIRMED)

