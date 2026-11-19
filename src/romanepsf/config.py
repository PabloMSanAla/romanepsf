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


def normalize_sca_id(sca: Union[int, str, None], default: str = "wfi01") -> str:
    """
    Normalize SCA identifier into standard lowercase 'wfiXX' format (e.g. 'wfi01' through 'wfi18').

    Parameters
    ----------
    sca : Union[int, str, None]
        Detector SCA number (1-18) as integer, or string (e.g. 1, '1', '01', 'wfi01', 'WFI01', 'sca01').
    default : str, default 'wfi01'
        Default fallback if sca is None or empty.

    Returns
    -------
    str
        Standardized identifier, e.g. 'wfi01', 'wfi02', ..., 'wfi18'.

    Raises
    ------
    ValueError
        If sca is not within range 1 to 18.
    """
    if sca is None or (isinstance(sca, str) and not sca.strip()):
        sca = default

    if isinstance(sca, (int, float)):
        num = int(sca)
    elif isinstance(sca, str):
        s = sca.strip().lower()
        if s.startswith("wfi"):
            s = s[3:]
        elif s.startswith("sca"):
            s = s[3:]
        try:
            num = int(s)
        except ValueError:
            raise ValueError(f"Invalid SCA identifier '{sca}'. Expected integer 1-18 or 'wfi01'-'wfi18'.")
    else:
        try:
            num = int(sca)
        except Exception:
            raise ValueError(f"Invalid SCA identifier type {type(sca)}. Expected int or str.")

    if num < 1 or num > 18:
        raise ValueError(f"Invalid SCA number {num}. Roman WFI detectors are numbered 1 through 18.")

    return f"wfi{num:02d}"


@dataclass
class PipelineSection:
    name: str = "romanepsf"
    version: str = "0.1.0"
    integrity_mode: str = "development"
    log_level: str = "INFO"
    random_seed: int = 42
    debug: Optional[int] = None


@dataclass
class EnvironmentSection:
    device: str = "auto"              # 'auto', 'mps', 'cuda', 'cpu'
    num_workers: int = 4
    memory_fraction: float = 0.70


@dataclass
class DataSection:
    detectors_dir: Path = field(default_factory=lambda: Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors"))
    catalog_path: Optional[Path] = field(default_factory=lambda: Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv"))
    output_dir: Path = field(default_factory=lambda: Path("output"))
    cache_dir: Path = field(default_factory=lambda: Path("cache"))
    gaia_cache_dir: Path = field(default_factory=lambda: Path("cache/gaia_healpix"))
    file_list: Optional[Path] = None
    sca: Optional[str] = None
    filter_name: str = "F146"
    detectors: List[str] = field(default_factory=lambda: ["wfi01"])

    def __post_init__(self):
        if isinstance(self.detectors_dir, str):
            self.detectors_dir = Path(self.detectors_dir)
        if self.catalog_path is not None and str(self.catalog_path).strip().lower() in ["none", "null", ""]:
            self.catalog_path = None
        elif isinstance(self.catalog_path, str):
            self.catalog_path = Path(self.catalog_path)
        if isinstance(self.output_dir, str):
            self.output_dir = Path(self.output_dir)
        if isinstance(self.cache_dir, str):
            self.cache_dir = Path(self.cache_dir)
        if isinstance(self.gaia_cache_dir, str):
            self.gaia_cache_dir = Path(self.gaia_cache_dir)
        if isinstance(self.file_list, str):
            self.file_list = Path(self.file_list)
        if self.sca is not None:
            self.sca = normalize_sca_id(self.sca)
        if isinstance(self.detectors, str):
            self.detectors = [normalize_sca_id(d.strip()) for d in self.detectors.split(",") if d.strip()]
        elif isinstance(self.detectors, (list, tuple)):
            self.detectors = [normalize_sca_id(d) for d in self.detectors]


@dataclass
class CatalogSection:
    mag_col: str = "mag_lambda"
    use_cached_gaia: bool = True
    query_gaia_fallback: bool = True
    isolation_safety_factor: float = 1.3
    min_dist_arcsec: float = 2.0
    edge_margin_px: int = 50
    centroid_box_fraction: float = 0.30
    centroid_refine_box_px: Optional[int] = None
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
class BackgroundSection:
    annulus_depth: List[float] = field(default_factory=lambda: [27.0, 28.0])
    sigma_upper: float = 2.0
    sigma_lower: float = 3.0
    max_iters: int = 10

    def __post_init__(self):
        if isinstance(self.annulus_depth, (tuple, list)):
            self.annulus_depth = [float(x) for x in self.annulus_depth]
        self.sigma_upper = float(self.sigma_upper)
        self.sigma_lower = float(self.sigma_lower)
        self.max_iters = int(self.max_iters)


@dataclass
class StampsSection:
    sizes: StampSizes = field(default_factory=StampSizes)
    subpixel_interpolation_order: int = 3
    dq_flags_to_mask: List[str] = field(default_factory=lambda: ["DO_NOT_USE", "SATURATED", "DROPOUT"])
    faint_core_protect_finite: bool = True
    background: BackgroundSection = field(default_factory=BackgroundSection)

    def __post_init__(self):
        if isinstance(self.sizes, dict):
            self.sizes = StampSizes(**self.sizes)
        if isinstance(self.background, dict):
            self.background = BackgroundSection(**self.background)


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
    contaminant_detection_sigma: float = 1.3
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
    growth_rate: float = 1.03
    bin_spacing: str = "geometric"
    r_min_px: float = 0.5


@dataclass
class OverlapAnnulusConfig:
    r_min: float = 8.0
    r_max: float = 16.0
    blend_start: float = 10.0
    blend_end: float = 18.0
    mode: str = "auto"  # 'auto', 'depth', 'pixel'
    norm_depth: Optional[Union[List[float], Tuple[float, float]]] = None
    blend_depth: Optional[Union[List[float], Tuple[float, float]]] = None

    def __post_init__(self):
        if self.norm_depth is not None:
            self.norm_depth = tuple(float(x) for x in self.norm_depth)
        if self.blend_depth is not None:
            self.blend_depth = tuple(float(x) for x in self.blend_depth)

    def resolve_radii(
        self,
        mag: float,
        pixel_scale: float = 0.11,
        max_stamp_radius: Optional[float] = None,
    ) -> Tuple[float, float, float, float]:
        """
        Resolve (r_min, r_max, blend_start, blend_end) pixel radii.
        If mode is 'depth' or ('auto' with norm_depth specified),
        derives pixel radii dynamically using get_psf_extension_moffat at the given magnitude.
        Otherwise falls back to explicit pixel radii.
        """
        use_depth = (
            str(self.mode).lower() in ("depth", "auto")
            and self.norm_depth is not None
        )
        if use_depth:
            from romanepsf.profile import get_psf_extension_moffat

            d_norm = self.norm_depth
            r_min_arc = float(get_psf_extension_moffat(mag, depth=float(d_norm[0])))
            r_max_arc = float(get_psf_extension_moffat(mag, depth=float(d_norm[1])))
            r_min_calc = r_min_arc / pixel_scale
            r_max_calc = r_max_arc / pixel_scale

            if self.blend_depth is not None:
                d_blend = self.blend_depth
                b_start_arc = float(get_psf_extension_moffat(mag, depth=float(d_blend[0])))
                b_end_arc = float(get_psf_extension_moffat(mag, depth=float(d_blend[1])))
                b_start_calc = b_start_arc / pixel_scale
                b_end_calc = b_end_arc / pixel_scale
            else:
                b_start_calc = float(self.blend_start) if self.blend_start is not None else r_min_calc
                b_end_calc = float(self.blend_end) if self.blend_end is not None else r_max_calc

            if r_max_calc <= r_min_calc:
                r_max_calc = r_min_calc + 1.0
            if b_end_calc <= b_start_calc:
                b_end_calc = b_start_calc + 1.0

            # Safety clamping to stay inside the inner stamp footprint
            if max_stamp_radius is not None and max_stamp_radius > 2.0:
                cap = float(max_stamp_radius) * 0.95
                if b_start_calc >= cap - 5.0 or b_end_calc > cap:
                    if (
                        self.blend_start is not None
                        and self.blend_end is not None
                        and float(self.blend_end) <= cap
                    ):
                        b_start_calc = float(self.blend_start)
                        b_end_calc = float(self.blend_end)
                    else:
                        b_end_calc = min(b_end_calc, cap)
                        min_width = max(15.0, min(25.0, 0.25 * cap))
                        b_start_calc = max(2.0, b_end_calc - min_width)
                else:
                    b_end_calc = min(b_end_calc, cap)
                    b_start_calc = min(b_start_calc, b_end_calc - 1.0)

                if r_max_calc > cap:
                    if (
                        self.r_min is not None
                        and self.r_max is not None
                        and float(self.r_max) <= cap
                    ):
                        r_min_calc = float(self.r_min)
                        r_max_calc = float(self.r_max)
                    else:
                        r_max_calc = min(r_max_calc, b_start_calc)
                        r_min_calc = min(r_min_calc, r_max_calc - 1.0)

            return float(r_min_calc), float(r_max_calc), float(b_start_calc), float(b_end_calc)

        # Fallback to pixel radii
        r_min = float(self.r_min) if self.r_min is not None else 8.0
        r_max = float(self.r_max) if self.r_max is not None else 16.0
        b_start = float(self.blend_start) if self.blend_start is not None else 10.0
        b_end = float(self.blend_end) if self.blend_end is not None else 18.0
        return r_min, r_max, b_start, b_end


@dataclass
class AssemblySection:
    canvas_size: int = 1025
    stack_sigma_clip: float = 3.0
    overlap_fm: OverlapAnnulusConfig = field(default_factory=lambda: OverlapAnnulusConfig(
        r_min=8.0, r_max=16.0, blend_start=10.0, blend_end=18.0,
        mode="auto", norm_depth=(20.0, 23.0), blend_depth=(25.0, 27.0)
    ))
    overlap_mb: OverlapAnnulusConfig = field(default_factory=lambda: OverlapAnnulusConfig(
        r_min=22.0, r_max=45.0, blend_start=30.0, blend_end=48.0,
        mode="auto", norm_depth=(20.0, 23.0), blend_depth=(25.0, 27.0)
    ))
    normalize_flux: bool = True
    oversampling_faint: int = 4
    oversampling_medium: int = 4
    bright_limit: float = 11.0
    faint_limit: float = 13.0
    pixel_scale: float = 0.11
    faint_size: int = 81
    medium_size: int = 201
    bright_max: int = 1001

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
    background: BackgroundSection = field(default_factory=BackgroundSection)

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
        if isinstance(self.background, dict):
            self.background = BackgroundSection(**self.background)

        # Synchronize background settings between root and stamps
        if hasattr(self, "stamps") and hasattr(self.stamps, "background"):
            if self.background != BackgroundSection() and self.stamps.background == BackgroundSection():
                self.stamps.background = self.background
            elif self.stamps.background != BackgroundSection() and self.background == BackgroundSection():
                self.background = self.stamps.background

        # Propagate tier limits and stamp footprints to assembly section
        if hasattr(self, "tiers") and hasattr(self, "assembly"):
            self.assembly.bright_limit = getattr(self.tiers, "bright_limit", self.assembly.bright_limit)
            self.assembly.faint_limit = getattr(self.tiers, "faint_limit", self.assembly.faint_limit)
        if hasattr(self, "stamps") and hasattr(self, "assembly"):
            sizes = getattr(self.stamps, "sizes", None)
            if sizes is not None:
                self.assembly.faint_size = getattr(sizes, "faint", self.assembly.faint_size)
                self.assembly.medium_size = getattr(sizes, "medium", self.assembly.medium_size)
                self.assembly.bright_max = getattr(sizes, "bright_max", self.assembly.bright_max)

    def validate(self) -> None:
        """Validate logical relationships and parameter constraints."""
        if self.tiers.bright_limit >= self.tiers.faint_limit:
            raise ValueError(
                f"bright_limit must be strictly less than faint_limit: {self.tiers.bright_limit} >= {self.tiers.faint_limit}"
            )

        if self.pipeline.debug is not None and self.pipeline.debug <= 0:
            raise ValueError(
                f"pipeline.debug must be a positive integer, got {self.pipeline.debug}"
            )

        if self.profile.growth_rate <= 1.0:
            raise ValueError(
                f"profile.growth_rate must be strictly greater than 1.0, got {self.profile.growth_rate}"
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
