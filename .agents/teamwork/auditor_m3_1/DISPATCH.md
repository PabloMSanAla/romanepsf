## 2026-11-07T00:46:18Z
You are auditor_m3_1 (role: Milestone 3 Forensic Integrity Auditor).
Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m3_1/
You must write your progress to /Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m3_1/progress.md and your final audit report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m3_1/handoff.md.

MANDATORY INTEGRITY DIRECTIVE:
You perform independent, forensic integrity verification. Your verdict is a BINARY VETO: if you detect an integrity violation (hardcoding test outputs, dummy implementations, circumvention of genuine computation, or circularizing the 2D PSF), the milestone FAILS UNCONDITIONALLY.

MANDATORY INSTRUCTION:
Read the authoritative user request at /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting your audit.

Python Environment:
Use /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python for all execution and testing.
Local ROSALIA codebase is at /Users/pmsanch1/code/ROSALIA.

Audit Targets:
- `src/romanepsf/pipeline.py`
- `src/pipeline.py`
- `src/romanepsf/assembly.py`
- `src/assembly.py`
- `src/romanepsf/cli.py`
- Generated outputs:
  * `output/single_wfi01/roman_epsf_wfi01.fits`
  * `output/run_all/roman_epsf_composite.fits`

Audit Checks to Perform:
1. Hardcoded Values & Facade Detection:
   - Perform AST analysis and regex scans on `pipeline.py`, `assembly.py`, `cli.py`.
   - Ensure scale factors ($k_{\text{FM}}, k_{\text{MB}}$), star counts, coverage maps, and ePSF canvases are NOT hardcoded constants or canned arrays.
   - Verify that `run_single_detector` and `run_pipeline` genuinely read ASDF files from disk, project catalog coordinates via GWCS, extract stamps, and assemble canvases dynamically.
2. 2D Non-Circular Structure & Spike Preservation Audit:
   - Audit `assembly.py` and `pipeline.py` to ensure zero radial averaging or azimuthal circularization of the 2D PSF canvas.
   - Verify that 1D radial profiles are used ONLY for measuring saturation boundaries and cross-tier scale factors, NEVER to overwrite or construct the 2D canvas.
   - Empirically verify that the 2D composite ePSF in `output/run_all/roman_epsf_composite.fits` exhibits true 2D non-circular diffraction spike structures.
3. Astropy FITS Standard Compliance:
   - Verify that all FITS headers in both `roman_epsf_wfi01.fits` and `roman_epsf_composite.fits` comply strictly with the FITS 8-character keyword standard without any `HIERARCH` cards.
4. Dynamic Execution Trace:
   - Run a short execution trace (e.g. running single detector on WFI01 to a temporary output directory) to verify that runtime functions execute genuine numerical algorithms and file I/O.

Write an audit test script (e.g. `/Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m3_1/test_audit_pipeline.py`), run it, and record all findings in `handoff.md`.

Deliver your verdict: **CLEAN** (zero integrity violations, genuine scientific pipeline) or **INTEGRITY VIOLATION** (with full evidence).
