"""
Roman Extended PSF (ePSF) Measurement Pipeline.
"""

import warnings

# Suppress harmless ASDF package version warning when ASDF file was saved with newer extension URI
try:
    from asdf.exceptions import AsdfPackageVersionWarning
    warnings.filterwarnings("ignore", category=AsdfPackageVersionWarning)
except ImportError:
    pass
warnings.filterwarnings("ignore", message=r".*was created with extension URI.*")
warnings.filterwarnings("ignore", message=r".*AsdfPackageVersionWarning.*")

__version__ = "0.1.0"

from .config import (
    Config,
    PipelineConfig,
    load_config,
    resolve_device,
)
from .loader import (
    ACTIVE_SHAPE,
    DEFAULT_DQ_MASK_FLAGS,
    DQ_FLAGS,
    NOMINAL_PIXEL_AREA,
    NOMINAL_PIXEL_SCALE,
    RomanL2Data,
    get_dq_mask,
    get_effective_mask,
    load_l2_image,
)
from .background import (
    estimate_detector_sky_noisechisel,
)
from .catalog import (
    assign_stellar_tiers,
    filter_isolated_stars,
    get_detector_sky_bounds,
    get_psf_extension_moffat,
    project_catalog_to_pixels,
    query_gaia_for_detector,
    refine_stellar_centroids,
    sanitize_source_catalog,
)
from .stamps import (
    StellarStamp,
    StampData,
    get_adaptive_stamp_size,
    extract_cutout,
    estimate_stamp_background,
    subtract_stamp_background,
    recenter_and_align_stamp,
    process_star_stamps,
)
from .masking import (
    ROMAN_PRIMARY_SPIKE_ANGLES_DEG,
    ROMAN_SECONDARY_SPIKE_ANGLES_DEG,
    ROMAN_BASE_SPIKE_ANGLES_DEG,
    NOMINAL_DETECTOR_OFFSET_DEG,
    get_theoretical_spike_angles,
    get_all_spike_angles,
    refine_spike_angles,
    detect_spike_peaks_from_profile,
    create_geometric_spike_mask,
    detect_morphological_spikes,
    compute_unsharp_mask_residual,
    radial_hough_transform,
    detect_spikes_rht,
    create_rht_spike_mask,
    fit_moffat_model,
    fit_moffat_astrophot,
    fit_moffat_astropy,
    fit_superback_model,
    fit_stpsf_model,
    fit_stellar_model,
    mask_gaia_companion_stars,
    mask_contaminants_with_spikes_protected,
    mask_sources_not_main_star_mto2,
    segment_sources_mto2,
)
from .mto2 import (
    MTO2Config,
)
from .profile import (
    get_geometric_radial_bins,
    create_ellipse_meshgrid_torch,
    elliptical_profile,
)
from .assembly import (
    stack_tier_stamps_torch,
    measure_radial_profile_1d,
    determine_overlap_scale_factor_dual,
    determine_overlap_scale_factor,
    blend_2d_annular_profiles,
    assemble_composite_extended_psf,
)
from .validation import (
    StarResidualResult,
    RadialMetrics,
    ValidationResults,
    compute_spike_ray_mask,
    fit_star_to_model,
    compute_radial_residual_metrics,
    evaluate_epsf_validation,
)
from .report import (
    ReportDataBundle,
    generate_publication_pdf_report,
)
from .debug_plots import (
    generate_all_debug_plots,
)

__all__ = [
    "__version__",
    "Config",
    "PipelineConfig",
    "load_config",
    "resolve_device",
    "RomanL2Data",
    "load_l2_image",
    "get_dq_mask",
    "get_effective_mask",
    "DQ_FLAGS",
    "DEFAULT_DQ_MASK_FLAGS",
    "ACTIVE_SHAPE",
    "NOMINAL_PIXEL_SCALE",
    "NOMINAL_PIXEL_AREA",
    "assign_stellar_tiers",
    "filter_isolated_stars",
    "get_detector_sky_bounds",
    "get_psf_extension_moffat",
    "project_catalog_to_pixels",
    "query_gaia_for_detector",
    "refine_stellar_centroids",
    "sanitize_source_catalog",
    "StellarStamp",
    "StampData",
    "get_adaptive_stamp_size",
    "extract_cutout",
    "estimate_stamp_background",
    "subtract_stamp_background",
    "estimate_detector_sky_noisechisel",
    "recenter_and_align_stamp",
    "process_star_stamps",
    "ROMAN_PRIMARY_SPIKE_ANGLES_DEG",
    "ROMAN_SECONDARY_SPIKE_ANGLES_DEG",
    "ROMAN_BASE_SPIKE_ANGLES_DEG",
    "NOMINAL_DETECTOR_OFFSET_DEG",
    "get_theoretical_spike_angles",
    "get_all_spike_angles",
    "refine_spike_angles",
    "detect_spike_peaks_from_profile",
    "create_geometric_spike_mask",
    "detect_morphological_spikes",
    "fit_moffat_model",
    "fit_moffat_astrophot",
    "fit_moffat_astropy",
    "mask_gaia_companion_stars",
    "mask_sources_not_main_star_mto2",
    "segment_sources_mto2",
    "MTO2Config",
    "mask_contaminants_with_spikes_protected",
    "get_geometric_radial_bins",
    "create_ellipse_meshgrid_torch",
    "elliptical_profile",
    "stack_tier_stamps_torch",
    "measure_radial_profile_1d",
    "determine_overlap_scale_factor_dual",
    "determine_overlap_scale_factor",
    "blend_2d_annular_profiles",
    "assemble_composite_extended_psf",
    "StarResidualResult",
    "RadialMetrics",
    "ValidationResults",
    "compute_spike_ray_mask",
    "fit_star_to_model",
    "compute_radial_residual_metrics",
    "evaluate_epsf_validation",
    "ReportDataBundle",
    "generate_publication_pdf_report",
    "generate_all_debug_plots",
]
