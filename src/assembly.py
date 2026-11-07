"""
Backward-compatibility wrapper re-exporting from romanepsf.assembly.
"""

from romanepsf.assembly import (
    stack_tier_stamps_torch,
    measure_radial_profile_1d,
    determine_overlap_scale_factor_dual,
    determine_overlap_scale_factor,
    blend_2d_annular_profiles,
    _embed_or_crop_canvas,
    assemble_composite_extended_psf,
    serialize_composite_epsf_fits,
)

__all__ = [
    "stack_tier_stamps_torch",
    "measure_radial_profile_1d",
    "determine_overlap_scale_factor_dual",
    "determine_overlap_scale_factor",
    "blend_2d_annular_profiles",
    "_embed_or_crop_canvas",
    "assemble_composite_extended_psf",
    "serialize_composite_epsf_fits",
]
