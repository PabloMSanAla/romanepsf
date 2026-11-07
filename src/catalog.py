"""
Backward-compatibility wrapper re-exporting from romanepsf.catalog.
"""

from romanepsf.catalog import (
    assign_stellar_tiers,
    filter_isolated_stars,
    get_detector_sky_bounds,
    get_psf_extension_moffat,
    project_catalog_to_pixels,
    query_gaia_for_detector,
    refine_stellar_centroids,
    sanitize_source_catalog,
)

__all__ = [
    "assign_stellar_tiers",
    "filter_isolated_stars",
    "get_detector_sky_bounds",
    "get_psf_extension_moffat",
    "project_catalog_to_pixels",
    "query_gaia_for_detector",
    "refine_stellar_centroids",
    "sanitize_source_catalog",
]
