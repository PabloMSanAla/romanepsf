"""
Blueprint patch for src/romanepsf/cli.py single command.

Replaces existing single_command in src/romanepsf/cli.py (lines 192-248).
Adds requested flags:
- --detector
- --asdf
- --catalog
- --config
- --output-dir
- --canvas-size
Maintains 100% backward compatibility with existing tests and Click invocation patterns.
"""

# BEFORE (lines 192-248 of src/romanepsf/cli.py):
# @cli.command("single", help="Run single-detector validation on WFI01.")
# @click.option(
#     "--detector",
#     default="wfi01",
#     show_default=True,
#     help="Detector SCA identifier (e.g. 'wfi01').",
# )
# @click.option(
#     "--canvas-size",
#     "-s",
#     type=int,
#     default=None,
#     help="Canvas dimension (e.g. 1025).",
# )
# @click.option(
#     "--output-dir",
#     "-o",
#     type=click.Path(file_okay=False, path_type=Path),
#     default=None,
#     help="Output directory for single-detector artifacts.",
# )
# @click.pass_context
# def single_command(
#     ctx: click.Context,
#     detector: str,
#     canvas_size: Optional[int],
#     output_dir: Optional[Path],
# ):
# ...

# AFTER:
PROPOSED_SINGLE_COMMAND = '''
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
    # If subcommand --config was provided, load that config; otherwise use global ctx config
    if sub_config is not None:
        cfg: Config = load_config(sub_config)
    else:
        cfg: Config = ctx.obj["config"]

    logger: logging.Logger = ctx.obj["logger"]

    cfg.data.detectors = [detector.lower()]
    if canvas_size is not None:
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
'''
