# DISPATCH: auditor_m4_it4_1

## Role
Milestone 4 Iteration 4 Forensic Integrity Auditor

## Working Directory
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m4_it4_1`

## Inputs
- Authoritative User Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- Target Codebase: `src/romanepsf/report.py` and `src/romanepsf/validation.py`
- Worker handoff: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_it4_1/handoff.md`

## Instructions
1. Perform static analysis across all files in `src/romanepsf/`:
   - Verify zero RNG calls (`random`, `numpy.random`, `torch.rand`, etc.).
   - Verify no dummy/facade implementations or hardcoded simulation results.
2. Perform runtime call interception:
   - Monkeypatch `numpy.random`, `random`, and `torch.rand` to raise an exception upon call.
   - Run full PDF compilation and model validation. Verify zero calls intercepted.
3. Verify R2 compliance:
   - Verify that 2D PSF is not circularized or radially averaged.
   - Verify 1D radial profiles are strictly reserved for finding saturation boundaries and cross-tier scaling factors.
   - Verify 6-fold diffraction spikes are authentically preserved.
4. Verify genuine data flow:
   - Residual maps on Page 6 load authentic FITS data from `output/validation/residual_*.fits`.
   - Annular metrics on Page 7 compute empirical residuals.
   - Benchmarks on Page 8 read real runtime metrics from HDU 3 and execution logs.
5. Formulate your verdict: **CLEAN** or **INTEGRITY VIOLATION**.
6. Write your detailed forensic report to `handoff.md` and report back via `send_message`.
## 2026-11-07T05:41:31Z
You are auditor_m4_it4_1, a teamwork_auditor responsible for forensic integrity verification of Milestone 4 Iteration 4 deliverables.

Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m4_it4_1
Project root: /Users/pmsanch1/code/romanepsf
Python executable: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python

MANDATORY FIRST STEP:
Read the authoritative user request at:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md
and read your dispatch instructions at:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m4_it4_1/DISPATCH.md
and the worker handoff at:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_it4_1/handoff.md

Tasks:
1. Static analysis across all files in src/romanepsf/:
   - Verify zero RNG calls (random, numpy.random, torch.rand, etc.).
   - Verify no dummy/facade implementations or hardcoded simulation results.
2. Runtime call interception:
   - Monkeypatch numpy.random, random, and torch.rand to raise an exception upon call.
   - Run full PDF compilation and model validation. Verify zero calls intercepted.
3. Verify R2 compliance:
   - Verify that 2D PSF is not circularized or radially averaged.
   - Verify 1D radial profiles are strictly reserved for finding saturation boundaries and cross-tier scaling factors.
   - Verify 6-fold diffraction spikes are authentically preserved.
4. Verify genuine data flow:
   - Residual maps on Page 6 load authentic FITS data from output/validation/residual_*.fits.
   - Annular metrics on Page 7 compute empirical residuals.
   - Benchmarks on Page 8 read real runtime metrics from HDU 3 and execution logs.
5. State your verdict clearly as CLEAN or INTEGRITY VIOLATION.
6. Write your detailed forensic report to handoff.md in your working directory.
7. Send your verdict and findings back to the orchestrator via send_message.
