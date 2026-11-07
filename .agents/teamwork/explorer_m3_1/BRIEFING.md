# BRIEFING — 2026-11-07T00:27:35Z

## Mission
Investigate and design the single-detector pipeline architecture and CLI execution (`src/romanepsf/pipeline.py` and `src/pipeline.py`) for Milestone 3.

## 🔒 My Identity
- Archetype: explorer
- Roles: explorer, analyst, pipeline designer
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: Milestone 3 (Single-Detector Validation & 18-Detector Pipeline Execution)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement in src/ directly.
- Deliver findings, blueprints, draft unit tests, and handoff report in working directory.

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `ORIGINAL_REQUEST.md`, `PROJECT.md`
  - `src/romanepsf/cli.py`, `loader.py`, `catalog.py`, `stamps.py`, `assembly.py`, `config.py`
  - `configs/default.yaml`
  - Simulated commissioning datasets on disk (`PID1083/detectors/*.asdf`, `wfi_source_catalog.csv`)
  - Existing unit test suite (486 passing tests)
- **Key findings**:
  - `src/romanepsf/pipeline.py` and top-level `src/pipeline.py` do not yet exist.
  - WFI01 has 5 isolated stars (1 bright, 2 medium, 2 faint).
  - WFI02 has 6 isolated stars (0 bright, 2 medium, 4 faint).
  - Multi-tier fallback in `assembly.assemble_composite_extended_psf` functions smoothly for both 3-tier (WFI01) and 2-tier (WFI02) modes.
  - Signature polymorphism allows `run_single_detector` to be called with positional arguments `(detector_id, asdf_path, catalog_path, config, output_dir)` OR config-first `(cfg, detector="wfi01")`, satisfying both dispatch specification and existing CLI tests.
  - CLI `romanepsf single` currently takes `--detector`, `--canvas-size`, `--output-dir`. Adding `--asdf`, `--catalog`, `--config` satisfies dispatch requirements while maintaining 100% backward compatibility.
  - Immediate `del l2_data` and `gc.collect()` drops peak memory back down in milliseconds, easily maintaining peak RAM << 4 GB.
  - Live testing on real ASDF data verifies 1025x1025 unit-normalized ePSF generation in ~3.5s per detector.
- **Unexplored areas**: Full 18-detector execution orchestration across all SCAs (covered by subsequent tasks/workers).

## Key Decisions Made
- Designed `SingleDetectorResult` dataclass with all required metadata, scale factors, star counts, and paths.
- Implemented `export_single_detector_fits` writing standard `astropy.io.fits` headers (`EXTNAME`, `TELESCOP`, `INSTRUME`, `DETECTOR`, `FILTER`, `PIXSCALE`, `CANVAS_S`, `CRPIX1/2`, `NORM`, `SUM_FLUX`, `N_BRIGHT`, `N_MEDIUM`, `N_FAINT`, `N_TOTAL`, `K_FM`, `K_MB`, `PA_APER`, `DATE`, `ORIGIN`).
- Designed polymorphic `run_single_detector` supporting all calling conventions.
- Designed `PROPOSED_SINGLE_COMMAND` for `src/romanepsf/cli.py` supporting all requested flags (`--detector`, `--asdf`, `--catalog`, `--config`, `--output-dir`, `--canvas-size`).
- Implemented and verified 11 unit tests in `test_single_detector.py` (100% passing).

## Artifact Index
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/DISPATCH.md — Incoming task dispatch
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/BRIEFING.md — Situational awareness
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/progress.md — Liveness heartbeat
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/blueprint_pipeline.py — Concrete production blueprint for `src/romanepsf/pipeline.py`
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/blueprint_pipeline_top.py — Backward-compatibility wrapper for `src/pipeline.py`
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/blueprint_cli_patch.py — Blueprint patch for `src/romanepsf/cli.py` (`single` subcommand)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/test_single_detector.py — 11 comprehensive unit and live tests (100% passing)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/handoff.md — 5-component handoff report
