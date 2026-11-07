"""
Unit tests for romanepsf.config (Configuration loader, schema, and validation).
"""

from pathlib import Path
import pytest
import yaml

from proposed_config import (
    load_config,
    PipelineConfig,
    PipelineSection,
    EnvironmentSection,
    DataSection,
    CatalogSection,
    TiersSection,
    StampsSection,
    SpikesSection,
    ProfileSection,
    AssemblySection,
    ValidationSection,
    ReportingSection,
)

DEFAULT_YAML_PATH = Path("/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_default.yaml")


def test_default_config_instantiation():
    cfg = PipelineConfig()
    assert cfg.pipeline.name == "romanepsf"
    assert cfg.environment.device == "auto"
    assert cfg.assembly.canvas_size == 1025
    assert cfg.tiers.bright_limit == 11.0
    assert cfg.tiers.faint_limit == 13.0
    cfg.validate()


def test_load_config_from_yaml():
    cfg = load_config(DEFAULT_YAML_PATH)
    assert cfg.pipeline.name == "romanepsf"
    assert cfg.assembly.canvas_size == 1025
    assert cfg.spikes.detector_alignment_offset_deg == -9.70
    assert len(cfg.spikes.base_angles_deg) == 6
    assert cfg.catalog.roundtrip_tolerance_arcsec == 0.5


def test_load_config_with_overrides():
    overrides = {
        "assembly.canvas_size": 2049,
        "tiers.bright_limit": 10.0,
        "environment.device": "cpu",
    }
    cfg = load_config(DEFAULT_YAML_PATH, overrides=overrides)
    assert cfg.assembly.canvas_size == 2049
    assert cfg.tiers.bright_limit == 10.0
    assert cfg.environment.device == "cpu"


def test_validation_bright_faint_limit_error():
    with pytest.raises(ValueError, match="bright_limit .* must be less than faint_limit"):
        cfg = PipelineConfig(tiers=TiersSection(bright_limit=14.0, faint_limit=12.0))
        cfg.validate()


def test_validation_canvas_size_error():
    with pytest.raises(ValueError, match="canvas_size must be positive"):
        cfg = PipelineConfig(assembly=AssemblySection(canvas_size=-10))
        cfg.validate()


def test_validation_overlap_bounds_error():
    from proposed_config import OverlapAnnulusConfig
    with pytest.raises(ValueError, match="overlap_fm.r_min .* must be < r_max"):
        cfg = PipelineConfig(
            assembly=AssemblySection(overlap_fm=OverlapAnnulusConfig(r_min=20.0, r_max=10.0, blend_start=12.0, blend_end=15.0))
        )
        cfg.validate()


def test_torch_device_resolution():
    import torch
    cfg = PipelineConfig(environment=EnvironmentSection(device="cpu"))
    assert cfg.get_torch_device() == torch.device("cpu")

    cfg_auto = PipelineConfig(environment=EnvironmentSection(device="auto"))
    dev = cfg_auto.get_torch_device()
    assert dev.type in ("mps", "cuda", "cpu")


def test_to_dict_and_save_roundtrip(tmp_path):
    cfg = PipelineConfig()
    d = cfg.to_dict()
    assert isinstance(d, dict)
    assert d["pipeline"]["name"] == "romanepsf"

    save_path = tmp_path / "test_saved_config.yaml"
    cfg.save(save_path)
    assert save_path.is_file()

    reloaded = load_config(save_path)
    assert reloaded.pipeline.name == cfg.pipeline.name
    assert reloaded.assembly.canvas_size == cfg.assembly.canvas_size
