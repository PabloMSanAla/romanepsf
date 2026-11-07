"""
Backward-compatibility wrapper re-exporting from romanepsf.masking.
"""

from romanepsf.masking import (
    ROMAN_PRIMARY_SPIKE_ANGLES_DEG,
    ROMAN_SECONDARY_SPIKE_ANGLES_DEG,
    ROMAN_BASE_SPIKE_ANGLES_DEG,
    NOMINAL_DETECTOR_OFFSET_DEG,
    create_geometric_spike_mask,
    detect_morphological_spikes,
    fit_moffat_model,
    mask_gaia_companion_stars,
    get_theoretical_spike_angles,
    get_all_spike_angles,
    refine_spike_angles,
    mask_contaminants_with_spikes_protected,
)

__all__ = [
    "ROMAN_PRIMARY_SPIKE_ANGLES_DEG",
    "ROMAN_SECONDARY_SPIKE_ANGLES_DEG",
    "ROMAN_BASE_SPIKE_ANGLES_DEG",
    "NOMINAL_DETECTOR_OFFSET_DEG",
    "create_geometric_spike_mask",
    "detect_morphological_spikes",
    "fit_moffat_model",
    "mask_gaia_companion_stars",
    "get_theoretical_spike_angles",
    "get_all_spike_angles",
    "refine_spike_angles",
    "mask_contaminants_with_spikes_protected",
]
