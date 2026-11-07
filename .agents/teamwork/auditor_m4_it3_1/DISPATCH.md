# DISPATCH: auditor_m4_it3_1

## Role
Milestone 4 Iteration 3 Forensic Integrity Auditor

## Target Scope
Perform rigorous, independent forensic integrity verification on `src/romanepsf/report.py`, `src/romanepsf/validation.py`, and `output/report.pdf`.

## Core Checks
1. ZERO Hardcoded Facades:
   - Verify that Page 6 reads real FITS data (`output/validation/residual_*.fits` or `output/run_all/validation/residual_*.fits`).
   - Verify that Page 7 computes empirical annular residuals from actual star residuals and performs authentic azimuthal scans.
   - Verify that Page 8 loads genuine execution times and memory measurements from HDU 3 (`DETECTOR_SUMMARY`).
2. ZERO Random Number Generation:
   - AST inspection of `src/romanepsf/report.py`, `src/report.py`, and `src/romanepsf/validation.py` for any `random`, `normal`, `uniform`, `seed`, `choice`, `randint`.
   - Runtime execution with poisoned `numpy.random`.
3. Requirement R2 Compliance:
   - Confirm that the 2D ePSF canvas is NOT circularized or azimuthally averaged.
   - Confirm that 1D radial profiles are used only for finding saturation boundaries and cross-tier scaling factors.
4. Report Artifact Authenticity:
   - Confirm `output/report.pdf` is genuinely generated from matplotlib `PdfPages`, has 8 pages, and is > 2 MB.

## Inputs to Audit
- Source Code: `src/romanepsf/report.py`, `src/romanepsf/validation.py`
- Output PDF: `output/report.pdf`
- Results: `output/run_all`
- Worker Handoff: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_it3_1/handoff.md`
- Authoritative User Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`

## Instructions
1. Read `ORIGINAL_REQUEST.md` and `worker_m4_it3_1/handoff.md`.
2. Run forensic static analysis and runtime tracing.
3. State your verdict clearly: `CLEAN` or `INTEGRITY VIOLATION`. Write `handoff.md` and notify parent.


## 2026-11-07T05:14:00Z
You are auditor_m4_it3_1. Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m4_it3_1/

Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing anything else.
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m4_it3_1/DISPATCH.md for your assigned task.

Perform rigorous, independent forensic integrity verification on `src/romanepsf/report.py`, `src/romanepsf/validation.py`, and `output/report.pdf`.
Check for:
1. Zero hardcoded facades (Page 6 genuine FITS residuals, Page 7 empirical annular residuals & azimuthal scans, Page 8 genuine HDU 3 benchmarks).
2. Zero random number generation (AST static analysis and poisoned runtime execution).
3. Requirement R2 compliance (no circularizing/radial averaging of 2D PSF canvas; 1D profiles used only for saturation boundaries and cross-tier scaling).
4. Authenticity of PDF report artifact (> 2 MB, 8 pages, %PDF-1.4).

Use Python environment `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`.
State your verdict clearly as CLEAN or INTEGRITY VIOLATION in handoff.md and notify the parent orchestrator via send_message.
