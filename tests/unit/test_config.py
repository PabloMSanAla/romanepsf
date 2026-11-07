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
    PipelineSection,
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

    assert cfg.pipeline.name in ("romanepsf", "roman_epsf_pipeline")
    assert cfg.pipeline.version in ("0.1.0", "1.0.0")
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
    """Verify validation raises ValueError if canvas_size is an even integer."""
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
