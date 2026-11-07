# Dispatch: Explorer M1-3 (CLI Framework & Unit Tests)

## Objective
Analyze and design the exact implementation specification for:
1. `src/romanepsf/cli.py` using Click (v8.3.1) with subcommands: `run`, `single`, `catalog`, `stamps`, `assemble`, `validate`, `report`.
2. Clean options parsing, `--config` loading, device selection, logging setup.
3. Unit test suite design under `tests/unit/`:
   - `test_config.py`: YAML schema validation and defaults.
   - `test_loader.py`: ASDF opening, shape, units, DQ mask, WCS extraction.
   - `test_catalog.py`: Catalog ingestion, roundtrip verification, isolation filtering, tier assignment.

## Reference Files
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md`
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/m1/SCOPE.md`
- Survey Reports: `explorer_survey_1/handoff.md`, `explorer_survey_2/handoff.md`, `spec_miner_survey_3/handoff.md`.

## Output
Produce `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_3/handoff.md` with implementation plan and code structure.


## 2026-11-06T09:14:03Z
From: e80d314a-b5a0-43fb-be2e-ceabc982347e
Content:
You are Explorer M1-3 (CLI Framework & Unit Tests Explorer).
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_3/
Parent Orchestrator: e80d314a-b5a0-43fb-be2e-ceabc982347e

MANDATORY FIRST STEPS:
1. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md.
2. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md.
3. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/m1/SCOPE.md.
4. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_3/DISPATCH.md.
5. Read previous survey reports:
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/handoff.md
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2/handoff.md
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md

YOUR MISSION:
Produce a detailed implementation plan and code specifications for:
1. `src/romanepsf/cli.py` using Click (v8.3.1) with subcommands: `run`, `single`, `catalog`, `stamps`, `assemble`, `validate`, `report`.
2. Unit tests under `tests/unit/`:
   - `test_config.py`: YAML schema validation and defaults.
   - `test_loader.py`: ASDF opening, shape, units, DQ mask, WCS extraction.
   - `test_catalog.py`: Catalog ingestion, roundtrip verification, isolation filtering, tier assignment.
