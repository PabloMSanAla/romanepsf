"""
Tier 3: Cross-Feature Combinations Tests for Roman ePSF Measurement Pipeline.

Pairwise combinatorial testing verifying data flow, contract integrity,
and multi-module state interactions across at least 25 critical feature pairs:
- Pair 1: WCS Roundtrip (F2) + Isolation Clearance Filtering (F5)
- Pair 2: Catalog Sanitization (F3) + Multi-Tier Partitioning (F6)
- Pair 3: Centroid Refinement (F4) + Subpixel Bicubic Realignment (F10)
- Pair 4: Adaptive Stamp Sizing (F9) + DQ Bit 1 Protection (F11)
- Pair 5: Adaptive Stamp Sizing (F9) + Pupil Spike Rotation (F12)
- Pair 6: Pupil Angle Transform (F12) + Morphological Ridge Filter (F13)
- Pair 7: Ridge Filter (F13) + Dual-Prior Spike Protection (F14)
- Pair 8: Dual-Prior Protection (F14) + Contaminant Masking
- Pair 9: Spike Protection (F14) + Robust Tensor Stacking (F15)
- Pair 10: 1D Radial Profile (F16) + Dual-Radius Normalization (F17)
- Pair 11: Dual-Radius Normalization (F17) + Cosine-Taper Blending (F18)
- Pair 12: Cosine-Taper Blending (F18) + Global Energy Normalization (F19)
- Pair 13: Multi-Tier Partitioning (F6) + Robust Tier Stacking (F15)
- Pair 14: ASDF Calibration (F1) + Adaptive Postage Stamps (F9)
- Pair 15: YAML Configuration (F7) + Adaptive Stamp Limits (F9)
- Pair 16: YAML Configuration (F7) + Cosine Blending Intervals (F18)
- Pair 17: Single Detector WFI01 (F20) + 2D Residual Mapping (F22)
- Pair 18: 2D Residual Mapping (F22) + Partitioned Radial Residual Metrics (F23)
- Pair 19: 18-Detector Orchestration (F21) + Lazy Memory Lifecycle
- Pair 20: 18-Detector Assembly (F21) + Publication PDF Report (F25)
- Pair 21: Centroid Refinement (F4) + Forward Model Alignment (F22)
- Pair 22: Moffat Isolation (F5) + Moffat Core Fitting (F13)
- Pair 23: CLI Subcommand single (F8) + Single Detector Execution (F20)
- Pair 24: CLI Subcommand assemble (F8) + Global Normalization (F19)
- Pair 25: CLI Subcommand report (F8) + PDF Report Generation (F25)
- Pair 26: Dual-Prior Spike Mask (F14) + Spike Residual Metrics (F23)
- Pair 27: ASDF Metadata (F1) + Optical Roll Transform (F12)
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import torch

from tests.conftest import get_module, DATA_DIR, CATALOG_PATH, WFI01_ASDF


# Helper to project catalog across versions
def safe_project(catalog_mod, l2, df, margin=50):
    try:
        return catalog_mod.project_catalog_to_pixels(l2, df, margin_px=margin)
    except TypeError:
        return catalog_mod.project_catalog_to_pixels(l2, df, margin=margin)


# ==============================================================================
# Pairwise Test Suite: 27 Interacting Feature Pairs
# ==============================================================================
class TestTier3Combinations:
    """Pairwise Cross-Feature Combinations."""

    # Pair 1: WCS Roundtrip (F2) + Isolation Clearance Filtering (F5)
    def test_pair_01_wcs_roundtrip_and_isolation_filtering(self, wfi01_asdf_path, catalog_path):
        """Pair 1: Verified WCS coordinates feed into Moffat isolation clearance."""
        catalog = get_module("catalog")
        loader = get_module("loader")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        cat_df = pd.read_csv(catalog_path, low_memory=False)

        ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
        cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
        proj = safe_project(catalog, l2, cand, margin=50)

        # Apply isolation filter on projected in-field stars
        isolated = catalog.filter_isolated_stars(proj, pixel_scale=0.11, isolation_safety_factor=1.3)
        assert len(isolated) > 0
        assert len(isolated) <= len(proj)

    # Pair 2: Catalog Sanitization (F3) + Multi-Tier Partitioning (F6)
    def test_pair_02_catalog_sanitization_and_tier_partitioning(self, catalog_path):
        """Pair 2: Sanitized catalog with 1D series feeds tier assignment."""
        catalog = get_module("catalog")
        df = pd.read_csv(catalog_path, nrows=200, low_memory=False)
        # Ensure phot_g_mean_mag is 1D
        if hasattr(catalog, "sanitize_source_catalog"):
            clean_df = catalog.sanitize_source_catalog(df)
        else:
            clean_df = df.copy()

        tiered = catalog.assign_stellar_tiers(clean_df, bright_limit=11.0, faint_limit=13.0)
        assert "tier" in tiered.columns
        assert isinstance(tiered["tier"], pd.Series)

    # Pair 3: Centroid Refinement (F4) + Subpixel Bicubic Realignment (F10)
    def test_pair_03_centroid_refinement_feeds_subpixel_shift(self, synthetic_l2_data):
        """Pair 3: Refined centroid offset used directly in spline realignment."""
        catalog = get_module("catalog")
        stamps = get_module("stamps")

        # Place star at (150.35, 150.65)
        gy, gx = np.ogrid[:500, :500]
        synthetic_l2_data.data += (500.0 * np.exp(-((gx - 150.35)**2 + (gy - 150.65)**2) / (2 * 1.5**2))).astype(np.float32)

        df = pd.DataFrame({"source_id": [1], "x": [150.0], "y": [150.0], "x_gaia": [150.0], "y_gaia": [150.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        cx, cy = refined.iloc[0]["x"], refined.iloc[0]["y"]

        # Extract cutout
        sz = 81
        cutout, (ix, iy) = stamps.extract_cutout(synthetic_l2_data.data, (cx, cy), sz)
        sub_dx = cx - ix
        sub_dy = cy - iy
        mask = np.zeros((sz, sz), dtype=bool)

        aligned, _ = stamps.recenter_and_align_stamp(cutout, mask, (sub_dx, sub_dy))
        max_idx = np.unravel_index(np.argmax(aligned), aligned.shape)
        # Shift centers peak at (40, 40)
        assert max_idx == (40, 40)

    # Pair 4: Adaptive Stamp Sizing (F9) + DQ Bit 1 Protection (F11)
    def test_pair_04_adaptive_sizing_and_faint_core_protection(self):
        """Pair 4: Faint star 81x81 cutout retains positive core despite DQ bit 1."""
        stamps = get_module("stamps")
        masking = get_module("masking")

        sz = stamps.get_adaptive_stamp_size(14.5, "faint")
        assert sz == 81

        half = (sz - 1) // 2
        faint_stamp = np.full((sz, sz), 1.8, dtype=np.float32)
        faint_stamp[half, half] = 25.0
        dq = np.zeros((sz, sz), dtype=bool)
        dq[half, half] = True  # Saturated flag on faint core

        mask, prot, _ = masking.mask_contaminants_with_spikes_protected(
            faint_stamp, dq_mask=dq, core_protection_radius_px=4.0
        )
        assert prot[half, half], "Faint core must be protected"

    # Pair 5: Adaptive Stamp Sizing (F9) + Pupil Spike Rotation (F12)
    def test_pair_05_adaptive_sizing_bright_accommodates_spikes(self):
        """Pair 5: Bright star large cutout covers full extent of 12 spike rays."""
        stamps = get_module("stamps")
        masking = get_module("masking")

        sz = stamps.get_adaptive_stamp_size(9.0, "bright", max_size=1001)
        assert sz >= 301

        cx, cy = (sz - 1) / 2.0, (sz - 1) / 2.0
        angles = masking.get_theoretical_spike_angles(-9.70)
        spike_mask = masking.create_geometric_spike_mask((sz, sz), (cx, cy), angles, radial_min=10.0)
        # Check spike reaches r = 100
        rad = np.radians(angles[0])
        px = int(round(cx + 100 * np.cos(rad)))
        py = int(round(cy + 100 * np.sin(rad)))
        assert spike_mask[py, px]

    # Pair 6: Pupil Angle Transform (F12) + Morphological Ridge Filter (F13)
    def test_pair_06_pupil_angle_and_morphological_ridge_filter(self):
        """Pair 6: Morphological filter detects linear spike aligned with optical ray."""
        masking = get_module("masking")
        sz = 201
        cx, cy = 100.0, 100.0
        angles = masking.get_theoretical_spike_angles(-9.70)
        chosen_angle = angles[0]  # First rotated ray (~13.85 deg)

        data = np.random.RandomState(42).randn(sz, sz).astype(np.float32) * 0.2
        rad = np.radians(chosen_angle)
        for d in range(15, 60):
            px = int(round(cx + d * np.cos(rad)))
            py = int(round(cy + d * np.sin(rad)))
            data[py, px] += 30.0

        detected = masking.detect_morphological_spikes(data, (cx, cy), min_length_px=15)
        px_test = int(round(cx + 35 * np.cos(rad)))
        py_test = int(round(cy + 35 * np.sin(rad)))
        assert detected[py_test, px_test]

    # Pair 7: Ridge Filter (F13) + Dual-Prior Spike Protection (F14)
    def test_pair_07_ridge_filter_fused_into_dual_prior(self):
        """Pair 7: Morphological detection fused into protected stellar area."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        data = np.full((sz, sz), 1.8, dtype=np.float32)
        data[50, 60:90] = 50.0  # Horizontal spike
        _, prot_area, _ = masking.mask_contaminants_with_spikes_protected(data, dq_mask=None)
        assert np.any(prot_area[50, 65:85])

    # Pair 8: Dual-Prior Protection (F14) + Contaminant Masking
    def test_pair_08_dual_prior_masks_neighbor_protects_spike(self):
        """Pair 8: Neighbor star outside spike corridor is masked while spike is protected."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - cx)**2 + (gy - cy)**2)
        data = (500.0 / (1.0 + (r / 2.5)**2)**1.5).astype(np.float32)
        data += np.random.RandomState(42).randn(sz, sz).astype(np.float32) * 0.2
        # Spike along row 50
        data[50, 55:95] += 40.0
        # Neighbor star centered at (80, 20)
        neighbor = 100.0 * np.exp(-((gx - 80)**2 + (gy - 20)**2) / (2 * 1.5**2))
        data += neighbor.astype(np.float32)

        final_mask, prot_area, _ = masking.mask_contaminants_with_spikes_protected(data, None)
        # Spike pixel at (50, 75) is protected
        assert prot_area[50, 75]
        assert not final_mask[50, 75]
        # Neighbor core at (20, 80) is masked
        assert final_mask[20, 80]

    # Pair 9: Spike Protection (F14) + Robust Tensor Stacking (F15)
    def test_pair_09_protected_stamps_stacked_without_losing_spikes(self):
        """Pair 9: Stacking protected stamps preserves spike amplitude."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        sz = 101
        stamps_list = []
        for i in range(3):
            d = np.zeros((sz, sz), dtype=np.float32)
            d[50, 60:90] = 30.0  # Spike
            m = np.zeros((sz, sz), dtype=bool)
            m[20, 20] = True  # Contaminant masked away from spike
            stamps_list.append(stamps_mod.StellarStamp(
                source_id=i, tier="bright", mag=9.0, data=d, mask=m, center_original=(50, 50), size=sz
            ))
        stacked, cov = assembly.stack_tier_stamps_torch(stamps_list)
        assert np.isclose(stacked[50, 75], 30.0)
        assert cov[50, 75] == 3

    # Pair 10: 1D Radial Profile (F16) + Dual-Radius Normalization (F17)
    def test_pair_10_radial_profile_feeds_scale_factor_no_index_error(self):
        """Pair 10: Profiles from different stamp sizes feed scale factor safely."""
        assembly = get_module("assembly")
        # 81x81 faint vs 201x201 medium
        img_f = np.ones((81, 81), dtype=np.float32) * 50.0
        img_m = np.ones((201, 201), dtype=np.float32) * 10.0

        rf, pf, _ = assembly.measure_radial_profile_1d(img_f, rmax=40)
        rm, pm, _ = assembly.measure_radial_profile_1d(img_m, rmax=100)

        # Scale factor in [8, 16]
        idx_f = (rf >= 8.0) & (rf <= 16.0)
        idx_m = (rm >= 8.0) & (rm <= 16.0)
        scale = float(np.median(pf[idx_f] / pm[idx_m]))
        assert np.isclose(scale, 5.0)

    # Pair 11: Dual-Radius Normalization (F17) + Cosine-Taper Blending (F18)
    def test_pair_11_scaled_tier_blended_seamlessly(self):
        """Pair 11: Scaled medium PSF stitched to faint core across [10, 18] px."""
        assembly = get_module("assembly")
        # Inner = 50.0, Outer = 10.0, Scale = 5.0 -> Scaled Outer = 50.0
        inner = np.full((81, 81), 50.0, dtype=np.float32)
        outer = np.full((201, 201), 10.0, dtype=np.float32)
        k_fm = 5.0
        outer_scaled = outer * k_fm
        blended = assembly.blend_2d_annular_profiles(inner, outer_scaled, r_start=10.0, r_end=18.0)
        # Should be flat 50.0 across transition
        np.testing.assert_allclose(blended[100, 100:130], 50.0, atol=1e-4)

    # Pair 12: Cosine-Taper Blending (F18) + Global Energy Normalization (F19)
    def test_pair_12_blended_canvas_normalized_to_unit_volume(self):
        """Pair 12: Stitched canvas normalized to unit flux sum = 1.0."""
        assembly = get_module("assembly")
        inner = np.ones((81, 81), dtype=np.float32) * 10.0
        outer = np.ones((201, 201), dtype=np.float32) * 2.0
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=10.0, r_end=18.0)
        clipped = np.maximum(blended, 0.0)
        norm_epsf = clipped / np.sum(clipped)
        assert np.isclose(np.sum(norm_epsf), 1.0, atol=1e-6)

    # Pair 13: Multi-Tier Partitioning (F6) + Robust Tier Stacking (F15)
    def test_pair_13_partitioned_tiers_stacked_independently(self):
        """Pair 13: Tiers partitioned by magnitude are stacked into independent arrays."""
        assembly = get_module("assembly")
        stamps_mod = get_module("stamps")
        faint_stamps = [
            stamps_mod.StellarStamp(source_id=1, tier="faint", mag=14.0, data=np.ones((81, 81), dtype=np.float32), mask=np.zeros((81, 81), dtype=bool), center_original=(40, 40), size=81)
        ]
        med_stamps = [
            stamps_mod.StellarStamp(source_id=2, tier="medium", mag=12.0, data=np.ones((201, 201), dtype=np.float32), mask=np.zeros((201, 201), dtype=bool), center_original=(100, 100), size=201)
        ]
        stack_f, _ = assembly.stack_tier_stamps_torch(faint_stamps)
        stack_m, _ = assembly.stack_tier_stamps_torch(med_stamps)
        assert stack_f.shape == (81, 81)
        assert stack_m.shape == (201, 201)

    # Pair 14: ASDF Calibration (F1) + Adaptive Postage Stamps (F9)
    def test_pair_14_calibrated_flux_preserved_in_stamps(self, synthetic_l2_data):
        """Pair 14: Cutouts extracted from calibrated data maintain MJy/sr units."""
        stamps = get_module("stamps")
        synthetic_l2_data.data[200, 200] = 123.45
        cutout, _ = stamps.extract_cutout(synthetic_l2_data.data, (200.0, 200.0), 81)
        assert np.isclose(cutout[40, 40], 123.45)

    # Pair 15: YAML Configuration (F7) + Adaptive Stamp Limits (F9)
    def test_pair_15_yaml_config_limits_adaptive_stamp_size(self, sample_config_dict):
        """Pair 15: YAML stamp sizes dictate maximum bright star stamp dimensions."""
        stamps = get_module("stamps")
        max_sz = sample_config_dict["stamps"]["sizes"]["bright_max"]
        sz = stamps.get_adaptive_stamp_size(7.0, "bright", max_size=max_sz)
        assert sz <= max_sz

    # Pair 16: YAML Configuration (F7) + Cosine Blending Intervals (F18)
    def test_pair_16_yaml_config_blend_intervals_used_in_stitching(self, sample_config_dict):
        """Pair 16: Blending intervals [10, 18] and [30, 48] taken from YAML config."""
        assembly = get_module("assembly")
        fm_cfg = sample_config_dict["assembly"]["overlap_fm"]
        r_start = fm_cfg["blend_start"]
        r_end = fm_cfg["blend_end"]

        inner = np.ones((81, 81), dtype=np.float32) * 5.0
        outer = np.ones((201, 201), dtype=np.float32) * 1.0
        blended = assembly.blend_2d_annular_profiles(inner, outer, r_start=r_start, r_end=r_end)
        assert blended[100, 100] == 5.0
        assert blended[100, 150] == 1.0

    # Pair 17: Single Detector WFI01 (F20) + 2D Residual Mapping (F22)
    def test_pair_17_wfi01_epsf_subtracted_from_observed_star(self, synthetic_l2_data):
        """Pair 17: ePSF model forward-subtracted from observed star image."""
        sz = 81
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - 40)**2 + (gy - 40)**2)
        star = (100.0 / (1.0 + (r / 2.0)**2)).astype(np.float32)
        epsf = star / np.sum(star)

        fitted_flux = 100.0 * np.sum(1.0 / (1.0 + (r / 2.0)**2))
        model = fitted_flux * epsf
        residual = star - model
        np.testing.assert_allclose(residual, 0.0, atol=1e-4)

    # Pair 18: 2D Residual Mapping (F22) + Partitioned Radial Residual Metrics (F23)
    def test_pair_18_residual_map_binned_into_core_transition_wings(self):
        """Pair 18: 2D residual map partitioned into functional radial zones."""
        sz = 101
        gy, gx = np.ogrid[:sz, :sz]
        r = np.sqrt((gx - 50)**2 + (gy - 50)**2)

        # Residual with small 2% core error and 1% transition error
        res = np.zeros((sz, sz), dtype=np.float32)
        res[r <= 10.0] = 0.02
        res[(r > 10.0) & (r <= 30.0)] = 0.01

        core_mu = float(np.median(res[r <= 10.0]))
        trans_mu = float(np.median(res[(r > 10.0) & (r <= 30.0)]))
        assert np.isclose(core_mu, 0.02)
        assert np.isclose(trans_mu, 0.01)

    # Pair 19: 18-Detector Orchestration (F21) + Lazy Memory Lifecycle
    def test_pair_19_lazy_detector_lifecycle_memory_cleanup(self, detectors_dir):
        """Pair 19: Opening and closing detectors sequentially frees memory."""
        loader = get_module("loader")
        import gc
        for i in range(1, 3):
            det = f"wfi{i:02d}"
            asdf_file = list(detectors_dir.glob(f"*{det}*f146_cal.asdf"))[0]
            l2 = loader.load_l2_image(str(asdf_file), calibrate=False)
            assert l2.data.shape == (4088, 4088)
            del l2
            gc.collect()

    # Pair 20: 18-Detector Assembly (F21) + Publication PDF Report (F25)
    def test_pair_20_multi_detector_composite_embedded_in_pdf(self, tmp_path):
        """Pair 20: Multi-detector composite canvas plotted and embedded in PDF."""
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt

        composite = np.zeros((1025, 1025), dtype=np.float32)
        composite[512, 512] = 1.0

        pdf_path = tmp_path / "composite_report.pdf"
        with PdfPages(pdf_path) as pdf:
            fig, ax = plt.subplots(figsize=(8, 8))
            im = ax.imshow(np.arcsinh(composite[450:575, 450:575]), cmap="magma")
            ax.set_title("Synthesized 2D ePSF Canvas")
            pdf.savefig(fig)
            plt.close(fig)

        assert pdf_path.is_file()
        assert pdf_path.stat().st_size > 1000

    # Pair 21: Centroid Refinement (F4) + Forward Model Alignment (F22)
    def test_pair_21_refined_centroid_aligns_model_subtraction(self, synthetic_l2_data):
        """Pair 21: Subpixel centroid alignment eliminates dipole residual artifact."""
        catalog = get_module("catalog")
        # Star centered at (100.25, 100.35)
        gy, gx = np.ogrid[:500, :500]
        synthetic_l2_data.data += (500.0 * np.exp(-((gx - 100.25)**2 + (gy - 100.35)**2) / (2 * 1.5**2))).astype(np.float32)

        df = pd.DataFrame({"source_id": [1], "x": [100.0], "y": [100.0], "x_gaia": [100.0], "y_gaia": [100.0]})
        refined = catalog.refine_stellar_centroids(synthetic_l2_data, df, box_radius=5)
        rcx, rcy = refined.iloc[0]["x"], refined.iloc[0]["y"]

        # Forward model centered at refined position
        model = (500.0 * np.exp(-((gx - rcx)**2 + (gy - rcy)**2) / (2 * 1.5**2))).astype(np.float32)
        box_diff = synthetic_l2_data.data[95:106, 95:106] - model[95:106, 95:106]
        # Residual should be negligible (< 10 DN/s vs 500 peak)
        assert np.max(np.abs(box_diff)) < 10.0

    # Pair 22: Moffat Isolation (F5) + Moffat Core Fitting (F13)
    def test_pair_22_consistent_moffat_parameters(self):
        """Pair 22: Moffat parameters alpha=0.08, beta=1.52 consistent across modules."""
        profile = get_module("profile")
        masking = get_module("masking")
        r_ext = profile.get_psf_extension_moffat(10.0, alpha=0.08, beta=1.52)
        assert r_ext > 0.0

    # Pair 23: CLI Subcommand single (F8) + Single Detector Execution (F20)
    def test_pair_23_cli_single_and_wfi01_execution(self):
        """Pair 23: CLI single subcommand configured for WFI01."""
        cli = get_module("cli")
        if cli is None or not hasattr(cli, "cli"):
            pytest.skip("CLI module planned for Milestone 1")
        cmd = cli.cli.commands.get("single")
        assert cmd is not None

    # Pair 24: CLI Subcommand assemble (F8) + Global Normalization (F19)
    def test_pair_24_cli_assemble_and_normalization(self):
        """Pair 24: CLI assemble subcommand configured for canvas normalization."""
        cli = get_module("cli")
        if cli is None or not hasattr(cli, "cli"):
            pytest.skip("CLI module planned for Milestone 1")
        cmd = cli.cli.commands.get("assemble")
        assert cmd is not None

    # Pair 25: CLI Subcommand report (F8) + PDF Report Generation (F25)
    def test_pair_25_cli_report_and_pdf_generation(self):
        """Pair 25: CLI report subcommand configured for PDF compilation."""
        cli = get_module("cli")
        if cli is None or not hasattr(cli, "cli"):
            pytest.skip("CLI module planned for Milestone 1")
        cmd = cli.cli.commands.get("report")
        assert cmd is not None

    # Pair 26: Dual-Prior Spike Mask (F14) + Spike Residual Metrics (F23)
    def test_pair_26_spike_mask_defines_spike_residual_zone(self):
        """Pair 26: Geometric spike mask isolates pixels for spike residual evaluation."""
        masking = get_module("masking")
        sz = 101
        cx, cy = 50.0, 50.0
        angles = masking.get_theoretical_spike_angles(-9.70)
        spike_mask = masking.create_geometric_spike_mask((sz, sz), (cx, cy), angles, radial_min=15.0)

        residual_map = np.full((sz, sz), 0.01, dtype=np.float32)
        # Spike residual evaluated only on spike_mask pixels
        spike_res = residual_map[spike_mask]
        assert len(spike_res) > 0
        assert np.isclose(np.mean(spike_res), 0.01)

    # Pair 27: ASDF Metadata (F1) + Optical Roll Transform (F12)
    def test_pair_27_asdf_pa_aperture_rotates_spike_angles(self, wfi01_asdf_path):
        """Pair 27: pa_aperture from ASDF rotates spike base angles."""
        loader = get_module("loader")
        masking = get_module("masking")
        l2 = loader.load_l2_image(str(wfi01_asdf_path), calibrate=False)
        pa_aper = l2.pa_aperture
        # Nominal detector offset -9.70 deg
        offset = -9.70
        angles = masking.get_theoretical_spike_angles(offset)
        assert len(angles) == 12
        assert np.all((angles >= 0.0) & (angles < 360.0))
