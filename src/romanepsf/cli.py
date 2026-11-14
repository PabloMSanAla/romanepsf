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

from __future__ import annotations

import sys
import os
import logging
import warnings
from pathlib import Path
from typing import Optional, List
import click

# Suppress harmless ASDF package version warnings when reading newer extension schemas
try:
    from asdf.exceptions import AsdfPackageVersionWarning
    warnings.filterwarnings("ignore", category=AsdfPackageVersionWarning)
except ImportError:
    pass
warnings.filterwarnings("ignore", message=r".*was created with extension URI.*")
warnings.filterwarnings("ignore", message=r".*AsdfPackageVersionWarning.*")

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
        is_explicit = ctx.get_parameter_source("config") != click.core.ParameterSource.DEFAULT
        if is_explicit:
            if not config.is_file():
                raise FileNotFoundError(f"Configuration file not found: {config}")
            cfg_file = config
        else:
            cfg_file = config if config.is_file() else None
        cfg = load_config(cfg_file)
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


@cli.command("run", help="Execute complete end-to-end ePSF measurement pipeline across all 18 detectors or batch SCA mode.")
@click.option(
    "--file-list",
    "-fl",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Text file listing input Level 2 ASDF detector files (activates batch SCA pipeline).",
)
@click.option(
    "--sca",
    "-s",
    type=str,
    default=None,
    help="Target Sensor Chip Assembly (e.g. 'wfi01') when processing file list.",
)
@click.option(
    "--input-dir",
    "-i",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory containing Level 2 ASDF detector files.",
)
@click.option(
    "--catalog",
    "-cat",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to precomputed source catalog CSV.",
)
@click.option(
    "--cache-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory for local HEALPix Parquet cache (default: 'cache/gaia_healpix').",
)
@click.option(
    "--config",
    "-c",
    "sub_config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to YAML configuration file (overrides global config).",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to store synthesized models, FITS outputs, and reports.",
)
@click.option(
    "--canvas-size",
    type=int,
    default=None,
    help="Composite ePSF canvas dimension (e.g. 1025 or 2049). Default: 1025.",
)
@click.option(
    "--device",
    "-d",
    type=click.Choice(["auto", "mps", "cuda", "cpu"], case_sensitive=False),
    default=None,
    help="Compute device for PyTorch operations ('auto', 'mps', 'cuda', 'cpu').",
)
@click.option(
    "--detectors",
    default=None,
    help="Comma-separated detectors list (e.g. 'wfi01,wfi02') or 'all'.",
)
@click.option(
    "--num-workers",
    "-w",
    type=int,
    default=None,
    help="Number of parallel worker processes.",
)
@click.option(
    "--debug",
    "debug_stars",
    type=int,
    default=None,
    help="Debug mode: process X stars across tiers and generate debug plots in output/debug/.",
)
@click.pass_context
def run_command(
    ctx: click.Context,
    file_list: Optional[Path],
    sca: Optional[str],
    input_dir: Optional[Path],
    catalog: Optional[Path],
    cache_dir: Optional[Path],
    sub_config: Optional[Path],
    output_dir: Optional[Path],
    canvas_size: Optional[int],
    device: Optional[str],
    detectors: Optional[str],
    num_workers: Optional[int],
    debug_stars: Optional[int] = None,
):
    """Execute complete end-to-end ePSF pipeline across all designated detectors or file list."""
    if sub_config is not None:
        cfg = load_config(sub_config)
        ctx.obj["config"] = cfg
    else:
        cfg: Config = ctx.obj["config"]

    logger: logging.Logger = ctx.obj["logger"]

    if file_list is not None:
        cfg.data.file_list = file_list
    if sca is not None:
        cfg.data.sca = sca
    if cache_dir is not None:
        cfg.data.gaia_cache_dir = cache_dir
    if input_dir is not None:
        cfg.data.detectors_dir = input_dir
    if catalog is not None:
        cfg.data.catalog_path = catalog
    if output_dir is not None:
        cfg.data.output_dir = output_dir
    if canvas_size is not None:
        if canvas_size > 0 and canvas_size % 2 == 0:
            logger.warning(
                f"Even canvas size {canvas_size} provided; promoting to odd {canvas_size + 1}"
            )
            canvas_size = canvas_size + 1
        cfg.assembly.canvas_size = canvas_size
    if device is not None:
        cfg.environment.device = device.lower()
        ctx.obj["device"] = resolve_device(cfg.environment.device)
    if num_workers is not None:
        cfg.environment.num_workers = num_workers
    if debug_stars is not None:
        cfg.pipeline.debug = debug_stars
    if detectors is not None:
        if detectors.lower().strip() == "all":
            cfg.data.detectors = [f"wfi{i:02d}" for i in range(1, 19)]
        else:
            cfg.data.detectors = [d.strip().lower() for d in detectors.split(",") if d.strip()]
    elif cfg.data.detectors == ["wfi01"] or "all" in [str(d).lower() for d in cfg.data.detectors]:
        cfg.data.detectors = [f"wfi{i:02d}" for i in range(1, 19)]

    try:
        cfg.validate()
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        click.echo(f"Configuration validation failed: {e}", err=True)
        sys.exit(1)

    # If file list is specified, run the high-throughput batch SCA pipeline
    if cfg.data.file_list is not None:
        target_sca = cfg.data.sca or (cfg.data.detectors[0] if cfg.data.detectors else "wfi01")
        logger.info(
            f"Executing High-Throughput Batch SCA Pipeline for {target_sca.upper()} "
            f"using file list: {cfg.data.file_list}"
        )
        try:
            from romanepsf.pipeline import run_sca_batch_pipeline

            outputs = run_sca_batch_pipeline(
                files=cfg.data.file_list,
                sca_id=target_sca,
                cfg=cfg,
                output_dir=cfg.data.output_dir,
                canvas_size=cfg.assembly.canvas_size,
                num_workers=cfg.environment.num_workers,
                gaia_cache_dir=cfg.data.gaia_cache_dir,
                master_catalog_path=cfg.data.catalog_path,
                device=cfg.environment.device,
            )
            logger.info(
                f"Batch SCA pipeline completed successfully. Composite FITS model saved: {outputs.fits_path}"
            )
            return
        except Exception as e:
            logger.error(f"Batch SCA pipeline execution failed: {e}")
            if ctx.obj.get("verbose"):
                import traceback
                traceback.print_exc()
            sys.exit(1)

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


@cli.command("batch", help="High-throughput batch synthesis of 1 composite ePSF model for a specific SCA.")
@click.option(
    "--file-list",
    "-fl",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Text file listing paths to Level 2 ASDF detector files (one per line).",
)
@click.option(
    "--sca",
    "-s",
    type=str,
    default=None,
    help="Target Sensor Chip Assembly (e.g. 'wfi01'). Default: auto-detect from files.",
)
@click.option(
    "--config",
    "-c",
    "sub_config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to YAML configuration file.",
)
@click.option(
    "--catalog",
    "-cat",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to precomputed Gaia master catalog CSV/Parquet (optional).",
)
@click.option(
    "--cache-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory for local HEALPix Parquet cache (default: 'cache/gaia_healpix').",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to store synthesized models, FITS outputs, and logs.",
)
@click.option(
    "--canvas-size",
    type=int,
    default=None,
    help="Composite ePSF canvas dimension (e.g. 1025 or 2049). Default: 1025.",
)
@click.option(
    "--device",
    "-d",
    type=click.Choice(["auto", "mps", "cuda", "cpu"], case_sensitive=False),
    default=None,
    help="Compute device for PyTorch operations ('auto', 'mps', 'cuda', 'cpu').",
)
@click.option(
    "--num-workers",
    "-w",
    type=int,
    default=None,
    help="Number of parallel worker processes (e.g. 56).",
)
@click.option(
    "--debug",
    "debug_stars",
    type=int,
    default=None,
    help="Debug mode: process X stars across tiers and generate debug plots in output/debug/.",
)
@click.pass_context
def batch_command(
    ctx: click.Context,
    file_list: Path,
    sca: Optional[str],
    sub_config: Optional[Path],
    catalog: Optional[Path],
    cache_dir: Optional[Path],
    output_dir: Optional[Path],
    canvas_size: Optional[int],
    device: Optional[str],
    num_workers: Optional[int],
    debug_stars: Optional[int] = None,
):
    """Execute high-throughput batch pipeline synthesizing 1 composite ePSF model for a specific SCA."""
    if sub_config is not None:
        cfg = load_config(sub_config)
        ctx.obj["config"] = cfg
    else:
        cfg: Config = ctx.obj["config"]

    logger: logging.Logger = ctx.obj["logger"]

    cfg.data.file_list = file_list
    if sca is not None:
        cfg.data.sca = sca
    if cache_dir is not None:
        cfg.data.gaia_cache_dir = cache_dir
    if catalog is not None:
        cfg.data.catalog_path = catalog
    if output_dir is not None:
        cfg.data.output_dir = output_dir
    if canvas_size is not None:
        if canvas_size > 0 and canvas_size % 2 == 0:
            canvas_size += 1
        cfg.assembly.canvas_size = canvas_size
    if device is not None:
        cfg.environment.device = device.lower()
        ctx.obj["device"] = resolve_device(cfg.environment.device)
    if num_workers is not None:
        cfg.environment.num_workers = num_workers
    if debug_stars is not None:
        cfg.pipeline.debug = debug_stars

    try:
        cfg.validate()
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        click.echo(f"Configuration validation failed: {e}", err=True)
        sys.exit(1)

    target_sca = cfg.data.sca or (cfg.data.detectors[0] if cfg.data.detectors else "wfi01")
    logger.info(
        f"Starting Batch SCA Pipeline for {target_sca.upper()} "
        f"across file list: {file_list} with {cfg.environment.num_workers} workers"
    )

    try:
        from romanepsf.pipeline import run_sca_batch_pipeline

        outputs = run_sca_batch_pipeline(
            files=file_list,
            sca_id=target_sca,
            cfg=cfg,
            output_dir=cfg.data.output_dir,
            canvas_size=cfg.assembly.canvas_size,
            num_workers=cfg.environment.num_workers,
            gaia_cache_dir=cfg.data.gaia_cache_dir,
            master_catalog_path=cfg.data.catalog_path,
            device=cfg.environment.device,
        )
        logger.info(
            f"Batch SCA pipeline completed successfully. Composite FITS model saved: {outputs.fits_path}"
        )
    except Exception as e:
        logger.error(f"Batch SCA pipeline execution failed: {e}")
        if ctx.obj.get("verbose"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


cli.add_command(batch_command, name="batch-run")


@cli.command("single", help="Run single-detector validation (default: WFI01).")
@click.option(
    "--detector",
    "-d",
    default="wfi01",
    show_default=True,
    help="Detector SCA identifier (e.g. 'wfi01').",
)
@click.option(
    "--asdf",
    "asdf_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to input Level 2 ASDF image file.",
)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to source catalog CSV.",
)
@click.option(
    "--config",
    "-c",
    "sub_config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to YAML configuration file (overrides global config).",
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
    help="Output directory for single-detector artifacts.",
)
@click.pass_context
def single_command(
    ctx: click.Context,
    detector: str,
    asdf_path: Optional[Path],
    catalog_path: Optional[Path],
    sub_config: Optional[Path],
    canvas_size: Optional[int],
    output_dir: Optional[Path],
):
    """Run pipeline execution on a single detector (default: WFI01)."""
    if sub_config is not None:
        cfg: Config = load_config(sub_config)
    else:
        cfg: Config = ctx.obj["config"]

    logger: logging.Logger = ctx.obj["logger"]

    cfg.data.detectors = [detector.lower()]
    if canvas_size is not None:
        if canvas_size > 0 and canvas_size % 2 == 0:
            logger.warning(
                f"Even canvas size {canvas_size} provided; promoting to odd {canvas_size + 1}"
            )
            canvas_size = canvas_size + 1
        cfg.assembly.canvas_size = canvas_size
    if output_dir is not None:
        cfg.data.output_dir = output_dir
    if asdf_path is not None:
        cfg.data.detectors_dir = asdf_path.parent
    if catalog_path is not None:
        cfg.data.catalog_path = catalog_path

    try:
        cfg.validate()
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        click.echo(f"Configuration validation failed: {e}", err=True)
        sys.exit(1)

    logger.info(f"Executing single-detector run on: {detector.upper()}")
    try:
        from romanepsf.pipeline import run_single_detector

        outputs = run_single_detector(
            cfg,
            detector=detector.lower(),
            asdf_path=asdf_path,
            catalog_path=catalog_path,
            output_dir=output_dir,
            canvas_size=canvas_size,
        )
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

    try:
        cfg.validate()
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        click.echo(f"Configuration validation failed: {e}", err=True)
        sys.exit(1)

    out_fits = output_fits or (cfg.data.output_dir / "roman_epsf_composite.fits")
    out_fits.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Synthesizing composite 2D ePSF canvas ({cfg.assembly.canvas_size}x{cfg.assembly.canvas_size})")
    try:
        from romanepsf.assembly import assemble_composite_extended_psf
        from astropy.io import fits
        import numpy as np
        import pickle

        stamps_file = (stamps_dir or cfg.data.output_dir / "stamps" / "wfi01") / "stamps_by_tier.pkl"
        with open(stamps_file, "rb") as f:
            stamps_by_tier = pickle.load(f)

        extended_psf, diagnostics = assemble_composite_extended_psf(
            stamps_by_tier,
            output_size=cfg.assembly.output_size,
            cfg=cfg.assembly,
            device=ctx.obj["device"],
        )

        hdu = fits.PrimaryHDU(extended_psf.astype(np.float32))
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

        results = evaluate_epsf_validation(
            epsf_data,
            asdf_path=asdf_path,
            cfg=cfg.validation,
            output_dir=val_dir,
            save_residual_fits=True,
        )
        summary_path = val_dir / "validation_summary.json"
        with open(summary_path, "w") as f:
            json.dump(results.to_dict(), f, indent=2)

        logger.info(f"Validation finished ({results.overall_status}). Summary saved to {summary_path}")
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

        generate_publication_pdf_report(res_dir, pdf_path, cfg=cfg, dpi=dpi)
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
