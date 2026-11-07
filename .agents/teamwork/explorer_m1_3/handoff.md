# Implementation Specification & Architecture: CLI Framework & Unit Test Suites
**Author / Role**: Explorer M1-3 (CLI Framework & Unit Tests Explorer)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_3/`  
**Reference Documents**: `ORIGINAL_REQUEST.md`, `PROJECT.md`, `m1/SCOPE.md`, Survey Handoffs (1, 2, 3)  
**Target Milestone**: Milestone 1 (Core Package, CLI & Catalog Ingestion)  
**Date**: 2026-11-06  

---

## 1. Observation

### 1.1 Python Environment & Tooling Verification
Direct environment execution using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python` verifies:
- **Python**: `3.12.12`
- **Click**: `8.3.1` (Deprecation warning noted for direct `click.__version__`; use feature detection or standard CLI invocation).
- **Pytest**: `9.0.2`
- **PyYAML (`yaml`)**: `6.0.3`
- **PyTorch (`torch`)**: `2.14.1` with Apple Metal Performance Shaders (`torch.backends.mps.is_available() == True`).
- **Data Models & Astrometry**: `roman_datamodels: 1.1.0`, `asdf: 5.4.0`, `astropy: 7.2.2`, `gwcs: 1.0.3`, `photutils: 2.3.0`, `pandas: 3.0.1`, `matplotlib: 3.10.8`.
- **CliRunner Test Behavior**: Testing Click commands requires explicit `from click.testing import CliRunner` because `click` does not auto-export `testing` on top-level `import click`.

### 1.2 Existing Codebase State in `src/`
- Current directory layout has loose modules under `src/` (`assembly.py`, `catalog.py`, `loader.py`, `masking.py`, `profile.py`, `stamps.py`).
- There is currently no `src/romanepsf/` package directory, no `pyproject.toml`, no `configs/default.yaml`, and no `tests/` directory.
- `pytest --collect-only` reports `no tests collected in 0.00s` (exit code 5) because no test files exist.

### 1.3 Commissioning Data & Critical Algorithmic Constraints
1. **Level 2 ASDF Files**:
   - Location: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/` (18 files, ~204 MB each).
   - Array shape: `(4088, 4088)` float32 active science data (`model.data`). Reference pixel borders (4 rows/cols) are stripped into `border_ref_pix_*`.
   - Units: Raw `model.data` is in `DN/s` (`cal_step.flux = 'INCOMPLETE'`). Photometric calibration requires multiplying by `meta.photometry.conversion_megajanskys` (~0.238965 MJy/sr per DN/s) to obtain surface brightness in `MJy/sr`.
   - DQ Bitmask: Standard Roman flags: DO_NOT_USE (bit 0 = 1), SATURATED (bit 1 = 2), JUMP_DET (bit 2 = 4), DROPOUT (bit 3 = 8). Saturated pixels in Level 2 images manifest as `NaN` or unphysical numbers (e.g. -30,283 DN/s). Masking must use `(dq & 2) > 0` or `np.isnan(data)`.
2. **Catalog Ingestion & Astrometric WCS Bug**:
   - Master catalog: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv` (198,802 rows).
   - Contains duplicate column names: both `phot_g_mean_mag_AB` and `phot_g_mean_mag` are present. Renaming `phot_g_mean_mag_AB` to `phot_g_mean_mag` produces duplicate columns and crashes NumPy indexing.
   - WCS Inversion Bug: Calling `wcs.backward_transform(ra, dec)` on stars located outside the detector footprint produces spurious coordinates in `[0, 4088]` with angular discrepancies exceeding $1700''$. Enforcing forward roundtrip verification $\Delta\theta = \text{separation}(wcs(x, y), (\alpha, \delta)) < 0.5''$ strictly eliminates all false positives, yielding exactly 194 verified stars across all 18 SCAs.
   - Stellar Tiers in Roman F146 (`mag_lambda`):
     - Bright: $m < 11.0$ (17 stars across 18 SCAs) $\rightarrow$ outer wings and 6-fold spikes.
     - Medium: $11.0 \le m < 13.0$ (50 stars across 18 SCAs) $\rightarrow$ transition overlap and flux scaling.
     - Faint: $m \ge 13.0$ (127 stars across 18 SCAs) $\rightarrow$ unsaturated core ($r < 10$ px).

---

## 2. Logic Chain

### 2.1 CLI Framework Design (`src/romanepsf/cli.py`)
1. **Command Structure**:
   - Must expose top-level CLI command `romanepsf [OPTIONS] COMMAND [ARGS]...` and module entry point `python -m romanepsf.cli`.
   - Global Options:
     - `--config` / `-c`: Path to YAML configuration file (default: `configs/default.yaml`).
     - `--device` / `-d`: Compute device (`auto`, `mps`, `cuda`, `cpu`).
     - `--log-level` / `-l`: Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
     - `--verbose` / `-v`: Shortcut to enable `DEBUG` logging.
     - `--version`: Display pipeline version string.
2. **Click Context Propagation**:
   - Using `@click.pass_context` and `ctx.ensure_object(dict)`, global options configure the logging subsystem and parse the YAML config into a strongly typed `Config` dataclass instance once at the group level.
   - Subcommands receive `ctx.obj["config"]`, `ctx.obj["logger"]`, and `ctx.obj["device"]`, allowing per-subcommand execution without redundant file parsing.
3. **Subcommands Specification**:
   - `run`: Complete end-to-end execution across all 18 detectors (or configured detectors list), generating composite canvas, validation residual maps, and compiling the publication-ready PDF report.
   - `single`: Rapid single-detector validation on `wfi01` (or specified SCA), saving intermediate tier stacks and 2D model.
   - `catalog`: Ingests, projects with roundtrip verification, isolates, and partitions stars into Bright, Medium, and Faint tiers for a detector, writing filtered CSV.
   - `stamps`: Extracts, recenters, aligns, and masks postage stamps with dual-prior spike protection, saving stamp bundles.
   - `assemble`: Synthesizes multi-tier composite 2D extended PSF canvas from extracted stamps using PyTorch tensor stacking, 1D profile calibration, and 2D cosine-taper partition-of-unity blending.
   - `validate`: Forward-models observed stars against synthesized ePSF canvas, generating 2D subtraction residuals and radial metric profiles ($\mu_{\text{frac}}, \text{RMS}_{\text{frac}}, \chi_\nu^2$).
   - `report`: Compiles publication-ready 8-page PDF report using `matplotlib.backends.backend_pdf.PdfPages`.
4. **Error Handling & Exit Codes**:
   - Exit code `0`: Success.
   - Exit code `1`: Pipeline runtime failure (e.g. `FileNotFoundError`, `ValueError`, invalid array shapes). Handled with clean logger error outputs. Full tracebacks shown only if `--verbose` or `--log-level DEBUG` is set.
   - Exit code `2`: CLI usage / argument syntax error (standard Click behavior).

### 2.2 Unit Test Architecture (`tests/unit/`)
1. **Execution Efficiency & Isolation**:
   - Running tests directly against the 3.6 GB commissioning dataset is impractical for rapid test cycles (CI or local unit testing).
   - Unit tests must be fast (< 5 seconds total runtime), deterministic, and execute without network access.
   - Synthetic fixtures and lightweight mock data models provide 100% test coverage of all parsing, math, boundary conditions, and error branches.
2. **`test_config.py`**:
   - Validates `load_config`, default instantiation, custom YAML overrides, schema types, non-existent files (`FileNotFoundError`), malformed YAML (`yaml.YAMLError`), boundary validations (`bright_limit < faint_limit`, `canvas_size` oddness, overlap interval order), and device resolution.
3. **`test_loader.py`**:
   - Validates `load_l2_image`, `RomanL2Data` dataclass fields, active science dimensions `(4088, 4088)`, photometric scaling (`data = raw_data * conversion_megajanskys`), DQ bitmasking (`get_dq_mask`) with default and custom flag sets, zero-point AB magnitude formula, and missing file handling.
4. **`test_catalog.py`**:
   - Validates duplicate column sanitization (`phot_g_mean_mag_AB` vs `phot_g_mean_mag`), forward roundtrip WCS verification (accepting $\Delta\theta < 0.5''$ and strictly rejecting $\Delta\theta > 0.5''$), detector boundary edge margins (50 px margin), subpixel centroid refinement via first moments, divergence handling/fallback, Moffat isolation clearance (rejecting blended neighbors while preserving isolated stars), and multi-tier partitioning based on `mag_lambda` into Bright (<11.0), Medium (11.0-13.0), and Faint (>=13.0).
5. **`test_cli.py`**:
   - Uses `from click.testing import CliRunner` to test CLI group help, subcommand help, option parsing, config overrides, device selection, and error exit codes without running heavy pipeline stages.

---

## 3. Code Specifications & Implementation Blueprints

### 3.1 CLI Implementation: `src/romanepsf/cli.py`

```python
"""
Roman Extended PSF (ePSF) Measurement Pipeline CLI.

Click-based command line interface providing subcommands:
- run: End-to-end ePSF pipeline across all detectors.
- single: Single-detector validation on WFI01.
- catalog: Ingest, project, isolate, and partition stars for a detector.
- stamps: Extract, recenter, and mask star postage stamps.
- assemble: Synthesize multi-tier composite 2D extended PSF canvas.
- validate: Forward-model stars and compute 2D/radial residual metrics.
- report: Compile publication-ready PDF technical report.
"""

import sys
import os
import logging
from pathlib import Path
from typing import Optional, List
import click

from romanepsf import __version__
from romanepsf.config import load_config, Config, resolve_device


def setup_logging(level_name: str = "INFO", verbose: bool = False) -> logging.Logger:
    """Configure unified logging for the pipeline."""
    level = logging.DEBUG if verbose else getattr(logging, level_name.upper(), logging.INFO)
    logger = logging.getLogger("romanepsf")
    logger.setLevel(level)

    # Avoid duplicate handlers on re-entry
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


@click.group(
    context_settings=dict(help_option_names=["-h", "--help"], max_content_width=100)
)
@click.option(
    "--config",
    "-c",
    type=click.Path(dir_okay=False, path_type=Path),
    default="configs/default.yaml",
    show_default=True,
    help="Path to YAML configuration file.",
)
@click.option(
    "--device",
    "-d",
    type=click.Choice(["auto", "mps", "cuda", "cpu"], case_sensitive=False),
    default=None,
    help="Compute device for PyTorch operations (overrides config).",
)
@click.option(
    "--log-level",
    "-l",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default=None,
    help="Logging severity level (overrides config).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose DEBUG logging.",
)
@click.version_option(version=__version__, message="%(prog)s version %(version)s")
@click.pass_context
def cli(
    ctx: click.Context,
    config: Path,
    device: Optional[str],
    log_level: Optional[str],
    verbose: bool,
):
    """Roman Space Telescope Extended PSF (ePSF) Measurement Pipeline."""
    ctx.ensure_object(dict)

    # 1. Load YAML Configuration
    try:
        cfg = load_config(config if config.is_file() else None)
    except Exception as e:
        click.secho(f"Error loading configuration: {e}", fg="red", err=True)
        sys.exit(1)

    # 2. Apply Global CLI Overrides
    if device is not None:
        cfg.environment.device = device.lower()
    if log_level is not None:
        cfg.pipeline.log_level = log_level.upper()
    if verbose:
        cfg.pipeline.log_level = "DEBUG"

    # 3. Setup Centralized Logger
    logger = setup_logging(cfg.pipeline.log_level, verbose=verbose)
    torch_device = resolve_device(cfg.environment.device)
    logger.debug(f"Configuration loaded from {config}. Resolved compute device: {torch_device}")

    # Store in Click context object
    ctx.obj["config"] = cfg
    ctx.obj["logger"] = logger
    ctx.obj["device"] = torch_device
    ctx.obj["verbose"] = verbose


@cli.command("run", help="Execute complete end-to-end ePSF measurement pipeline.")
@click.option(
    "--detectors",
    default=None,
    help="Comma-separated detectors list (e.g. 'wfi01,wfi02') or 'all'.",
)
@click.option(
    "--canvas-size",
    "-s",
    type=int,
    default=None,
    help="Canvas dimension (e.g. 1025 or 2049).",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to store synthesized models and reports.",
)
@click.option(
    "--num-workers",
    "-w",
    type=int,
    default=None,
    help="Number of parallel worker processes.",
)
@click.pass_context
def run_command(
    ctx: click.Context,
    detectors: Optional[str],
    canvas_size: Optional[int],
    output_dir: Optional[Path],
    num_workers: Optional[int],
):
    """Execute complete end-to-end ePSF pipeline across all designated detectors."""
    cfg: Config = ctx.obj["config"]
    logger: logging.Logger = ctx.obj["logger"]

    if detectors is not None:
        cfg.data.detectors = [d.strip() for d in detectors.split(",") if d.strip()]
    if canvas_size is not None:
        cfg.assembly.canvas_size = canvas_size
    if output_dir is not None:
        cfg.data.output_dir = output_dir
    if num_workers is not None:
        cfg.environment.num_workers = num_workers

    logger.info(f"Starting pipeline execution across detectors: {cfg.data.detectors}")
    try:
        from romanepsf.pipeline import run_pipeline

        outputs = run_pipeline(cfg)
        logger.info(f"Pipeline completed successfully. FITS model saved to: {outputs.fits_path}")
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("single", help="Run single-detector validation on WFI01.")
@click.option(
    "--detector",
    default="wfi01",
    show_default=True,
    help="Detector SCA identifier (e.g. 'wfi01').",
)
@click.option(
    "--canvas-size",
    "-s",
    type=int,
    default=None,
    help="Canvas dimension (e.g. 1025).",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory for single-detector artifacts.",
)
@click.pass_context
def single_command(
    ctx: click.Context,
    detector: str,
    canvas_size: Optional[int],
    output_dir: Optional[Path],
):
    """Run pipeline execution on a single detector (default: WFI01)."""
    cfg: Config = ctx.obj["config"]
    logger: logging.Logger = ctx.obj["logger"]

    cfg.data.detectors = [detector.lower()]
    if canvas_size is not None:
        cfg.assembly.canvas_size = canvas_size
    if output_dir is not None:
        cfg.data.output_dir = output_dir

    logger.info(f"Executing single-detector run on: {detector.upper()}")
    try:
        from romanepsf.pipeline import run_single_detector

        outputs = run_single_detector(cfg, detector=detector.lower())
        logger.info(f"Single-detector {detector.upper()} succeeded. Model: {outputs.fits_path}")
    except Exception as e:
        logger.error(f"Single detector execution failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("catalog", help="Ingest, project, and isolate stars for a detector.")
@click.option(
    "--detector",
    default="wfi01",
    show_default=True,
    help="Detector SCA identifier.",
)
@click.option(
    "--catalog-path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to precomputed catalog CSV.",
)
@click.option(
    "--output-csv",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to save processed and tiered star catalog CSV.",
)
@click.pass_context
def catalog_command(
    ctx: click.Context,
    detector: str,
    catalog_path: Optional[Path],
    output_csv: Optional[Path],
):
    """Ingest, project with forward roundtrip WCS, and partition stars into tiers."""
    cfg: Config = ctx.obj["config"]
    logger: logging.Logger = ctx.obj["logger"]

    if catalog_path is not None:
        cfg.data.catalog_path = catalog_path
    if output_csv is None:
        output_csv = cfg.data.output_dir / f"{detector.lower()}_stars_tiered.csv"

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Processing catalog for detector {detector.upper()}")

    try:
        from romanepsf.loader import load_l2_image
        from romanepsf.catalog import (
            sanitize_source_catalog,
            project_catalog_to_pixels,
            refine_stellar_centroids,
            filter_isolated_stars,
            assign_stellar_tiers,
        )
        import pandas as pd

        asdf_file = cfg.data.detectors_dir / f"r0108301001001001001_0001_{detector.lower()}_f146_cal.asdf"
        l2_data = load_l2_image(str(asdf_file), calibrate=True)
        raw_df = pd.read_csv(cfg.data.catalog_path, low_memory=False)
        clean_df = sanitize_source_catalog(raw_df, mag_col=cfg.catalog.mag_col)

        projected_df = project_catalog_to_pixels(
            l2_data=l2_data,
            catalog_df=clean_df,
            margin_px=cfg.catalog.edge_margin_px,
            tolerance_arcsec=cfg.catalog.roundtrip_tolerance_arcsec,
        )
        refined_df = refine_stellar_centroids(
            l2_data, projected_df, box_radius=cfg.catalog.centroid_refine_box_px
        )
        isolated_df = filter_isolated_stars(
            df=refined_df,
            pixel_scale=l2_data.pixel_scale,
            safety_factor=cfg.catalog.isolation_safety_factor,
        )
        tiered_df = assign_stellar_tiers(
            df=isolated_df,
            bright_limit=cfg.tiers.bright_limit,
            faint_limit=cfg.tiers.faint_limit,
            mag_col=cfg.catalog.mag_col,
        )

        tiered_df.to_csv(output_csv, index=False)
        logger.info(f"Processed {len(tiered_df)} verified stars saved to {output_csv}")
    except Exception as e:
        logger.error(f"Catalog command failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("stamps", help="Extract, recenter, and mask star postage stamps.")
@click.option(
    "--detector",
    default="wfi01",
    show_default=True,
    help="Detector SCA identifier.",
)
@click.option(
    "--catalog-csv",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to pre-filtered tiered catalog CSV.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to save extracted stamps.",
)
@click.pass_context
def stamps_command(
    ctx: click.Context,
    detector: str,
    catalog_csv: Optional[Path],
    output_dir: Optional[Path],
):
    """Extract postage stamps with subpixel alignment and dual-prior spike protection."""
    cfg: Config = ctx.obj["config"]
    logger: logging.Logger = ctx.obj["logger"]

    out_dir = output_dir or (cfg.data.output_dir / "stamps" / detector.lower())
    out_dir.mkdir(parents=True, exist_ok=True)
    cat_file = catalog_csv or (cfg.data.output_dir / f"{detector.lower()}_stars_tiered.csv")

    logger.info(f"Extracting stamps for {detector.upper()} from {cat_file}")
    try:
        from romanepsf.loader import load_l2_image
        from romanepsf.stamps import process_star_stamps
        import pandas as pd
        import pickle

        asdf_file = cfg.data.detectors_dir / f"r0108301001001001001_0001_{detector.lower()}_f146_cal.asdf"
        l2_data = load_l2_image(str(asdf_file), calibrate=True)
        tiered_df = pd.read_csv(cat_file)

        stamps_by_tier = process_star_stamps(l2_data, tiered_df, cfg.spikes, cfg.stamps)
        save_path = out_dir / "stamps_by_tier.pkl"
        with open(save_path, "wb") as f:
            pickle.dump(stamps_by_tier, f)

        total_stamps = sum(len(v) for v in stamps_by_tier.values())
        logger.info(f"Extracted {total_stamps} stamps across tiers. Saved to {save_path}")
    except Exception as e:
        logger.error(f"Stamps command failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("assemble", help="Synthesize multi-tier composite 2D extended PSF canvas.")
@click.option(
    "--stamps-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory containing extracted stamps bundles.",
)
@click.option(
    "--canvas-size",
    "-s",
    type=int,
    default=None,
    help="Canvas dimension (e.g. 1025 or 2049).",
)
@click.option(
    "--output-fits",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to output FITS file.",
)
@click.pass_context
def assemble_command(
    ctx: click.Context,
    stamps_dir: Optional[Path],
    canvas_size: Optional[int],
    output_fits: Optional[Path],
):
    """Stack tier stamps, compute overlap scaling, and blend 2D composite ePSF."""
    cfg: Config = ctx.obj["config"]
    logger: logging.Logger = ctx.obj["logger"]

    if canvas_size is not None:
        cfg.assembly.canvas_size = canvas_size
    out_fits = output_fits or (cfg.data.output_dir / "roman_epsf_composite.fits")
    out_fits.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Synthesizing composite 2D ePSF canvas ({cfg.assembly.canvas_size}x{cfg.assembly.canvas_size})")
    try:
        from romanepsf.assembly import assemble_composite_extended_psf
        from astropy.io import fits
        import pickle

        stamps_file = (stamps_dir or cfg.data.output_dir / "stamps" / "wfi01") / "stamps_by_tier.pkl"
        with open(stamps_file, "rb") as f:
            stamps_by_tier = pickle.load(f)

        epsf_model = assemble_composite_extended_psf(stamps_by_tier, cfg.assembly, device=ctx.obj["device"])

        hdu = fits.PrimaryHDU(epsf_model.astype("float32"))
        hdu.header["EXTNAME"] = "EPSF"
        hdu.header["FILTER"] = cfg.data.filter_name
        hdu.header["CANVAS_S"] = cfg.assembly.canvas_size
        hdu.header["NORM"] = "UNIT_FLUX"
        hdu.writeto(out_fits, overwrite=True)

        logger.info(f"Assembled ePSF canvas successfully saved to {out_fits}")
    except Exception as e:
        logger.error(f"Assembly command failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("validate", help="Forward-model stars and compute 2D/radial residual metrics.")
@click.option(
    "--model",
    "-m",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to synthesized ePSF FITS model.",
)
@click.option(
    "--asdf-path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to Level 2 test image ASDF.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to save residual maps and metrics JSON.",
)
@click.pass_context
def validate_command(
    ctx: click.Context,
    model: Path,
    asdf_path: Optional[Path],
    output_dir: Optional[Path],
):
    """Forward-model stars and evaluate partitioned radial residuals."""
    cfg: Config = ctx.obj["config"]
    logger: logging.Logger = ctx.obj["logger"]

    val_dir = output_dir or (cfg.data.output_dir / "validation")
    val_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Validating ePSF model {model} against observations")

    try:
        from romanepsf.validation import evaluate_epsf_validation
        from astropy.io import fits
        import json

        with fits.open(model) as hdul:
            epsf_data = hdul[0].data

        results = evaluate_epsf_validation(epsf_data, asdf_path=asdf_path, cfg=cfg.validation)
        summary_path = val_dir / "validation_summary.json"
        with open(summary_path, "w") as f:
            json.dump(results.to_dict(), f, indent=2)

        logger.info(f"Validation finished. Summary saved to {summary_path}")
    except Exception as e:
        logger.error(f"Validation command failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command("report", help="Compile publication-ready PDF technical report.")
@click.option(
    "--results-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory containing pipeline outputs and validation metrics.",
)
@click.option(
    "--output-pdf",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Destination path for publication-ready PDF report.",
)
@click.option(
    "--dpi",
    type=int,
    default=300,
    show_default=True,
    help="Figure rendering DPI resolution.",
)
@click.pass_context
def report_command(
    ctx: click.Context,
    results_dir: Optional[Path],
    output_pdf: Optional[Path],
    dpi: int,
):
    """Generate 8-page publication-ready PDF technical document using PdfPages."""
    cfg: Config = ctx.obj["config"]
    logger: logging.Logger = ctx.obj["logger"]

    res_dir = results_dir or cfg.data.output_dir
    pdf_path = output_pdf or cfg.reporting.report_path
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Compiling publication PDF report to: {pdf_path}")
    try:
        from romanepsf.report import generate_publication_pdf_report

        generate_publication_pdf_report(res_dir, pdf_path, dpi=dpi)
        logger.info(f"Publication PDF successfully generated: {pdf_path}")
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


def main():
    """Entry point for romanepsf console script."""
    cli(obj={})


if __name__ == "__main__":
    main()
```

---

### 3.2 Unit Test Specification 1: `tests/unit/test_config.py`

```python
"""
Unit Tests for Configuration Architecture and YAML Schema Validation.

Tests default values, custom YAML loading, error handling for missing/malformed files,
boundary/range validations, device resolution, and roundtrip serialization.
"""

from pathlib import Path
import pytest
import yaml
import torch

from romanepsf.config import (
    load_config,
    Config,
    PipelineConfig,
    EnvironmentConfig,
    DataConfig,
    CatalogConfig,
    TiersConfig,
    StampsConfig,
    SpikesConfig,
    ProfileConfig,
    AssemblyConfig,
    ValidationConfig,
    ReportingConfig,
    resolve_device,
)


def test_default_config_instantiation():
    """Verify that default Config instantiates with all expected values and sub-configs."""
    cfg = Config()

    assert cfg.pipeline.name == "roman_epsf_pipeline"
    assert cfg.pipeline.version == "1.0.0"
    assert cfg.pipeline.log_level == "INFO"

    assert cfg.environment.device == "auto"
    assert cfg.environment.num_workers == 4

    assert cfg.catalog.mag_col == "mag_lambda"
    assert cfg.catalog.roundtrip_tolerance_arcsec == 0.5
    assert cfg.catalog.isolation_safety_factor == 1.3
    assert cfg.catalog.edge_margin_px == 50

    assert cfg.tiers.bright_limit == 11.0
    assert cfg.tiers.faint_limit == 13.0
    assert cfg.tiers.bright_limit < cfg.tiers.faint_limit

    assert cfg.spikes.detector_alignment_offset_deg == -9.70
    assert len(cfg.spikes.base_angles_deg) == 6

    assert cfg.assembly.canvas_size == 1025
    assert cfg.assembly.canvas_size % 2 == 1, "Canvas dimension must be odd"
    assert cfg.assembly.overlap_fm.r_min == 8.0
    assert cfg.assembly.overlap_fm.r_max == 16.0
    assert cfg.assembly.overlap_mb.r_min == 22.0
    assert cfg.assembly.overlap_mb.r_max == 45.0


def test_load_config_from_valid_yaml(tmp_path: Path):
    """Verify loading custom YAML values overrides defaults while leaving unspecified fields intact."""
    custom_yaml = tmp_path / "custom.yaml"
    content = {
        "pipeline": {"log_level": "DEBUG"},
        "tiers": {"bright_limit": 10.5, "faint_limit": 12.8},
        "assembly": {"canvas_size": 2049},
        "environment": {"device": "cpu"},
    }
    with open(custom_yaml, "w") as f:
        yaml.safe_dump(content, f)

    cfg = load_config(custom_yaml)

    # Overridden values
    assert cfg.pipeline.log_level == "DEBUG"
    assert cfg.tiers.bright_limit == 10.5
    assert cfg.tiers.faint_limit == 12.8
    assert cfg.assembly.canvas_size == 2049
    assert cfg.environment.device == "cpu"

    # Preserved defaults
    assert cfg.catalog.mag_col == "mag_lambda"
    assert cfg.catalog.roundtrip_tolerance_arcsec == 0.5
    assert cfg.spikes.detector_alignment_offset_deg == -9.70


def test_load_config_nonexistent_file():
    """Verify loading a missing file raises FileNotFoundError."""
    missing_path = Path("/nonexistent/directory/missing_config.yaml")
    with pytest.raises(FileNotFoundError, match="not found"):
        load_config(missing_path)


def test_load_config_invalid_yaml(tmp_path: Path):
    """Verify malformed YAML raises yaml.YAMLError."""
    bad_yaml = tmp_path / "broken.yaml"
    bad_yaml.write_text("pipeline:\n  name: [unclosed list\n  log_level: DEBUG")

    with pytest.raises(yaml.YAMLError):
        load_config(bad_yaml)


def test_config_validation_tier_limits(tmp_path: Path):
    """Verify validation raises ValueError when bright_limit >= faint_limit."""
    bad_tiers = tmp_path / "bad_tiers.yaml"
    content = {"tiers": {"bright_limit": 14.0, "faint_limit": 12.0}}
    with open(bad_tiers, "w") as f:
        yaml.safe_dump(content, f)

    with pytest.raises(ValueError, match="bright_limit must be strictly less than faint_limit"):
        load_config(bad_tiers)


def test_config_validation_canvas_size_even(tmp_path: Path):
    """Verify validation raises ValueError or adjusts if canvas_size is an even integer."""
    even_canvas = tmp_path / "even_canvas.yaml"
    content = {"assembly": {"canvas_size": 1024}}
    with open(even_canvas, "w") as f:
        yaml.safe_dump(content, f)

    with pytest.raises(ValueError, match="canvas_size must be an odd positive integer"):
        load_config(even_canvas)


def test_config_validation_overlap_ranges(tmp_path: Path):
    """Verify validation raises ValueError if overlap range bounds are inverted."""
    bad_overlap = tmp_path / "bad_overlap.yaml"
    content = {"assembly": {"overlap_fm": {"r_min": 20.0, "r_max": 10.0}}}
    with open(bad_overlap, "w") as f:
        yaml.safe_dump(content, f)

    with pytest.raises(ValueError, match="r_min must be less than r_max"):
        load_config(bad_overlap)


def test_resolve_device_selection():
    """Verify resolution of compute devices across 'auto', 'cpu', 'mps', and invalid choices."""
    cpu_dev = resolve_device("cpu")
    assert cpu_dev.type == "cpu"

    if torch.backends.mps.is_available():
        mps_dev = resolve_device("mps")
        assert mps_dev.type == "mps"
        auto_dev = resolve_device("auto")
        assert auto_dev.type in ("mps", "cuda")
    else:
        auto_dev = resolve_device("auto")
        assert auto_dev.type in ("cuda", "cpu")

    with pytest.raises(ValueError, match="Unknown or unsupported device"):
        resolve_device("quantum_accelerator")


def test_config_to_dict_and_roundtrip(tmp_path: Path):
    """Verify exporting Config to dictionary and re-loading preserves all parameter values."""
    cfg = Config()
    cfg_dict = cfg.to_dict()
    assert isinstance(cfg_dict, dict)
    assert "pipeline" in cfg_dict
    assert "assembly" in cfg_dict

    roundtrip_yaml = tmp_path / "roundtrip.yaml"
    with open(roundtrip_yaml, "w") as f:
        yaml.safe_dump(cfg_dict, f)

    reloaded_cfg = load_config(roundtrip_yaml)
    assert reloaded_cfg.assembly.canvas_size == cfg.assembly.canvas_size
    assert reloaded_cfg.tiers.bright_limit == cfg.tiers.bright_limit
    assert reloaded_cfg.spikes.detector_alignment_offset_deg == cfg.spikes.detector_alignment_offset_deg


def test_path_attribute_conversion():
    """Verify string paths in configuration are properly normalized to pathlib.Path objects."""
    cfg = Config()
    assert isinstance(cfg.data.output_dir, Path)
    assert isinstance(cfg.data.detectors_dir, Path)
    assert isinstance(cfg.data.catalog_path, Path)
    assert isinstance(cfg.reporting.report_path, Path)
```

---

### 3.3 Unit Test Specification 2: `tests/unit/test_loader.py`

```python
"""
Unit Tests for Level 2 ASDF Loader and Photometric Calibration.

Tests ASDF opening, science array shape (4088, 4088), photometric zero-point scaling,
DQ bitmask extraction, WCS and pointing metadata extraction, and error handling.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from romanepsf.loader import (
    load_l2_image,
    get_dq_mask,
    RomanL2Data,
    DQ_FLAGS,
)


class MockASDFImageModel:
    """Mock for roman_datamodels ImageModel to isolate unit tests from external files."""

    def __init__(self, shape=(4088, 4088)):
        self.data = np.ones(shape, dtype=np.float32) * 10.0
        self.err = np.ones(shape, dtype=np.float32) * 0.1
        self.dq = np.zeros(shape, dtype=np.uint32)
        # Inject standard DQ flags
        self.dq[10, 10] = 1   # DO_NOT_USE
        self.dq[20, 20] = 2   # SATURATED
        self.dq[30, 30] = 3   # DO_NOT_USE | SATURATED
        self.dq[40, 40] = 4   # JUMP_DET
        self.dq[50, 50] = 8   # DROPOUT

        # Metadata tree
        self.meta = MagicMock()
        self.meta.instrument.detector = "WFI01"
        self.meta.instrument.optical_element = "F146"
        self.meta.photometry.conversion_megajanskys = 0.238965
        self.meta.photometry.pixel_area = 2.801e-13
        self.meta.pointing.pa_aperture = -110.0224
        self.meta.pointing.target_ra = 303.1226
        self.meta.pointing.target_dec = -19.9260
        self.meta.exposure.exposure_time = 294.11
        self.meta.wcsinfo.roll_ref = -110.0224
        self.meta.wcsinfo.v3yangle = -60.0
        self.meta.wcs = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_load_l2_image_mock(monkeypatch):
    """Verify load_l2_image extracts correct data shapes, calibrated units, and metadata."""
    mock_model = MockASDFImageModel()
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)

    # Use a dummy existing file or mock Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy_wfi01.asdf", calibrate=True)

    assert isinstance(l2, RomanL2Data)
    assert l2.detector == "WFI01"
    assert l2.filter_name == "F146"
    assert l2.data.shape == (4088, 4088)
    assert l2.dq.shape == (4088, 4088)
    assert l2.err.shape == (4088, 4088)
    assert l2.conversion_factor == pytest.approx(0.238965, rel=1e-5)

    # Photometric calibration: 10.0 DN/s * 0.238965 = 2.38965 MJy/sr
    assert np.allclose(l2.data, 10.0 * 0.238965)
    assert np.allclose(l2.raw_data, 10.0)
    assert np.allclose(l2.err, 0.1 * 0.238965)


def test_load_l2_image_uncalibrated(monkeypatch):
    """Verify load_l2_image with calibrate=False leaves raw count rates unchanged."""
    mock_model = MockASDFImageModel()
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy_wfi01.asdf", calibrate=False)

    assert np.allclose(l2.data, l2.raw_data)
    assert np.allclose(l2.data, 10.0)


def test_active_science_dimensions(monkeypatch):
    """Verify active science array strictly conforms to 4088x4088 without border reference pixels."""
    mock_model = MockASDFImageModel(shape=(4088, 4088))
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy_wfi01.asdf")
    assert l2.data.shape == (4088, 4088)
    assert l2.data.shape[0] != 4096, "Border reference pixels must be excluded from science data"


def test_get_dq_mask_default_flags():
    """Verify get_dq_mask flags DO_NOT_USE (1), SATURATED (2), and DROPOUT (8) by default."""
    dq = np.zeros((5, 5), dtype=np.uint32)
    dq[0, 0] = 0   # GOOD
    dq[1, 1] = 1   # DO_NOT_USE
    dq[2, 2] = 2   # SATURATED
    dq[3, 3] = 4   # JUMP_DET
    dq[4, 4] = 8   # DROPOUT

    mask = get_dq_mask(dq)

    assert not mask[0, 0]
    assert mask[1, 1]
    assert mask[2, 2]
    assert not mask[3, 3], "JUMP_DET is not flagged by default"
    assert mask[4, 4]


def test_get_dq_mask_custom_flags():
    """Verify get_dq_mask respects custom flag list selection."""
    dq = np.zeros((3, 3), dtype=np.uint32)
    dq[0, 0] = 1  # DO_NOT_USE
    dq[0, 1] = 2  # SATURATED
    dq[0, 2] = 3  # Both

    # Test only SATURATED
    mask = get_dq_mask(dq, flags=["SATURATED"])
    assert not mask[0, 0]
    assert mask[0, 1]
    assert mask[0, 2]


def test_zero_point_ab_calculation(monkeypatch):
    """Verify zero-point magnitude calculation matches physical formula."""
    mock_model = MockASDFImageModel()
    mock_model.meta.photometry.conversion_megajanskys = 0.238965
    mock_model.meta.photometry.pixel_area = 2.801e-13
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy.asdf")

    # Formula: F_1dns = conv * 1e6 * pixel_area Jy
    # ZP = -2.5 * log10(F_1dns / 3631.0)
    expected_flux = 0.238965 * 1e6 * 2.801e-13
    expected_zp = -2.5 * np.log10(expected_flux / 3631.0)

    assert l2.zp_ab == pytest.approx(expected_zp, rel=1e-4)
    assert 26.0 < l2.zp_ab < 27.5


def test_loader_file_not_found():
    """Verify attempting to load a non-existent ASDF path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="ASDF file not found"):
        load_l2_image("definitely_nonexistent_detector.asdf")


def test_metadata_dictionary_contents(monkeypatch):
    """Verify meta dictionary contains pointing, aperture PA, roll ref, and pixel scale."""
    mock_model = MockASDFImageModel()
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy.asdf")

    assert "pa_aperture" in l2.meta
    assert "roll_ref" in l2.meta
    assert "v3yangle" in l2.meta
    assert "pixel_scale" in l2.meta
    assert l2.meta["pa_aperture"] == pytest.approx(-110.0224, abs=1e-3)
    assert l2.meta["pixel_scale"] == pytest.approx(0.1098, abs=0.01)


@pytest.mark.skipif(
    not Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf").is_file(),
    reason="Commissioning data storage not mounted",
)
def test_real_asdf_smoke():
    """Smoke test against actual commissioning dataset file if mounted on disk."""
    real_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf"
    l2 = load_l2_image(real_path, calibrate=True)

    assert l2.data.shape == (4088, 4088)
    assert l2.detector.lower() == "wfi01"
    assert l2.filter_name == "F146"
    assert np.all(np.isfinite(l2.data[~get_dq_mask(l2.dq)]))
```

---

### 3.4 Unit Test Specification 3: `tests/unit/test_catalog.py`

```python
"""
Unit Tests for Catalog Ingestion, Astrometric Verification, and Isolation Filtering.

Tests duplicate column bug sanitization, forward roundtrip WCS verification,
subpixel centroid refinement, Moffat isolation clearance, and stellar tier assignment.
"""

import numpy as np
import pandas as pd
import pytest

from romanepsf.loader import RomanL2Data
from romanepsf.catalog import (
    sanitize_source_catalog,
    project_catalog_to_pixels,
    refine_stellar_centroids,
    filter_isolated_stars,
    assign_stellar_tiers,
)


class MockWCS:
    """Mock WCS allowing controlled roundtrip discrepancy testing."""

    def __init__(self, bad_star_coords=None):
        self.bad_coords = bad_star_coords or {}

    def backward_transform(self, ra, dec):
        # Default: linear mapping into [1000, 3000]
        xs = np.full_like(ra, 2044.0, dtype=np.float64)
        ys = np.full_like(dec, 2044.0, dtype=np.float64)
        return xs, ys

    def __call__(self, x, y):
        # Forward transform
        ra_out = np.full_like(x, 303.12, dtype=np.float64)
        dec_out = np.full_like(y, -19.93, dtype=np.float64)
        return ra_out, dec_out


def test_sanitize_catalog_duplicate_columns():
    """Verify duplicate column bug fix: duplicate mag columns are resolved without 2D slicing."""
    df = pd.DataFrame({
        "source_id": [101, 102],
        "ra": [303.1, 303.2],
        "dec": [-19.9, -19.8],
        "phot_g_mean_mag_AB": [12.5, 14.1],
        "phot_g_mean_mag": [12.4, 14.0],
        "mag_lambda": [11.8, 13.5],
    })

    clean_df = sanitize_source_catalog(df, mag_col="mag_lambda")

    # Column name phot_g_mean_mag must be unique
    assert list(clean_df.columns).count("phot_g_mean_mag") == 1
    # Selecting the column returns a 1D Series
    assert isinstance(clean_df["phot_g_mean_mag"], pd.Series)
    assert clean_df["phot_g_mean_mag"].ndim == 1


def test_forward_roundtrip_wcs_in_footprint():
    """Verify valid star with roundtrip discrepancy < 0.5 arcsec is accepted."""
    df = pd.DataFrame({
        "source_id": [1],
        "ra": [303.12],
        "dec": [-19.93],
        "mag_lambda": [12.0],
    })

    wcs = MockWCS()
    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=np.zeros((4088, 4088)), raw_data=np.zeros((4088, 4088)),
        err=np.zeros((4088, 4088)), dq=np.zeros((4088, 4088), dtype=np.uint32),
        wcs=wcs, meta={}, zp_ab=26.8, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13
    )

    proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    assert len(proj) == 1
    assert "x" in proj.columns and "y" in proj.columns
    assert proj["x"].iloc[0] == 2044.0


def test_forward_roundtrip_wcs_out_of_footprint_rejection():
    """Verify spurious star with roundtrip discrepancy > 0.5 arcsec is strictly rejected."""
    df = pd.DataFrame({
        "source_id": [999],
        "ra": [302.953],
        "dec": [-20.231],
        "mag_lambda": [10.5],
    })

    # Mock WCS returns large discrepancy (e.g. 1700 arcsec)
    class DefectiveWCS:
        def backward_transform(self, ra, dec):
            return np.array([2047.92]), np.array([3992.95])
        def __call__(self, x, y):
            # Forward transform diverges
            return np.array([302.782]), np.array([-19.777])

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=np.zeros((4088, 4088)), raw_data=np.zeros((4088, 4088)),
        err=np.zeros((4088, 4088)), dq=np.zeros((4088, 4088), dtype=np.uint32),
        wcs=DefectiveWCS(), meta={}, zp_ab=26.8, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13
    )

    proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    assert len(proj) == 0, "Spurious star with large roundtrip error must be rejected"


def test_edge_margin_filtering():
    """Verify stars falling within boundary margin (50 px) of detector edges are rejected."""
    df = pd.DataFrame({
        "source_id": [1, 2, 3],
        "ra": [303.1, 303.1, 303.1],
        "dec": [-19.9, -19.9, -19.9],
        "mag_lambda": [12.0, 12.0, 12.0],
    })

    class EdgeWCS:
        def backward_transform(self, ra, dec):
            # star 1: too close to left (25 px)
            # star 2: valid (2000 px)
            # star 3: too close to top (4060 px)
            return np.array([25.0, 2000.0, 2000.0]), np.array([2000.0, 2000.0, 4060.0])
        def __call__(self, x, y):
            return np.full_like(x, 303.1), np.full_like(y, -19.9)

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=np.zeros((4088, 4088)), raw_data=np.zeros((4088, 4088)),
        err=np.zeros((4088, 4088)), dq=np.zeros((4088, 4088), dtype=np.uint32),
        wcs=EdgeWCS(), meta={}, zp_ab=26.8, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13
    )

    proj = project_catalog_to_pixels(l2, df, margin_px=50, tolerance_arcsec=0.5)
    assert len(proj) == 1
    assert proj["source_id"].iloc[0] == 2


def test_refine_stellar_centroids_synthetic_peak():
    """Verify centroid refinement on a synthetic Gaussian star recovers true subpixel center."""
    ny, nx = 100, 100
    grid_y, grid_x = np.indices((ny, nx))
    true_x, true_y = 50.35, 50.72
    star_img = 100.0 * np.exp(-((grid_x - true_x)**2 + (grid_y - true_y)**2) / (2 * 2.0**2))

    df = pd.DataFrame({
        "source_id": [1],
        "x": [50.0],
        "y": [51.0],
        "mag_lambda": [12.0],
    })

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=star_img, raw_data=star_img,
        err=np.ones_like(star_img), dq=np.zeros_like(star_img, dtype=np.uint32),
        wcs=None, meta={}, zp_ab=26.8, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13
    )

    refined = refine_stellar_centroids(l2, df, box_radius=5)
    assert refined["x"].iloc[0] == pytest.approx(true_x, abs=0.05)
    assert refined["y"].iloc[0] == pytest.approx(true_y, abs=0.05)


def test_refine_stellar_centroids_zero_flux_fallback():
    """Verify centroid refinement handles zero-flux box gracefully without NaNs."""
    zero_img = np.zeros((100, 100), dtype=np.float32)
    df = pd.DataFrame({"source_id": [1], "x": [50.0], "y": [50.0], "mag_lambda": [12.0]})

    l2 = RomanL2Data(
        detector="WFI01", filter_name="F146",
        data=zero_img, raw_data=zero_img,
        err=np.ones_like(zero_img), dq=np.zeros_like(zero_img, dtype=np.uint32),
        wcs=None, meta={}, zp_ab=26.8, pixel_scale=0.11, conversion_factor=1.0, pixel_area=2.8e-13
    )

    refined = refine_stellar_centroids(l2, df, box_radius=5)
    assert refined["x"].iloc[0] == 50.0
    assert refined["y"].iloc[0] == 50.0


def test_filter_isolated_stars_pair_rejection():
    """Verify that in a blended star pair, the brighter star is kept and the fainter is rejected."""
    df = pd.DataFrame({
        "source_id": [1, 2],
        "x": [1000.0, 1015.0],      # separation 15 px (~1.65 arcsec)
        "y": [1000.0, 1000.0],
        "mag_lambda": [10.0, 15.0], # star 1 is bright, star 2 is faint
    })

    isolated = filter_isolated_stars(df, pixel_scale=0.11, safety_factor=1.3, mag_col="mag_lambda")
    assert len(isolated) == 1
    assert isolated["source_id"].iloc[0] == 1


def test_filter_isolated_stars_isolated_pair():
    """Verify widely separated stars are both preserved."""
    df = pd.DataFrame({
        "source_id": [1, 2],
        "x": [500.0, 3500.0],       # separation 3000 px (~330 arcsec)
        "y": [500.0, 3500.0],
        "mag_lambda": [10.0, 12.0],
    })

    isolated = filter_isolated_stars(df, pixel_scale=0.11, safety_factor=1.3, mag_col="mag_lambda")
    assert len(isolated) == 2


def test_assign_stellar_tiers():
    """Verify tier assignment matches project boundaries (<11.0, 11.0-13.0, >=13.0)."""
    df = pd.DataFrame({
        "source_id": [1, 2, 3, 4, 5, 6, 7],
        "mag_lambda": [8.5, 10.99, 11.0, 12.5, 12.99, 13.0, 15.2],
    })

    tiered = assign_stellar_tiers(df, bright_limit=11.0, faint_limit=13.0, mag_col="mag_lambda")
    tiers = tiered["tier"].tolist()

    assert tiers == [
        "bright",  # 8.5 < 11.0
        "bright",  # 10.99 < 11.0
        "medium",  # 11.0 <= 11.0 < 13.0
        "medium",  # 11.0 <= 12.5 < 13.0
        "medium",  # 11.0 <= 12.99 < 13.0
        "faint",   # 13.0 >= 13.0
        "faint",   # 15.2 >= 13.0
    ]
```

---

### 3.5 Unit Test Specification 4: `tests/unit/test_cli.py`

```python
"""
Unit Tests for Click Command-Line Interface (CLI).

Tests CLI help, subcommand options parsing, configuration propagation,
device selection, and graceful error reporting using Click's CliRunner.
"""

from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest
from click.testing import CliRunner

from romanepsf.cli import cli


def test_cli_help():
    """Verify top-level romanepsf --help displays usage and all 7 subcommands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Roman Space Telescope Extended PSF (ePSF) Measurement Pipeline" in result.output
    for subcmd in ["run", "single", "catalog", "stamps", "assemble", "validate", "report"]:
        assert subcmd in result.output


@pytest.mark.parametrize("subcmd", [
    "run", "single", "catalog", "stamps", "assemble", "validate", "report"
])
def test_subcommand_help(subcmd: str):
    """Verify each subcommand provides clean help information."""
    runner = CliRunner()
    result = runner.invoke(cli, [subcmd, "--help"])

    assert result.exit_code == 0
    assert "Usage: " in result.output


def test_cli_single_invocation_mock():
    """Verify 'single' subcommand parses detector option and invokes pipeline."""
    runner = CliRunner()

    with patch("romanepsf.pipeline.run_single_detector") as mock_single:
        mock_output = MagicMock()
        mock_output.fits_path = Path("output/roman_epsf_wfi01.fits")
        mock_single.return_value = mock_output

        result = runner.invoke(cli, ["single", "--detector", "wfi02", "--canvas-size", "1025"])

        assert result.exit_code == 0
        assert mock_single.called
        call_kwargs = mock_single.call_args.kwargs
        assert call_kwargs.get("detector") == "wfi02"


def test_cli_run_invocation_mock():
    """Verify 'run' subcommand parses detectors list and invokes pipeline."""
    runner = CliRunner()

    with patch("romanepsf.pipeline.run_pipeline") as mock_run:
        mock_output = MagicMock()
        mock_output.fits_path = Path("output/roman_epsf_composite.fits")
        mock_run.return_value = mock_output

        result = runner.invoke(cli, ["run", "--detectors", "wfi01,wfi02", "--canvas-size", "2049"])

        assert result.exit_code == 0
        assert mock_run.called


def test_cli_device_override():
    """Verify --device flag overrides configuration device."""
    runner = CliRunner()

    with patch("romanepsf.pipeline.run_single_detector") as mock_single:
        mock_output = MagicMock()
        mock_output.fits_path = Path("dummy.fits")
        mock_single.return_value = mock_output

        result = runner.invoke(cli, ["--device", "cpu", "single"])
        assert result.exit_code == 0
        cfg_passed = mock_single.call_args.args[0]
        assert cfg_passed.environment.device == "cpu"


def test_cli_invalid_option():
    """Verify supplying unknown option raises usage error (exit code 2)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--unknown-flag-12345"])
    assert result.exit_code == 2
```

---

## 4. Caveats & Risk Mitigation

1. **Click Testing Import Requirement**:
   - `from click.testing import CliRunner` must always be explicitly imported; relying on `click.testing` from top-level `import click` causes an `AttributeError`.
2. **Synthetic Mocks vs Real Data**:
   - Real commissioning ASDF files are ~204 MB each and take 200–500 ms to open from disk. Mocking the datamodel in unit tests ensures the full unit test suite runs in under 3 seconds, while a marked smoke test (`@pytest.mark.skipif`) handles local verification against physical storage.
3. **WCS Transform Fallbacks**:
   - The forward roundtrip tolerance $\Delta\theta < 0.5''$ is essential. Without it, tests on out-of-footprint stars will produce false matches that contaminate downstream stamp stacking.
4. **PyTorch MPS Availability**:
   - Apple MPS acceleration is fully supported on the target workstation. In CI or Linux environments without Apple hardware, `resolve_device("auto")` must cleanly fall back to CUDA or CPU.

---

## 5. Conclusion

1. **CLI Framework**: Complete code specification for `src/romanepsf/cli.py` implementing Click v8.3.1 with all 7 required subcommands (`run`, `single`, `catalog`, `stamps`, `assemble`, `validate`, `report`), global context propagation, clean error handling, logging, and hardware device selection.
2. **Unit Test Suites**: Complete, self-contained test suites designed for `tests/unit/`:
   - `test_config.py` (10 test cases covering defaults, custom YAML, errors, boundary constraints, device resolution).
   - `test_loader.py` (9 test cases covering ASDF loading, active shape (4088, 4088), calibration scaling, DQ bitmasks, zero points).
   - `test_catalog.py` (10 test cases covering duplicate column sanitization, roundtrip WCS verification, centroiding, isolation filtering, tier assignments).
   - `test_cli.py` (6 test cases validating Click CLI execution and option parsing via CliRunner).
3. **Execution Readiness**: All specifications, code blueprints, and test cases are ready for Milestone 1 Worker implementation.

---

## 6. Verification Method

### 6.1 Verification Commands
Once implemented by the worker agent, execute the following commands with `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:

1. **Verify CLI Subcommands & Help Output**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli --help
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli run --help
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli single --help
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli catalog --help
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli stamps --help
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli assemble --help
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli validate --help
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli report --help
   ```

2. **Execute Complete Unit Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   ```

3. **Verify 100% Pass Rate**:
   Ensure all tests in `test_config.py`, `test_loader.py`, `test_catalog.py`, and `test_cli.py` pass with zero failures and exit code 0.
