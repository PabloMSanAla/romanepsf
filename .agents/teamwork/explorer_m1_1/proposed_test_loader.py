"""
Unit tests for romanepsf.loader (Level 2 ASDF loader and calibration).
"""

from pathlib import Path
import numpy as np
import pytest

from proposed_loader import (
    load_l2_image,
    get_dq_mask,
    get_effective_mask,
    RomanL2Data,
    ACTIVE_SHAPE,
    DQ_FLAGS,
)

REAL_ASDF_PATH = Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf")


def test_load_l2_image_file_not_found():
    with pytest.raises(FileNotFoundError, match="not found"):
        load_l2_image("non_existent_file_path.asdf")


def test_load_l2_image_invalid_shape(monkeypatch, tmp_path):
    class MockMeta:
        wcs = None
        instrument = None
        photometry = None
        pointing = None
        wcsinfo = None
        exposure = None

    class MockDM:
        data = np.zeros((4096, 4096), dtype=np.float32)
        err = np.zeros((4096, 4096), dtype=np.float32)
        dq = np.zeros((4096, 4096), dtype=np.uint32)
        meta = MockMeta()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    import roman_datamodels as rdm
    dummy_file = tmp_path / "dummy.asdf"
    dummy_file.write_text("dummy")

    monkeypatch.setattr(rdm, "open", lambda path: MockDM())

    with pytest.raises(ValueError, match="Invalid Roman science array shape"):
        load_l2_image(dummy_file, validate_shape=True)


@pytest.mark.skipif(not REAL_ASDF_PATH.is_file(), reason="Real ASDF file not accessible")
def test_load_l2_image_calibrated_success():
    l2 = load_l2_image(REAL_ASDF_PATH, calibrate=True)
    assert isinstance(l2, RomanL2Data)
    assert l2.shape == (4088, 4088)
    assert l2.detector == "WFI01"
    assert l2.filter_name == "F146"
    assert l2.data.dtype == np.float32
    assert l2.raw_data.dtype == np.float32
    assert l2.dq.dtype == np.uint32
    assert l2.wcs is not None
    assert isinstance(l2.pa_aperture, float)
    assert np.isclose(l2.pa_aperture, -110.022, atol=0.01)
    assert l2.conversion_factor > 0.0
    assert l2.pixel_scale > 0.0
    assert l2.zp_ab > 0.0
    assert l2.is_calibrated is True

    # Check that data is scaled by conversion_factor relative to raw_data
    finite_pix = np.isfinite(l2.raw_data) & (l2.raw_data > 10.0)
    ratio = l2.data[finite_pix] / l2.raw_data[finite_pix]
    assert np.allclose(ratio, l2.conversion_factor, rtol=1e-5)


@pytest.mark.skipif(not REAL_ASDF_PATH.is_file(), reason="Real ASDF file not accessible")
def test_load_l2_image_uncalibrated():
    l2 = load_l2_image(REAL_ASDF_PATH, calibrate=False)
    assert l2.is_calibrated is False
    assert np.array_equal(l2.data, l2.raw_data, equal_nan=True)


def test_get_dq_mask_flags():
    dq = np.zeros((10, 10), dtype=np.uint32)
    dq[1, 1] = DQ_FLAGS["DO_NOT_USE"]
    dq[2, 2] = DQ_FLAGS["SATURATED"]
    dq[3, 3] = DQ_FLAGS["DROPOUT"]
    dq[4, 4] = DQ_FLAGS["HOT"]

    # Default flags mask DO_NOT_USE (1), SATURATED (2), DROPOUT (8)
    mask = get_dq_mask(dq)
    assert mask[1, 1] is np.True_ or mask[1, 1] == True
    assert mask[2, 2] is np.True_ or mask[2, 2] == True
    assert mask[3, 3] is np.True_ or mask[3, 3] == True
    assert mask[4, 4] == False
    assert mask[0, 0] == False

    # Custom flags
    mask_hot = get_dq_mask(dq, flags=["HOT"])
    assert mask_hot[4, 4] == True
    assert mask_hot[1, 1] == False


def test_get_dq_mask_custom_bitmask():
    dq = np.zeros((5, 5), dtype=np.uint32)
    dq[0, 0] = 16
    mask = get_dq_mask(dq, bitmask=16)
    assert mask[0, 0] == True
    assert mask[0, 1] == False


def test_get_effective_mask_with_nan():
    data = np.ones((5, 5), dtype=np.float32)
    data[1, 1] = np.nan
    data[2, 2] = np.inf
    dq = np.zeros((5, 5), dtype=np.uint32)
    dq[0, 0] = DQ_FLAGS["SATURATED"]

    eff_mask = get_effective_mask(data, dq)
    assert eff_mask[0, 0] == True  # from DQ
    assert eff_mask[1, 1] == True  # from NaN
    assert eff_mask[2, 2] == True  # from Inf
    assert eff_mask[3, 3] == False # good pixel
