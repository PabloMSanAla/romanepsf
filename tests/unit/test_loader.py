"""
Unit Tests for Level 2 ASDF Loader and Photometric Calibration.

Tests ASDF opening, science array shape (4088, 4088), photometric zero-point scaling,
DQ bitmask extraction, WCS and pointing metadata extraction, and error handling.
"""

from pathlib import Path
from unittest.mock import MagicMock
import numpy as np
import pytest

from romanepsf.loader import (
    load_l2_image,
    get_dq_mask,
    get_effective_mask,
    RomanL2Data,
    DQ_FLAGS,
)


class MockASDFImageModel:
    """Mock for roman_datamodels ImageModel to isolate unit tests from external files."""

    def __init__(self, shape=(4088, 4088)):
        self.data = np.ones(shape, dtype=np.float32) * 10.0
        self.err = np.ones(shape, dtype=np.float32) * 0.1
        self.dq = np.zeros(shape, dtype=np.uint32)
        # Inject standard DQ flags
        self.dq[10, 10] = 1   # DO_NOT_USE
        self.dq[20, 20] = 2   # SATURATED
        self.dq[30, 30] = 3   # DO_NOT_USE | SATURATED
        self.dq[40, 40] = 4   # JUMP_DET
        self.dq[50, 50] = 8   # DROPOUT

        # Metadata tree
        self.meta = MagicMock()
        self.meta.instrument.detector = "WFI01"
        self.meta.instrument.optical_element = "F146"
        self.meta.photometry.conversion_megajanskys = 0.238965
        self.meta.photometry.pixel_area = 2.801e-13
        self.meta.pointing.pa_aperture = -110.0224
        self.meta.pointing.target_ra = 303.1226
        self.meta.pointing.target_dec = -19.9260
        self.meta.exposure.exposure_time = 294.11
        self.meta.wcsinfo.roll_ref = -110.0224
        self.meta.wcsinfo.v3yangle = -60.0
        self.meta.wcs = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_load_l2_image_mock(monkeypatch):
    """Verify load_l2_image extracts correct data shapes, calibrated units, and metadata."""
    mock_model = MockASDFImageModel()
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy_wfi01.asdf", calibrate=True)

    assert isinstance(l2, RomanL2Data)
    assert l2.detector == "WFI01"
    assert l2.filter_name == "F146"
    assert l2.data.shape == (4088, 4088)
    assert l2.dq.shape == (4088, 4088)
    assert l2.err.shape == (4088, 4088)
    assert l2.conversion_factor == pytest.approx(0.238965, rel=1e-5)

    # Photometric calibration: 10.0 DN/s * 0.238965 = 2.38965 MJy/sr
    assert np.allclose(l2.data, 10.0 * 0.238965)
    assert np.allclose(l2.raw_data, 10.0)
    assert np.allclose(l2.err, 0.1 * 0.238965)


def test_load_l2_image_uncalibrated(monkeypatch):
    """Verify load_l2_image with calibrate=False leaves raw count rates unchanged."""
    mock_model = MockASDFImageModel()
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy_wfi01.asdf", calibrate=False)

    assert np.allclose(l2.data, l2.raw_data)
    assert np.allclose(l2.data, 10.0)


def test_active_science_dimensions(monkeypatch):
    """Verify active science array strictly conforms to 4088x4088 without border reference pixels."""
    mock_model = MockASDFImageModel(shape=(4088, 4088))
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy_wfi01.asdf")
    assert l2.data.shape == (4088, 4088)
    assert l2.data.shape[0] != 4096, "Border reference pixels must be excluded from science data"


def test_get_dq_mask_default_flags():
    """Verify get_dq_mask flags DO_NOT_USE (1), SATURATED (2), and DROPOUT (8) by default."""
    dq = np.zeros((5, 5), dtype=np.uint32)
    dq[0, 0] = 0   # GOOD
    dq[1, 1] = 1   # DO_NOT_USE
    dq[2, 2] = 2   # SATURATED
    dq[3, 3] = 4   # JUMP_DET
    dq[4, 4] = 8   # DROPOUT

    mask = get_dq_mask(dq)

    assert not mask[0, 0]
    assert mask[1, 1]
    assert mask[2, 2]
    assert not mask[3, 3], "JUMP_DET is not flagged by default"
    assert mask[4, 4]


def test_get_dq_mask_custom_flags():
    """Verify get_dq_mask respects custom flag list selection."""
    dq = np.zeros((3, 3), dtype=np.uint32)
    dq[0, 0] = 1  # DO_NOT_USE
    dq[0, 1] = 2  # SATURATED
    dq[0, 2] = 3  # Both

    # Test only SATURATED
    mask = get_dq_mask(dq, flags=["SATURATED"])
    assert not mask[0, 0]
    assert mask[0, 1]
    assert mask[0, 2]


def test_zero_point_ab_calculation(monkeypatch):
    """Verify zero-point magnitude calculation matches physical formula."""
    mock_model = MockASDFImageModel()
    mock_model.meta.photometry.conversion_megajanskys = 0.238965
    mock_model.meta.photometry.pixel_area = 2.801e-13
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy.asdf")

    expected_flux = 0.238965 * 1e6 * 2.801e-13
    expected_zp = -2.5 * np.log10(expected_flux / 3631.0)

    assert l2.zp_ab == pytest.approx(expected_zp, rel=1e-4)
    assert 26.0 < l2.zp_ab < 27.5


def test_loader_file_not_found():
    """Verify attempting to load a non-existent ASDF path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        load_l2_image("definitely_nonexistent_detector.asdf")


def test_metadata_dictionary_contents(monkeypatch):
    """Verify meta dictionary contains pointing, aperture PA, roll ref, and pixel scale."""
    mock_model = MockASDFImageModel()
    monkeypatch.setattr("roman_datamodels.open", lambda path: mock_model)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    l2 = load_l2_image("dummy.asdf")

    assert "pa_aperture" in l2.meta
    assert "roll_ref" in l2.meta
    assert "v3yangle" in l2.meta
    assert "pixel_scale" in l2.meta
    assert l2.meta["pa_aperture"] == pytest.approx(-110.0224, abs=1e-3)
    assert l2.meta["pixel_scale"] == pytest.approx(0.1098, abs=0.01)


@pytest.mark.skipif(
    not Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf").is_file(),
    reason="Commissioning data storage not mounted",
)
def test_real_asdf_smoke():
    """Smoke test against actual commissioning dataset file if mounted on disk."""
    real_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf"
    l2 = load_l2_image(real_path, calibrate=True)

    assert l2.data.shape == (4088, 4088)
    assert l2.detector.lower() == "wfi01"
    assert l2.filter_name == "F146"
    assert np.all(np.isfinite(l2.data[~get_effective_mask(l2.data, l2.dq)]))
