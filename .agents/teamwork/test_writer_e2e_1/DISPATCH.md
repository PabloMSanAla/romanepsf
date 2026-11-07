## 2026-11-06T09:14:13Z
You are E2E Test Writer (E2E Testing Track).
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/test_writer_e2e_1/
Parent Orchestrator: e80d314a-b5a0-43fb-be2e-ceabc982347e

MANDATORY FIRST STEPS:
1. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md.
2. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md.
3. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/TEST_INFRA.md.
4. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/test_writer_e2e_1/DISPATCH.md.
5. Read previous survey reports:
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/handoff.md
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2/handoff.md
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md

YOUR MISSION:
Implement the comprehensive, opaque-box, requirement-driven test suite under `tests/e2e/` as specified in `TEST_INFRA.md`, derived from `ORIGINAL_REQUEST.md`.
Upon completion, publish `/Users/pmsanch1/code/romanepsf/.agents/teamwork/TEST_READY.md`.

Test Structure to build under `tests/e2e/`:
1. `tests/e2e/test_tier1_features.py`:
   - Feature coverage (F1 to F25): >= 5 test cases/assertions per feature.
   - Opaque-box: tests CLI flags, YAML config loading, data loading, catalog outputs, masking functions, assembly, validation, and PDF output.
2. `tests/e2e/test_tier2_boundaries.py`:
   - Boundary & corner cases: >= 5 test cases per feature (e.g., edge stars at pixel bounds [0, 4088], saturated NaN pixels vs extreme values, negative fluxes, empty tiers, even vs odd canvas dimensions, corrupt catalog rows).
3. `tests/e2e/test_tier3_combinations.py`:
   - Cross-feature interactions: >= 25 pairwise tests (WCS roundtrip + isolation filtering; adaptive stamps + spike rotation; Moffat residuals + morphological line opening; radial profile scaling + cosine-taper partition-of-unity blending).
4. `tests/e2e/test_tier4_scenarios.py`:
   - >= 5 real-world commissioning application scenarios (single detector wfi01 CLI execution, 18-detector memory scalability, dynamic range preservation on m=7.37 star, 2D residual mapping, publication PDF generation).

CONSTRAINTS:
- You are a test writer (`teamwork_test_writer`). You MUST NOT modify production implementation code under `src/`.
- Use python `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`.
- Create `/Users/pmsanch1/code/romanepsf/.agents/teamwork/TEST_READY.md` when the test infrastructure and test files are written.

Write progress to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/test_writer_e2e_1/progress.md`.
Write your handoff report to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/test_writer_e2e_1/handoff.md`.
When done, call send_message to notify parent e80d314a-b5a0-43fb-be2e-ceabc982347e.
