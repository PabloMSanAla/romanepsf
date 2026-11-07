# Dispatch: Spec Miner Survey 3 (Mathematical & Pipeline Specifications)

## Objective
Extract and formalize mathematical, algorithmic, and engineering specifications for the Roman ePSF measurement pipeline based on `ORIGINAL_REQUEST.md`, Roman optical geometry, 6-fold pupil geometry angle priors, multi-tier modeling, high-aspect-ratio filtering, residual metrics, and PDF reporting requirements.

## Reference Files
- User Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- Local Codebase & Docs: `/Users/pmsanch1/code/ROSALIA`, `/Users/pmsanch1/code/romanepsf`
- Python Environment: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`

## Output Requirements
Produce a comprehensive handoff report at `/Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md`.


## 2026-11-06T08:54:35Z
You are Spec Miner 3 (Pipeline Specification Miner).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/
Your parent orchestrator is: e80d314a-b5a0-43fb-be2e-ceabc982347e

MANDATORY FIRST STEP: Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md.

YOUR MISSION:
Mine and formulate detailed mathematical, algorithmic, and engineering specifications for the Roman extended PSF (ePSF) measurement pipeline based on ORIGINAL_REQUEST.md, Roman optical geometry, 6-fold pupil geometry angle priors, multi-tier modeling, high-aspect-ratio filtering, residual metrics, and PDF reporting requirements.

Investigate & Formalize:
1. Pupil Geometry & Diffraction Spikes:
   - Base angles: [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] degrees.
   - What is the relationship between these base angles and telescope aperture position angle (V3PA / PA_APER)? How are the predicted spike angles computed in detector pixel coordinates for each detector?
   - How does high-aspect-ratio morphological filtering work on Moffat residuals? (e.g., directional line structuring elements or Radon transform or elongated Gaussian/top-hat filters along predicted spike directions). How to ensure diffraction spikes are protected from contaminant masking while neighbor stars are masked?
2. Multi-tier Modeling & Non-circular 2D Preservation:
   - Faint stars: unsaturated core.
   - Medium stars: transition overlap region.
   - Bright stars: extended wings & diffraction spikes.
   - Strict rule: NO radial averaging or circularizing the 2D PSF.
   - Strict rule: 1D radial profiles (via `src/profile.py`) are strictly reserved for finding saturation boundaries and calculating cross-tier flux scaling factors.
   - How should cross-tier normalization and stitching produce a smooth, calibrated 2D composite canvas (1024x1024 to 2048x2048)?
3. Single-Detector (`wfi01`) to Full 18-Detector Execution (`wfi01`..`wfi18`):
   - Memory efficiency: how to process large arrays (4088x4088 per detector, 18 detectors) without running out of memory.
   - Parallelization strategy (multiprocessing across detectors or star stamps).
4. Validation & Residual Analysis:
   - Subtraction of ePSF from observed stars.
   - 2D residual maps and radial residual metrics (fractional residuals, RMS residuals vs radius in core, transition, wing, and spike regions).
5. YAML Configuration & CLI specifications:
   - What configuration sections and keys are required?
   - CLI commands, options, outputs.
6. Documentation & Publication-ready PDF Report:
   - Structure of technical docs and PDF report.
   - Exact figures needed: star selection, spike protection masks, overlap radial profiles, composite 2D ePSF, subtraction residuals, performance metrics.

Deliverables:
- Keep /Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/progress.md updated.
- Write your final structured handoff report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md with full mathematical definitions, pseudocode algorithms, and requirement matrices.
- When done, call send_message to notify parent e80d314a-b5a0-43fb-be2e-ceabc982347e that your handoff is ready.
