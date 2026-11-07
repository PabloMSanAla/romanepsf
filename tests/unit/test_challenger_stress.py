"""
Adversarial Stress Test Suite for Milestone 1 (Challenger M1-2).

Empirically challenges:
1. Click CLI: invalid options, non-existent files, contradictory device flags,
   permission errors, SIGINT handling, and validation bypasses.
2. YAML Configuration Loader: deeply nested overrides, type mismatches, inverted
   intervals, non-mapping YAML documents, and float canvas sizes.
3. Level 2 ASDF Loader: truncated files, non-Roman ASDF files, unexpected shapes,
   missing WCS/DQ/ERR arrays, non-finite values, and mismatched array shapes.
"""

from __future__ import annotations

import tempfile
import stat
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import numpy as np
import pandas as pd
import yaml
from click.testing import CliRunner

from romanepsf.cli import cli
from romanepsf.config import load_config, Config, resolve_device
from romanepsf.loader import (
    load_l2_image,
    get_dq_mask,
    get_effective_mask,
    RomanL2Data,
)
from romanepsf.catalog import project_catalog_to_pixels, get_detector_sky_bounds


# ==============================================================================
# 1. Click CLI Adversarial Stress Tests
# ==============================================================================

class TestCLIStress:
    """Adversarial stress tests for the Click CLI."""

    def test_cli_unrecognized_global_option(self):
        """CLI must exit with code 2 on unknown global options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--completely-bogus-option"])
        assert result.exit_code == 2
        assert "No such option" in result.output

    def test_cli_unrecognized_subcommand(self):
        """CLI must exit with code 2 on unknown subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["teleport_to_mars"])
        assert result.exit_code == 2
        assert "No such command" in result.output

    def test_cli_invalid_device_choice(self):
        """CLI must reject invalid --device options with exit code 2."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--device", "quantum_tpu", "single"])
        assert result.exit_code == 2
        assert "Invalid value for '--device'" in result.output

    def test_cli_invalid_log_level_choice(self):
        """CLI must reject invalid --log-level options with exit code 2."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--log-level", "SUPER_VERBOSE", "single"])
        assert result.exit_code == 2
        assert "Invalid value for '--log-level'" in result.output

    def test_cli_missing_required_validate_model(self):
        """'validate' subcommand requires --model; omitting it must exit with code 2."""
        runner = CliRunner()
        result = runner.invoke(cli, ["validate"])
        assert result.exit_code == 2
        assert "Missing option '--model'" in result.output or "-m" in result.output

    def test_cli_nonexistent_catalog_path(self):
        """'catalog' subcommand must reject non-existent catalog-path with exit code 2."""
        runner = CliRunner()
        result = runner.invoke(cli, ["catalog", "--catalog-path", "/nonexistent/path/catalog.csv"])
        assert result.exit_code == 2
        assert "does not exist" in result.output

    def test_cli_nonexistent_stamps_catalog_csv(self):
        """'stamps' subcommand must reject non-existent catalog-csv with exit code 2."""
        runner = CliRunner()
        result = runner.invoke(cli, ["stamps", "--catalog-csv", "/nonexistent/stars.csv"])
        assert result.exit_code == 2
        assert "does not exist" in result.output

    def test_cli_nonexistent_config_behavior(self):
        """
        Adversarial test: Supplying a non-existent --config path.
        Hardened contract: An explicitly passed --config file that does not exist
        must fail with exit code 1 and report an error.
        """
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run_single_detector.return_value = MagicMock(fits_path=Path("dummy.fits"))

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["--config", "nonexistent_config_file_xyz.yaml", "single"])
            assert result.exit_code == 1
            assert "Error loading configuration" in result.output or "not found" in result.output
            assert not mock_pipeline.run_single_detector.called

    def test_cli_even_canvas_size_override_bypasses_validation(self):
        """
        Adversarial test: Supplying an even --canvas-size on CLI.
        Contract: CLI promotes even canvas sizes (e.g. 1024 -> 1025) before validation.
        """
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run_single_detector.return_value = MagicMock(fits_path=Path("dummy.fits"))

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["single", "--canvas-size", "1024"])
            assert result.exit_code == 0
            assert mock_pipeline.run_single_detector.called
            cfg_used = mock_pipeline.run_single_detector.call_args.args[0]
            assert cfg_used.assembly.canvas_size == 1025

    def test_cli_read_only_directory_permission_error(self, tmp_path: Path):
        """CLI subcommands writing to a read-only directory must fail cleanly with code 1."""
        ro_dir = tmp_path / "ro_dir"
        ro_dir.mkdir(0o555)
        out_csv = ro_dir / "output.csv"

        runner = CliRunner()
        try:
            result = runner.invoke(cli, ["catalog", "--detector", "wfi01", "-o", str(out_csv)])
            assert result.exit_code == 1
            assert "Permission denied" in result.output or "Catalog command failed" in result.output
        finally:
            os.chmod(ro_dir, 0o777)

    def test_cli_sigint_simulation(self):
        """Simulating SIGINT / KeyboardInterrupt in CLI pipeline must abort cleanly with code 1."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run_single_detector.side_effect = KeyboardInterrupt()

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["single"])
            assert result.exit_code == 1
            assert "Aborted!" in result.output


# ==============================================================================
# 2. YAML Configuration Loader Adversarial Stress Tests
# ==============================================================================

class TestConfigStress:
    """Adversarial stress tests for YAML configuration loading and validation."""

    def test_config_nonexistent_file_raises_filenotfound(self):
        """load_config must raise FileNotFoundError for missing path."""
        with pytest.raises(FileNotFoundError, match="not found"):
            load_config(Path("/nonexistent/file/path/conf.yaml"))

    def test_config_empty_file_loads_defaults(self, tmp_path: Path):
        """An empty YAML file should fall back to default dataclass parameters."""
        empty_yaml = tmp_path / "empty.yaml"
        empty_yaml.write_text("")
        cfg = load_config(empty_yaml)
        assert cfg.assembly.canvas_size == 1025
        assert cfg.pipeline.name == "romanepsf"

    def test_config_non_mapping_yaml_raises_typeerror(self, tmp_path: Path):
        """A YAML file containing a list or scalar root must raise TypeError."""
        list_yaml = tmp_path / "list_root.yaml"
        list_yaml.write_text("- item1\n- item2\n")
        with pytest.raises(TypeError):
            load_config(list_yaml)

    def test_config_inverted_tier_limits_raises_valueerror(self):
        """bright_limit >= faint_limit must raise ValueError."""
        with pytest.raises(ValueError, match="bright_limit must be strictly less than faint_limit"):
            load_config(overrides={"tiers.bright_limit": 15.0, "tiers.faint_limit": 12.0})

        with pytest.raises(ValueError, match="bright_limit must be strictly less than faint_limit"):
            load_config(overrides={"tiers.bright_limit": 13.0, "tiers.faint_limit": 13.0})

    def test_config_inverted_overlap_fm_intervals_raises_valueerror(self):
        """Inverted overlap_fm boundaries must raise ValueError."""
        with pytest.raises(ValueError, match="r_min must be less than r_max"):
            load_config(overrides={"assembly.overlap_fm.r_min": 25.0, "assembly.overlap_fm.r_max": 10.0})

        with pytest.raises(ValueError, match="blend_start must be less than blend_end"):
            load_config(overrides={"assembly.overlap_fm.blend_start": 20.0, "assembly.overlap_fm.blend_end": 10.0})

    def test_config_inverted_overlap_mb_intervals_raises_valueerror(self):
        """Inverted overlap_mb boundaries must raise ValueError."""
        with pytest.raises(ValueError, match="r_min must be less than r_max"):
            load_config(overrides={"assembly.overlap_mb.r_min": 50.0, "assembly.overlap_mb.r_max": 20.0})

        with pytest.raises(ValueError, match="blend_start must be less than blend_end"):
            load_config(overrides={"assembly.overlap_mb.blend_start": 48.0, "assembly.overlap_mb.blend_end": 30.0})

    def test_config_non_positive_roundtrip_tolerance_raises_valueerror(self):
        """roundtrip_tolerance_arcsec <= 0 must raise ValueError."""
        with pytest.raises(ValueError, match="roundtrip_tolerance_arcsec must be > 0"):
            load_config(overrides={"catalog.roundtrip_tolerance_arcsec": 0.0})

        with pytest.raises(ValueError, match="roundtrip_tolerance_arcsec must be > 0"):
            load_config(overrides={"catalog.roundtrip_tolerance_arcsec": -0.5})

    def test_config_type_mismatch_string_for_float_raises_typeerror(self):
        """Overriding a numeric limit with a string must trigger a TypeError during validation."""
        with pytest.raises(TypeError):
            load_config(overrides={"tiers.bright_limit": "not_a_number"})

    def test_config_type_mismatch_string_for_canvas_size_raises_typeerror(self):
        """Overriding canvas_size with a string must trigger a TypeError during validation."""
        with pytest.raises(TypeError):
            load_config(overrides={"assembly.canvas_size": "odd_string"})

    def test_config_float_canvas_size_vulnerability(self):
        """
        Adversarial test: canvas_size set to a float (e.g. 1025.5).
        Hardened contract: PipelineConfig.validate() rejects non-integer canvas_size.
        """
        with pytest.raises(ValueError, match="canvas_size must be an odd positive integer"):
            load_config(overrides={"assembly.canvas_size": 1025.5})

    def test_config_deeply_nested_invalid_keys_raises_typeerror(self):
        """Passing unexpected keys in overrides must raise TypeError."""
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            load_config(overrides={"unknown_top_level_section": {"dummy": 123}})


# ==============================================================================
# 3. Level 2 ASDF Loader Adversarial Stress Tests
# ==============================================================================

class TestASDFLoaderStress:
    """Adversarial stress tests for Level 2 ASDF loader and calibration."""

    def test_loader_truncated_asdf_raises_error(self, tmp_path: Path):
        """A truncated ASDF file (partial header or bytes) must raise an error."""
        trunc_file = tmp_path / "truncated.asdf"
        trunc_file.write_bytes(b"#ASDF 1.0.0\n#ASDF_STANDARD 1.5.0\n%YAML 1.1\n")
        with pytest.raises((TypeError, ValueError)):
            load_l2_image(trunc_file)

    def test_loader_non_roman_asdf_raises_valueerror(self, tmp_path: Path):
        """A plain ASDF file without Roman datamodel schema must raise ValueError."""
        import asdf
        plain_asdf = tmp_path / "plain.asdf"
        with asdf.AsdfFile({"arbitrary_key": [1, 2, 3]}) as af:
            af.write_to(plain_asdf)

        with pytest.raises(ValueError, match="not a roman file"):
            load_l2_image(plain_asdf)

    def test_loader_unexpected_science_shape_rejected(self):
        """ASDF with science shape != (4088, 4088) must raise ValueError when validate_shape=True."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4096, 4096), dtype=np.float32)
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                with pytest.raises(ValueError, match="Invalid Roman science array shape"):
                    load_l2_image("dummy.asdf", validate_shape=True)

    def test_loader_unexpected_science_shape_accepted_when_validation_disabled(self):
        """validate_shape=False allows loading non-standard dimensions."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((512, 512), dtype=np.float32)
        mock_dm.err = np.ones((512, 512), dtype=np.float32)
        mock_dm.dq = np.zeros((512, 512), dtype=np.uint32)
        mock_dm.meta = MagicMock()
        mock_dm.meta.instrument.detector = "WFI01"
        mock_dm.meta.instrument.optical_element = "F146"
        mock_dm.meta.photometry.conversion_megajanskys = 1.0
        mock_dm.meta.photometry.pixel_area = 2.8e-13
        mock_dm.meta.pointing.pa_aperture = 0.0
        mock_dm.meta.wcs = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                l2 = load_l2_image("dummy.asdf", validate_shape=False)
                assert l2.shape == (512, 512)

    def test_loader_missing_wcs_handled(self):
        """If ASDF lacks WCS, l2.wcs is None; downstream projection must raise clean AttributeError."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.err = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.dq = np.zeros((4088, 4088), dtype=np.uint32)
        mock_dm.meta = MagicMock()
        mock_dm.meta.instrument.detector = "WFI01"
        mock_dm.meta.instrument.optical_element = "F146"
        mock_dm.meta.photometry.conversion_megajanskys = 1.0
        mock_dm.meta.photometry.pixel_area = 2.8e-13
        mock_dm.meta.pointing.pa_aperture = 0.0
        mock_dm.meta.wcs = None  # Missing WCS
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                l2 = load_l2_image("dummy.asdf")
                assert l2.wcs is None

                df = pd.DataFrame({"source_id": [1], "ra": [303.0], "dec": [-19.0], "mag_lambda": [12.0]})
                with pytest.raises(AttributeError, match="WCS object does not provide backward_transform"):
                    project_catalog_to_pixels(l2, df)

    def test_loader_missing_dq_array_defaults_to_zeros(self):
        """If ASDF lacks DQ array, loader defaults to zeros of correct shape."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.err = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.dq = None  # Missing DQ
        mock_dm.meta = MagicMock()
        mock_dm.meta.instrument.detector = "WFI01"
        mock_dm.meta.instrument.optical_element = "F146"
        mock_dm.meta.photometry.conversion_megajanskys = 1.0
        mock_dm.meta.photometry.pixel_area = 2.8e-13
        mock_dm.meta.pointing.pa_aperture = 0.0
        mock_dm.meta.wcs = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                l2 = load_l2_image("dummy.asdf")
                assert l2.dq.shape == (4088, 4088)
                assert np.all(l2.dq == 0)
                mask = l2.get_dq_mask()
                assert not np.any(mask)

    def test_loader_nan_and_infinite_pixels_masked(self):
        """get_effective_mask must mask NaN, +Inf, -Inf in addition to DQ bitflags."""
        data = np.array([
            [1.0, np.nan, 2.0],
            [np.inf, 3.0, -np.inf],
            [4.0, 5.0, 6.0],
        ], dtype=np.float32)
        dq = np.zeros((3, 3), dtype=np.uint32)
        dq[2, 2] = 1  # DO_NOT_USE

        eff_mask = get_effective_mask(data, dq)
        assert eff_mask[0, 1]  # NaN
        assert eff_mask[1, 0]  # +Inf
        assert eff_mask[1, 2]  # -Inf
        assert eff_mask[2, 2]  # DQ flag
        assert not eff_mask[0, 0]
        assert not eff_mask[0, 2]
        assert not eff_mask[1, 1]
        assert not eff_mask[2, 0]

    def test_loader_mismatched_dq_array_shape_vulnerability(self):
        """
        Adversarial test: ASDF with mismatched dq array shape (e.g. 50x50 vs 4088x4088).
        Hardened contract: load_l2_image validates dq.shape == raw_data.shape.
        """
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.err = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.dq = np.zeros((50, 50), dtype=np.uint32)  # Mismatched shape!
        mock_dm.meta = MagicMock()
        mock_dm.meta.instrument.detector = "WFI01"
        mock_dm.meta.instrument.optical_element = "F146"
        mock_dm.meta.photometry.conversion_megajanskys = 1.0
        mock_dm.meta.photometry.pixel_area = 2.8e-13
        mock_dm.meta.pointing.pa_aperture = 0.0
        mock_dm.meta.wcs = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                with pytest.raises(ValueError, match="dq array shape"):
                    _ = load_l2_image("dummy.asdf")

    def test_loader_nan_conversion_megajanskys_vulnerability(self):
        """
        Adversarial test: Photometry metadata with NaN conversion_megajanskys.
        Hardened contract: load_l2_image validates conversion_megajanskys is positive and finite.
        """
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32) * 10.0
        mock_dm.err = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.dq = np.zeros((4088, 4088), dtype=np.uint32)
        mock_dm.meta = MagicMock()
        mock_dm.meta.instrument.detector = "WFI01"
        mock_dm.meta.instrument.optical_element = "F146"
        mock_dm.meta.photometry.conversion_megajanskys = float("nan")
        mock_dm.meta.photometry.pixel_area = 2.8e-13
        mock_dm.meta.pointing.pa_aperture = 0.0
        mock_dm.meta.wcs = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                with pytest.raises(ValueError, match="Invalid photometric conversion factor"):
                    _ = load_l2_image("dummy.asdf")
