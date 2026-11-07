"""
Backward-compatibility wrapper re-exporting from romanepsf.validation.
"""

from romanepsf.validation import (
    StarResidualResult,
    RadialMetrics,
    ValidationResults,
    compute_spike_ray_mask,
    fit_star_to_model,
    compute_radial_residual_metrics,
    evaluate_epsf_validation,
)

__all__ = [
    "StarResidualResult",
    "RadialMetrics",
    "ValidationResults",
    "compute_spike_ray_mask",
    "fit_star_to_model",
    "compute_radial_residual_metrics",
    "evaluate_epsf_validation",
]
