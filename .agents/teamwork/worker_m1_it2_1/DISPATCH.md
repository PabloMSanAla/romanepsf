## 2026-11-06T09:53:43Z

You are the Milestone 1 Iteration 2 Implementation Worker (worker_m1_it2_1).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m1_it2_1

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

First, read the authoritative user request:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md

Next, read the project specification and the reports from the 3 Explorers:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_it2_1/handoff.md (and /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_it2_1/catalog_fix.patch)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_it2_2/handoff.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_it2_3/handoff.md

Your exclusive write ownership is:
- `src/romanepsf/catalog.py`
- `src/romanepsf/loader.py`
- `src/romanepsf/config.py`
- `src/romanepsf/cli.py`
- `tests/unit/test_adversarial_m1.py`
- `tests/unit/test_challenger_stress.py`

Your tasks:
1. Implement the unified remediation and hardening blueprint detailed in explorer_m1_it2_3 and explorer_m1_it2_1/2:
   - `src/romanepsf/catalog.py`:
     * Import `DQ_FLAGS` from `romanepsf.loader`.
     * Strip column whitespace in `sanitize_source_catalog`.
     * Filter negative magnitudes across active and secondary magnitude columns without dropping valid stars with `NaN` in secondary columns (preserves all 198,774 stars in commissioning catalog).
     * RA wrap-around across $0^\circ/360^\circ$ meridian in `project_catalog_to_pixels` forward roundtrip verification (`(ra_back - ra_cand + 180.0) % 360.0 - 180.0`) and tangent projection relative to detector center.
     * Centroid refinement: slice `l2_data.dq` and bitwise mask `(dq_box & (DO_NOT_USE | JUMP_DET)) > 0`, zeroing out cosmic ray weights.
     * Centroid refinement: guard `if peak <= 0.0 or total_w <= 0.0:` fallback to catalog position with `shift = 0.0`.
   - `src/romanepsf/loader.py`:
     * Add `__post_init__` to `RomanL2Data` checking `err.shape == data.shape` and `dq.shape == data.shape`.
     * In `load_l2_image`: validate `err.shape` and `dq.shape` match `raw_data.shape`, and validate `conversion_megajanskys` is positive and finite.
   - `src/romanepsf/config.py`:
     * In `PipelineConfig.validate()`: enforce `isinstance(self.assembly.canvas_size, int) and not isinstance(self.assembly.canvas_size, bool) and canvas_size > 0 and canvas_size % 2 == 1`.
   - `src/romanepsf/cli.py`:
     * Explicit `--config` check raises `FileNotFoundError` with exit code 1 when file does not exist.
     * Re-validate `cfg.validate()` after CLI option overrides in `run_command`, `single_command`, and `assemble_command`.
   - `tests/unit/test_adversarial_m1.py`:
     * Wrap `d_ra = (ra_arr - self.crval_ra + 180.0) % 360.0 - 180.0` in `MockGWCS.backward_transform` line 40.
   - `tests/unit/test_challenger_stress.py`:
     * Align the 5 tests documenting unhardened vulnerabilities to assert the hardened contracts.

2. Execute full verification using:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_adversarial_m1.py -v` (must be 10/10 passed)
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v` (must be 82/82 passed)
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v` (must show zero regressions)

3. Write your handoff report to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m1_it2_1/handoff.md` and send a completion message to the parent orchestrator via `send_message`.

## 2026-11-06T10:04:06Z

**Context**: Milestone 1 Iteration 2 Implementation
**Content**: Checking in on status. Please update progress.md with your current step and let us know if you've encountered any blockers or if test runs are in progress.
**Action**: Report your current progress and ETA.
