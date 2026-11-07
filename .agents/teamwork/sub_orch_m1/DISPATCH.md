# Dispatch: Sub-Orchestrator Milestone 1 (Core Package, CLI & Catalog Ingestion)

## Mission
You are the Sub-Orchestrator for Milestone 1 of the Roman Extended PSF (ePSF) Measurement Pipeline.
Your role is to orchestrate the implementation, verification, review, and forensic auditing of Milestone 1.

## Scope & Assigned Features
From `/Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md`:
- **Feature 1**: Level 2 ASDF Loader & Photometric Calibration (`src/romanepsf/loader.py`).
- **Feature 2**: WCS Forward Roundtrip Verification ($\Delta\theta < 0.5''$) to eliminate false positives.
- **Feature 3**: Source Catalog Ingestion & Sanitization (`src/romanepsf/catalog.py`), fixing duplicate column bug.
- **Feature 4**: Centroid Refinement using background-subtracted first moments.
- **Feature 5**: Moffat Isolation Clearance Filtering down to $28\ \text{mag}/\text{arcsec}^2$.
- **Feature 6**: Multi-Tier Partitioning into Bright ($<11.0$), Medium ($11.0-13.0$), and Faint ($\ge 13.0$) using synthetic Roman F146 `mag_lambda`.
- **Feature 7**: Hierarchical YAML Configuration Architecture (`configs/default.yaml` and `src/romanepsf/config.py`).
- **Feature 8**: Click CLI Framework (`src/romanepsf/cli.py`) with modular subcommands.

## Essential Bugs to Resolve:
1. Fix duplicate column rename in `catalog.py` (`phot_g_mean_mag_AB` vs `phot_g_mean_mag`).
2. Add forward roundtrip validation in `project_catalog_to_pixels` ($\Delta\theta < 0.5''$).
3. Fix index error preparation in `assembly.py` for dual radii coordinates.
4. Set up package structure under `src/romanepsf/` and `pyproject.toml`.

## Working Directory
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/sub_orch_m1/`

## Reference Documents
- Original Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- Project Document: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md`
- Survey Handoffs:
  - Data: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/handoff.md`
  - Codebase: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2/handoff.md`
  - Specs: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md`

## Instructions
Execute the iteration loop:
1. Spawn Explorer(s) to verify implementation plan.
2. Spawn Worker (`teamwork_worker`) to implement code, CLI, YAML config, and unit tests under `tests/unit/`.
   - Mandatory worker integrity warning applies.
3. Spawn Reviewers (`teamwork_reviewer`) to verify correctness, linting, tests.
4. Spawn Challengers (`teamwork_challenger`) to stress-test catalog matching, WCS roundtrip, and CLI commands.
5. Spawn Forensic Auditor (`teamwork_auditor`) for integrity verification.
6. Gate check: pass all criteria, update SCOPE.md and GATE_STATUS.md.
7. Deliver completion handoff to parent orchestrator (`e80d314a-b5a0-43fb-be2e-ceabc982347e`).
