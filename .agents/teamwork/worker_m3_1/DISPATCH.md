## 2026-11-07T00:32:17Z

You are worker_m3_1 (role: Milestone 3 Implementation Worker).
Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m3_1/
You must write your progress to /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m3_1/progress.md and your final report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m3_1/handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

MANDATORY INSTRUCTION:
Read the authoritative user request at /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before writing code.

Python Environment:
Use /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python for all execution and testing.
Local ROSALIA codebase is at /Users/pmsanch1/code/ROSALIA.

Mission:
Implement Milestone 3: Single-Detector Pipeline Architecture, Validation & 18-Detector Execution.

Authoritative Input & Blueprints to read:
1. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/blueprint_pipeline.py
2. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/blueprint_pipeline_top.py
3. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/blueprint_cli_patch.py
4. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/test_single_detector.py
5. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/handoff.md
6. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_2/handoff.md
7. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_3/handoff.md

Tasks:
1. Implement `src/romanepsf/pipeline.py`:
   - Data structures: `SingleDetectorResult`, `PipelineOutputs`.
   - `discover_detectors(detectors_dir: Union[str, Path], requested: Optional[Sequence[str]] = None) -> Dict[str, Path]`
   - `process_single_detector_stamps(asdf_path: Path, catalog_df: pd.DataFrame, cfg: Config) -> Tuple[str, Dict[str, List[StellarStamp]], Dict[str, Any]]`:
     Use `get_detector_sky_bounds` for fast spatial candidate bounding, project coordinates with `project_catalog_to_pixels`, refine centroids with `refine_stellar_centroids`, filter isolated stars with `filter_isolated_stars`, assign tiers with `assign_stellar_tiers`, extract stamps with `process_star_stamps`.
     CRITICAL: In a `finally:` block, explicitly invoke `del l2_data; gc.collect()` to guarantee peak RSS stays << 4 GB.
   - `export_single_detector_fits(result: SingleDetectorResult, output_path: Union[str, Path], filter_name: str = "F146", pixel_scale: float = 0.11) -> Path`:
     Write standard primary HDU FITS with standard <= 8 char keywords (`EXTNAME='EPSF'`, `DETECTOR`, `FILTER`, `PIXSCALE`, `CANVAS_S`, `NORM='UNIT_FLUX'`, `CRPIX1`, `CRPIX2`, `CDELT1`, `CDELT2`, `N_BRIGHT`, `N_MEDIUM`, `N_FAINT`, `N_TOTAL`, `K_FM`, `K_MB`, `TOTALFLX`, `DATE_UTC`, `PROV_VER`).
   - `run_single_detector(...) -> SingleDetectorResult`:
     Support signature polymorphism:
     * Callable as `run_single_detector(cfg, detector="wfi01")` (used by existing CLI & tests)
     * Callable as `run_single_detector(detector_id="wfi01", asdf_path=..., catalog_path=..., config=..., output_dir=...)`
     * Keyword overrides for `canvas_size`, `output_dir`, `device`, etc.
     * Robust handling for detectors with missing bright stars (e.g. WFI02) so it does not crash, setting `k_mb = None` and `K_MB = -1.0` in FITS header.
   - `run_pipeline(cfg=None, detectors_dir=None, catalog_path=None, output_dir=None, canvas_size=None, device=None, detectors=None, num_workers=None) -> PipelineOutputs`:
     Sequentially process designated detectors (or all 18 WFI SCAs), free memory after each detector, pool stamps across all SCAs into `pooled_stamps['bright']`, `'medium'`, `'faint'`, call `assemble_composite_extended_psf`, call `serialize_composite_epsf_fits` to write 4-HDU FITS output (`PRIMARY`, `COVERAGE`, `RADIAL_PROFILES`, `DETECTOR_SUMMARY`), and return `PipelineOutputs`.
2. Implement `src/pipeline.py`:
   - Backward-compatibility module re-exporting all symbols from `romanepsf.pipeline`.
3. Update `src/romanepsf/assembly.py` and `src/assembly.py`:
   - Implement `serialize_composite_epsf_fits(composite_epsf, diagnostics, detector_summaries, output_fits_path, filter_name="F146", pixel_scale=0.11) -> Path` (standard 4-HDU multi-extension FITS format without HIERARCH warnings, as detailed in explorer_m3_3).
   - Re-export `serialize_composite_epsf_fits` in `src/assembly.py`.
4. Update `src/romanepsf/cli.py`:
   - Enhance `single` subcommand: support `--detector`, `--asdf`, `--catalog`, `--config`, `--output-dir`, `--canvas-size`.
   - Enhance `run` subcommand: support `--input-dir`, `--catalog`, `--config`, `--output-dir`, `--canvas-size`, `--device`, `--detectors`, `--num-workers`.
5. Author Unit and Integration Tests:
   - `tests/unit/test_pipeline.py`: Integrate comprehensive tests for single detector (WFI01, WFI02), multi-detector pooling, signature polymorphism, FITS headers, missing-tier resilience, discover_detectors.
   - `tests/unit/test_cli.py`: Update/expand tests for `single` and `run` commands with the new options.
6. Verify Build & Tests:
   - Run `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
   - Run `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v`
7. Live Execution Verification:
   - Run single detector WFI01:
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli single --detector wfi01 --canvas-size 1025 --output-dir output/single_wfi01`
   - Run all 18 detectors:
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli run --canvas-size 1025 --output-dir output/run_all`
   - Verify that output FITS files are valid and peak RSS < 4 GB.
8. Deliver comprehensive `handoff.md` and message the orchestrator when finished.
