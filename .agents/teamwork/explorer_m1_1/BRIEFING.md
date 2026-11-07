# BRIEFING — 2026-11-06T09:21:00Z

## Mission
Produce a detailed implementation plan and code specifications for package structure, pyproject.toml, configuration system (default.yaml & config.py), and Level 2 ASDF loader (loader.py).

## 🔒 My Identity
- Archetype: explorer
- Roles: Packaging, Config & Loader Explorer
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: M1

## 🔒 Key Constraints
- Read-only investigation — do NOT implement code in src/
- Only write within /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/
- Provide complete code specifications, schemas, interfaces, and test strategies in handoff.md

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `ORIGINAL_REQUEST.md`, `PROJECT.md`, `m1/SCOPE.md`, `TEST_INFRA.md`
  - Previous survey reports (`explorer_survey_1/handoff.md`, `explorer_survey_2/handoff.md`, `spec_miner_survey_3/handoff.md`)
  - Prototype files (`src/loader.py`, `src/catalog.py`, `src/stamps.py`, `info.md`)
  - Simulated Level 2 dataset (`/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf`)
- **Key findings**:
  - `setuptools` (v84.0.0) is the designated build system; standard `src`-layout with `pyproject.toml` enables clean editable installs.
  - Active science shape is strictly `(4088, 4088)`, float32, with 4 boundary reference pixels stripped by Level 2 calibration.
  - Interface contract requires `RomanL2Data` to expose `pa_aperture: float`, `conversion_factor: float`, and `pixel_scale: float` directly as attributes.
  - Photometric zero point calculation confirmed: $ZP_{AB} \approx 26.836$ mag for F146.
  - Saturated ramp pixels produce NaNs and `DQ & 2 > 0`; `get_effective_mask` combines DQ with non-finite values.
  - Config system supports strongly typed dataclasses, hierarchical YAML parsing, dot-notation overrides, constraint validation, and device resolution (`auto` -> Apple MPS).
  - Designed, implemented, and verified 15 unit tests in proposed test files passing 100%.
- **Unexplored areas**: None for M1-1 scope.

## Key Decisions Made
- Provided complete proposed reference files in `.agents/teamwork/explorer_m1_1/`:
  - `proposed_pyproject.toml`
  - `proposed_default.yaml`
  - `proposed_config.py`
  - `proposed_loader.py`
  - `proposed___init__.py`
  - `proposed_test_loader.py`
  - `proposed_test_config.py`
- Expose `is_calibrated: bool` directly as a field on `RomanL2Data` rather than relying on expensive full-array comparison.
- Verified that `setuptools` build backend, pytest runner, and Apple MPS acceleration operate without error.

## Artifact Index
- DISPATCH.md — Dispatch instructions
- BRIEFING.md — Persistent working memory
- progress.md — Liveness heartbeat and progress log
- proposed_pyproject.toml — Complete PEP 517/621 pyproject.toml specification
- proposed_default.yaml — Complete YAML configuration file
- proposed_config.py — Dataclasses, validation, and config loader
- proposed_loader.py — Level 2 ASDF loader and DQ masking
- proposed___init__.py — Package export specification
- proposed_test_loader.py — 7 unit tests for loader and DQ mask
- proposed_test_config.py — 8 unit tests for config loader and validation
- handoff.md — Final comprehensive handoff report
