## 2026-11-07T00:20:19Z
You are Explorer 1 for Milestone 3 (Single-Detector Validation & 18-Detector Pipeline Execution) of the Roman Extended PSF (ePSF) pipeline project.
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1
Project root: /Users/pmsanch1/code/romanepsf
Python executable: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python

MANDATORY FIRST STEP:
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/src/romanepsf/cli.py
- /Users/pmsanch1/code/romanepsf/src/romanepsf/assembly.py
- /Users/pmsanch1/code/romanepsf/src/romanepsf/stamps.py
- /Users/pmsanch1/code/romanepsf/src/romanepsf/loader.py
- /Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py

Your task:
Investigate and design the single-detector pipeline architecture and CLI execution (`src/romanepsf/pipeline.py` and `src/pipeline.py`):
1. Design the `run_single_detector(detector_id: str, asdf_path: Path, catalog_path: Path, config: RomanPSFConfig, output_dir: Path) -> SingleDetectorResult` function:
   - Lazy ASDF loading and calibration.
   - Bounding sky coordinates extraction and catalog spatial filtering.
   - Coordinate roundtrip projection and 3-tier stellar assignment.
   - Postage stamp extraction, subpixel bicubic centering, and spike-protected contaminant masking.
   - 2D composite ePSF assembly with multi-tier fallback (handling detectors with 0 bright stars).
   - Exporting single-detector intermediate ePSF model to FITS format with standard astropy.io.fits headers (detector ID, star counts by tier, scale factors, pixel scale 0.11 arcsec).
2. Design the CLI command `romanepsf single` (and compatibility with main CLI):
   - Command line flags: `--detector`, `--asdf`, `--catalog`, `--config`, `--output-dir`, `--canvas-size`.
3. Provide a concrete implementation blueprint and draft unit test file for single-detector execution.
4. Deliver a structured handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m3_1/handoff.md`.
Notify the orchestrator with send_message upon completion.
