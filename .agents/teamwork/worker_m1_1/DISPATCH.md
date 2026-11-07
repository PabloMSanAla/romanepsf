# Dispatch: Worker M1-1 (Milestone 1 Implementation Worker)

## Objective
Implement Milestone 1 of the Roman Extended PSF Measurement Pipeline:
1. `pyproject.toml`: PEP 517/621 setuptools configuration with `src`-layout and Click console script `romanepsf = romanepsf.cli:cli`. Install in editable mode (`pip install -e .`).
2. `configs/default.yaml`: Complete 11-section YAML configuration for operational parameters.
3. `src/romanepsf/__init__.py`: Package export interface.
4. `src/romanepsf/config.py`: Dataclass configuration schema, dot-notation overrides, constraint validation, and device resolution (MPS/CUDA/CPU).
5. `src/romanepsf/loader.py`: Level 2 ASDF loader, `RomanL2Data` dataclass with all required attributes (`data`, `raw_data`, `err`, `dq`, `wcs`, `pa_aperture`, `pixel_scale`, `conversion_factor`), active science shape `(4088, 4088)` enforcement, photometric scaling to MJy/sr, and comprehensive DQ bitmasking (`get_dq_mask`, `get_effective_mask`).
6. `src/romanepsf/catalog.py`: Stellar catalog processing:
   - Deduplicate columns, fixing duplicate `phot_g_mean_mag` column collision bug.
   - Vectorized `project_catalog_to_pixels` with forward roundtrip WCS verification ($\Delta\theta < 0.5''$) to eliminate false out-of-footprint matches.
   - Subpixel centroid refinement using background-subtracted first moments, NaN handling, and divergence guard.
   - Priority-ordered Moffat isolation filtering (ascending magnitude priority, 1.3x clearance).
   - Multi-tier partitioning (`'bright'` < 11.0, `'medium'` 11.0-13.0, `'faint'` >= 13.0 in synthetic Roman F146 `mag_lambda`).
7. `src/romanepsf/cli.py`: Click CLI with all 7 subcommands (`run`, `single`, `catalog`, `stamps`, `assemble`, `validate`, `report`), global context propagation, device selection, and logging.
8. Backward-compatibility wrappers in `src/loader.py` and `src/catalog.py` re-exporting from `romanepsf.*`.
9. Complete unit test suite under `tests/unit/`:
   - `test_config.py`
   - `test_loader.py`
   - `test_catalog.py`
   - `test_cli.py`
10. Execute build/install and test command:
    ```bash
    /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/pip install -e /Users/pmsanch1/code/romanepsf
    /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
    /Users/pmsanch1/code/romanepsf/src/romanepsf/cli.py --help  # or romanepsf --help
    ```

## Reference Code from Explorers
Explorers have prepared tested, verified reference implementations:
- Explorer M1-1: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/`
  - `proposed_pyproject.toml`
  - `proposed_default.yaml`
  - `proposed_config.py`
  - `proposed_loader.py`
  - `proposed___init__.py`
  - `proposed_test_loader.py`
  - `proposed_test_config.py`
- Explorer M1-2: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2/`
  - `proposed_catalog.py`
- Explorer M1-3: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_3/`
  - `handoff.md` (complete `cli.py` and unit test code)

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Working Directory
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m1_1/`

## Output Requirements
Produce a comprehensive handoff report at `/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m1_1/handoff.md` documenting:
- Files modified/created
- Test execution output and passing assertion counts
- CLI verification output
