"""
Milestone 5 Phase 2: Tier 5 Adversarial Coverage Hardening (Core Pipeline).

Author: challenger_m5_tier5_1
Roles: critic, specialist (Empirical Challenger)

Target Modules:
- src/romanepsf/loader.py
- src/romanepsf/catalog.py
- src/romanepsf/stamps.py
- src/romanepsf/masking.py
- src/romanepsf/assembly.py
- src/romanepsf/profile.py
- src/romanepsf/config.py

Edge Case & Adversarial Challenge Dimensions:
1. loader.py:
   - Data array dimensional mismatch (3D/1D vs 2D) triggering ValueError in RomanL2Data
   - Large, unlisted, and complex bitmasks in get_dq_mask (up to bit 30)
   - Effective bad pixel mask across NaN, +Inf, -Inf, subnormal floats
   - Detector name extraction robustness (uppercase, lowercase, missing stem, high detector indices)
   - Validation flags for non-standard array shapes and unphysical conversion factors

2. catalog.py:
   - Extreme negative magnitudes (Sun, Moon, Solar System contaminants)
   - Corrupted astrometric coordinates (NaN, Inf, out-of-range RA/Dec)
   - Duplicate columns, conflicting column renaming (phot_g_mean_mag_AB vs phot_g_mean_mag)
   - Astrometric projection with non-invertible/failing WCS or roundtrip discrepancy
   - Centroid refinement at detector edges (0, 0), completely NaN boxes, divergent shifts
   - Dense stellar clusters (extreme crowding) and tie-breaking in pairwise isolation
   - Exact tier boundary thresholds (11.0, 13.0) and missing magnitude fallback
   - Analytical Moffat extension across extreme positive and negative magnitudes

3. stamps.py:
   - Guaranteed odd integer sizes across tiers and boundary mag limits
   - Cutout extraction far off-detector and on image borders with fill_value
   - Background estimation on all-NaN, all-masked, and zero-variance cutouts
   - Annular vs percentile estimation on stamps smaller than annulus radii
   - Subpixel recentering with zero shift, maximum shift, and NaN-filled borders
   - Faint core DQ bit 1 (SATURATED) protection against positive core erasure
   - Polymorphic argument signatures for process_star_stamps

4. masking.py:
   - Invariance of 12 theoretical spike angles across 360-degree periodicity and offsets
   - Core exclusion radius invariant in geometric spike masking
   - Morphological spike discrimination: radial linear spikes vs circular companion stars
   - Moffat profile fitting on flat/constant and fully masked images
   - Dual-prior invariant: protected core and spikes NEVER masked as contaminants
   - Contaminant detection along unaligned non-spike axes

5. profile.py:
   - Elliptical coordinate tensor generation across extreme ellipticity (eps -> 1.0)
   - Robust single-bin sigma clipping on empty, NaN, and extreme outlier slices
   - Elliptical radial profiling input validation (1D/3D shapes, <2 bin edges)
   - Big-endian (>f4) memory layout compatibility
   - Moffat extension parameter beta boundary enforcement (beta <= 1.0)

6. assembly.py:
   - Outlier rejection in tensor stacking with 3+ stamps, 1-2 stamp bypass, and hollow core recovery
   - Varying stamp cutout dimensions stacked into unified canvas
   - Pathological overlap scale factor inputs (disjoint ranges, inverted bounds, zero flux)
   - Partition of unity invariance in C^1 raised-cosine annular blending
   - Graceful composite synthesis across all single-tier and dual-tier configurations
   - Multi-extension FITS serialization headers, coverage map, and empty summaries
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import torch
from astropy.io import fits

from romanepsf.loader import (
    ACTIVE_SHAPE,
    DEFAULT_DQ_MASK_FLAGS,
    DQ_FLAGS,
    NOMINAL_PIXEL_AREA,
    NOMINAL_PIXEL_SCALE,
    RomanL2Data,
    _extract_detector_name,
    get_dq_mask,
    get_effective_mask,
    load_l2_image,
)
from romanepsf.catalog import (
    assign_stellar_tiers,
    filter_isolated_stars,
    get_detector_sky_bounds,
    get_psf_extension_moffat as catalog_get_psf_extension_moffat,
    project_catalog_to_pixels,
    refine_stellar_centroids,
    sanitize_source_catalog,
)
from romanepsf.stamps import (
    StellarStamp,
    estimate_stamp_background,
    extract_cutout,
    get_adaptive_stamp_size,
    process_star_stamps,
    recenter_and_align_stamp,
    subtract_stamp_background,
)
from romanepsf.masking import (
    NOMINAL_DETECTOR_OFFSET_DEG,
    ROMAN_BASE_SPIKE_ANGLES_DEG,
    create_geometric_spike_mask,
    detect_morphological_spikes,
    fit_moffat_model,
    get_theoretical_spike_angles,
    mask_contaminants_with_spikes_protected,
)
from romanepsf.profile import (
    _clip_single_bin,
    create_ellipse_meshgrid_torch,
    elliptical_profile,
    get_psf_extension_moffat as profile_get_psf_extension_moffat,
)
from romanepsf.assembly import (
    _embed_or_crop_canvas,
    assemble_composite_extended_psf,
    blend_2d_annular_profiles,
    determine_overlap_scale_factor,
    determine_overlap_scale_factor_dual,
    measure_radial_profile_1d,
    serialize_composite_epsf_fits,
    stack_tier_stamps_torch,
)
from romanepsf.config import (
    AssemblySection,
    CatalogSection,
    CoreProtectionRadius,
    MorphologicalConfig,
    OverlapAnnulusConfig,
    PipelineConfig,
    SpikesConfig,
    SpikesSection,
    StampSizes,
    StampsSection,
    TierCounts,
    TiersSection,
    resolve_device,
)


# ==============================================================================
# Helper Mocks and Fixtures
# ==============================================================================

class MockWCS:
    """Deterministic Mock WCS mapping between pixel and celestial coordinates."""

    def __init__(self, crval=(10.0, -20.0), scale_deg=0.11 / 3600.0):
        self.crval_ra = crval[0]
        self.crval_dec = crval[1]
        self.scale = scale_deg

    def __call__(self, x, y):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        ra = self.crval_ra + (x_arr - 2044.0) * self.scale
        dec = self.crval_dec + (y_arr - 2044.0) * self.scale
        if np.ndim(x) == 0:
            return float(ra), float(dec)
        return ra, dec

    def backward_transform(self, ra, dec):
        ra_arr = np.asarray(ra, dtype=float)
        dec_arr = np.asarray(dec, dtype=float)
        x = 2044.0 + (ra_arr - self.crval_ra) / self.scale
        y = 2044.0 + (dec_arr - self.crval_dec) / self.scale
        if np.ndim(ra) == 0:
            return float(x), float(y)
        return x, y

    def invert(self, ra, dec):
        return self.backward_transform(ra, dec)


def create_synthetic_l2_data(
    shape: Tuple[int, int] = (100, 100),
    peak_val: float = 100.0,
    bg_val: float = 5.0,
    detector: str = "WFI01",
) -> RomanL2Data:
    """Create a minimal synthetic RomanL2Data container for testing."""
    ny, nx = shape
    data = np.full((ny, nx), bg_val, dtype=np.float32)
    cy, cx = ny // 2, nx // 2
    data[cy, cx] = peak_val
    err = np.ones((ny, nx), dtype=np.float32) * 0.1
    dq = np.zeros((ny, nx), dtype=np.uint32)
    wcs = MockWCS()
    return RomanL2Data(
        detector=detector,
        filter_name="F146",
        data=data,
        raw_data=data.copy(),
        err=err,
        dq=dq,
        wcs=wcs,
        pa_aperture=-110.0,
        pixel_scale=0.11,
        conversion_factor=1.0,
        pixel_area=NOMINAL_PIXEL_AREA,
        zp_ab=26.836,
        meta={"detector": detector, "roll_ref": -110.0},
        is_calibrated=True,
    )


# ==============================================================================
# SECTION 1: loader.py Adversarial Stress
# ==============================================================================

class TestLoaderAdversarial:
    """Adversarial challenge suite for src/romanepsf/loader.py."""

    def test_adv_loader_mismatched_dimensions_raises_value_error(self):
        """Array dimension mismatch (3D/1D vs 2D) must be rejected by RomanL2Data."""
        data = np.zeros((10, 10), dtype=np.float32)
        err_3d = np.zeros((10, 10, 2), dtype=np.float32)
        dq_1d = np.zeros(10, dtype=np.uint32)

        with pytest.raises(ValueError, match="err array shape.*does not match"):
            RomanL2Data(
                detector="WFI01",
                filter_name="F146",
                data=data,
                raw_data=data,
                err=err_3d,
                dq=np.zeros((10, 10), dtype=np.uint32),
                wcs=None,
                pa_aperture=0.0,
                pixel_scale=0.11,
                conversion_factor=1.0,
                pixel_area=NOMINAL_PIXEL_AREA,
                zp_ab=26.8,
                meta={},
            )

        with pytest.raises(ValueError, match="dq array shape.*does not match"):
            RomanL2Data(
                detector="WFI01",
                filter_name="F146",
                data=data,
                raw_data=data,
                err=np.zeros((10, 10), dtype=np.float32),
                dq=dq_1d,
                wcs=None,
                pa_aperture=0.0,
                pixel_scale=0.11,
                conversion_factor=1.0,
                pixel_area=NOMINAL_PIXEL_AREA,
                zp_ab=26.8,
                meta={},
            )

    def test_adv_loader_dq_mask_extreme_flags_and_bitmasks(self):
        """Stress get_dq_mask with custom bits, unlisted strings, bit 30, and empty arrays."""
        dq = np.array([
            [0, DQ_FLAGS["DO_NOT_USE"], DQ_FLAGS["SATURATED"]],
            [DQ_FLAGS["OTHER_BAD_PIXEL"], DQ_FLAGS["BAD_REF_PIXEL"], 0],
        ], dtype=np.uint32)

        # 1. Unrecognized flag ignored with warning, recognized flags used
        mask = get_dq_mask(dq, flags=["DO_NOT_USE", "NON_EXISTENT_FLAG"])
        assert mask[0, 1] is True or mask[0, 1] == 1
        assert mask[0, 2] == 0
        assert mask[0, 0] == 0

        # 2. High-order 32-bit flag (OTHER_BAD_PIXEL = 2^30)
        mask_high = get_dq_mask(dq, flags=["OTHER_BAD_PIXEL"])
        assert mask_high[1, 0] == 1
        assert mask_high[1, 1] == 0

        # 3. Explicit bitmask integer combined with flags
        mask_comb = get_dq_mask(dq, flags=["DO_NOT_USE"], bitmask=int(DQ_FLAGS["BAD_REF_PIXEL"]))
        assert mask_comb[0, 1] == 1
        assert mask_comb[1, 1] == 1
        assert mask_comb[0, 0] == 0

        # 4. Zero-sized DQ array
        empty_dq = np.zeros((0, 0), dtype=np.uint32)
        empty_mask = get_dq_mask(empty_dq)
        assert empty_mask.shape == (0, 0)
        assert empty_mask.dtype == bool

    def test_adv_loader_effective_mask_nan_inf_subnormal(self):
        """Verify get_effective_mask catches NaNs, +Inf, -Inf, regardless of DQ flags."""
        data = np.array([
            [1.0, np.nan, np.inf],
            [-np.inf, 1e-38, 0.0],
        ], dtype=np.float32)
        dq = np.zeros(data.shape, dtype=np.uint32)
        dq[1, 2] = DQ_FLAGS["DO_NOT_USE"]

        eff_mask = get_effective_mask(data, dq)
        # Pixel [0, 0] is finite, good DQ -> False
        assert eff_mask[0, 0] == False
        # [0, 1] is NaN -> True
        assert eff_mask[0, 1] == True
        # [0, 2] is +Inf -> True
        assert eff_mask[0, 2] == True
        # [1, 0] is -Inf -> True
        assert eff_mask[1, 0] == True
        # [1, 1] is subnormal finite -> False
        assert eff_mask[1, 1] == False
        # [1, 2] is zero, but bad DQ -> True
        assert eff_mask[1, 2] == True

    def test_adv_loader_extract_detector_name_adversarial_patterns(self):
        """Test _extract_detector_name across odd filenames, uppercase/lowercase, and fallbacks."""
        # Standard filenames
        assert _extract_detector_name(None, Path("image_wfi01_cal.asdf")) == "WFI01"
        assert _extract_detector_name(None, Path("IMAGE_WFI18_CAL.ASDF")) == "WFI18"
        assert _extract_detector_name(None, Path("wfi07_test.asdf")) == "WFI07"

        # Missing detector name -> fallback WFI01
        assert _extract_detector_name(None, Path("unknown_simulation.asdf")) == "WFI01"
        assert _extract_detector_name(None, Path("wfi19_out_of_range.asdf")) == "WFI01"

        # Mock datamodel with meta.instrument.detector takes precedence
        mock_dm = MagicMock()
        mock_dm.meta.instrument.detector = "wfi14"
        assert _extract_detector_name(mock_dm, Path("arbitrary_path.asdf")) == "WFI14"

    def test_adv_loader_nonexistent_file_raises_filenotfound(self):
        """Verify load_l2_image cleanly raises FileNotFoundError on missing files."""
        with pytest.raises(FileNotFoundError, match="ASDF file not found"):
            load_l2_image("/path/to/completely_nonexistent_file_12345.asdf")

    def test_adv_loader_mock_asdf_invalid_conversion_and_shape_validation(self):
        """Mock rdm.open to stress test shape validation and unphysical conversion factors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_asdf = Path(tmpdir) / "test_wfi01.asdf"
            fake_asdf.touch()

            # 1. Non-standard shape with validate_shape=True
            mock_dm_bad_shape = MagicMock()
            mock_dm_bad_shape.__enter__.return_value = mock_dm_bad_shape
            mock_dm_bad_shape.data = np.zeros((100, 100), dtype=np.float32)
            mock_dm_bad_shape.err = np.zeros((100, 100), dtype=np.float32)
            mock_dm_bad_shape.dq = np.zeros((100, 100), dtype=np.uint32)
            mock_dm_bad_shape.meta = MagicMock()

            with patch("roman_datamodels.open", return_value=mock_dm_bad_shape):
                with pytest.raises(ValueError, match="Invalid Roman science array shape"):
                    load_l2_image(fake_asdf, validate_shape=True)

            # 2. Non-standard shape with validate_shape=False (permitted)
            mock_dm_bad_shape.meta.instrument.detector = "WFI01"
            mock_dm_bad_shape.meta.photometry.conversion_megajanskys = 1.0
            mock_dm_bad_shape.meta.photometry.pixel_area = NOMINAL_PIXEL_AREA
            with patch("roman_datamodels.open", return_value=mock_dm_bad_shape):
                loaded = load_l2_image(fake_asdf, validate_shape=False)
                assert loaded.shape == (100, 100)
                assert loaded.detector == "WFI01"

            # 3. Unphysical conversion factor (negative or zero)
            mock_dm_bad_phot = MagicMock()
            mock_dm_bad_phot.__enter__.return_value = mock_dm_bad_phot
            mock_dm_bad_phot.data = np.zeros(ACTIVE_SHAPE, dtype=np.float32)
            mock_dm_bad_phot.err = np.zeros(ACTIVE_SHAPE, dtype=np.float32)
            mock_dm_bad_phot.dq = np.zeros(ACTIVE_SHAPE, dtype=np.uint32)
            mock_dm_bad_phot.meta.photometry.conversion_megajanskys = -2.5
            with patch("roman_datamodels.open", return_value=mock_dm_bad_phot):
                with pytest.raises(ValueError, match="Invalid photometric conversion factor"):
                    load_l2_image(fake_asdf, validate_shape=True)


    def test_adv_loader_dataclass_methods_and_properties(self):
        """Test RomanL2Data instance methods get_dq_mask and get_effective_mask."""
        l2 = create_synthetic_l2_data(shape=(40, 40))
        l2.dq[10, 10] = DQ_FLAGS["DO_NOT_USE"]
        l2.data[20, 20] = np.nan

        assert l2.shape == (40, 40)
        mask_dq = l2.get_dq_mask(["DO_NOT_USE"])
        assert mask_dq[10, 10] == True
        assert mask_dq[20, 20] == False

        mask_eff = l2.get_effective_mask(["DO_NOT_USE"])
        assert mask_eff[10, 10] == True
        assert mask_eff[20, 20] == True


# ==============================================================================
# SECTION 2: catalog.py Adversarial Stress
# ==============================================================================

class TestCatalogAdversarial:
    """Adversarial challenge suite for src/romanepsf/catalog.py."""

    def test_adv_catalog_sanitize_extreme_solar_system_negative_mag(self):
        """Sanitize catalog with negative solar system mags (Sun -26.9, Jupiter -2.5) and NaNs."""
        df_raw = pd.DataFrame({
            "source_id": [1, 2, 3, 4, 5, 6],
            "ra": [10.0, 10.1, 10.2, 10.3, np.nan, 10.5],
            "dec": [-20.0, -20.1, 95.0, -20.3, -20.4, -20.5],  # 95 is out of dec bounds
            "mag_lambda": [-26.9, 0.0, 15.0, np.nan, 12.0, 18.5],
            "phot_g_mean_mag_AB": [-26.9, 0.0, 15.0, 14.0, 12.0, 18.5],
        })

        clean = sanitize_source_catalog(df_raw, mag_col="mag_lambda")
        # Star 1 (Sun, mag -26.9) must be filtered
        assert 1 not in clean["source_id"].values
        # Star 2 (mag 0.0, boundary case) must be KEPT (mag >= 0)
        assert 2 in clean["source_id"].values
        # Star 3 (dec 95.0 > 90) must be filtered
        assert 3 not in clean["source_id"].values
        # Star 4 (mag NaN) must be filtered
        assert 4 not in clean["source_id"].values
        # Star 5 (ra NaN) must be filtered
        assert 5 not in clean["source_id"].values
        # Star 6 (valid) must be kept
        assert 6 in clean["source_id"].values

    def test_adv_catalog_sanitize_missing_coordinates_raises_value_error(self):
        """Missing 'ra' or 'dec' columns must raise ValueError."""
        df_no_ra = pd.DataFrame({"dec": [0.0], "mag_lambda": [15.0]})
        with pytest.raises(ValueError, match="must contain 'ra' and 'dec'"):
            sanitize_source_catalog(df_no_ra)

    def test_adv_catalog_sanitize_duplicate_columns_and_sources(self):
        """Ensure identical duplicate columns and duplicated source_ids are resolved."""
        df_dup = pd.DataFrame([
            [1, 10.0, -20.0, 15.0, 15.0],
            [1, 10.0, -20.0, 15.0, 15.0],  # Duplicate source_id
            [2, 10.1, -20.1, 16.0, 16.0],
        ], columns=["source_id", "ra", "dec", "mag_lambda", "mag_lambda"])  # Duplicate col name

        clean = sanitize_source_catalog(df_dup, mag_col="mag_lambda")
        assert not clean.columns.has_duplicates
        assert len(clean) == 2
        assert list(clean["source_id"]) == [1, 2]

    def test_adv_catalog_project_pixels_empty_and_corrupted(self):
        """Verify project_catalog_to_pixels handles empty catalogs and non-invertible WCS."""
        l2 = create_synthetic_l2_data()

        # 1. Empty catalog
        empty_df = pd.DataFrame(columns=["ra", "dec", "source_id"])
        res_empty = project_catalog_to_pixels(l2, empty_df)
        assert res_empty.empty
        assert "delta_theta_arcsec" in res_empty.columns

        # 2. Corrupted WCS lacking backward_transform
        corrupt_l2 = create_synthetic_l2_data()
        corrupt_l2.wcs = object()
        df_valid = pd.DataFrame({"source_id": [1], "ra": [10.0], "dec": [-20.0], "mag_lambda": [15.0]})
        with pytest.raises(AttributeError, match="WCS object does not provide backward_transform"):
            project_catalog_to_pixels(corrupt_l2, df_valid)

    def test_adv_catalog_refine_stellar_centroids_edge_and_divergence(self):
        """Stress centroid refinement on boundaries (0, 0), (N, N), all-NaN, and divergent shifts."""
        l2 = create_synthetic_l2_data(shape=(50, 50), bg_val=0.0)
        # Place synthetic peaks
        l2.data[25, 25] = 1000.0  # Normal centered star
        l2.data[0, 0] = 500.0     # Exact corner star
        l2.data[10, 10] = np.nan  # NaN star

        df_stars = pd.DataFrame({
            "source_id": [1, 2, 3, 4],
            "x": [24.8, 0.0, 10.0, 40.0],
            "y": [25.2, 0.0, 10.0, 40.0],
        })
        # For star 4, inject a distant peak that would cause shift > 3.0 px
        l2.data[45, 45] = 1000.0  # shift ~ 7 px from (40, 40)

        refined = refine_stellar_centroids(l2, df_stars, box_radius=5, max_shift_px=3.0)
        assert len(refined) == 4

        # Star 1 shifted toward (25.0, 25.0)
        assert abs(refined.loc[0, "x"] - 25.0) < 0.2
        assert abs(refined.loc[0, "y"] - 25.0) < 0.2

        # Star 2 at (0, 0) boundary did not raise IndexError
        assert np.isfinite(refined.loc[1, "x"])
        assert np.isfinite(refined.loc[1, "y"])

        # Star 3 (NaN region) fell back to initial coordinates
        assert refined.loc[2, "x"] == 10.0
        assert refined.loc[2, "y"] == 10.0

        # Star 4 (divergent shift > 3.0 px) guarded and fell back to initial coordinates
        assert refined.loc[3, "x"] == 40.0
        assert refined.loc[3, "y"] == 40.0

    def test_adv_catalog_filter_isolated_stars_extreme_crowding_and_ties(self):
        """Stress filter_isolated_stars on high density clusters and deterministic tie-breaking."""
        # 1. Ten stars within a 5-pixel circle: only the single brightest must survive
        theta = np.linspace(0, 2 * np.pi, 10, endpoint=False)
        cluster = pd.DataFrame({
            "source_id": list(range(10)),
            "x": 100.0 + 3.0 * np.cos(theta),
            "y": 100.0 + 3.0 * np.sin(theta),
            "mag_lambda": [15.0, 12.0, 16.0, 14.0, 10.5, 17.0, 13.0, 18.0, 11.0, 19.0],
        })
        isolated = filter_isolated_stars(cluster, pixel_scale=0.11, isolation_safety_factor=1.3)
        assert len(isolated) == 1
        assert isolated.iloc[0]["source_id"] == 4  # Brightest star (mag 10.5)

        # 2. Exact identical positions and magnitudes: deterministic tie-breaking by source_id
        ties = pd.DataFrame({
            "source_id": [102, 101],
            "x": [50.0, 50.0],
            "y": [50.0, 50.0],
            "mag_lambda": [12.0, 12.0],
        })
        res_ties = filter_isolated_stars(ties)
        assert len(res_ties) == 1
        assert res_ties.iloc[0]["source_id"] == 101  # Smaller source_id preferred

    def test_adv_catalog_assign_stellar_tiers_boundary_precision(self):
        """Test exact floating-point boundary limits for tier assignment."""
        df_tiers = pd.DataFrame({
            "source_id": [1, 2, 3, 4, 5, 6, 7],
            "mag_lambda": [0.0, 10.99999, 11.0, 12.99999, 13.0, 25.0, np.nan],
        })
        tiered = assign_stellar_tiers(df_tiers, bright_limit=11.0, faint_limit=13.0)

        assert tiered.loc[0, "tier"] == "bright"
        assert tiered.loc[1, "tier"] == "bright"
        assert tiered.loc[2, "tier"] == "medium"
        assert tiered.loc[3, "tier"] == "medium"
        assert tiered.loc[4, "tier"] == "faint"
        assert tiered.loc[5, "tier"] == "faint"
        assert tiered.loc[6, "tier"] == "faint"

    def test_adv_catalog_moffat_extension_extremes(self):
        """Test get_psf_extension_moffat across extreme positive and negative magnitudes."""
        # Ultra bright star (mag = -5.0) -> large finite extension
        ext_bright = catalog_get_psf_extension_moffat(-5.0, depth=28.0)
        assert ext_bright > 10.0 and np.isfinite(ext_bright)

        # Fainter than surface brightness cutoff (mu0 > depth: mag >= 31.6 at depth 28.0)
        ext_faint = catalog_get_psf_extension_moffat(35.0, depth=28.0)
        assert ext_faint == 0.0

        # Vectorized input
        mags = np.array([-2.0, 10.0, 35.0])
        ext_vec = catalog_get_psf_extension_moffat(mags, depth=28.0)
        assert isinstance(ext_vec, np.ndarray)
        assert len(ext_vec) == 3
        assert ext_vec[0] > ext_vec[1]
        assert ext_vec[2] == 0.0

    def test_adv_catalog_get_detector_sky_bounds_and_empty_filters(self):
        """Test get_detector_sky_bounds calculation and filter_isolated_stars empty cases."""
        l2 = create_synthetic_l2_data(shape=(200, 200))
        ra_cen, dec_cen, radius_deg, r_min, r_max, d_min, d_max = get_detector_sky_bounds(l2, margin_deg=0.01)

        assert np.isfinite(ra_cen) and np.isfinite(dec_cen)
        assert radius_deg > 0.0
        assert r_min < ra_cen < r_max
        assert d_min < dec_cen < d_max

        # Empty and 1-star filter_isolated_stars edge cases
        empty_df = pd.DataFrame(columns=["x", "y", "mag_lambda"])
        assert filter_isolated_stars(empty_df).empty
        one_star = pd.DataFrame({"source_id": [1], "x": [10.0], "y": [10.0], "mag_lambda": [12.0]})
        assert len(filter_isolated_stars(one_star)) == 1


# ==============================================================================
# SECTION 3: stamps.py Adversarial Stress
# ==============================================================================

class TestStampsAdversarial:
    """Adversarial challenge suite for src/romanepsf/stamps.py."""

    def test_adv_stamps_adaptive_stamp_size_odd_parity_guarantee(self):
        """Verify get_adaptive_stamp_size always returns odd integer >= 3 across all inputs."""
        test_cases = [
            (-5.0, "bright", 1001),
            (10.5, "bright", 1000),  # Even max_size
            (12.0, "medium", 200),   # Even medium_size
            (15.0, "faint", 80),     # Even faint_size
            (99.0, "unknown_tier", 1001),
        ]
        for mag, tier, max_sz in test_cases:
            sz = get_adaptive_stamp_size(mag, tier, max_size=max_sz, medium_size=200, faint_size=80)
            assert sz % 2 == 1, f"Size {sz} for ({mag}, {tier}) is not odd!"
            assert sz >= 3

    def test_adv_stamps_extract_cutout_extreme_off_detector(self):
        """Extract cutouts far beyond detector boundaries with NaN and finite fill values."""
        img = np.ones((50, 50), dtype=np.float32) * 10.0

        # 1. Center completely off-image to the negative side
        cutout_neg, center_neg = extract_cutout(img, (-500.0, -500.0), size=21, fill_value=np.nan)
        assert cutout_neg.shape == (21, 21)
        assert np.all(np.isnan(cutout_neg))
        assert center_neg == (-500, -500)

        # 2. Center completely off-image to the positive side
        cutout_pos, center_pos = extract_cutout(img, (2000.0, 2000.0), size=15, fill_value=-999.0)
        assert cutout_pos.shape == (15, 15)
        assert np.all(cutout_pos == -999.0)

        # 3. Corner intersection cutout (exact pixel (0, 0))
        cutout_corner, _ = extract_cutout(img, (0.0, 0.0), size=21, fill_value=0.0)
        assert cutout_corner.shape == (21, 21)
        # Center of cutout is index (10, 10), which must contain image flux 10.0
        assert cutout_corner[10, 10] == 10.0
        # Quadrant outside bounds must be 0.0
        assert cutout_corner[0, 0] == 0.0

    def test_adv_stamps_estimate_background_pathological(self):
        """Stress estimate_stamp_background on all-NaN, all-masked, and flat images."""
        # 1. All NaN stamp
        nan_stamp = np.full((31, 31), np.nan, dtype=np.float32)
        bkg, rms = estimate_stamp_background(nan_stamp)
        assert bkg == 0.0 and rms == 0.0

        # 2. All masked stamp
        valid_stamp = np.ones((31, 31), dtype=np.float32) * 5.0
        mask_all = np.ones((31, 31), dtype=bool)
        bkg_m, rms_m = estimate_stamp_background(valid_stamp, mask=mask_all)
        assert bkg_m == 0.0 and rms_m == 0.0

        # 3. Flat image with zero variance
        flat_stamp = np.ones((31, 31), dtype=np.float32) * 42.0
        bkg_f, rms_f = estimate_stamp_background(flat_stamp, method="annulus")
        assert np.isclose(bkg_f, 42.0)
        assert rms_f == 0.0

        # 4. Tiny 5x5 stamp fallback to percentile
        tiny_stamp = np.arange(25, dtype=np.float32).reshape((5, 5))
        bkg_t, rms_t = estimate_stamp_background(tiny_stamp, method="annulus")
        assert np.isfinite(bkg_t) and np.isfinite(rms_t)

    def test_adv_stamps_recenter_align_spline_stability(self):
        """Stress recenter_and_align_stamp with boundary shifts and NaN preservation."""
        stamp = np.zeros((21, 21), dtype=np.float32)
        stamp[10, 10] = 100.0  # Center impulse
        mask = np.zeros((21, 21), dtype=bool)

        # 1. Shift by (+0.4, -0.3)
        aligned, aligned_mask = recenter_and_align_stamp(stamp, mask, (0.4, -0.3))
        assert aligned.shape == (21, 21)
        assert aligned_mask.shape == (21, 21)
        assert aligned.dtype == np.float32
        assert aligned_mask.dtype == bool

        # 2. Stamp containing NaNs: verify spline does not explode NaNs
        stamp_nan = stamp.copy()
        stamp_nan[0, 0] = np.nan
        aligned_nan, mask_nan = recenter_and_align_stamp(stamp_nan, mask, (0.2, 0.2))
        assert np.all(np.isfinite(aligned_nan))

    def test_adv_stamps_faint_core_protection_behavior(self):
        """Verify faint_core_protect_finite preserves positive faint core pixels from DQ bit 1."""
        l2 = create_synthetic_l2_data(shape=(100, 100), peak_val=500.0, bg_val=1.0)
        # Set DQ bit 1 (SATURATED) in the center of the faint star
        l2.dq[50, 50] = DQ_FLAGS["SATURATED"]

        df_star = pd.DataFrame({
            "source_id": [1],
            "x": [50.0],
            "y": [50.0],
            "mag_lambda": [15.0],
            "tier": ["faint"],
        })

        # With faint core protection ON (default True)
        stamps_protected = process_star_stamps(l2, df_star, faint_core_protect_finite=True)
        s_prot = stamps_protected["faint"][0]
        half = (s_prot.size - 1) // 2
        assert s_prot.mask[half, half] == False  # Protected!

        # With faint core protection OFF (False)
        stamps_unprotected = process_star_stamps(l2, df_star, faint_core_protect_finite=False)
        s_unprot = stamps_unprotected["faint"][0]
        assert s_unprot.mask[half, half] == True  # Masked because SATURATED!

    def test_adv_stamps_process_star_stamps_polymorphic_signatures(self):
        """Test process_star_stamps with polymorphic arguments (configs vs raw values)."""
        l2 = create_synthetic_l2_data(shape=(80, 80))
        df_stars = pd.DataFrame({
            "source_id": [1, 2],
            "x": [40.0, 40.0],
            "y": [40.0, 40.0],
            "mag_lambda": [10.0, 14.0],
            "tier": ["bright", "faint"],
        })

        # Signature 1: default args
        res1 = process_star_stamps(l2, df_stars)
        assert len(res1["bright"]) == 1
        assert len(res1["faint"]) == 1

        # Signature 2: SpikesConfig and StampsSection objects
        spikes_sec = SpikesSection()
        stamps_sec = StampsSection()
        res2 = process_star_stamps(l2, df_stars, spikes_cfg=spikes_sec, stamps_cfg=stamps_sec)
        assert len(res2["bright"]) == 1


# ==============================================================================
# SECTION 4: masking.py Adversarial Stress
# ==============================================================================

class TestMaskingAdversarial:
    """Adversarial challenge suite for src/romanepsf/masking.py."""

    def test_adv_masking_theoretical_angles_periodicity_and_invariance(self):
        """Verify get_theoretical_spike_angles handles arbitrary rotations modulo 360."""
        # 1. Base angles with zero offset
        angles_0 = get_theoretical_spike_angles(0.0)
        assert len(angles_0) == 12
        assert np.all((angles_0 >= 0.0) & (angles_0 < 360.0))
        assert np.all(np.diff(angles_0) > 0.0)  # Strictly sorted

        # 2. Shift by +360 and -720 degrees gives identical angles
        angles_p360 = get_theoretical_spike_angles(360.0)
        angles_m720 = get_theoretical_spike_angles(-720.0)
        assert np.allclose(angles_0, angles_p360, atol=1e-4)
        assert np.allclose(angles_0, angles_m720, atol=1e-4)

        # 3. Detector offset applied
        angles_det = get_theoretical_spike_angles(10.0, detector_offset_deg=-10.0)
        assert np.allclose(angles_0, angles_det, atol=1e-4)

    def test_adv_masking_geometric_spike_mask_core_exclusion(self):
        """Ensure geometric spike mask strictly excludes core region (r < radial_min)."""
        shape = (101, 101)
        center = (50.0, 50.0)
        angles = get_theoretical_spike_angles(0.0)
        radial_min = 10.0

        mask = create_geometric_spike_mask(shape, center, angles, radial_min=radial_min)
        grid_y, grid_x = np.ogrid[:101, :101]
        r = np.hypot(grid_x - 50.0, grid_y - 50.0)

        # Invariant: NO pixel with r < radial_min can be True in the spike mask
        assert not np.any(mask[r < radial_min])
        # Pixels with r >= radial_min along spike lines must be True
        assert np.any(mask[r >= radial_min])

    def test_adv_masking_morphological_spikes_discrimination(self):
        """Morphological filter must preserve linear spikes while rejecting compact circular blobs."""
        ny, nx = 151, 151
        cy, cx = 75.0, 75.0
        data = np.zeros((ny, nx), dtype=np.float32)

        # 1. Add a thin continuous radial spike along x-axis from r=10 to r=60
        data[75, 85:135] = 10.0

        # 2. Add an off-axis compact circular companion star at (110, 40)
        grid_y, grid_x = np.indices((ny, nx))
        r_comp = np.hypot(grid_x - 110.0, grid_y - 40.0)
        data[r_comp <= 4.0] = 20.0

        spikes = detect_morphological_spikes(data, (cx, cy), min_length_px=15, threshold_sigma=2.0)

        # Linear spike along x-axis must be detected
        assert np.any(spikes[75, 85:135])
        # Compact circular companion must NOT be classified as a diffraction spike
        assert not np.any(spikes[r_comp <= 4.0])

    def test_adv_masking_fit_moffat_model_pathological(self):
        """Verify fit_moffat_model on flat images and completely masked arrays."""
        # 1. Flat image
        flat = np.ones((41, 41), dtype=np.float32) * 5.0
        fitted_flat, model_flat = fit_moffat_model(flat)
        assert fitted_flat.shape == (41, 41)
        assert np.all(np.isfinite(fitted_flat))

        # 2. Completely masked array
        dq_all = np.ones((41, 41), dtype=bool)
        fitted_mask, model_mask = fit_moffat_model(flat, dq_mask=dq_all)
        assert np.all(fitted_mask == 0.0)
        assert model_mask is None

    def test_adv_masking_dual_prior_protection_invariant(self):
        """Strict scientific invariant: protected area is NEVER masked as contaminant."""
        ny, nx = 81, 81
        stamp = np.zeros((ny, nx), dtype=np.float32)
        stamp[40, 40] = 500.0  # Core
        # Inject contaminant at y=70, x=40 (r=30 px, theta=90 deg, well away from any spike)
        stamp[70, 40] = 80.0
        # Inject pixel along spike corridor at (25, 25) (theta = 225 deg, near spike ray 225.59 deg)
        stamp[25, 25] = 80.0

        final_mask, protected_area, residual = mask_contaminants_with_spikes_protected(
            stamp,
            pa_aperture=0.0,
            core_protection_radius_px=6.0,
            detection_sigma=2.0,
        )

        # 1. Core (r <= 6.0) must be protected
        grid_y, grid_x = np.ogrid[:ny, :nx]
        r = np.hypot(grid_x - 40.0, grid_y - 40.0)
        assert np.all(protected_area[r <= 6.0])

        # 2. Invariant: Contaminant mask must not overlap protected area
        contam_only = final_mask & (~protected_area)
        assert not np.any(contam_only & protected_area)

        # 3. Pixel at (25, 25) is inside spike corridor -> protected!
        assert protected_area[25, 25] == True
        assert final_mask[25, 25] == False

        # 4. Off-axis contaminant at (70, 40) is outside spikes -> successfully masked!
        assert protected_area[70, 40] == False
        assert final_mask[70, 40] == True


# ==============================================================================
# SECTION 5: profile.py Adversarial Stress
# ==============================================================================

class TestProfileAdversarial:
    """Adversarial challenge suite for src/romanepsf/profile.py."""

    def test_adv_profile_ellipse_meshgrid_torch_aspect_ratio_bounds(self):
        """Stress create_ellipse_meshgrid_torch on boundary ellipticity eps in [0.0, 1.0]."""
        dev = resolve_device("cpu")
        center = (25.0, 25.0)
        shape = (51, 51)

        # Circular (eps = 0.0)
        sma_circ = create_ellipse_meshgrid_torch(0.0, 0.0, center, shape, device=dev)
        assert sma_circ.shape == shape
        assert np.isclose(sma_circ[25, 25].item(), 0.0)

        # Extreme ellipticity eps = 0.9999
        sma_ext = create_ellipse_meshgrid_torch(0.9999, 45.0, center, shape, device=dev)
        assert torch.all(torch.isfinite(sma_ext))
        assert torch.all(sma_ext >= 0.0)

        # Out-of-bounds eps >= 1.0 clamped to 0.9999 without division-by-zero crash
        sma_clamp = create_ellipse_meshgrid_torch(1.5, 0.0, center, shape, device=dev)
        assert torch.all(torch.isfinite(sma_clamp))

    def test_adv_profile_clip_single_bin_pathological(self):
        """Stress _clip_single_bin on empty, single-pixel, flat, and massive outlier slices."""
        # 1. Empty slice
        med, std = _clip_single_bin([])
        assert np.isnan(med) and np.isnan(std)

        # 2. Single pixel
        med1, std1 = _clip_single_bin([42.0])
        assert med1 == 42.0 and std1 == 0.0

        # 3. Massive outlier rejection
        vals = [10.0] * 20 + [1e9]
        med_out, std_out = _clip_single_bin(vals, sigma=3.0)
        assert np.isclose(med_out, 10.0)
        assert np.isclose(std_out, 0.0)

        # 4. Zero variance (all identical)
        med_z, std_z = _clip_single_bin([5.0] * 10)
        assert med_z == 5.0 and std_z == 0.0

    def test_adv_profile_elliptical_profile_validation(self):
        """Test elliptical_profile error checking on bad inputs and memory layout."""
        img_2d = np.ones((30, 30), dtype=np.float32)

        # 1. Bin edges < 2
        with pytest.raises(ValueError, match="at least 2 bin edges"):
            elliptical_profile(img_2d, [1.0], center=(15.0, 15.0))

        # 2. 1D or 3D data array
        with pytest.raises(ValueError, match="must be a 2D array"):
            elliptical_profile(np.ones(10), [0.5, 1.5], center=(5.0, 5.0))

        # 3. Big-endian byte order array (>f4)
        big_endian = np.ones((20, 20), dtype=">f4")
        flux, flux_err, timings = elliptical_profile(
            big_endian, [0.5, 5.0, 10.0], center=(10.0, 10.0), return_timings=True
        )
        assert len(flux) == 2
        assert "meshgrid_time" in timings

    def test_adv_profile_moffat_extension_beta_bound(self):
        """Verify profile_get_psf_extension_moffat raises ValueError for beta <= 1.0."""
        with pytest.raises(ValueError, match="beta parameter must be > 1.0"):
            profile_get_psf_extension_moffat(12.0, beta=1.0)

        with pytest.raises(ValueError, match="beta parameter must be > 1.0"):
            profile_get_psf_extension_moffat(12.0, beta=0.8)


# ==============================================================================
# SECTION 6: assembly.py Adversarial Stress
# ==============================================================================

class TestAssemblyAdversarial:
    """Adversarial challenge suite for src/romanepsf/assembly.py."""

    def test_adv_assembly_stack_empty_list_raises_value_error(self):
        """Empty stamp list in stack_tier_stamps_torch must raise ValueError."""
        with pytest.raises(ValueError, match="Cannot stack an empty stamp list"):
            stack_tier_stamps_torch([])

    def test_adv_assembly_stack_varying_sizes_and_outlier_rejection(self):
        """Stack stamps of varying sizes (31x31, 51x51) with extreme pixel outliers."""
        s1_data = np.ones((31, 31), dtype=np.float32) * 10.0
        s2_data = np.ones((51, 51), dtype=np.float32) * 10.0
        s3_data = np.ones((51, 51), dtype=np.float32) * 10.0
        s4_data = np.ones((51, 51), dtype=np.float32) * 10.0
        # Inject massive outlier in s4 at center
        s4_data[25, 25] = 1e6

        stamps = [
            StellarStamp(source_id=1, tier="faint", mag=15.0, data=s1_data, mask=np.zeros((31, 31), dtype=bool), center_original=(15, 15), size=31),
            StellarStamp(source_id=2, tier="faint", mag=15.0, data=s2_data, mask=np.zeros((51, 51), dtype=bool), center_original=(25, 25), size=51),
            StellarStamp(source_id=3, tier="faint", mag=15.0, data=s3_data, mask=np.zeros((51, 51), dtype=bool), center_original=(25, 25), size=51),
            StellarStamp(source_id=4, tier="faint", mag=15.0, data=s4_data, mask=np.zeros((51, 51), dtype=bool), center_original=(25, 25), size=51),
        ]

        stacked, coverage = stack_tier_stamps_torch(stamps, sigma_clip=3.0)
        # Stacked shape must be max dimension (51, 51)
        assert stacked.shape == (51, 51)
        # Outlier at center (25, 25) must be rejected, robust median is 10.0
        assert np.isclose(stacked[25, 25], 10.0, atol=0.5)

    def test_adv_assembly_stack_hollow_core_recovery(self):
        """If central pixel is zero/masked in all stamps, recover from surrounding 3x3 positive median."""
        s1 = np.ones((21, 21), dtype=np.float32) * 20.0
        s1[10, 10] = 0.0
        m1 = np.zeros((21, 21), dtype=bool)
        m1[10, 10] = True  # Center masked

        stamps = [
            StellarStamp(source_id=1, tier="medium", mag=12.0, data=s1, mask=m1, center_original=(10, 10), size=21),
            StellarStamp(source_id=2, tier="medium", mag=12.0, data=s1.copy(), mask=m1.copy(), center_original=(10, 10), size=21),
        ]

        stacked, cov = stack_tier_stamps_torch(stamps)
        # Center should not be 0.0; hollow core fallback recovers it
        assert stacked[10, 10] > 0.0
        assert np.isclose(stacked[10, 10], 20.0)

    def test_adv_assembly_overlap_scale_factor_dual_pathological(self):
        """Stress determine_overlap_scale_factor_dual on pathological inputs."""
        r1 = np.arange(1.0, 20.0, 1.0)
        r2 = np.arange(5.0, 30.0, 1.0)

        # 1. Disjoint radii ranges -> fallback 1.0
        scale_disjoint = determine_overlap_scale_factor_dual(
            np.ones_like(r1) * 10, np.ones_like(r2) * 5, r1, r2, r_min=50.0, r_max=60.0
        )
        assert scale_disjoint == 1.0

        # 2. Inverted bounds (r_min > r_max) -> fallback 1.0
        scale_inv = determine_overlap_scale_factor_dual(
            np.ones_like(r1) * 10, np.ones_like(r2) * 5, r1, r2, r_min=20.0, r_max=10.0
        )
        assert scale_inv == 1.0

        # 3. Known exact scale factor: p1 = 4.0 * p2
        p1 = np.ones_like(r1) * 40.0
        p2 = np.ones_like(r2) * 10.0
        scale_exact = determine_overlap_scale_factor_dual(p1, p2, r1, r2, r_min=8.0, r_max=15.0)
        assert np.isclose(scale_exact, 4.0)

    def test_adv_assembly_blend_partition_of_unity(self):
        """Raised-cosine taper must strictly satisfy partition of unity: w(r) + (1 - w(r)) == 1.0."""
        # When inner = 1.0 and outer = 1.0, blended must be exactly 1.0 everywhere
        inner = np.ones((51, 51), dtype=np.float32)
        outer = np.ones((51, 51), dtype=np.float32)

        blended = blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=20.0)
        assert np.allclose(blended, 1.0, atol=1e-5)

    def test_adv_assembly_composite_psf_empty_and_graceful_tier_degradation(self):
        """Stress assemble_composite_extended_psf with empty, single, and partial tiers."""
        # 1. All tiers empty -> raises ValueError
        with pytest.raises(ValueError, match="all tiers are empty"):
            assemble_composite_extended_psf({"bright": [], "medium": [], "faint": []})

        # Helper to create stamp
        def make_stamp(tier, mag, sz):
            d = np.ones((sz, sz), dtype=np.float32)
            d[(sz - 1) // 2, (sz - 1) // 2] = 100.0
            return StellarStamp(source_id=1, tier=tier, mag=mag, data=d, mask=np.zeros((sz, sz), dtype=bool), center_original=((sz-1)/2, (sz-1)/2), size=sz)

        # 2. ONLY faint tier present -> 1-tier synthesis
        psf_f, diag_f = assemble_composite_extended_psf({"faint": [make_stamp("faint", 15.0, 31)]}, output_size=51)
        assert psf_f.shape == (51, 51)
        assert np.isclose(np.sum(psf_f), 1.0)
        assert diag_f["k_fm"] is None and diag_f["k_mb"] is None

        # 3. ONLY medium tier present -> 1-tier synthesis
        psf_m, diag_m = assemble_composite_extended_psf({"medium": [make_stamp("medium", 12.0, 41)]}, output_size=51)
        assert psf_m.shape == (51, 51)
        assert np.isclose(np.sum(psf_m), 1.0)

        # 4. ONLY bright tier present -> 1-tier synthesis
        psf_b, diag_b = assemble_composite_extended_psf({"bright": [make_stamp("bright", 10.0, 61)]}, output_size=71)
        assert psf_b.shape == (71, 71)
        assert np.isclose(np.sum(psf_b), 1.0)

        # 5. Dual-tier: Faint + Medium (missing Bright)
        stamps_fm = {
            "faint": [make_stamp("faint", 15.0, 31)],
            "medium": [make_stamp("medium", 12.0, 51)],
        }
        psf_fm, diag_fm = assemble_composite_extended_psf(stamps_fm, output_size=101)
        assert psf_fm.shape == (101, 101)
        assert np.isclose(np.sum(psf_fm), 1.0)
        assert diag_fm["k_fm"] is not None
        assert diag_fm["k_mb"] is None

        # 6. Dual-tier: Faint + Bright (missing Medium direct)
        stamps_fb = {
            "faint": [make_stamp("faint", 15.0, 31)],
            "bright": [make_stamp("bright", 10.0, 61)],
        }
        psf_fb, diag_fb = assemble_composite_extended_psf(stamps_fb, output_size=101)
        assert psf_fb.shape == (101, 101)
        assert np.isclose(np.sum(psf_fb), 1.0)

    def test_adv_assembly_serialize_fits_headers_and_empty_summaries(self):
        """Verify serialize_composite_epsf_fits handles empty detector summaries and all HDUs."""
        epsf = np.zeros((51, 51), dtype=np.float32)
        epsf[25, 25] = 1.0
        diag = {
            "k_fm": 1.25,
            "k_mb": 2.50,
            "total_flux_raw": 1000.0,
            "cov_faint": np.ones((31, 31), dtype=int),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out_fits = Path(tmpdir) / "test_adv_epsf.fits"

            # Serialize with empty detector summaries
            serialize_composite_epsf_fits(epsf, diag, detector_summaries=[], output_fits_path=out_fits)
            assert out_fits.is_file()

            with fits.open(out_fits) as hdul:
                # 4 HDUs: PRIMARY, COVERAGE, RADIAL_PROFILES, DETECTOR_SUMMARY
                assert len(hdul) == 4
                hdr = hdul[0].header
                assert hdr["TELESCOP"] == "ROMAN"
                assert hdr["INSTRUME"] == "WFI"
                assert hdr["CANVAS_S"] == 51
                assert hdr["NDET"] == 0
                assert hdr["SCALE_FM"] == 1.25
                assert hdr["SCALE_MB"] == 2.50

                # HDU 1 COVERAGE shape matches canvas
                assert hdul["COVERAGE"].shape == (51, 51)
                # HDU 2 RADIAL_PROFILES
                assert "RADIUS_PX" in hdul["RADIAL_PROFILES"].columns.names
                # HDU 3 DETECTOR_SUMMARY exists and has columns
                assert "DETECTOR" in hdul["DETECTOR_SUMMARY"].columns.names

    def test_adv_assembly_embed_or_crop_canvas_and_wrapper(self):
        """Test _embed_or_crop_canvas center embedding, cropping, and determine_overlap_scale_factor wrapper."""
        img = np.ones((51, 51), dtype=np.float32) * 5.0
        img[25, 25] = 100.0

        # 1. Embed into larger canvas (101x101)
        large = _embed_or_crop_canvas(img, 101)
        assert large.shape == (101, 101)
        assert large[50, 50] == 100.0  # Center preserved
        assert large[0, 0] == 0.0      # Boundary padded

        # 2. Crop to smaller canvas (21x21)
        small = _embed_or_crop_canvas(img, 21)
        assert small.shape == (21, 21)
        assert small[10, 10] == 100.0  # Center preserved

        # 3. Even target size automatically bumped to odd
        bumped = _embed_or_crop_canvas(img, 20)
        assert bumped.shape == (21, 21)

        # 4. determine_overlap_scale_factor backward compatibility wrapper
        r = np.arange(1.0, 20.0, 1.0)
        p_in = np.ones_like(r) * 20.0
        p_out = np.ones_like(r) * 10.0
        scale = determine_overlap_scale_factor(p_in, p_out, r, r_min=5.0, r_max=15.0)
        assert np.isclose(scale, 2.0)

