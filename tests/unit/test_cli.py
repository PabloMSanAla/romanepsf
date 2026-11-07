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
    mock_pipeline = MagicMock()
    mock_output = MagicMock()
    mock_output.fits_path = Path("output/roman_epsf_wfi01.fits")
    mock_pipeline.run_single_detector.return_value = mock_output

    with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
        result = runner.invoke(cli, ["single", "--detector", "wfi02", "--canvas-size", "1025"])

        assert result.exit_code == 0
        assert mock_pipeline.run_single_detector.called
        call_kwargs = mock_pipeline.run_single_detector.call_args.kwargs
        assert call_kwargs.get("detector") == "wfi02"


def test_cli_run_invocation_mock():
    """Verify 'run' subcommand parses detectors list and invokes pipeline."""
    runner = CliRunner()
    mock_pipeline = MagicMock()
    mock_output = MagicMock()
    mock_output.fits_path = Path("output/roman_epsf_composite.fits")
    mock_pipeline.run_pipeline.return_value = mock_output

    with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
        result = runner.invoke(cli, ["run", "--detectors", "wfi01,wfi02", "--canvas-size", "2049"])

        assert result.exit_code == 0
        assert mock_pipeline.run_pipeline.called


def test_cli_device_override():
    """Verify --device flag overrides configuration device."""
    runner = CliRunner()
    mock_pipeline = MagicMock()
    mock_output = MagicMock()
    mock_output.fits_path = Path("dummy.fits")
    mock_pipeline.run_single_detector.return_value = mock_output

    with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
        result = runner.invoke(cli, ["--device", "cpu", "single"])
        assert result.exit_code == 0
        cfg_passed = mock_pipeline.run_single_detector.call_args.args[0]
        assert cfg_passed.environment.device == "cpu"


def test_cli_invalid_option():
    """Verify supplying unknown option raises usage error (exit code 2)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--unknown-flag-12345"])
    assert result.exit_code == 2


def test_cli_single_full_options(tmp_path):
    """Verify 'single' subcommand parses all enhanced flags."""
    runner = CliRunner()
    mock_pipeline = MagicMock()
    mock_output = MagicMock()
    mock_output.fits_path = tmp_path / "out" / "roman_epsf_wfi01.fits"
    mock_pipeline.run_single_detector.return_value = mock_output

    asdf_file = tmp_path / "test.asdf"
    asdf_file.touch()
    cat_file = tmp_path / "cat.csv"
    cat_file.touch()
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text("data:\n  filter_name: F146\n")

    with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
        result = runner.invoke(cli, [
            "single",
            "--detector", "wfi05",
            "--asdf", str(asdf_file),
            "--catalog", str(cat_file),
            "--config", str(cfg_file),
            "--canvas-size", "1025",
            "--output-dir", str(tmp_path / "out"),
        ])

        assert result.exit_code == 0
        assert mock_pipeline.run_single_detector.called
        kwargs = mock_pipeline.run_single_detector.call_args.kwargs
        assert kwargs.get("detector") == "wfi05"
        assert kwargs.get("asdf_path") == asdf_file
        assert kwargs.get("catalog_path") == cat_file
        assert kwargs.get("canvas_size") == 1025


def test_cli_run_full_options(tmp_path):
    """Verify 'run' subcommand parses all enhanced flags."""
    runner = CliRunner()
    mock_pipeline = MagicMock()
    mock_output = MagicMock()
    mock_output.fits_path = tmp_path / "out" / "roman_epsf_composite.fits"
    mock_pipeline.run_pipeline.return_value = mock_output

    in_dir = tmp_path / "asdf_dir"
    in_dir.mkdir()
    cat_file = tmp_path / "cat.csv"
    cat_file.touch()
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text("data:\n  filter_name: F146\n")

    with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
        result = runner.invoke(cli, [
            "run",
            "--input-dir", str(in_dir),
            "--catalog", str(cat_file),
            "--config", str(cfg_file),
            "--output-dir", str(tmp_path / "out"),
            "--canvas-size", "1025",
            "--device", "cpu",
            "--detectors", "wfi01,wfi02",
            "--num-workers", "2",
        ])

        assert result.exit_code == 0
        assert mock_pipeline.run_pipeline.called
        cfg_passed = mock_pipeline.run_pipeline.call_args.args[0]
        assert cfg_passed.data.detectors_dir == in_dir
        assert cfg_passed.data.catalog_path == cat_file
        assert cfg_passed.data.output_dir == tmp_path / "out"
        assert cfg_passed.assembly.canvas_size == 1025
        assert cfg_passed.environment.device == "cpu"
        assert cfg_passed.data.detectors == ["wfi01", "wfi02"]
        assert cfg_passed.environment.num_workers == 2
