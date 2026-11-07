# Dispatch: Sub-Orchestrator E2E Testing Track

## Mission
You are the Sub-Orchestrator for the E2E Testing Track of the Roman Extended PSF (ePSF) Measurement Pipeline.
Your role is to build a comprehensive, opaque-box, requirement-driven test suite independently of the implementation internals, covering Tiers 1-4, and publish `TEST_READY.md`.

## Scope
From `/Users/pmsanch1/code/romanepsf/.agents/teamwork/TEST_INFRA.md` and `ORIGINAL_REQUEST.md`:
- **Tier 1 - Feature Coverage**: $\ge 5$ test cases per feature (F1 through F25). Happy-path tests verifying each feature via simplest verification channels.
- **Tier 2 - Boundary & Corner Cases**: $\ge 5$ test cases per feature covering boundaries, empty/corrupted inputs, extreme saturation, NaNs, edge stars.
- **Tier 3 - Cross-Feature Combinations**: $\ge 25$ test cases testing pairwise interactions (e.g. WCS roundtrip + tier assignment; catalog isolation + stamp sizing; spike rotation + morphological filtering; cross-tier scaling + cosine taper blending).
- **Tier 4 - Real-World Commissioning Scenarios**: $\ge 5$ comprehensive application scenarios:
  1. Single detector WFI01 end-to-end execution and validation.
  2. Multi-detector WFI01-18 composite synthesis and memory benchmarking.
  3. Extreme brightness and 6-fold spike preservation on $m=7.37$ star (WFI05).
  4. 2D subtraction residual mapping and radial metric tolerances.
  5. Publication PDF report generation and visual completeness.

## Working Directory
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/sub_orch_e2e/`

## Reference Documents
- Original Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- Project Document: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md`
- Test Infrastructure Document: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/TEST_INFRA.md`
- Survey Reports:
  - Data: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/handoff.md`
  - Codebase: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2/handoff.md`
  - Specs: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md`

## Output Requirements
1. Comprehensive test suite under `tests/e2e/` runnable via `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v`.
2. Publication of `/Users/pmsanch1/code/romanepsf/.agents/teamwork/TEST_READY.md` containing test runner command, tier breakdown, and feature checklist.
3. Deliver completion handoff to parent orchestrator (`e80d314a-b5a0-43fb-be2e-ceabc982347e`).
