"""
Configuration loader, dataclass schema, and validation for Roman ePSF Pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union
import copy
import logging
import yaml
import torch

logger = logging.getLogger("romanepsf.config")


def resolve_device(device_str: str = "auto") -> torch.device:
    """
    Resolve device string to torch.device object.

    Parameters
    ----------
    device_str : str, default 'auto'
        Requested compute device ('auto', 'mps', 'cuda', 'cpu').

    Returns
    -------
    torch.device
        Resolved PyTorch device.

    Raises
    ------
    ValueError
        If device_str is not recognized.
    """
    dev = device_str.lower().strip()
    if dev == "auto":
        if torch.backends.mps.is_available():
            return torch.device("mps")
        elif torch.cuda.is_available():
            return torch.device("cuda")
        else:
            return torch.device("cpu")
    elif dev == "mps":
        if not torch.backends.mps.is_available():
            logger.warning("MPS requested but not available. Falling back to CPU.")
            return torch.device("cpu")
        return torch.device("mps")
    elif dev == "cuda":
        if not torch.cuda.is_available():
            logger.warning("CUDA requested but not available. Falling back to CPU.")
            return torch.device("cpu")
        return torch.device("cuda")
    elif dev == "cpu":
        return torch.device("cpu")
    else:
        raise ValueError(
            f"Unknown or unsupported device: '{device_str}'. Valid options: auto, mps, cuda, cpu"
        )


@dataclass
class PipelineSection:
    name: str = "romanepsf"
    version: str = "0.1.0"
    integrity_mode: str = "development"
    log_level: str = "INFO"
    random_seed: int = 42


@dataclass
class EnvironmentSection:
    device: str = "auto"              # 'auto', 'mps', 'cuda', 'cpu'
    num_workers: int = 4
    memory_fraction: float = 0.70


@dataclass
class DataSection:
    detectors_dir: Path = field(default_factory=lambda: Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors"))
    catalog_path: Path = field(default_factory=lambda: Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv"))
    output_dir: Path = field(default_factory=lambda: Path("output"))
    cache_dir: Path = field(default_factory=lambda: Path("cache"))
    filter_name: str = "F146"
    detectors: List[str] = field(default_factory=lambda: ["wfi01"])

    def __post_init__(self):
        if isinstance(self.detectors_dir, str):
            self.detectors_dir = Path(self.detectors_dir)
        if isinstance(self.catalog_path, str):
            self.catalog_path = Path(self.catalog_path)
        if isinstance(self.output_dir, str):
            self.output_dir = Path(self.output_dir)
        if isinstance(self.cache_dir, str):
            self.cache_dir = Path(self.cache_dir)
        if isinstance(self.detectors, str):
            self.detectors = [self.detectors]


@dataclass
class CatalogSection:
    mag_col: str = "mag_lambda"
    use_cached_gaia: bool = True
    query_gaia_fallback: bool = True
    isolation_safety_factor: float = 1.3
    min_dist_arcsec: float = 2.0
    edge_margin_px: int = 50
    centroid_refine_box_px: int = 5
    roundtrip_tolerance_arcsec: float = 0.5


@dataclass
class TierCounts:
    bright: int = 20
    medium: int = 50
    faint: int = 100


@dataclass
class TiersSection:
    bright_limit: float = 11.0
    faint_limit: float = 13.0
    max_stars_per_tier: TierCounts = field(default_factory=TierCounts)

    def __post_init__(self):
        if isinstance(self.max_stars_per_tier, dict):
            self.max_stars_per_tier = TierCounts(**self.max_stars_per_tier)


@dataclass
class StampSizes:
    bright_max: int = 1001
    medium: int = 201
    faint: int = 81


@dataclass
class StampsSection:
    sizes: StampSizes = field(default_factory=StampSizes)
    subpixel_interpolation_order: int = 3
    dq_flags_to_mask: List[str] = field(default_factory=lambda: ["DO_NOT_USE", "SATURATED", "DROPOUT"])
    faint_core_protect_finite: bool = True

    def __post_init__(self):
        if isinstance(self.sizes, dict):
            self.sizes = StampSizes(**self.sizes)


@dataclass
class MorphologicalConfig:
    threshold_sigma: float = 2.0
    min_length_px: int = 15
    dilation_iterations: int = 2


@dataclass
class CoreProtectionRadius:
    bright: float = 6.0
    medium: float = 4.0
    faint: float = 3.0


@dataclass
class MTO2ConfigSection:
    s_sigma: float = 1.6
    alpha: float = 1e-6
    move_factor: float = 0.1
    area_ratio: float = 0.90
    dilation_px: int = 2
    min_source_area_px: int = 3
    background_mode: str = "const"


@dataclass
class SpikesSection:
    spike_order: Optional[str] = None
    base_angles_deg: List[float] = field(default_factory=lambda: [23.55, 55.29, 80.25, 118.65, 142.88, 178.07])
    detector_alignment_offset_deg: float = -9.70
    angular_half_width_deg: float = 4.0
    spike_width_px: float = 4.0
    width_growth_rate: float = 0.025
    core_protection_radius_px: CoreProtectionRadius = field(default_factory=CoreProtectionRadius)
    morphological: MorphologicalConfig = field(default_factory=MorphologicalConfig)
    contaminant_detection_sigma: float = 3.0
    contaminant_detector: str = "erosion_dilation"
    mto2: MTO2ConfigSection = field(default_factory=MTO2ConfigSection)

    def __post_init__(self):
        if isinstance(self.core_protection_radius_px, dict):
            self.core_protection_radius_px = CoreProtectionRadius(**self.core_protection_radius_px)
        if isinstance(self.morphological, dict):
            self.morphological = MorphologicalConfig(**self.morphological)
        if isinstance(self.mto2, dict):
            self.mto2 = MTO2ConfigSection(**self.mto2)


@dataclass
class ProfileSection:
    ellipticity: float = 0.0
    position_angle: float = 0.0
    sigma_clip: float = 3.0
    max_clip_iters: int = 5
    radial_step_px: float = 1.0
    num_workers: int = 8


@dataclass
class OverlapAnnulusConfig:
    r_min: float
    r_max: float
    blend_start: float = 10.0
    blend_end: float = 18.0


@dataclass
class AssemblySection:
    canvas_size: int = 1025
    stack_sigma_clip: float = 3.0
    overlap_fm: OverlapAnnulusConfig = field(default_factory=lambda: OverlapAnnulusConfig(8.0, 16.0, 10.0, 18.0))
    overlap_mb: OverlapAnnulusConfig = field(default_factory=lambda: OverlapAnnulusConfig(22.0, 45.0, 30.0, 48.0))
    normalize_flux: bool = True
    oversampling_faint: int = 4
    oversampling_medium: int = 4

    def __post_init__(self):
        if isinstance(self.overlap_fm, dict):
            self.overlap_fm = OverlapAnnulusConfig(**self.overlap_fm)
        if isinstance(self.overlap_mb, dict):
            self.overlap_mb = OverlapAnnulusConfig(**self.overlap_mb)

    @property
    def output_size(self) -> int:
        """Alias for canvas_size for assembly compatibility."""
        return self.canvas_size

    @output_size.setter
    def output_size(self, val: int) -> None:
        self.canvas_size = val


@dataclass
class ValidationSection:
    eval_stars_per_tier: int = 5
    core_radius_max_px: float = 10.0
    transition_radius_px: List[float] = field(default_factory=lambda: [10.0, 30.0])
    wings_radius_min_px: float = 30.0
    regularization_sigma: float = 3.0


@dataclass
class ReportingSection:
    generate_pdf: bool = True
    report_path: Path = field(default_factory=lambda: Path("output/roman_epsf_commissioning_report.pdf"))
    dpi: int = 300

    def __post_init__(self):
        if isinstance(self.report_path, str):
            self.report_path = Path(self.report_path)


@dataclass
class PipelineConfig:
    """Root configuration object containing all pipeline parameters."""
    pipeline: PipelineSection = field(default_factory=PipelineSection)
    environment: EnvironmentSection = field(default_factory=EnvironmentSection)
    data: DataSection = field(default_factory=DataSection)
    catalog: CatalogSection = field(default_factory=CatalogSection)
    tiers: TiersSection = field(default_factory=TiersSection)
    stamps: StampsSection = field(default_factory=StampsSection)
    spikes: SpikesSection = field(default_factory=SpikesSection)
    profile: ProfileSection = field(default_factory=ProfileSection)
    assembly: AssemblySection = field(default_factory=AssemblySection)
    validation: ValidationSection = field(default_factory=ValidationSection)
    reporting: ReportingSection = field(default_factory=ReportingSection)

    def __post_init__(self):
        if isinstance(self.pipeline, dict):
            self.pipeline = PipelineSection(**self.pipeline)
        if isinstance(self.environment, dict):
            self.environment = EnvironmentSection(**self.environment)
        if isinstance(self.data, dict):
            self.data = DataSection(**self.data)
        if isinstance(self.catalog, dict):
            self.catalog = CatalogSection(**self.catalog)
        if isinstance(self.tiers, dict):
            self.tiers = TiersSection(**self.tiers)
        if isinstance(self.stamps, dict):
            self.stamps = StampsSection(**self.stamps)
        if isinstance(self.spikes, dict):
            self.spikes = SpikesSection(**self.spikes)
        if isinstance(self.profile, dict):
            self.profile = ProfileSection(**self.profile)
        if isinstance(self.assembly, dict):
            self.assembly = AssemblySection(**self.assembly)
        if isinstance(self.validation, dict):
            self.validation = ValidationSection(**self.validation)
        if isinstance(self.reporting, dict):
            self.reporting = ReportingSection(**self.reporting)

    def validate(self) -> None:
        """Validate logical relationships and parameter constraints."""
        if self.tiers.bright_limit >= self.tiers.faint_limit:
            raise ValueError(
                f"bright_limit must be strictly less than faint_limit: {self.tiers.bright_limit} >= {self.tiers.faint_limit}"
            )

        if isinstance(self.assembly.canvas_size, str) or not isinstance(self.assembly.canvas_size, (int, float)):
            raise TypeError(
                f"canvas_size must be an integer, got {type(self.assembly.canvas_size).__name__}"
            )
        if (
            not isinstance(self.assembly.canvas_size, int)
            or isinstance(self.assembly.canvas_size, bool)
            or self.assembly.canvas_size <= 0
            or self.assembly.canvas_size % 2 == 0
        ):
            raise ValueError(
                f"canvas_size must be an odd positive integer, got {self.assembly.canvas_size}"
            )

        # Check overlap intervals
        fm = self.assembly.overlap_fm
        if fm.r_min >= fm.r_max:
            raise ValueError(f"r_min must be less than r_max for overlap_fm: {fm.r_min} >= {fm.r_max}")
        if fm.blend_start >= fm.blend_end:
            raise ValueError(f"blend_start must be less than blend_end for overlap_fm: {fm.blend_start} >= {fm.blend_end}")

        mb = self.assembly.overlap_mb
        if mb.r_min >= mb.r_max:
            raise ValueError(f"r_min must be less than r_max for overlap_mb: {mb.r_min} >= {mb.r_max}")
        if mb.blend_start >= mb.blend_end:
            raise ValueError(f"blend_start must be less than blend_end for overlap_mb: {mb.blend_start} >= {mb.blend_end}")

        if self.catalog.roundtrip_tolerance_arcsec <= 0:
            raise ValueError(f"roundtrip_tolerance_arcsec must be > 0, got {self.catalog.roundtrip_tolerance_arcsec}")

        valid_devices = ["auto", "mps", "cuda", "cpu"]
        if self.environment.device.lower() not in valid_devices:
            raise ValueError(f"Unknown or unsupported device: '{self.environment.device}'. Valid options: {valid_devices}")

    def get_torch_device(self) -> torch.device:
        """Resolve device string to torch.device object."""
        return resolve_device(self.environment.device)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config structure to primitive python dictionary."""
        d = asdict(self)

        def _stringify_paths(obj):
            if isinstance(obj, dict):
                return {k: _stringify_paths(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_stringify_paths(v) for v in obj]
            elif isinstance(obj, Path):
                return str(obj)
            return obj

        return _stringify_paths(d)

    def save(self, target_path: Union[str, Path]) -> None:
        """Serialize configuration to a YAML file."""
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)


# Aliases for flexibility and compatibility
Config = PipelineConfig
EnvironmentConfig = EnvironmentSection
DataConfig = DataSection
CatalogConfig = CatalogSection
TiersConfig = TiersSection
StampsConfig = StampsSection
SpikesConfig = SpikesSection
ProfileConfig = ProfileSection
AssemblyConfig = AssemblySection
ValidationConfig = ValidationSection
ReportingConfig = ReportingSection


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively update a dictionary without mutating the original."""
    res = copy.deepcopy(base)
    for k, v in updates.items():
        if isinstance(v, dict) and k in res and isinstance(res[k], dict):
            res[k] = _deep_update(res[k], v)
        else:
            res[k] = copy.deepcopy(v)
    return res


def _apply_dot_overrides(cfg_dict: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply dictionary overrides supporting both nested and dot-notation keys."""
    res = copy.deepcopy(cfg_dict)
    for key, value in overrides.items():
        if "." in key:
            parts = key.split(".")
            curr = res
            for part in parts[:-1]:
                if part not in curr or not isinstance(curr[part], dict):
                    curr[part] = {}
                curr = curr[part]
            curr[parts[-1]] = value
        elif isinstance(value, dict) and key in res and isinstance(res[key], dict):
            res[key] = _deep_update(res[key], value)
        else:
            res[key] = value
    return res


def load_config(
    config_path: Union[str, Path, None] = None,
    overrides: Optional[Dict[str, Any]] = None,
    validate: bool = True,
) -> PipelineConfig:
    """
    Load pipeline configuration from a YAML file with default fallback and overrides.

    Parameters
    ----------
    config_path : str, Path, or None
        Path to YAML configuration file. If None, looks for 'configs/default.yaml'.
    overrides : dict, optional
        Dictionary of parameter overrides (supports nested dict or dot notation).
    validate : bool, default True
        Whether to run post-load validation on constraints.

    Returns
    -------
    PipelineConfig
        Validated configuration dataclass instance.
    """
    raw_dict: Dict[str, Any] = {}

    if config_path is not None:
        p = Path(config_path)
        if not p.is_file():
            raise FileNotFoundError(f"Configuration file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if loaded:
                raw_dict = loaded
    else:
        # Default search path
        default_p = Path("configs/default.yaml")
        if default_p.is_file():
            with open(default_p, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if loaded:
                    raw_dict = loaded

    if overrides:
        raw_dict = _apply_dot_overrides(raw_dict, overrides)

    cfg = PipelineConfig(**raw_dict)
    if validate:
        cfg.validate()

    return cfg
