# Scope: Milestone 1 — Core Package, CLI & Catalog Ingestion

## Milestone Objectives
Implement the foundation of the Roman extended PSF measurement pipeline:
1. Package layout under `src/romanepsf/` and `pyproject.toml`.
2. Hierarchical YAML configuration loader (`configs/default.yaml` and `src/romanepsf/config.py`).
3. Click CLI framework (`src/romanepsf/cli.py`) with all subcommands (`run`, `single`, `catalog`, `stamps`, `assemble`, `validate`, `report`).
4. Level 2 ASDF loader and photometric calibration (`src/romanepsf/loader.py`).
5. Catalog ingestion, duplicate column bug fix, forward roundtrip WCS verification ($\Delta\theta < 0.5''$), centroid refinement, isolation filtering, and multi-tier partitioning (`src/romanepsf/catalog.py`).
6. Unit tests under `tests/unit/` (`test_loader.py`, `test_catalog.py`, `test_config.py`).

## Assigned Features from PROJECT.md
- Feature 1: Level 2 ASDF Loader & Photometric Calibration
- Feature 2: WCS Forward Roundtrip Verification
- Feature 3: Source Catalog Ingestion & Sanitization (fix duplicate column bug)
- Feature 4: Centroid Refinement using first moments
- Feature 5: Moffat Isolation Clearance Filtering
- Feature 6: Multi-Tier Partitioning (Bright, Medium, Faint in F146)
- Feature 7: YAML Configuration Architecture
- Feature 8: Click CLI Framework

## Dependencies
None.

## Status
IN_PROGRESS
