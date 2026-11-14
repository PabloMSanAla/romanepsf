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


class TestGeometricRadialBins:
    """Unit tests for get_geometric_radial_bins and logarithmic spacing."""

    def test_default_growth_rate_1_03(self):
        """Verify consecutive bins grow by ~1.03x."""
        bins = profile.get_geometric_radial_bins(r_min=0.5, r_max=500.0, growth_rate=1.03)
        assert isinstance(bins, np.ndarray)
        assert len(bins) > 10
        assert np.isclose(bins[0], 0.5)
        assert np.isclose(bins[-1], 500.0)
        assert np.all(np.diff(bins) > 0), "Bins must be strictly monotonically increasing"
        ratios = bins[1:] / bins[:-1]
        assert np.allclose(ratios, 1.03, atol=2e-3), f"Ratios mean={np.mean(ratios):.4f} should be ~1.03"

    def test_torch_tensor_output(self):
        """Verify PyTorch tensor generation on target device."""
        bins_t = profile.get_geometric_radial_bins(r_min=0.1, r_max=100.0, growth_rate=1.05, as_tensor=True, device="cpu")
        assert isinstance(bins_t, torch.Tensor)
        assert bins_t.device.type == "cpu"
        assert np.isclose(bins_t[0].item(), 0.1)
        assert np.isclose(bins_t[-1].item(), 100.0)
        ratios = (bins_t[1:] / bins_t[:-1]).numpy()
        assert np.allclose(ratios, 1.05, atol=2e-3)

    def test_invalid_parameters_raise_error(self):
        """Verify invalid bounds and growth rates raise ValueError."""
        with pytest.raises(ValueError, match="r_min must be strictly positive"):
            profile.get_geometric_radial_bins(r_min=0.0, r_max=100.0)
        with pytest.raises(ValueError, match="r_max .* must be greater than r_min"):
            profile.get_geometric_radial_bins(r_min=10.0, r_max=5.0)
        with pytest.raises(ValueError, match="growth_rate must be strictly greater than 1.0"):
            profile.get_geometric_radial_bins(r_min=0.5, r_max=500.0, growth_rate=1.0)


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


class TestMeasureAngularProfileTorch:
    """Unit tests for measure_angular_profile_torch."""

    def test_synthetic_spikes_detection(self):
        """Verify that synthetic spike rays along cardinal angles produce clear peaks."""
        sz = 101
        center = (50.0, 50.0)
        img = np.zeros((sz, sz), dtype=np.float32)

        # Draw bright rays along horizontal (+x, theta=0) and vertical (+y, theta=90)
        img[50, 55:95] = 10.0  # theta ~ 0 deg
        img[55:95, 50] = 10.0  # theta ~ 90 deg

        angles, medians = profile.measure_angular_profile_torch(
            image=img,
            center=center,
            num_bins=360,
            r_min=2.0,
            device="cpu",
        )

        assert len(angles) == 360
        assert len(medians) == 360
        # Angles near 0 deg and 90 deg should have elevated flux
        idx_0 = int(round(np.interp(0.0, angles, np.arange(360))))
        idx_90 = int(round(np.interp(90.0, angles, np.arange(360))))
        idx_45 = int(round(np.interp(45.0, angles, np.arange(360))))

        assert medians[idx_0] > medians[idx_45]
        assert medians[idx_90] > medians[idx_45]

    def test_companion_and_dq_mask_exclusion(self):
        """Verify that companion stars and DQ flags are properly excluded from angular bins."""
        sz = 101
        center = (50.0, 50.0)
        img = np.zeros((sz, sz), dtype=np.float32)

        gy, gx = np.ogrid[:sz, :sz]
        dy = gy - center[1]
        dx = gx - center[0]
        theta = np.remainder(np.rad2deg(np.arctan2(dy, dx)), 360.0)
        r = np.hypot(dx, dy)

        # Inject feature along theta in [45, 46) deg (bin 45)
        ray_45 = (theta >= 45.0) & (theta < 46.0) & (r >= 3.0) & (r <= 35.0)
        img[ray_45] = 50.0

        # Without mask, theta=45 has strong positive signal
        _, med_unmasked = profile.measure_angular_profile_torch(
            img, center, num_bins=360, r_min=3.0, r_max=35.0, device="cpu"
        )
        idx_45 = 45
        assert med_unmasked[idx_45] > 10.0

        # With companion mask covering the ray
        comp_mask = ray_45.copy()
        _, med_comp = profile.measure_angular_profile_torch(
            img, center, comp_mask=comp_mask, num_bins=360, r_min=3.0, r_max=35.0, device="cpu"
        )
        assert np.isnan(med_comp[idx_45]) or np.isclose(med_comp[idx_45], 0.0, atol=1e-3)

        # With DQ mask covering the ray
        dq = ray_45.astype(np.uint32)
        _, med_dq = profile.measure_angular_profile_torch(
            img, center, dq_mask=dq, num_bins=360, r_min=3.0, r_max=35.0, device="cpu"
        )
        assert np.isnan(med_dq[idx_45]) or np.isclose(med_dq[idx_45], 0.0, atol=1e-3)

    def test_all_masked_or_nan_returns_nans(self):
        """Verify all-NaN image returns all NaNs without crashing."""
        img = np.full((51, 51), np.nan, dtype=np.float32)
        angles, medians = profile.measure_angular_profile_torch(img, (25.0, 25.0), num_bins=360, device="cpu")
        assert len(angles) == 360
        assert np.all(np.isnan(medians))

