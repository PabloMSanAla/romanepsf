"""
Unit tests for romanepsf.background module (NoiseChisel sky and noise estimation).
"""

import numpy as np
import pytest

from romanepsf.background import (
    estimate_detector_sky_noisechisel,
    resolve_noisechisel_device,
    _fallback_sky_estimation,
)
from romanepsf.loader import RomanL2Data


class TestNoisechiselBackground:
    """Test suite for NoiseChisel background and noise estimation."""

    def test_resolve_device(self):
        """Test device resolution logic."""
        assert resolve_noisechisel_device("cpu") == "cpu"
        assert resolve_noisechisel_device("mps") == "cpu"
        dev = resolve_noisechisel_device("auto")
        assert dev in ("cpu", "cuda")

    def test_fallback_sky_estimation(self):
        """Test fallback estimation on known constant + Gaussian noise."""
        np.random.seed(42)
        true_bkg = 12.5
        true_std = 1.2
        img = true_bkg + np.random.normal(0, true_std, size=(64, 64)).astype(np.float32)

        sky_map, std_map, sky_val, std_val = _fallback_sky_estimation(img)
        assert sky_map.shape == (64, 64)
        assert std_map.shape == (64, 64)
        assert np.isclose(sky_val, true_bkg, atol=0.2)
        assert np.isclose(std_val, true_std, atol=0.2)

    def test_estimate_detector_sky_fallback_for_small_images(self):
        """Test that small images gracefully route to fallback without crashing."""
        small_img = np.ones((50, 50), dtype=np.float32) * 5.0
        sky_map, std_map, sky_val, std_val = estimate_detector_sky_noisechisel(small_img)
        assert sky_map.shape == (50, 50)
        assert std_map.shape == (50, 50)
        assert np.isclose(sky_val, 5.0)

    def test_estimate_detector_sky_noisechisel_synthetic(self):
        """Test NoiseChisel on a synthetic detector image (e.g. 180x180)."""
        np.random.seed(123)
        ny, nx = 180, 180
        true_sky = 0.5
        true_std = 0.05
        # Background + noise
        img = true_sky + np.random.normal(0, true_std, size=(ny, nx)).astype(np.float32)

        # Add a couple of synthetic sources
        img[50:60, 50:60] += 5.0
        img[120:130, 120:130] += 8.0

        sky_map, std_map, sky_val, std_val = estimate_detector_sky_noisechisel(
            img, tilesize=(30, 30), interpnumngb=5, device="cpu"
        )
        assert sky_map.shape == (ny, nx)
        assert std_map.shape == (ny, nx)
        assert np.isclose(sky_val, true_sky, atol=0.03)
        assert np.isclose(std_val, true_std, atol=0.02)

    def test_estimate_detector_sky_with_dq_mask(self):
        """Test that bad pixels marked in dq_mask are ignored."""
        np.random.seed(999)
        img = np.random.normal(1.0, 0.1, size=(150, 150)).astype(np.float32)
        dq_mask = np.zeros_like(img, dtype=bool)

        # Inject extreme bad pixels
        img[10:20, 10:20] = 9999.0
        dq_mask[10:20, 10:20] = True

        sky_map, std_map, sky_val, std_val = estimate_detector_sky_noisechisel(
            img, dq_mask=dq_mask, tilesize=(30, 30), interpnumngb=5, device="cpu"
        )
        assert sky_val < 2.0  # bad pixels didn't corrupt the sky background
        assert std_val < 0.5

    def test_roman_l2_data_caching_behavior(self):
        """Test that RomanL2Data.measure_sky_noisechisel caches result and runs only once."""
        arr = np.full((150, 150), 3.0, dtype=np.float32)
        l2 = RomanL2Data(
            detector="WFI01",
            filter_name="F146",
            data=arr.copy(),
            raw_data=arr.copy(),
            err=np.ones_like(arr),
            dq=np.zeros_like(arr, dtype=np.uint32),
            wcs=None,
            pa_aperture=0.0,
            pixel_scale=0.11,
            conversion_factor=1.0,
            pixel_area=1.0,
            zp_ab=25.0,
            meta={},
        )
        assert l2.sky_bkg_val is None
        assert l2.sky_std_val is None

        # First run computes, subtracts sky, and returns scalar values
        bkg_v1, std_v1 = l2.measure_sky_noisechisel(device="cpu", tilesize=(30, 30), interpnumngb=5)
        assert l2.sky_bkg_val is not None
        assert l2.sky_std_val is not None
        assert l2.sky_bkg is None  # No big array stored
        assert l2.sky_std is None  # No big array stored
        assert np.isclose(bkg_v1, 3.0)
        assert np.allclose(l2.data, 0.0)  # sky was subtracted from data

        # Mutate the cached reference to verify second call returns cached instance without recomputing
        l2.sky_bkg_val = 999.0
        bkg_v2, std_v2 = l2.measure_sky_noisechisel(overwrite=False)
        assert bkg_v2 == 999.0

        # With overwrite=True, it recomputes
        l2.data = arr.copy()
        bkg_v3, std_v3 = l2.measure_sky_noisechisel(overwrite=True, device="cpu", tilesize=(30, 30), interpnumngb=5)
        assert np.isclose(bkg_v3, 3.0)

    def test_contaminant_detection_with_noisechisel_sky_std(self):
        """Test that mask_contaminants_with_spikes_protected properly respects sky_std."""
        from romanepsf.masking import mask_contaminants_with_spikes_protected

        np.random.seed(42)
        sz = 81
        # Background noise with known std
        noise_std = 0.5
        cutout = np.random.normal(0.0, noise_std, size=(sz, sz)).astype(np.float32)

        # Add faint companion at offset (25, 25) with peak flux = 4.0 (8-sigma above noise_std=0.5)
        # But if sky_std were assumed to be 10.0, it wouldn't be masked at 3-sigma.
        cutout[23:27, 23:27] += 4.0

        dq = np.zeros_like(cutout, dtype=bool)

        # Run with sky_std = 0.5, detection_sigma = 3.0 (threshold ~ 1.5, companion flux is 4.0 -> should be masked)
        final_mask, prot_area, residual = mask_contaminants_with_spikes_protected(
            cutout,
            dq_mask=dq,
            tier="medium",
            mag=16.0,
            sky_std=noise_std,
            detection_sigma=3.0,
            engine="photutils",
        )
        assert final_mask[25, 25] == True

        # Run with high sky_std = 10.0, detection_sigma = 3.0 (threshold ~ 30.0 -> companion not masked)
        final_mask2, prot_area2, residual2 = mask_contaminants_with_spikes_protected(
            cutout,
            dq_mask=dq,
            tier="medium",
            mag=16.0,
            sky_std=10.0,
            detection_sigma=3.0,
            engine="photutils",
        )
        assert final_mask2[25, 25] == False

    def test_noisechisel_retry_on_not_enough_valid_tiles(self):
        """Test that NoiseChisel retries with interpnumngb=5 when not enough valid tiles."""
        from unittest.mock import MagicMock, patch

        arr = np.full((150, 150), 2.5, dtype=np.float32)

        call_args_list = []

        def fake_nc_init(*args, **kwargs):
            mock_runner = MagicMock()
            ngb = kwargs.get("interpnumngb", 15)
            call_args_list.append(ngb)

            if ngb == 15:
                # First run with default 15 fails with user error
                mock_runner.side_effect = ValueError("not enough valid tiles for the neighbour search")
            else:
                # Retry with ngb=5 succeeds
                mock_res = MagicMock()
                mock_res.numpy.return_value = {
                    "sky": np.full((150, 150), 2.5, dtype=np.float32),
                    "std": np.full((150, 150), 0.1, dtype=np.float32),
                }
                mock_res.med_std = 0.1
                mock_runner.return_value = mock_res
            return mock_runner

        with patch("noisechisel_torch.NoiseChisel", side_effect=fake_nc_init):
            sky_map, std_map, sky_val, std_val = estimate_detector_sky_noisechisel(
                arr, interpnumngb=15, device="cpu"
            )

        assert call_args_list == [15, 5]
        assert np.isclose(sky_val, 2.5)
        assert np.isclose(std_val, 0.1)
