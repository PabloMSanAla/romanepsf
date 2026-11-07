# Challenger M3 1 Dispatch Log

## 2026-11-07T00:48:00Z
Task: Empirical Stress Testing 1 for Milestone 3 (CLI, Signature Polymorphism & Empty-Tier Resilience).
Target modules:
- `src/romanepsf/pipeline.py`
- `src/romanepsf/cli.py`

## 2026-11-07T00:46:01Z
[Message] sender=e80d314a-b5a0-43fb-be2e-ceabc982347e priority=MESSAGE_PRIORITY_HIGH
You are challenger_m3_1 (role: Milestone 3 Challenger 1 — CLI, Configuration & Signature Adversarial Stress Testing).
Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_1/
You must write your progress to /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_1/progress.md and your final challenge report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_1/handoff.md.

MANDATORY INSTRUCTION:
Read the authoritative user request at /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting your challenges.

Python Environment:
Use /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python for all execution and testing.
Local ROSALIA codebase is at /Users/pmsanch1/code/ROSALIA.

Mission:
Write and execute rigorous adversarial stress tests against the Milestone 3 implementation:
- `src/romanepsf/pipeline.py`
- `src/pipeline.py`
- `src/romanepsf/cli.py`

Adversarial Stress Test Areas:
1. Missing-Tier Detectors:
   - Test all 6 SCAs that lack bright stars (`wfi02`, `wfi03`, `wfi08`, `wfi13`, `wfi17`, `wfi18`) via `run_single_detector`. Ensure that none crash with empty tier errors, all return valid models, set `k_mb = None`, and export FITS with `K_MB = -1.0`.
2. Signature Polymorphism Stress:
   - Call `run_single_detector` with:
     * positional `(cfg, detector="wfi01")`
     * positional `(detector_id, asdf_path, catalog_path, config, output_dir)`
     * keyword-only calls with various subsets of overrides
     * path strings vs Path objects
     * invalid types/values to ensure informative exceptions rather than silent corruptions.
3. Canvas Dimensions & Coordinate Centering:
   - Test even canvas dimensions (e.g. 1024, 2048) and odd dimensions (1025, 2049). Ensure odd dimensions have exact center at `(S-1)//2` and even dimensions are safely handled or promoted.
   - Verify that peak flux is located exactly at the canvas center pixel.
4. CLI Subcommand Invocations:
   - Test `romanepsf single` and `romanepsf run` via Click's `CliRunner` with valid and invalid options:
     * missing arguments, invalid detector names, non-existent ASDF files, non-existent catalog files, invalid device strings.
     * verify exit codes and error messages.
5. Zero-Star Detector Graceful Error:
   - Test behavior when catalog has zero stars in footprint (ensure clean descriptive RuntimeError, not unhandled crash).

Write a standalone adversarial test suite (e.g. `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_1/test_adversarial_pipeline.py`), run it with pytest, and document all findings in `handoff.md`.

Deliver your verdict: **APPROVE** (all stress tests pass and implementation is robust) or **REQUEST_CHANGES** (critical bugs/crashes discovered).
