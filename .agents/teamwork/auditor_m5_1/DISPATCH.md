# DISPATCH: auditor_m5_1

## Role
Milestone 5 Forensic Integrity Auditor (Final Project Audit)

## Working Directory
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m5_1`

## Inputs
- Authoritative User Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- Target Codebase: `src/` and `src/romanepsf/`
- Output Deliverables: `output/report.pdf`, `output/run_all/`, `docs/technical_documentation.md`

## Instructions
1. Perform comprehensive static analysis across all Python source files under `src/`:
   - Verify zero RNG calls or imports (`random`, `numpy.random`, `torch.rand`, etc.).
   - Verify no dummy, facade, or hardcoded return implementations.
2. Perform runtime call interception:
   - Poison monkeypatching on `random`, `numpy.random`, and `torch` RNG.
   - Run full pipeline report generation and model validation. Verify zero calls intercepted.
3. Verify R2 compliance:
   - Verify that 2D composite ePSF model is strictly non-circular and directly captures the 6-fold pupil diffraction geometry and 12 diffraction spikes.
   - Verify 1D radial profiles (`src/romanepsf/profile.py` and `src/profile.py`) are strictly reserved for saturation boundaries and cross-tier scaling factors, and are never used to circularize or radially average the 2D PSF canvas.
4. Verify genuine data flow:
   - Multi-extension FITS data loaded genuinely from `output/run_all/composite_epsf_wfi_1025.fits`.
   - Star residual maps load genuine Level 2 observed star cutouts and subtraction residuals.
   - Annular metrics compute empirical residuals without fabricated curves.
   - Performance benchmarks ingest real runtime metrics from HDU 3 (`DETECTOR_SUMMARY`).
5. Formulate your final verdict: **CLEAN** or **INTEGRITY VIOLATION**.
6. Write your detailed forensic audit report to `handoff.md` and report back via `send_message`.

## 2026-11-07T06:20:01Z
You are auditor_m5_1, a teamwork_auditor responsible for the Final Forensic Integrity Audit of the Roman ePSF Pipeline project for Milestone 5.

Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m5_1
Project root: /Users/pmsanch1/code/romanepsf
Python executable: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python

MANDATORY FIRST STEP:
Read the authoritative user request at:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md
and read your dispatch instructions at:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m5_1/DISPATCH.md
and the worker handoff at:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m5_tier5_remediation/handoff.md

Tasks:
1. Static analysis across all files under src/:
   - Zero RNG calls or imports (random, numpy.random, torch.rand, etc.).
   - Zero dummy, facade, or hardcoded return implementations.
2. Runtime call interception:
   - Poison monkeypatching on random, numpy.random, default_rng, and torch.
   - Run full pipeline report generation and model validation. Verify zero calls intercepted.
3. Verify R2 compliance:
   - Verify that 2D composite ePSF model is strictly non-circular and directly captures the 6-fold pupil diffraction geometry and 12 diffraction spikes.
   - Verify 1D radial profiles are strictly reserved for finding saturation boundaries and cross-tier scaling factors, and are never used to circularize or radially average the 2D PSF canvas.
4. Verify authentic data flow:
   - Multi-extension FITS data loaded genuinely from output/run_all/composite_epsf_wfi_1025.fits.
   - Star residual maps load genuine Level 2 observed star cutouts and subtraction residuals.
   - Annular metrics compute empirical residuals without fabricated curves.
   - Performance benchmarks ingest real runtime metrics from HDU 3 (DETECTOR_SUMMARY).
5. State your verdict clearly as CLEAN or INTEGRITY VIOLATION.
6. Write your detailed forensic audit report to handoff.md in your working directory.
7. Send your verdict and findings back to the orchestrator via send_message.
