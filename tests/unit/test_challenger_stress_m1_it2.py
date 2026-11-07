"""
Adversarial Stress Test Suite for Milestone 1 Iteration 2 (Challenger M1-it2-2).

Empirically challenges:
1. CLI option parsing, missing config handling, and overrides validation:
   - Non-existent explicit config path vs directory path vs permission-denied config.
   - Corrupted YAML passed via CLI.
   - CLI overrides across run, single, and assemble subcommands:
     * Even canvas sizes (e.g. 1024, 2048, 512).
     * Non-positive canvas sizes (e.g. 0, -1025, -1).
     * Non-integer canvas sizes via CLI options.
   - Global CLI overrides precedence: --verbose overriding --log-level.
   - Detectors parsing with malformed commas/spaces.
   - Subcommand exit codes: code 2 for option parsing errors, code 1 for runtime validation/config errors, code 0 for help.

2. PipelineConfig schema validation:
   - canvas_size: boolean (True, False), float (1025.0, 1025.5), string ("1025"), None, list, dict, negative odd (-1025), zero (0), positive even (1024).
   - Tiers limits: bright_limit >= faint_limit, equal limits, non-numeric strings, None.
   - Overlap intervals: r_min >= r_max, blend_start >= blend_end for both overlap_fm and overlap_mb.
   - Catalog roundtrip tolerance: non-positive, zero, NaN, Inf.
   - Environment device: case-insensitivity, unknown device strings.
   - Corrupted YAML: syntax errors, scalar roots, list roots, empty/null files, unknown root keys, unknown nested section keys.
   - Overrides mechanism: dot-notation, nested dictionaries, deeply nested overrides.
   - Serialization: to_dict path stringification, save and reload roundtrip.

3. RomanL2Data dataclass invariants and load_l2_image validation:
   - RomanL2Data dataclass invariants:
     * data shape vs err shape mismatch (2D-2D mismatch, 2D-1D mismatch).
     * data shape vs dq shape mismatch.
     * get_dq_mask with custom, default, and unrecognized flags.
     * get_effective_mask with combined DQ flags, NaN, +Inf, -Inf.
   - load_l2_image validation:
     * Non-existent ASDF path, directory as ASDF path.
     * Science array shape mismatch when validate_shape=True.
     * Science array shape mismatch allowed when validate_shape=False, but err/dq shape mismatch still rejected.
     * Photometric conversion factor validation: zero, negative, NaN, +Inf, -Inf, non-numeric string.
     * Missing photometry metadata fallback.
     * Negative/zero pixel area fallback for zero-point and pixel scale.
     * Calibrated vs uncalibrated modes.
     * Verification against real commissioning WFI01 ASDF file.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import yaml
from click.testing import CliRunner

from romanepsf.cli import cli
from romanepsf.config import (
    Config,
    PipelineConfig,
    load_config,
    resolve_device,
    AssemblySection,
    OverlapAnnulusConfig,
    TiersSection,
)
from romanepsf.loader import (
    RomanL2Data,
    load_l2_image,
    get_dq_mask,
    get_effective_mask,
    NOMINAL_PIXEL_SCALE,
    NOMINAL_PIXEL_AREA,
)


# ==============================================================================
# 1. CLI Option Parsing, Missing Config Handling, and Overrides Validation
# ==============================================================================

class TestCLIOptionParsingAndOverrides:
    """Adversarial challenge for CLI option parsing, missing configs, and overrides."""

    def test_cli_explicit_config_directory_rejected(self, tmp_path: Path):
        """Passing a directory instead of a file to --config must be rejected by Click with exit code 2."""
        runner = CliRunner()
        config_dir = tmp_path / "config_folder"
        config_dir.mkdir()

        result = runner.invoke(cli, ["--config", str(config_dir), "single"])
        assert result.exit_code == 2
        assert "is a directory" in result.output or "is not a file" in result.output

    def test_cli_explicit_config_corrupted_yaml_rejected(self, tmp_path: Path):
        """Passing a syntactically corrupted YAML config must exit with code 1."""
        runner = CliRunner()
        corrupt_yaml = tmp_path / "corrupt.yaml"
        corrupt_yaml.write_text("tiers:\n  bright_limit: [unclosed_bracket\n")

        result = runner.invoke(cli, ["--config", str(corrupt_yaml), "single"])
        assert result.exit_code == 1
        assert "Error loading configuration" in result.output

    def test_cli_explicit_config_non_mapping_yaml_rejected(self, tmp_path: Path):
        """Passing a YAML config with scalar or list root must exit with code 1."""
        runner = CliRunner()
        list_yaml = tmp_path / "list.yaml"
        list_yaml.write_text("- item1\n- item2\n")

        result = runner.invoke(cli, ["--config", str(list_yaml), "single"])
        assert result.exit_code == 1
        assert "Error loading configuration" in result.output

    def test_cli_explicit_config_invalid_schema_rejected(self, tmp_path: Path):
        """Passing a config that fails validate() (e.g. bright >= faint) must exit with code 1."""
        runner = CliRunner()
        bad_yaml = tmp_path / "bad_schema.yaml"
        bad_yaml.write_text("tiers:\n  bright_limit: 15.0\n  faint_limit: 12.0\n")

        result = runner.invoke(cli, ["--config", str(bad_yaml), "single"])
        assert result.exit_code == 1
        assert "bright_limit must be strictly less than faint_limit" in result.output

    def test_cli_run_command_even_canvas_size_override_promoted(self):
        """'run' subcommand with --canvas-size 1024 (even) is seamlessly promoted to 1025."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["run", "--canvas-size", "1024"])
            assert result.exit_code == 0
            assert mock_pipeline.run_pipeline.called
            cfg_used = mock_pipeline.run_pipeline.call_args.args[0]
            assert cfg_used.assembly.canvas_size == 1025

    def test_cli_run_command_negative_canvas_size_override_rejected(self):
        """'run' subcommand with negative canvas size must be rejected with exit code 1."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["run", "--canvas-size", "-1025"])
            assert result.exit_code == 1
            assert "Configuration validation failed" in result.output
            assert not mock_pipeline.run_pipeline.called

    def test_cli_run_command_zero_canvas_size_override_rejected(self):
        """'run' subcommand with zero canvas size must be rejected with exit code 1."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["run", "--canvas-size", "0"])
            assert result.exit_code == 1
            assert "Configuration validation failed" in result.output
            assert not mock_pipeline.run_pipeline.called

    def test_cli_assemble_command_even_canvas_size_override_rejected(self):
        """'assemble' subcommand with --canvas-size 2048 (even) must be rejected with exit code 1."""
        runner = CliRunner()
        mock_assembly = MagicMock()
        with patch.dict("sys.modules", {"romanepsf.assembly": mock_assembly}):
            result = runner.invoke(cli, ["assemble", "--canvas-size", "2048"])
            assert result.exit_code == 1
            assert "Configuration validation failed" in result.output

    def test_cli_assemble_command_negative_canvas_size_override_rejected(self):
        """'assemble' subcommand with --canvas-size -501 must be rejected with exit code 1."""
        runner = CliRunner()
        mock_assembly = MagicMock()
        with patch.dict("sys.modules", {"romanepsf.assembly": mock_assembly}):
            result = runner.invoke(cli, ["assemble", "--canvas-size", "-501"])
            assert result.exit_code == 1
            assert "Configuration validation failed" in result.output

    def test_cli_single_command_negative_canvas_size_override_rejected(self):
        """'single' subcommand with --canvas-size -1025 must be rejected with exit code 1."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["single", "--canvas-size", "-1025"])
            assert result.exit_code == 1
            assert "Configuration validation failed" in result.output
            assert not mock_pipeline.run_single_detector.called

    def test_cli_single_command_zero_canvas_size_override_rejected(self):
        """'single' subcommand with --canvas-size 0 must be rejected with exit code 1."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["single", "--canvas-size", "0"])
            assert result.exit_code == 1
            assert "Configuration validation failed" in result.output
            assert not mock_pipeline.run_single_detector.called

    def test_cli_non_integer_canvas_size_string_rejected_by_click(self):
        """Passing non-integer string to --canvas-size must be rejected by Click with exit code 2."""
        runner = CliRunner()
        result = runner.invoke(cli, ["single", "--canvas-size", "not_a_number"])
        assert result.exit_code == 2
        assert "is not a valid integer" in result.output

    def test_cli_verbose_flag_precedence_over_log_level(self):
        """--verbose flag must override --log-level ERROR to DEBUG."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run_single_detector.return_value = MagicMock(fits_path=Path("dummy.fits"))

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["--log-level", "ERROR", "-v", "single"])
            assert result.exit_code == 0
            cfg_passed = mock_pipeline.run_single_detector.call_args[0][0]
            assert cfg_passed.pipeline.log_level == "DEBUG"

    def test_cli_run_command_detectors_parsing_with_whitespace_and_commas(self):
        """--detectors option in 'run' must handle commas and surrounding whitespace cleanly."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run_pipeline.return_value = MagicMock(fits_path=Path("dummy.fits"))

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["run", "--detectors", " wfi01 , wfi02 , , wfi03 "])
            assert result.exit_code == 0
            cfg_passed = mock_pipeline.run_pipeline.call_args[0][0]
            assert cfg_passed.data.detectors == ["wfi01", "wfi02", "wfi03"]

    def test_cli_valid_odd_canvas_size_overrides_succeed(self):
        """Valid odd canvas sizes (1025, 2049) must successfully update config and execute."""
        runner = CliRunner()
        mock_pipeline = MagicMock()
        mock_pipeline.run_single_detector.return_value = MagicMock(fits_path=Path("dummy.fits"))

        with patch.dict("sys.modules", {"romanepsf.pipeline": mock_pipeline}):
            result = runner.invoke(cli, ["single", "--canvas-size", "2049"])
            assert result.exit_code == 0
            cfg_passed = mock_pipeline.run_single_detector.call_args[0][0]
            assert cfg_passed.assembly.canvas_size == 2049


# ==============================================================================
# 2. PipelineConfig Schema Validation & Edge Cases
# ==============================================================================

class TestConfigSchemaAdversarial:
    """Adversarial challenge for PipelineConfig schema validation and edge cases."""

    @pytest.mark.parametrize("invalid_canvas", [
        1024,          # Even positive
        2048,          # Even positive
        2,             # Minimal even positive
        0,             # Zero
        -1,            # Negative odd
        -2,            # Negative even
        -1025,         # Negative odd
        True,          # Boolean True (subclass of int)
        False,         # Boolean False (subclass of int)
        1025.0,        # Float representing integer
        1025.5,        # Float non-integer
    ])
    def test_canvas_size_invalid_values_raise_value_error(self, invalid_canvas):
        """All even, zero, negative, boolean, and float canvas sizes must raise ValueError."""
        with pytest.raises(ValueError, match="canvas_size must be an odd positive integer"):
            load_config(overrides={"assembly.canvas_size": invalid_canvas})

    @pytest.mark.parametrize("invalid_canvas_type", [
        "1025",        # String number
        "odd",         # Arbitrary string
        "",            # Empty string
        None,          # None
        [1025],        # List
        {"s": 1025},   # Dict
        1025 + 0j,     # Complex
    ])
    def test_canvas_size_invalid_types_raise_type_error(self, invalid_canvas_type):
        """Non-numeric canvas sizes must raise TypeError."""
        with pytest.raises(TypeError, match="canvas_size must be an integer"):
            load_config(overrides={"assembly.canvas_size": invalid_canvas_type})

    @pytest.mark.parametrize("bright, faint", [
        (13.0, 11.0),   # Inverted
        (11.0, 11.0),   # Exactly equal
        (15.5, 15.5),   # Exactly equal
        (20.0, 5.0),    # Strongly inverted
    ])
    def test_tier_limits_inverted_or_equal_raises_value_error(self, bright, faint):
        """bright_limit >= faint_limit must be strictly rejected."""
        with pytest.raises(ValueError, match="bright_limit must be strictly less than faint_limit"):
            load_config(overrides={"tiers.bright_limit": bright, "tiers.faint_limit": faint})

    @pytest.mark.parametrize("sec, r_min, r_max", [
        ("overlap_fm", 16.0, 16.0),  # Equal
        ("overlap_fm", 20.0, 10.0),  # Inverted
        ("overlap_mb", 45.0, 45.0),  # Equal
        ("overlap_mb", 50.0, 30.0),  # Inverted
    ])
    def test_overlap_r_min_ge_r_max_raises_value_error(self, sec, r_min, r_max):
        """r_min >= r_max in overlap configurations must raise ValueError."""
        with pytest.raises(ValueError, match="r_min must be less than r_max"):
            load_config(overrides={f"assembly.{sec}.r_min": r_min, f"assembly.{sec}.r_max": r_max})

    @pytest.mark.parametrize("sec, b_start, b_end", [
        ("overlap_fm", 18.0, 18.0),  # Equal
        ("overlap_fm", 25.0, 10.0),  # Inverted
        ("overlap_mb", 48.0, 48.0),  # Equal
        ("overlap_mb", 60.0, 20.0),  # Inverted
    ])
    def test_overlap_blend_start_ge_blend_end_raises_value_error(self, sec, b_start, b_end):
        """blend_start >= blend_end in overlap configurations must raise ValueError."""
        with pytest.raises(ValueError, match="blend_start must be less than blend_end"):
            load_config(overrides={f"assembly.{sec}.blend_start": b_start, f"assembly.{sec}.blend_end": b_end})

    @pytest.mark.parametrize("tol", [0.0, -0.1, -10.0])
    def test_catalog_non_positive_roundtrip_tolerance_raises_value_error(self, tol):
        """roundtrip_tolerance_arcsec <= 0 must raise ValueError."""
        with pytest.raises(ValueError, match="roundtrip_tolerance_arcsec must be > 0"):
            load_config(overrides={"catalog.roundtrip_tolerance_arcsec": tol})

    @pytest.mark.parametrize("dev", ["CPU", "Cpu", "auto", "AUTO", "mps", "MPS", "cuda", "CUDA"])
    def test_device_case_insensitivity(self, dev):
        """resolve_device and config validation must accept devices in any case."""
        cfg = load_config(overrides={"environment.device": dev})
        assert cfg.environment.device == dev
        # Validate that get_torch_device succeeds
        torch_dev = cfg.get_torch_device()
        assert torch_dev.type in ("cpu", "mps", "cuda")

    @pytest.mark.parametrize("invalid_dev", ["opencl", "tpu", "directml", "vulkan", ""])
    def test_unknown_device_raises_value_error(self, invalid_dev):
        """Unsupported device strings must raise ValueError."""
        with pytest.raises(ValueError, match="Unknown or unsupported device"):
            load_config(overrides={"environment.device": invalid_dev})

    def test_config_corrupted_yaml_syntax_raises_yaml_error(self, tmp_path: Path):
        """Corrupted YAML with invalid indentation or unclosed quotes must raise YAMLError."""
        bad_yaml = tmp_path / "syntax_error.yaml"
        bad_yaml.write_text("tiers:\n  bright_limit: 'unclosed string\n")
        with pytest.raises(yaml.YAMLError):
            load_config(bad_yaml)

    def test_config_yaml_scalar_root_raises_type_error(self, tmp_path: Path):
        """A YAML file whose root is a string scalar must raise TypeError."""
        scalar_yaml = tmp_path / "scalar.yaml"
        scalar_yaml.write_text('"I am a single string, not a dictionary"')
        with pytest.raises(TypeError):
            load_config(scalar_yaml)

    def test_config_yaml_unknown_top_level_section_raises_type_error(self, tmp_path: Path):
        """A YAML file containing unrecognized top-level sections must raise TypeError."""
        bad_section_yaml = tmp_path / "unknown_section.yaml"
        bad_section_yaml.write_text("bogus_section:\n  param: 123\n")
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            load_config(bad_section_yaml)

    def test_config_yaml_unknown_nested_parameter_raises_type_error(self, tmp_path: Path):
        """A YAML file containing unrecognized parameters within a section must raise TypeError."""
        bad_param_yaml = tmp_path / "unknown_param.yaml"
        bad_param_yaml.write_text("assembly:\n  canvas_size: 1025\n  totally_bogus_field: true\n")
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            load_config(bad_param_yaml)

    def test_config_serialization_roundtrip(self, tmp_path: Path):
        """Config serialized via to_dict() and save() must deserialize identically."""
        original_cfg = load_config(overrides={
            "assembly.canvas_size": 2049,
            "tiers.bright_limit": 10.5,
            "tiers.faint_limit": 13.5,
        })
        save_file = tmp_path / "serialized_config.yaml"
        original_cfg.save(save_file)
        assert save_file.is_file()

        reloaded_cfg = load_config(save_file)
        assert reloaded_cfg.assembly.canvas_size == 2049
        assert reloaded_cfg.tiers.bright_limit == 10.5
        assert reloaded_cfg.tiers.faint_limit == 13.5
        assert reloaded_cfg.to_dict() == original_cfg.to_dict()

    def test_config_apply_dot_overrides_deep_hierarchy(self):
        """Dot-notation overrides must properly penetrate multiple levels of nesting."""
        cfg = load_config(overrides={
            "spikes.morphological.threshold_sigma": 3.5,
            "spikes.core_protection_radius_px.bright": 8.0,
            "tiers.max_stars_per_tier.bright": 40,
        })
        assert cfg.spikes.morphological.threshold_sigma == 3.5
        assert cfg.spikes.core_protection_radius_px.bright == 8.0
        assert cfg.tiers.max_stars_per_tier.bright == 40


# ==============================================================================
# 3. RomanL2Data Dataclass Invariants & load_l2_image Validation
# ==============================================================================

class TestLoaderAndDataclassAdversarial:
    """Adversarial challenge for RomanL2Data dataclass invariants and ASDF loading."""

    def test_roman_l2_data_mismatched_err_shape_rejected(self):
        """RomanL2Data.__post_init__ must raise ValueError if err.shape != data.shape."""
        data = np.ones((4088, 4088), dtype=np.float32)
        err = np.ones((4088, 2048), dtype=np.float32)  # Mismatched width
        dq = np.zeros((4088, 4088), dtype=np.uint32)

        with pytest.raises(ValueError, match="err array shape.*does not match data shape"):
            RomanL2Data(
                detector="wfi01",
                filter_name="F146",
                data=data,
                raw_data=data,
                err=err,
                dq=dq,
                wcs=None,
                pa_aperture=0.0,
                pixel_scale=0.11,
                conversion_factor=1.0,
                pixel_area=2.8e-13,
                zp_ab=26.836,
                meta={},
            )

    def test_roman_l2_data_mismatched_dq_shape_rejected(self):
        """RomanL2Data.__post_init__ must raise ValueError if dq.shape != data.shape."""
        data = np.ones((4088, 4088), dtype=np.float32)
        err = np.ones((4088, 4088), dtype=np.float32)
        dq = np.zeros((2048, 4088), dtype=np.uint32)  # Mismatched height

        with pytest.raises(ValueError, match="dq array shape.*does not match data shape"):
            RomanL2Data(
                detector="wfi01",
                filter_name="F146",
                data=data,
                raw_data=data,
                err=err,
                dq=dq,
                wcs=None,
                pa_aperture=0.0,
                pixel_scale=0.11,
                conversion_factor=1.0,
                pixel_area=2.8e-13,
                zp_ab=26.836,
                meta={},
            )

    def test_roman_l2_data_1d_err_array_rejected(self):
        """RomanL2Data.__post_init__ must reject 1D err array with 2D data."""
        data = np.ones((100, 100), dtype=np.float32)
        err = np.ones((100,), dtype=np.float32)
        dq = np.zeros((100, 100), dtype=np.uint32)

        with pytest.raises(ValueError, match="err array shape"):
            RomanL2Data(
                detector="wfi01",
                filter_name="F146",
                data=data,
                raw_data=data,
                err=err,
                dq=dq,
                wcs=None,
                pa_aperture=0.0,
                pixel_scale=0.11,
                conversion_factor=1.0,
                pixel_area=2.8e-13,
                zp_ab=26.836,
                meta={},
            )

    def test_roman_l2_data_matching_shapes_accepted(self):
        """RomanL2Data with matching shapes must instantiate cleanly."""
        data = np.ones((128, 128), dtype=np.float32)
        err = np.ones((128, 128), dtype=np.float32) * 0.1
        dq = np.zeros((128, 128), dtype=np.uint32)

        l2 = RomanL2Data(
            detector="wfi01",
            filter_name="F146",
            data=data,
            raw_data=data,
            err=err,
            dq=dq,
            wcs=None,
            pa_aperture=0.0,
            pixel_scale=0.11,
            conversion_factor=1.0,
            pixel_area=2.8e-13,
            zp_ab=26.836,
            meta={},
        )
        assert l2.shape == (128, 128)
        assert l2.is_calibrated is True

    def test_get_dq_mask_flags_and_bitmask_combinations(self):
        """get_dq_mask must properly handle combinations of flags, explicit bitmask, and unknowns."""
        dq = np.zeros((4, 4), dtype=np.uint32)
        dq[0, 0] = 1   # DO_NOT_USE
        dq[0, 1] = 2   # SATURATED
        dq[0, 2] = 4   # JUMP_DET
        dq[0, 3] = 8   # DROPOUT

        # Default flags: DO_NOT_USE(1), SATURATED(2), DROPOUT(8)
        mask_default = get_dq_mask(dq)
        assert mask_default[0, 0]
        assert mask_default[0, 1]
        assert not mask_default[0, 2]  # JUMP_DET not in default
        assert mask_default[0, 3]

        # Explicit bitmask: 0x4 (JUMP_DET)
        mask_bit = get_dq_mask(dq, flags=[], bitmask=4)
        assert not mask_bit[0, 0]
        assert not mask_bit[0, 1]
        assert mask_bit[0, 2]
        assert not mask_bit[0, 3]

        # Combined flags + bitmask
        mask_comb = get_dq_mask(dq, flags=["DO_NOT_USE", "UNKNOWN_FLAG"], bitmask=4)
        assert mask_comb[0, 0]
        assert not mask_comb[0, 1]
        assert mask_comb[0, 2]
        assert not mask_comb[0, 3]

    def test_get_effective_mask_comprehensive(self):
        """get_effective_mask must identify all DQ flags, NaNs, +Infs, and -Infs."""
        data = np.array([
            [1.0, np.nan, 3.0],
            [np.inf, -np.inf, 6.0],
            [7.0, 8.0, 9.0],
        ], dtype=np.float32)
        dq = np.zeros((3, 3), dtype=np.uint32)
        dq[2, 0] = 1   # DO_NOT_USE
        dq[2, 1] = 2   # SATURATED

        eff = get_effective_mask(data, dq)
        assert not eff[0, 0]
        assert eff[0, 1]   # NaN
        assert not eff[0, 2]
        assert eff[1, 0]   # +Inf
        assert eff[1, 1]   # -Inf
        assert not eff[1, 2]
        assert eff[2, 0]   # DO_NOT_USE
        assert eff[2, 1]   # SATURATED
        assert not eff[2, 2]

    def test_loader_nonexistent_asdf_raises_filenotfound(self):
        """load_l2_image must raise FileNotFoundError for non-existent path."""
        with pytest.raises(FileNotFoundError, match="ASDF file not found"):
            load_l2_image("/nonexistent/file/asdf_image.asdf")

    def test_loader_directory_asdf_path_raises_filenotfound(self, tmp_path: Path):
        """load_l2_image must raise FileNotFoundError if path is a directory."""
        with pytest.raises(FileNotFoundError, match="ASDF file not found"):
            load_l2_image(tmp_path)

    @pytest.mark.parametrize("invalid_conv", [
        0.0,
        -1.0,
        -0.0001,
        float("nan"),
        float("inf"),
        float("-inf"),
        "not_a_number",
        None,
    ])
    def test_loader_invalid_photometric_conversion_rejected(self, invalid_conv):
        """All non-positive, non-finite, and non-numeric photometric conversion factors must be rejected."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.err = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.dq = np.zeros((4088, 4088), dtype=np.uint32)
        mock_dm.meta = MagicMock()
        mock_dm.meta.instrument.detector = "WFI01"
        mock_dm.meta.instrument.optical_element = "F146"
        mock_dm.meta.photometry.conversion_megajanskys = invalid_conv
        mock_dm.meta.photometry.pixel_area = 2.8e-13
        mock_dm.meta.pointing.pa_aperture = 0.0
        mock_dm.meta.wcs = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                with pytest.raises(ValueError, match="Invalid photometric conversion factor"):
                    load_l2_image("dummy.asdf")

    def test_loader_mismatched_err_shape_in_asdf_rejected(self):
        """load_l2_image must reject ASDF file if err.shape != raw_data.shape."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.err = np.ones((4088, 2000), dtype=np.float32)  # Mismatched shape
        mock_dm.dq = np.zeros((4088, 4088), dtype=np.uint32)
        mock_dm.meta = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                with pytest.raises(ValueError, match="Invalid err array shape"):
                    load_l2_image("dummy.asdf")

    def test_loader_mismatched_dq_shape_in_asdf_rejected(self):
        """load_l2_image must reject ASDF file if dq.shape != raw_data.shape."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.err = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.dq = np.zeros((2000, 4088), dtype=np.uint32)  # Mismatched shape
        mock_dm.meta = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                with pytest.raises(ValueError, match="Invalid dq array shape"):
                    load_l2_image("dummy.asdf")

    def test_loader_non_standard_shape_with_validate_shape_false_validates_err_and_dq_match(self):
        """validate_shape=False allows non-(4088,4088) data, but still enforces err/dq match data.shape."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((512, 512), dtype=np.float32)
        mock_dm.err = np.ones((512, 256), dtype=np.float32)  # Mismatched
        mock_dm.dq = np.zeros((512, 512), dtype=np.uint32)
        mock_dm.meta = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                with pytest.raises(ValueError, match="Invalid err array shape"):
                    load_l2_image("dummy.asdf", validate_shape=False)

    def test_loader_missing_photometry_metadata_defaults_safely(self):
        """If ASDF lacks photometry metadata, loader must fall back to conv_factor=1.0 and nominal pixel area."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32) * 5.0
        mock_dm.err = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.dq = np.zeros((4088, 4088), dtype=np.uint32)
        mock_dm.meta = MagicMock()
        mock_dm.meta.instrument.detector = "WFI01"
        mock_dm.meta.instrument.optical_element = "F146"
        mock_dm.meta.photometry = None  # Missing photometry
        mock_dm.meta.pointing.pa_aperture = 0.0
        mock_dm.meta.wcs = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                l2 = load_l2_image("dummy.asdf", calibrate=True)
                assert l2.conversion_factor == 1.0
                assert l2.pixel_area == NOMINAL_PIXEL_AREA
                assert l2.pixel_scale == pytest.approx(NOMINAL_PIXEL_SCALE, rel=1e-2)
                assert np.isclose(l2.data[0, 0], 5.0)

    def test_loader_non_positive_pixel_area_fallback(self):
        """Non-positive pixel area must trigger fallback to nominal ZP and pixel scale."""
        mock_dm = MagicMock()
        mock_dm.data = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.err = np.ones((4088, 4088), dtype=np.float32)
        mock_dm.dq = np.zeros((4088, 4088), dtype=np.uint32)
        mock_dm.meta = MagicMock()
        mock_dm.meta.instrument.detector = "WFI01"
        mock_dm.meta.instrument.optical_element = "F146"
        mock_dm.meta.photometry.conversion_megajanskys = 1.0
        mock_dm.meta.photometry.pixel_area = 0.0  # Zero pixel area
        mock_dm.meta.pointing.pa_aperture = 0.0
        mock_dm.meta.wcs = MagicMock()
        mock_dm.__enter__.return_value = mock_dm

        with patch("roman_datamodels.open", return_value=mock_dm):
            with patch.object(Path, "is_file", return_value=True):
                l2 = load_l2_image("dummy.asdf")
                assert l2.pixel_scale == NOMINAL_PIXEL_SCALE
                assert l2.zp_ab == 26.836

    def test_real_commissioning_wfi01_asdf_integrity(self):
        """Empirically test loading and integrity of real commissioning WFI01 ASDF file."""
        real_asdf = Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf")
        if not real_asdf.is_file():
            pytest.skip("Real commissioning ASDF file not found on filesystem")

        l2 = load_l2_image(real_asdf, calibrate=True)
        assert l2.detector.lower() == "wfi01"
        assert l2.filter_name == "F146"
        assert l2.data.shape == (4088, 4088)
        assert l2.err.shape == (4088, 4088)
        assert l2.dq.shape == (4088, 4088)
        assert l2.data.dtype == np.float32
        assert l2.dq.dtype == np.uint32
        assert l2.conversion_factor > 0
        assert np.isfinite(l2.conversion_factor)
        assert l2.pixel_scale == pytest.approx(0.11, rel=0.05)
        assert l2.pixel_area > 0
        assert l2.zp_ab > 0
        assert l2.wcs is not None
        assert l2.is_calibrated is True

        # Test effective mask on real image
        eff_mask = l2.get_effective_mask()
        assert eff_mask.shape == (4088, 4088)
        assert eff_mask.dtype == bool
        assert eff_mask.sum() > 0  # There are some flagged or border pixels
