"""
Backward-compatibility wrapper re-exporting from romanepsf.stamps.
"""

from romanepsf.stamps import (
    StellarStamp,
    StampData,
    get_adaptive_stamp_size,
    extract_cutout,
    estimate_stamp_background,
    subtract_stamp_background,
    recenter_and_align_stamp,
    process_star_stamps,
)

__all__ = [
    "StellarStamp",
    "StampData",
    "get_adaptive_stamp_size",
    "extract_cutout",
    "estimate_stamp_background",
    "subtract_stamp_background",
    "recenter_and_align_stamp",
    "process_star_stamps",
]
