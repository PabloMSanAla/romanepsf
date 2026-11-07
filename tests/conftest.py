"""
Pytest configuration and shared fixtures for Roman ePSF Measurement Pipeline E2E tests.
"""

import sys
from pathlib import Path
import numpy as np
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

DATA_DIR = Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors")
CATALOG_PATH = DATA_DIR / "code" / "r0108301001001001001_0001_wfi_source_catalog.csv"
WFI01_ASDF = DATA_DIR / "r0108301001001001001_0001_wfi01_f146_cal.asdf"
WFI05_ASDF = DATA_DIR / "r0108301001001001001_0001_wfi05_f146_cal.asdf"


def get_module(module_name: str):
    """
    Safely import a module from either 'romanepsf.<module_name>' or 'src.<module_name>' or '<module_name>'.
    Returns the module if found, or None if not yet implemented.
    """
    for prefix in ["romanepsf.", "src.", ""]:
        full_name = f"{prefix}{module_name}" if prefix else module_name
        try:
            mod = __import__(full_name, fromlist=["*"])
            return mod
        except (ImportError, ModuleNotFoundError):
            continue
    return None


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def detectors_dir() -> Path:
    return DATA_DIR


@pytest.fixture(scope="session")
def catalog_path() -> Path:
    return CATALOG_PATH


@pytest.fixture(scope="session")
def wfi01_asdf_path() -> Path:
    return WFI01_ASDF


@pytest.fixture(scope="session")
def wfi05_asdf_path() -> Path:
    return WFI05_ASDF


@pytest.fixture
def sample_config_dict() -> dict:
    """Default configuration dictionary reflecting configs/default.yaml specification."""
    return {
        "pipeline": {
            "name": "roman_epsf_pipeline",
            "version": "1.0.0",
            "integrity_mode": "development",
            "log_level": "INFO",
            "random_seed": 42,
        },
        "environment": {
            "device": "cpu",
            "num_workers": 2,
            "memory_fraction": 0.70,
        },
        "data": {
            "detectors_dir": str(DATA_DIR),
            "catalog_path": str(CATALOG_PATH),
            "output_dir": "output",
            "cache_dir": "cache",
            "filter_name": "F146",
            "detectors": ["wfi01"],
        },
        "catalog": {
            "mag_col": "mag_lambda",
            "use_cached_gaia": True,
            "query_gaia_fallback": False,
            "isolation_safety_factor": 1.3,
            "min_dist_arcsec": 2.0,
            "edge_margin_px": 50,
            "centroid_refine_box_px": 5,
            "roundtrip_tolerance_arcsec": 0.5,
        },
        "tiers": {
            "bright_limit": 11.0,
            "faint_limit": 13.0,
            "max_stars_per_tier": {"bright": 10, "medium": 20, "faint": 30},
        },
        "stamps": {
            "sizes": {"bright_max": 1001, "medium": 201, "faint": 81},
            "subpixel_interpolation_order": 3,
            "dq_flags_to_mask": ["DO_NOT_USE", "SATURATED", "DROPOUT"],
            "faint_core_protect_finite": True,
        },
        "spikes": {
            "base_angles_deg": [23.55, 55.29, 80.25, 118.65, 142.88, 178.07],
            "detector_alignment_offset_deg": -9.70,
            "angular_half_width_deg": 4.0,
            "spike_width_px": 4.0,
            "core_protection_radius_px": {"bright": 6.0, "medium": 4.0, "faint": 3.0},
            "morphological": {
                "threshold_sigma": 2.0,
                "min_length_px": 15,
                "dilation_iterations": 2,
            },
            "contaminant_detection_sigma": 3.0,
        },
        "profile": {
            "ellipticity": 0.0,
            "position_angle": 0.0,
            "sigma_clip": 3.0,
            "max_clip_iters": 5,
            "radial_step_px": 1.0,
            "num_workers": 4,
        },
        "assembly": {
            "canvas_size": 1025,
            "stack_sigma_clip": 3.0,
            "overlap_fm": {
                "r_min": 8.0,
                "r_max": 16.0,
                "blend_start": 10.0,
                "blend_end": 18.0,
            },
            "overlap_mb": {
                "r_min": 22.0,
                "r_max": 45.0,
                "blend_start": 30.0,
                "blend_end": 48.0,
            },
            "normalize_flux": True,
        },
        "validation": {
            "eval_stars_per_tier": 5,
            "core_radius_max_px": 10.0,
            "transition_radius_px": [10.0, 30.0],
            "wings_radius_min_px": 30.0,
            "regularization_sigma": 3.0,
        },
        "reporting": {
            "generate_pdf": True,
            "report_path": "output/roman_epsf_commissioning_report.pdf",
            "dpi": 300,
        },
    }


@pytest.fixture
def synthetic_l2_data():
    """
    Constructs a lightweight mock RomanL2Data for rapid isolated unit and boundary testing
    without loading a full 200 MB ASDF file each time.
    """
    from src.loader import RomanL2Data

    shape = (500, 500)
    data = np.full(shape, 1.8, dtype=np.float32)  # Background ~1.8 MJy/sr
    raw_data = data.copy() / 0.238965
    err = np.full(shape, 0.05, dtype=np.float32)
    dq = np.zeros(shape, dtype=np.uint32)

    # Simple mock WCS
    class MockWCS:
        def __init__(self, crval_ra=303.12, crval_dec=-19.93, cdelt=0.11 / 3600.0):
            self.crval_ra = crval_ra
            self.crval_dec = crval_dec
            self.cdelt = cdelt

        def __call__(self, x, y):
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            ra = self.crval_ra + (x - 250.0) * self.cdelt
            dec = self.crval_dec + (y - 250.0) * self.cdelt
            return ra, dec

        def invert(self, ra, dec):
            return self.backward_transform(ra, dec)

        def backward_transform(self, ra, dec):
            ra = np.asarray(ra, dtype=float)
            dec = np.asarray(dec, dtype=float)
            x = (ra - self.crval_ra) / self.cdelt + 250.0
            y = (dec - self.crval_dec) / self.cdelt + 250.0
            return x, y

    meta = {
        "detector": "WFI01",
        "filter": "F146",
        "exposure_time": 294.11,
        "roll_ref": -110.02,
        "v3yangle": -60.00,
        "pa_aperture": -110.02,
        "conversion_megajanskys": 0.238965,
        "pixel_area": 2.8e-13,
        "zp_ab": 26.0,
        "pixel_scale": 0.11,
    }

    return RomanL2Data(
        detector="WFI01",
        filter_name="F146",
        data=data,
        raw_data=raw_data,
        err=err,
        dq=dq,
        wcs=MockWCS(),
        pa_aperture=-110.02,
        meta=meta,
        zp_ab=26.0,
        pixel_scale=0.11,
        conversion_factor=0.238965,
        pixel_area=2.8e-13,
    )
