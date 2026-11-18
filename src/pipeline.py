"""
Backward-compatibility wrapper re-exporting from romanepsf.pipeline.
"""

from romanepsf.pipeline import (
    SingleDetectorResult,
    PipelineOutputs,
    RomanPSFConfig,
    discover_detectors,
    process_single_detector_stamps,
    export_single_detector_fits,
    run_single_detector,
    run_pipeline,
    run_sca_batch_pipeline,
    prefetch_gaia_for_files,
    fast_scan_asdf_footprint,
)

__all__ = [
    "SingleDetectorResult",
    "PipelineOutputs",
    "RomanPSFConfig",
    "discover_detectors",
    "process_single_detector_stamps",
    "export_single_detector_fits",
    "run_single_detector",
    "run_pipeline",
    "run_sca_batch_pipeline",
    "prefetch_gaia_for_files",
    "fast_scan_asdf_footprint",
]
