"""
Unit Tests for Postage Stamp Extraction, Adaptive Sizing, Realignment, and Background Subtraction.

Tests for tests/unit/test_stamps.py.
Covers:
- Adaptive stamp sizing by tier and magnitude (Feature 9)
- Cutout extraction and boundary edge padding
- Subpixel bicubic spline realignment to grid center (Feature 10)
- Background estimation (annular and percentile) and subtraction
- Faint core DQ bit 1 protection (Feature 11)
- Column fallback (mag_lambda vs phot_g_mean_mag) and RomanL2Data integration
"""

from typing import Dict, List
import numpy as np
import pandas as pd
import pytest

import romanepsf.stamps as stamps


@pytest.fixture
def stamps_module():
    """Retrieve stamps module."""
    return stamps


@pytest.fixture
def synthetic_l2_data():
    """Mock RomanL2Data for standalone testing."""
    from romanepsf.loader import RomanL2Data

    shape = (500, 500)
    data = np.full(shape, 1.8, dtype=np.float32)
    raw_data = data.copy() / 0.238965
    err = np.full(shape, 0.05, dtype=np.float32)
    dq = np.zeros(shape, dtype=np.uint32)

    class MockWCS:
        def __init__(self, crval_ra=303.12, crval_dec=-19.93, cdelt=0.11 / 3600.0):
            self.crval_ra = crval_ra
            self.crval_dec = crval_dec
            self.cdelt = cdelt

        def __call__(self, x, y):
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            return self.crval_ra + (x - 250.0) * self.cdelt, self.crval_dec + (y - 250.0) * self.cdelt

    meta = {
        "detector": "WFI01",
        "filter": "F146",
        "roll_ref": -110.02,
        "pa_aperture": -110.02,
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
        pixel_scale=0.11,
        conversion_factor=0.238965,
        pixel_area=2.8e-13,
        zp_ab=26.0,
        meta=meta,
    )


# ==============================================================================
# 1. Adaptive Stamp Sizing (Feature 9)
# ==============================================================================
class TestAdaptiveStampSize:
    """Tests for get_adaptive_stamp_size across stellar tiers and magnitudes."""

    def test_faint_stamp_size_default(self, stamps_module):
        """Faint stars (m >= 13.0) must receive default size 81x81."""
        sz = stamps_module.get_adaptive_stamp_size(14.0, "faint")
        assert sz == 81
        assert sz % 2 == 1

    def test_medium_stamp_size_default(self, stamps_module):
        """Medium stars (11.0 <= m < 13.0) must receive default size 201x201."""
        sz = stamps_module.get_adaptive_stamp_size(12.0, "medium")
        assert sz == 201
        assert sz % 2 == 1

    def test_bright_stamp_scaling(self, stamps_module):
        """Bright stars (m < 11.0) must scale with magnitude; brighter stars receive larger sizes."""
        sz_bright1 = stamps_module.get_adaptive_stamp_size(7.37, "bright", max_size=1001)
        sz_bright2 = stamps_module.get_adaptive_stamp_size(9.0, "bright", max_size=1001)
        sz_bright3 = stamps_module.get_adaptive_stamp_size(10.8, "bright", max_size=1001)

        assert sz_bright1 >= sz_bright2 >= sz_bright3
        assert sz_bright1 >= 501
        assert sz_bright3 >= 301

    def test_bright_stamp_max_size_clamp(self, stamps_module):
        """Bright cutout dimensions must strictly respect max_size ceiling."""
        sz_clamped = stamps_module.get_adaptive_stamp_size(7.0, "bright", max_size=501)
        assert sz_clamped <= 501
        assert sz_clamped % 2 == 1

    def test_stamp_sizes_always_odd(self, stamps_module):
        """All returned dimensions must be odd integers so integer center is exact."""
        test_mags = [6.5, 7.37, 8.5, 10.2, 11.0, 12.5, 13.0, 14.8, 16.0]
        for mag in test_mags:
            for tier in ["bright", "medium", "faint"]:
                sz = stamps_module.get_adaptive_stamp_size(mag, tier)
                assert sz % 2 == 1, f"Stamp size {sz} for mag {mag} tier {tier} is not odd"

    def test_custom_tier_sizes(self, stamps_module):
        """Verify configurable faint_size and medium_size arguments."""
        sz_f = stamps_module.get_adaptive_stamp_size(14.0, "faint", faint_size=61)
        sz_m = stamps_module.get_adaptive_stamp_size(12.0, "medium", medium_size=151)
        assert sz_f == 61
        assert sz_m == 151

    def test_tier_case_insensitivity(self, stamps_module):
        """Tier strings must be handled case-insensitively with whitespace stripping."""
        assert stamps_module.get_adaptive_stamp_size(14.0, "  FAINT  ") == 81
        assert stamps_module.get_adaptive_stamp_size(12.0, "Medium") == 201
        assert stamps_module.get_adaptive_stamp_size(8.0, "Bright") >= 301


# ==============================================================================
# 2. Cutout Extraction & Boundary Padding
# ==============================================================================
class TestExtractCutout:
    """Tests for extract_cutout geometry and edge boundary handling."""

    def test_cutout_shape_and_center(self, stamps_module):
        """Cutout shape must be strictly (size, size) and center integer rounded."""
        img = np.arange(10000, dtype=np.float32).reshape(100, 100)
        cut, (ix, iy) = stamps_module.extract_cutout(img, (50.3, 40.8), 21)
        assert cut.shape == (21, 21)
        assert (ix, iy) == (50, 41)

    def test_cutout_centered_content(self, stamps_module):
        """The center pixel of the cutout must match the source array value at (ix, iy)."""
        img = np.zeros((100, 100), dtype=np.float32)
        img[45, 55] = 999.0
        cut, _ = stamps_module.extract_cutout(img, (55.0, 45.0), 21)
        half = 10
        assert cut[half, half] == 999.0

    def test_cutout_edge_boundary_padding(self, stamps_module):
        """Near image boundary, out-of-bounds pixels must be padded with fill_value."""
        img = np.ones((100, 100), dtype=np.float32) * 42.0
        # Center near left edge: x=5, half=10 -> columns 0..4 in cutout are out of bounds
        cut, (ix, iy) = stamps_module.extract_cutout(img, (5.0, 50.0), 21, fill_value=np.nan)
        assert cut.shape == (21, 21)
        assert np.isnan(cut[:, 0]).all()
        assert np.isnan(cut[:, 4]).all()
        assert (cut[:, 6] == 42.0).all()

    def test_cutout_corner_boundary_padding(self, stamps_module):
        """At corner (0, 0), top-left quadrant is padded and bottom-right quadrant has valid pixels."""
        img = np.ones((100, 100), dtype=np.float32) * 10.0
        cut, (ix, iy) = stamps_module.extract_cutout(img, (0.0, 0.0), 21, fill_value=-999.0)
        assert cut.shape == (21, 21)
        assert (ix, iy) == (0, 0)
        half = 10
        # Bottom-right quadrant should be in-bounds
        assert cut[half:, half:].shape == (11, 11)
        assert np.all(cut[half:, half:] == 10.0)
        # Out of bounds padded with fill_value
        assert cut[0, 0] == -999.0

    def test_cutout_custom_fill_value_dq(self, stamps_module):
        """DQ mask cutout fills boundary with DO_NOT_USE bit 1."""
        dq = np.zeros((50, 50), dtype=np.uint8)
        cut, _ = stamps_module.extract_cutout(dq, (2.0, 25.0), 15, fill_value=1)
        assert cut.shape == (15, 15)
        assert cut[7, 0] == 1  # Out of bounds is masked bad
        assert cut[7, 7] == 0  # In bounds is clean


# ==============================================================================
# 3. Background Estimation & Subtraction
# ==============================================================================
class TestBackgroundEstimation:
    """Tests for annular and percentile background estimation and subtraction."""

    def test_annular_background_recovery(self, stamps_module):
        """Annular background estimator must accurately recover added constant background."""
        sz = 81
        half = 40
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - half, gy - half)
        # Centered star on top of true background B = 2.5
        true_bkg = 2.5
        star = (100.0 * np.exp(-r**2 / (2 * 3.0**2)) + true_bkg).astype(np.float32)
        # Add small Gaussian noise
        noise = np.random.RandomState(42).normal(0.0, 0.05, (sz, sz)).astype(np.float32)
        stamp = star + noise

        bkg_val, bkg_rms = stamps_module.estimate_stamp_background(stamp, method="annulus")
        assert np.isclose(bkg_val, true_bkg, atol=0.05)
        assert bkg_rms < 0.10

    def test_annular_background_with_spike_mask(self, stamps_module):
        """Masked pixels in annulus (e.g. companion star or diffraction spike) must not bias background."""
        sz = 81
        true_bkg = 1.8
        stamp = np.full((sz, sz), true_bkg, dtype=np.float32)
        mask = np.zeros((sz, sz), dtype=bool)

        # Inject bright contaminating star in outer annulus
        stamp[70:75, 70:75] = 500.0
        mask[70:75, 70:75] = True

        bkg_val, _ = stamps_module.estimate_stamp_background(stamp, mask=mask, method="annulus")
        assert np.isclose(bkg_val, true_bkg, atol=0.02)

    def test_percentile_background_recovery(self, stamps_module):
        """Percentile method must estimate robust lower background floor."""
        sz = 81
        true_bkg = 3.0
        stamp = np.full((sz, sz), true_bkg, dtype=np.float32)
        # Add random positive Poisson fluctuations
        stamp += np.random.RandomState(123).exponential(0.5, (sz, sz)).astype(np.float32)

        bkg_val, _ = stamps_module.estimate_stamp_background(stamp, method="percentile", percentile_val=10.0)
        assert bkg_val >= true_bkg
        assert bkg_val < true_bkg + 0.20

    def test_background_subtraction_zero_mean(self, stamps_module):
        """Subtracting estimated background must reduce outer perimeter median to ~0.0."""
        sz = 81
        true_bkg = 5.0
        stamp = np.full((sz, sz), true_bkg, dtype=np.float32)
        bkg_val, _ = stamps_module.estimate_stamp_background(stamp)
        sub_stamp = stamps_module.subtract_stamp_background(stamp, bkg_val)
        assert np.isclose(np.median(sub_stamp), 0.0, atol=1e-5)

    def test_background_estimation_all_nan_safe_fallback(self, stamps_module):
        """When all pixels are NaN, returns (0.0, 0.0) without crashing."""
        stamp = np.full((81, 81), np.nan, dtype=np.float32)
        bkg_val, bkg_rms = stamps_module.estimate_stamp_background(stamp)
        assert bkg_val == 0.0
        assert bkg_rms == 0.0


# ==============================================================================
# 4. Subpixel Bicubic Realignment (Feature 10)
# ==============================================================================
class TestSubpixelRealignment:
    """Tests for recenter_and_align_stamp."""

    def test_recenter_gaussian_peak(self, stamps_module):
        """Fractional shift centers continuous centroid to exact integer center ((S-1)/2, (S-1)/2)."""
        sz = 81
        half = (sz - 1) // 2
        # Place Gaussian peak offset by (dx=0.3, dy=-0.4)
        gy, gx = np.ogrid[:sz, :sz]
        peak_x = half + 0.3
        peak_y = half - 0.4
        stamp = np.exp(-((gx - peak_x)**2 + (gy - peak_y)**2) / (2 * 2.0**2)).astype(np.float32)
        mask = np.zeros((sz, sz), dtype=bool)

        aligned, _ = stamps_module.recenter_and_align_stamp(stamp, mask, (0.3, -0.4))
        max_idx = np.unravel_index(np.argmax(aligned), aligned.shape)
        assert max_idx == (half, half)

    def test_flux_conservation_subpixel_shift(self, stamps_module):
        """Spline shift must conserve total stellar flux within 1%."""
        sz = 81
        half = 40
        gy, gx = np.ogrid[:sz, :sz]
        stamp = (100.0 * np.exp(-((gx - half)**2 + (gy - half)**2) / (2 * 3.0**2))).astype(np.float32)
        mask = np.zeros((sz, sz), dtype=bool)

        aligned, _ = stamps_module.recenter_and_align_stamp(stamp, mask, (0.25, 0.35))
        flux_orig = float(np.sum(stamp))
        flux_aligned = float(np.sum(aligned))
        assert abs(flux_aligned - flux_orig) / flux_orig < 0.01

    def test_zero_offset_identity(self, stamps_module):
        """Zero subpixel offset (0.0, 0.0) must return exact data array."""
        stamp = np.random.RandomState(42).randn(81, 81).astype(np.float32)
        mask = np.zeros((81, 81), dtype=bool)
        aligned, _ = stamps_module.recenter_and_align_stamp(stamp, mask, (0.0, 0.0))
        np.testing.assert_allclose(aligned, stamp, atol=1e-5)

    def test_mask_aligned_identically(self, stamps_module):
        """Boolean mask must be shifted synchronously with science data."""
        sz = 81
        stamp = np.ones((sz, sz), dtype=np.float32)
        mask = np.zeros((sz, sz), dtype=bool)
        mask[40, 40] = True

        _, aligned_mask = stamps_module.recenter_and_align_stamp(stamp, mask, (1.0, 0.0))
        # Masked pixel should move to column 39
        assert aligned_mask[40, 39]

    def test_nan_guard_prevents_ringing(self, stamps_module):
        """Isolated NaN filled prior to spline shift to prevent NaN contagion."""
        stamp = np.full((81, 81), 5.0, dtype=np.float32)
        stamp[10, 10] = np.nan
        mask = np.isnan(stamp)

        aligned_data, aligned_mask = stamps_module.recenter_and_align_stamp(stamp, mask, (0.5, 0.5))
        assert np.isfinite(aligned_data[40, 40])
        assert not aligned_mask[40, 40]


# ==============================================================================
# 5. Faint Core DQ Bit 1 Protection (Feature 11)
# ==============================================================================
class TestFaintCoreDQProtection:
    """Tests verifying faint star unsaturated cores are protected from DQ bit 1."""

    def test_faint_star_finite_positive_core_protected(self, stamps_module, synthetic_l2_data):
        """Faint star with finite positive flux and DQ=2 (SATURATED) is preserved without masking."""
        df = pd.DataFrame({
            "source_id": [1],
            "mag_lambda": [14.5],
            "x": [250.0],
            "y": [250.0],
            "tier": ["faint"],
        })
        # Set core pixel to have DQ=2 (SATURATED)
        synthetic_l2_data.dq[250, 250] = 2
        synthetic_l2_data.data[250, 250] = 100.0  # Positive finite core peak

        stamps_dict = stamps_module.process_star_stamps(
            synthetic_l2_data, df, faint_core_protect_finite=True
        )
        faint_stamps = stamps_dict["faint"]
        assert len(faint_stamps) == 1
        s = faint_stamps[0]
        half = (s.size - 1) // 2
        # Core pixel must NOT be masked
        assert not s.mask[half, half]
        assert s.data[half, half] > 0.0


# ==============================================================================
# 6. Integration and Catalog Robustness
# ==============================================================================
class TestProcessStarStampsIntegration:
    """Tests verifying process_star_stamps integration with RomanL2Data and catalogs."""

    def test_process_star_stamps_column_fallback(self, stamps_module, synthetic_l2_data):
        """Verify process_star_stamps works when phot_g_mean_mag is NaN and mag_lambda is present."""
        df = pd.DataFrame({
            "source_id": [1, 2, 3],
            "phot_g_mean_mag": [np.nan, np.nan, np.nan],
            "mag_lambda": [9.5, 12.0, 14.0],
            "x": [150.0, 250.0, 350.0],
            "y": [150.0, 250.0, 350.0],
            "tier": ["bright", "medium", "faint"],
        })
        stamps_dict = stamps_module.process_star_stamps(synthetic_l2_data, df)
        assert len(stamps_dict["bright"]) == 1
        assert len(stamps_dict["medium"]) == 1
        assert len(stamps_dict["faint"]) == 1

        assert stamps_dict["bright"][0].mag == 9.5
        assert stamps_dict["medium"][0].mag == 12.0
        assert stamps_dict["faint"][0].mag == 14.0

    def test_process_star_stamps_stellar_stamp_attributes(self, stamps_module, synthetic_l2_data):
        """Verify StellarStamp contains all required attributes."""
        df = pd.DataFrame({
            "source_id": [42],
            "mag_lambda": [14.0],
            "x": [200.0],
            "y": [200.0],
            "tier": ["faint"],
        })
        stamps_dict = stamps_module.process_star_stamps(synthetic_l2_data, df)
        s = stamps_dict["faint"][0]

        assert hasattr(s, "source_id") and s.source_id == 42
        assert hasattr(s, "tier") and s.tier == "faint"
        assert hasattr(s, "mag") and s.mag == 14.0
        assert hasattr(s, "data") and s.data.shape == (81, 81)
        assert hasattr(s, "mask") and s.mask.shape == (81, 81)
        assert hasattr(s, "center_original") and s.center_original == (200.0, 200.0)
        assert hasattr(s, "size") and s.size == 81
        assert hasattr(s, "norm_factor") and s.norm_factor == 1.0
        assert hasattr(s, "bkg_value")
        assert hasattr(s, "bkg_rms")

    def test_process_star_stamps_tier_limits(self, stamps_module, synthetic_l2_data):
        """Verify max_stars_per_tier limits number of extracted stamps."""
        # 10 faint stars
        df = pd.DataFrame({
            "source_id": list(range(10)),
            "mag_lambda": [14.0 + 0.1 * i for i in range(10)],
            "x": [100.0 + 10 * i for i in range(10)],
            "y": [100.0 + 10 * i for i in range(10)],
            "tier": ["faint"] * 10,
        })
        stamps_dict = stamps_module.process_star_stamps(
            synthetic_l2_data, df, max_stars_per_tier={"bright": 2, "medium": 2, "faint": 3}
        )
        assert len(stamps_dict["faint"]) == 3

    def test_process_star_stamps_empty_catalog(self, stamps_module, synthetic_l2_data):
        """Verify empty DataFrame returns empty dictionary cleanly without error."""
        empty_df = pd.DataFrame()
        stamps_dict = stamps_module.process_star_stamps(synthetic_l2_data, empty_df)
        assert stamps_dict == {"bright": [], "medium": [], "faint": []}
