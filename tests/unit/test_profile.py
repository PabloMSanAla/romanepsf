"""
Comprehensive Unit Tests for romanepsf.profile module.

Covers:
- Elliptical coordinate meshgrid generation (PyTorch accelerated)
- Iterative sigma clipping on single bins (_clip_single_bin)
- High-performance elliptical radial profile extraction (elliptical_profile)
- Analytical Moffat PSF extension calculator (get_psf_extension_moffat)
- Scientific constraint verification: Strictly 1D profile without 2D circularization
"""

import numpy as np
import pytest
import torch

import romanepsf.profile as profile


class TestMeshgridTorch:
    """Unit tests for create_ellipse_meshgrid_torch."""

    def test_circular_meshgrid_distances(self):
        """Verify circular ellipse (eps=0.0) yields Euclidean radial distances."""
        cx, cy = 25.0, 25.0
        sma = profile.create_ellipse_meshgrid_torch(eps=0.0, pa=0.0, center=(cx, cy), grid_shape=(51, 51), device="cpu")
        assert sma.shape == (51, 51)
        assert np.isclose(sma[25, 25].item(), 0.0, atol=1e-5)
        # Point at (x=35, y=25) -> dist = 10
        assert np.isclose(sma[25, 35].item(), 10.0, atol=1e-5)
        # Point at (x=25, y=35) -> dist = 10
        assert np.isclose(sma[35, 25].item(), 10.0, atol=1e-5)

    def test_elliptical_meshgrid_stretching(self):
        """Verify semi-major axis formula under ellipticity eps=0.5 along x-axis."""
        # eps=0.5 -> b/a = 1 - 0.5 = 0.5. At y=10, x=0: sma = sqrt(0 + 10^2 / 0.5^2) = 20.0
        cx, cy = 25.0, 25.0
        sma = profile.create_ellipse_meshgrid_torch(eps=0.5, pa=0.0, center=(cx, cy), grid_shape=(51, 51), device="cpu")
        assert np.isclose(sma[25, 35].item(), 10.0, atol=1e-5)  # along major axis
        assert np.isclose(sma[35, 25].item(), 20.0, atol=1e-5)  # along minor axis

    def test_position_angle_rotation(self):
        """Verify position angle rotation (pa=90 deg swaps x and y axes)."""
        cx, cy = 25.0, 25.0
        sma = profile.create_ellipse_meshgrid_torch(eps=0.5, pa=90.0, center=(cx, cy), grid_shape=(51, 51), device="cpu")
        assert np.isclose(sma[35, 25].item(), 10.0, atol=1e-5)  # major axis now along y
        assert np.isclose(sma[25, 35].item(), 20.0, atol=1e-5)  # minor axis now along x

    def test_clamped_high_ellipticity(self):
        """Verify extreme ellipticity eps >= 1.0 is clamped and does not raise ZeroDivisionError."""
        cx, cy = 25.0, 25.0
        sma = profile.create_ellipse_meshgrid_torch(eps=1.0, pa=0.0, center=(cx, cy), grid_shape=(51, 51), device="cpu")
        assert torch.isfinite(sma[25, 35])


class TestClipSingleBin:
    """Unit tests for _clip_single_bin."""

    def test_clean_uniform_values(self):
        """Verify identical values converge immediately with std=0."""
        vals = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        med, std = profile._clip_single_bin(vals)
        assert np.isclose(med, 5.0)
        assert np.isclose(std, 0.0)

    def test_single_outlier_rejection(self):
        """Verify single +1000 sigma outlier is rejected."""
        vals = np.array([10.0, 10.2, 9.8, 10.1, 9.9, 10000.0])
        med, std = profile._clip_single_bin(vals, sigma=3.0)
        assert np.isclose(med, 10.0, atol=0.2)
        assert std < 1.0

    def test_empty_or_all_nan_slice(self):
        """Verify empty and all-NaN inputs return (nan, nan)."""
        med, std = profile._clip_single_bin([])
        assert np.isnan(med) and np.isnan(std)

        med, std = profile._clip_single_bin([np.nan, np.inf, -np.inf])
        assert np.isnan(med) and np.isnan(std)


class TestEllipticalProfile:
    """Unit tests for elliptical_profile."""

    def test_profile_on_constant_disk(self):
        """Verify flat disk image produces constant radial profile."""
        img = np.full((101, 101), 42.0, dtype=np.float32)
        rad_bins = np.arange(0.5, 30.5, 1.0)
        flux, flux_err = profile.elliptical_profile(img, rad=rad_bins, center=(50, 50))
        assert len(flux) == 29
        np.testing.assert_allclose(flux, 42.0, atol=1e-5)
        np.testing.assert_allclose(flux_err, 0.0, atol=1e-5)

    def test_profile_masked_array_support(self):
        """Verify masked pixels are excluded from binning without corrupting statistics."""
        img = np.full((101, 101), 10.0, dtype=np.float32)
        mask = np.zeros((101, 101), dtype=bool)
        # Poison center with huge value but mask it
        img[50, 50] = 99999.0
        mask[50, 50] = True
        ma = np.ma.masked_array(img, mask=mask)
        rad_bins = np.arange(0.5, 10.5, 1.0)
        flux, _ = profile.elliptical_profile(ma, rad=rad_bins, center=(50, 50))
        assert np.isclose(flux[0], 10.0, atol=1e-4)

    def test_profile_return_timings(self):
        """Verify return_timings returns timing dictionary."""
        img = np.ones((81, 81), dtype=np.float32)
        rad_bins = np.arange(0.5, 20.5, 1.0)
        res = profile.elliptical_profile(img, rad=rad_bins, center=(40, 40), return_timings=True)
        assert len(res) == 3
        flux, flux_err, timings = res
        assert "meshgrid_time" in timings
        assert "bin_sort_time" in timings
        assert "sigma_clip_time" in timings
        assert "total_profile_time" in timings

    def test_invalid_dimension_raises_error(self):
        """Verify 1D or 3D input raises ValueError."""
        with pytest.raises(ValueError, match="Image data must be a 2D array"):
            profile.elliptical_profile(np.ones((10, 10, 10)), rad=[1, 2], center=(5, 5))

    def test_short_rad_bins_raises_error(self):
        """Verify rad with fewer than 2 elements raises ValueError."""
        with pytest.raises(ValueError, match="at least 2 bin edges"):
            profile.elliptical_profile(np.ones((10, 10)), rad=[1], center=(5, 5))


class TestMoffatExtension:
    """Unit tests for get_psf_extension_moffat."""

    def test_scalar_magnitude_returns_float(self):
        """Verify scalar magnitude input returns float."""
        ext = profile.get_psf_extension_moffat(10.0, depth=30.0)
        assert isinstance(ext, float)
        assert ext > 0.0

    def test_array_magnitude_returns_ndarray(self):
        """Verify array of magnitudes returns ndarray of matching length."""
        mags = [8.0, 10.0, 12.0]
        exts = profile.get_psf_extension_moffat(mags, depth=30.0)
        assert isinstance(exts, np.ndarray)
        assert len(exts) == 3
        # Brighter star has larger extension
        assert exts[0] > exts[1] > exts[2]

    def test_fainter_than_depth_returns_zero(self):
        """Verify stars fainter than detection depth return 0.0 without crash."""
        ext = profile.get_psf_extension_moffat(35.0, depth=30.0)
        assert ext == 0.0

    def test_beta_under_one_raises_error(self):
        """Verify beta <= 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="beta parameter must be > 1.0"):
            profile.get_psf_extension_moffat(10.0, beta=1.0)


class TestScientificConstraintProfile:
    """Strict scientific constraint verification: 1D profiles must never circularize 2D data."""

    def test_radial_profile_is_purely_1d(self):
        """Verify measure_radial_profile_1d strictly outputs 1D arrays and preserves input image."""
        img = np.random.RandomState(42).randn(81, 81).astype(np.float32)
        img_copy = img.copy()
        flux, _ = profile.elliptical_profile(img, rad=np.arange(0.5, 20.5, 1.0), center=(40, 40))
        assert flux.ndim == 1
        # Original 2D image must not be mutated
        np.testing.assert_array_equal(img, img_copy)
