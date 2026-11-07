# Dispatch: Explorer M1-1 (Packaging, Config & Loader)

## Objective
Analyze the exact requirements and design the implementation specification for:
1. Package layout under `src/romanepsf/`, `pyproject.toml` configuration.
2. Hierarchical YAML configuration (`configs/default.yaml`) and loader (`src/romanepsf/config.py`).
3. Level 2 ASDF loader (`src/romanepsf/loader.py`) with photometric calibration factor (`meta.photometry.conversion_megajanskys`), DQ bitmask handling, WCS extraction, and aperture position angle extraction.

## Reference Files
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md`
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/m1/SCOPE.md`
- Survey Reports: `explorer_survey_1/handoff.md`, `explorer_survey_2/handoff.md`, `spec_miner_survey_3/handoff.md`.

## Output
Produce `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/handoff.md` with implementation plan and code structure.

## 2026-11-06T09:13:49Z
You are Explorer M1-1 (Packaging, Config & Loader Explorer).
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/
Parent Orchestrator: e80d314a-b5a0-43fb-be2e-ceabc982347e

MANDATORY FIRST STEPS:
1. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md.
2. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md.
3. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/m1/SCOPE.md.
4. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/DISPATCH.md.
5. Read previous survey reports:
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/handoff.md
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2/handoff.md
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md

YOUR MISSION:
Produce a detailed implementation plan and code specifications for:
1. Package structure under `src/romanepsf/` and `pyproject.toml`.
2. `configs/default.yaml` and `src/romanepsf/config.py` (configuration loader, schema validation, dataclasses).
3. `src/romanepsf/loader.py` (`load_l2_image`, `RomanL2Data`, photometric zero point scaling `conversion_megajanskys`, DQ bitmasking, active shape `(4088, 4088)`, WCS extraction).

Write progress to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/progress.md`.
Write your handoff report to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/handoff.md`.
When done, call send_message to notify parent e80d314a-b5a0-43fb-be2e-ceabc982347e.
