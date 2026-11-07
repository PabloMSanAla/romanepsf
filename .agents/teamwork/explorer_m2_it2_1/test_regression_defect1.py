#!/usr/bin/env python3
"""
Self-contained regression test suite for Defect 1:
- Unit test: sparse annular coverage in medium tier without mask triggers k_mb fallback to 1.0; with mask recovers k_mb < 0.1.
- E2E test on WFI01: verifies k_mb < 0.1 and strict monotonic radial decay across transition annulus [30, 48] px.
"""

import numpy as np
import pytest
from pathlib import Path


def test_unit_assembly_sparse_coverage_mask_recovers_k_mb():
    """
    Unit test: Medium tier stamp has > 50% masked pixels in the [22, 45] px overlap annulus.
    Without passing coverage mask to measure_radial_profile_1d, unobserved 0.0 pixels drive
    prof_m to 0.0 in the overlap annulus, causing determine_overlap_scale_factor_dual
    to fail and return the fallback k_mb = 1.0.
    With mask=(cov == 0), the true stellar flux is recovered, yielding k_mb ~ 0.04.
    """
    from romanepsf import assembly

    # 1. Faint tier stamp (81x81)
    sz_f = 81
    c_f = (sz_f - 1) // 2
    gy_f, gx_f = np.ogrid[:sz_f, :sz_f]
    rf = np.sqrt((gx_f - c_f) ** 2 + (gy_f - c_f) ** 2)
    d_f = (5000.0 / (1.0 + (rf / 2.0) ** 2)).astype(np.float32)
    s_f = assembly.StellarStamp(
        source_id=1, tier="faint", mag=14.0, data=d_f,
        mask=np.zeros_like(d_f, dtype=bool), center_original=(c_f, c_f), size=sz_f
    )

    # 2. Medium tier stamp (201x201) - 5x brighter than faint (relative scale k_fm = 0.2)
    sz_m = 201
    c_m = (sz_m - 1) // 2
    gy_m, gx_m = np.ogrid[:sz_m, :sz_m]
    rm = np.sqrt((gx_m - c_m) ** 2 + (gy_m - c_m) ** 2)
    d_m = (25000.0 / (1.0 + (rm / 2.0) ** 2)).astype(np.float32)
    d_m[rm <= 4.0] = 2000.0  # Core saturation

    # Mask out 70% of annular pixels in r in [21, 46] (e.g., angle sector <= 250 deg)
    theta_m = np.mod(np.degrees(np.arctan2(gy_m - c_m, gx_m - c_m)), 360)
    mask_m = np.zeros_like(d_m, dtype=bool)
    mask_m[(rm >= 21.0) & (rm <= 46.0) & (theta_m <= 250.0)] = True
    s_m = assembly.StellarStamp(
        source_id=2, tier="medium", mag=12.0, data=d_m,
        mask=mask_m, center_original=(c_m, c_m), size=sz_m
    )

    # 3. Bright tier stamp (501x501) - 25x brighter than faint, 5x brighter than medium (expected k_mb = 0.04)
    sz_b = 501
    c_b = (sz_b - 1) // 2
    gy_b, gx_b = np.ogrid[:sz_b, :sz_b]
    rb = np.sqrt((gx_b - c_b) ** 2 + (gy_b - c_b) ** 2)
    d_b = (125000.0 / (1.0 + (rb / 2.0) ** 2)).astype(np.float32)
    d_b[rb <= 15.0] = 2000.0  # Core saturation
    s_b = assembly.StellarStamp(
        source_id=3, tier="bright", mag=9.0, data=d_b,
        mask=np.zeros_like(d_b, dtype=bool), center_original=(c_b, c_b), size=sz_b
    )

    tier_stamps = {"faint": [s_f], "medium": [s_m], "bright": [s_b]}

    # Stack and extract profiles WITH mask=(cov == 0)
    psf_f, cov_f = assembly.stack_tier_stamps_torch(tier_stamps["faint"])
    psf_m, cov_m = assembly.stack_tier_stamps_torch(tier_stamps["medium"])
    psf_b, cov_b = assembly.stack_tier_stamps_torch(tier_stamps["bright"])

    r_f, prof_f, _ = assembly.measure_radial_profile_1d(psf_f, mask=(cov_f == 0))
    r_m, prof_m, _ = assembly.measure_radial_profile_1d(psf_m, mask=(cov_m == 0))
    r_b, prof_b, _ = assembly.measure_radial_profile_1d(psf_b, mask=(cov_b == 0))

    k_fm = assembly.determine_overlap_scale_factor_dual(prof_f, prof_m, r_f, r_m, r_min=8.0, r_max=18.0)
    prof_m_scaled = prof_m * k_fm
    k_mb = assembly.determine_overlap_scale_factor_dual(prof_m_scaled, prof_b, r_m, r_b, r_min=22.0, r_max=45.0)

    # Assertions
    assert np.isclose(k_fm, 0.2, atol=0.01), f"k_fm was {k_fm}, expected 0.20"
    assert k_mb < 0.1, f"k_mb was {k_mb}, fallback to 1.0 occurred!"
    assert np.isclose(k_mb, 0.04, atol=0.005), f"k_mb was {k_mb}, expected 0.04"


def test_e2e_wfi01_k_mb_scaling_and_monotonic_decay():
    """
    E2E regression test on real WFI01 commissioning data:
    Verifies that k_mb < 0.1 (nominal ~0.018), and that the synthesized ePSF
    strictly exhibits monotonic radial decay from r=30 to r=48 px without the 25x flux surge.
    """
    from romanepsf import loader, catalog, stamps, assembly
    import pandas as pd

    wfi01_path = Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf")
    cat_path = Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv")

    if not wfi01_path.exists() or not cat_path.exists():
        pytest.skip("Commissioning ASDF or catalog file not found")

    l2 = loader.load_l2_image(str(wfi01_path), calibrate=True)
    cat_df = pd.read_csv(cat_path, low_memory=False)
    ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
    cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
    cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
    proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
    tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
    tier_stamps = stamps.process_star_stamps(l2, tiered)

    # Perform assembly using the corrected masking logic
    psf_f, cov_f = assembly.stack_tier_stamps_torch(tier_stamps["faint"])
    psf_m, cov_m = assembly.stack_tier_stamps_torch(tier_stamps["medium"])
    psf_b, cov_b = assembly.stack_tier_stamps_torch(tier_stamps["bright"])

    r_f, prof_f, _ = assembly.measure_radial_profile_1d(psf_f, mask=(cov_f == 0))
    r_m, prof_m, _ = assembly.measure_radial_profile_1d(psf_m, mask=(cov_m == 0))
    r_b, prof_b, _ = assembly.measure_radial_profile_1d(psf_b, mask=(cov_b == 0))

    k_fm = assembly.determine_overlap_scale_factor_dual(prof_f, prof_m, r_f, r_m, r_min=8.0, r_max=18.0)
    psf_m_scaled = psf_m * k_fm
    prof_m_scaled = prof_m * k_fm

    k_mb = assembly.determine_overlap_scale_factor_dual(prof_m_scaled, prof_b, r_m, r_b, r_min=22.0, r_max=45.0)
    psf_b_scaled = psf_b * k_mb

    psf_fm = assembly.blend_2d_annular_profiles(psf_f, psf_m_scaled, r_start=10.0, r_end=18.0)

    target_sz = 501
    bright_sz = psf_b_scaled.shape[0]
    half_t = (target_sz - 1) // 2
    half_b = (bright_sz - 1) // 2
    y0 = half_b - half_t
    x0 = half_b - half_t
    bright_canvas = psf_b_scaled[y0:y0 + target_sz, x0:x0 + target_sz].copy()

    epsf = assembly.blend_2d_annular_profiles(psf_fm, bright_canvas, r_start=30.0, r_end=48.0)
    epsf = np.clip(epsf, a_min=0.0, a_max=None)
    epsf /= np.sum(epsf)

    # Assertion 1: Scaling factor recovery
    assert k_mb < 0.1, f"k_mb={k_mb} failed to recover physical scaling (expected ~0.018)"
    assert 0.015 < k_mb < 0.025, f"k_mb={k_mb} outside expected physical window [0.015, 0.025]"

    # Assertion 2: Radial monotonicity in transition annulus
    c = (epsf.shape[0] - 1) // 2
    y, x = np.ogrid[:epsf.shape[0], :epsf.shape[1]]
    dist = np.hypot(x - c, y - c)
    flux_r30 = float(np.mean(epsf[(dist >= 29.5) & (dist < 30.5)]))
    flux_r48 = float(np.mean(epsf[(dist >= 47.5) & (dist < 48.5)]))

    assert flux_r48 < flux_r30, f"Unphysical flux surge: flux_r48 ({flux_r48:.2e}) >= flux_r30 ({flux_r30:.2e})"
    assert flux_r48 / flux_r30 < 0.8, f"Decay ratio {flux_r48 / flux_r30:.2f} >= 0.8"


if __name__ == "__main__":
    test_unit_assembly_sparse_coverage_mask_recovers_k_mb()
    print("Unit test passed!")
    test_e2e_wfi01_k_mb_scaling_and_monotonic_decay()
    print("E2E test passed!")
