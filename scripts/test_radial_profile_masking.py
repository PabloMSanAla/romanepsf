#!/usr/bin/env python3
"""
Test and Benchmark: Radial Profile 2D Model Masking vs Moffat Fitting
--------------------------------------------------------------------
Tests the proposed method:
1. Compute azimuthal 1D radial profile using sigma-clipping per radial bin.
2. Reconstruct a 2D model from the sigma-clipped radial profile.
3. Compute residuals: (stamp - 2D_radial_model).
4. Apply 2-sigma thresholding followed by morphological erosion and dilation.
5. Compare with standard Moffat profile fitting.
6. Generate diagnostic figures for both Bright and Medium stars.
"""

from __future__ import annotations

from pathlib import Path
import time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import AsinhNorm, LogNorm
from astropy.stats import sigma_clip, mad_std
from scipy.ndimage import binary_erosion, binary_dilation
from scipy.interpolate import interp1d

from romanepsf.loader import load_l2_image
from romanepsf.stamps import (
    extract_cutout,
    estimate_stamp_background,
    subtract_stamp_background,
    get_adaptive_stamp_size,
)
from romanepsf.masking import (
    fit_moffat_astropy,
    get_theoretical_spike_angles,
    create_geometric_spike_mask,
)

ASDF_PATH = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf"
CATALOG_PATH = "output/wfi01_stars_tiered.csv"
OUTPUT_DIR = Path("plots")


def compute_radial_profile_sigma_clipped(
    stamp: np.ndarray,
    center: tuple[float, float],
    dr: float = 1.0,
    sigma_clip_val: float = 3.0,
    max_iters: int = 3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute azimuthal radial profile using sigma clipping in radial annuli.

    Returns:
    --------
    r_map : 2D radius from center
    r_mids : radial bin midpoints
    f_profile : sigma-clipped median profile values
    s_profile : sigma-clipped MAD std profile values
    n_profile : number of valid pixels per bin
    """
    ny, nx = stamp.shape
    cx, cy = center
    gy, gx = np.indices((ny, nx))
    r_map = np.hypot(gx - cx, gy - cy)

    valid_mask = np.isfinite(stamp)
    r_max = np.nanmax(r_map[valid_mask]) if np.any(valid_mask) else float(max(nx, ny) // 2)

    bins = np.arange(0.0, r_max + dr, dr)
    r_mids = 0.5 * (bins[:-1] + bins[1:])
    f_prof = []
    s_prof = []
    n_prof = []

    for i in range(len(bins) - 1):
        in_bin = (r_map >= bins[i]) & (r_map < bins[i + 1]) & valid_mask
        pix = stamp[in_bin]
        n_valid = len(pix)
        n_prof.append(n_valid)

        if n_valid >= 4:
            clipped = sigma_clip(pix, sigma=sigma_clip_val, maxiters=max_iters)
            c_data = clipped.compressed()
            if len(c_data) > 0:
                f_prof.append(float(np.median(c_data)))
                s_prof.append(float(mad_std(c_data, ignore_nan=True)))
            else:
                f_prof.append(float(np.median(pix)))
                s_prof.append(float(mad_std(pix, ignore_nan=True)))
        elif n_valid > 0:
            f_prof.append(float(np.median(pix)))
            s_prof.append(float(np.std(pix)))
        else:
            f_prof.append(0.0)
            s_prof.append(0.0)

    return r_map, r_mids, np.array(f_prof), np.array(s_prof), np.array(n_prof)


def build_2d_model_from_radial(
    r_map: np.ndarray,
    r_mids: np.ndarray,
    f_profile: np.ndarray,
    s_profile: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate 1D radial profiles to full 2D model and 2D scatter maps."""
    interp_f = interp1d(
        r_mids,
        f_profile,
        bounds_error=False,
        fill_value=(f_profile[0] if len(f_profile) else 0.0, 0.0),
    )
    interp_s = interp1d(
        r_mids,
        s_profile,
        bounds_error=False,
        fill_value=(s_profile[0] if len(s_profile) else 0.0, float(s_profile[-1]) if len(s_profile) else 0.0),
    )

    model_2d = interp_f(r_map)
    std_2d = interp_s(r_map)
    # Ensure inner region is well-conditioned
    model_2d[r_map < r_mids[0]] = f_profile[0]
    std_2d[r_map < r_mids[0]] = s_profile[0]

    return np.maximum(model_2d, 0.0), np.maximum(std_2d, 1e-6)


def run_test_for_star(
    l2_data,
    row: pd.Series,
    tier_label: str,
    output_dir: Path,
) -> dict:
    """Run radial profile 2D model masking and generate diagnostic plot for a given star."""
    cx, cy = float(row["x"]), float(row["y"])
    mag = float(row.get("mag_lambda", row.get("phot_g_mean_mag", 12.0)))
    source_id = str(row.get("source_id", "Unknown"))
    
    # 1. Determine size and extract cutout
    sz = get_adaptive_stamp_size(mag, tier=tier_label, max_size=1001 if tier_label == "bright" else 201)
    cutout, (ix, iy) = extract_cutout(l2_data.data, (cx, cy), sz, fill_value=np.nan)
    # The cutout is centered at integer pixel (ix, iy). The star's center in stamp coordinates is:
    scx = (sz - 1) / 2.0 + (cx - ix)
    scy = (sz - 1) / 2.0 + (cy - iy)

    # Background subtraction
    bkg_val, bkg_rms = estimate_stamp_background(cutout)
    stamp = subtract_stamp_background(cutout, bkg_val)

    # 2. Benchmark Moffat Fit
    t_m0 = time.perf_counter()
    moffat_img, moffat_mod = fit_moffat_astropy(stamp, max_radius=min(sz // 2, 80))
    t_moffat = time.perf_counter() - t_m0

    # 3. Benchmark Radial Profile 2D Model
    t_r0 = time.perf_counter()
    r_map, r_mids, f_prof, s_prof, n_prof = compute_radial_profile_sigma_clipped(
        stamp, (scx, scy), dr=1.0, sigma_clip_val=3.0
    )
    model_2d, std_2d = build_2d_model_from_radial(r_map, r_mids, f_prof, s_prof)
    t_radial = time.perf_counter() - t_r0

    # 4. Residuals
    res_radial = (stamp - model_2d).astype(np.float32)
    res_moffat = (stamp - moffat_img).astype(np.float32)

    # 5. Thresholding & Morphological Masking
    # Estimate background noise from outer region
    outer_finite = (r_map > (sz // 3)) & np.isfinite(stamp)
    bkg_sigma = mad_std(stamp[outer_finite], ignore_nan=True) if np.any(outer_finite) else 0.05

    # Method A: Global 2-sigma threshold (residual > 2 * bkg_sigma)
    raw_mask_global = (res_radial > (2.0 * bkg_sigma)) & np.isfinite(stamp)
    eroded_global = binary_erosion(raw_mask_global, structure=np.ones((2, 2)))
    dilated_global = binary_dilation(eroded_global, structure=np.ones((3, 3)), iterations=2)

    # Method B: Local / Radial 2-sigma threshold (residual > 2 * std_2d(r))
    raw_mask_radial = (res_radial > (2.0 * std_2d)) & np.isfinite(stamp)
    eroded_radial = binary_erosion(raw_mask_radial, structure=np.ones((2, 2)))
    dilated_radial = binary_dilation(eroded_radial, structure=np.ones((3, 3)), iterations=2)

    # 6. Core & Spike Protection
    core_rad = 6.0 if tier_label == "bright" else 4.0
    pa_aperture = float(getattr(l2_data, "pa_aperture", 0.0))
    spike_angles = get_theoretical_spike_angles(pa_aperture, detector_offset_deg=-9.70, order="both")
    spike_mask = create_geometric_spike_mask(
        (sz, sz), (scx, scy), spike_angles,
        angular_half_width_deg=1.0 if tier_label == "bright" else 0.8,
        radial_min=core_rad,
        spike_width_px=2.5 if tier_label == "bright" else 1.8,
        width_growth_rate=0.015,
    )
    core_mask = (r_map <= core_rad)
    protected_area = spike_mask | core_mask

    # Final contaminant masks with protection:
    final_mask_protected_global = dilated_global & (~protected_area)
    final_mask_protected_radial = dilated_radial & (~protected_area)

    # Add bad/NaN pixels
    final_mask_protected_global |= (~np.isfinite(stamp))
    final_mask_protected_radial |= (~np.isfinite(stamp))

    # 7. Statistics
    valid_eval = np.isfinite(stamp) & (r_map > core_rad)
    rms_radial = float(np.sqrt(np.mean(res_radial[valid_eval] ** 2)))
    rms_moffat = float(np.sqrt(np.mean(res_moffat[valid_eval] ** 2)))

    # 8. Multi-panel Figure
    fig = plt.figure(figsize=(20, 10))
    gs = fig.add_gridspec(2, 4, hspace=0.28, wspace=0.22)

    # Panel 1: Original Stamp
    ax1 = fig.add_subplot(gs[0, 0])
    v_min = np.nanpercentile(stamp, 1)
    v_max = np.nanpercentile(stamp, 99.8)
    norm = AsinhNorm(linear_width=max(v_max * 0.01, 1.0), vmin=v_min, vmax=v_max)
    im1 = ax1.imshow(stamp, origin="lower", cmap="inferno", norm=norm)
    ax1.set_title(f"Original Stamp ({sz}x{sz})\n{tier_label.upper()} Star (mag={mag:.2f})", fontsize=11, fontweight="bold")
    ax1.set_xlabel("X (px)")
    ax1.set_ylabel("Y (px)")
    fig.colorbar(im1, ax=ax1, shrink=0.8, label="Flux (DN/s)")

    # Panel 2: 1D Radial Profile (Azimuthal Data & Models)
    ax2 = fig.add_subplot(gs[0, 1])
    sample_r = r_map[valid_eval]
    sample_f = stamp[valid_eval]
    if len(sample_r) > 10000:
        idx_sub = np.random.choice(len(sample_r), size=10000, replace=False)
        sample_r = sample_r[idx_sub]
        sample_f = sample_f[idx_sub]
    ax2.scatter(sample_r, np.maximum(sample_f, 1e-3), s=1, color="gray", alpha=0.15, label="Stamp Pixels", rasterized=True)
    ax2.plot(r_mids, np.maximum(f_prof, 1e-3), "b-", lw=2.2, label="Sigma-Clipped Median")
    ax2.fill_between(
        r_mids,
        np.maximum(f_prof - 2.0 * s_prof, 1e-3),
        np.maximum(f_prof + 2.0 * s_prof, 1e-3),
        color="blue", alpha=0.2, label=r"Azimuthal $\pm 2\sigma(r)$"
    )
    # Moffat 1D overlay
    r_eval = np.linspace(0.1, r_mids[-1], 200)
    if moffat_mod is not None:
        try:
            m_1d = moffat_mod(scx + r_eval, scy)
            ax2.plot(r_eval, np.maximum(m_1d, 1e-3), "r--", lw=1.8, label="Moffat Fit")
        except Exception:
            pass
    ax2.set_yscale("log")
    ax2.set_xscale("log")
    ax2.set_xlim(0.8, max(r_mids[-1], 10))
    ax2.set_ylim(max(bkg_sigma * 0.1, 1e-3), v_max * 1.5)
    ax2.set_title("1D Radial Profile Comparison", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Radius (pixels)")
    ax2.set_ylabel("Flux (DN/s)")
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, which="both", ls=":", alpha=0.5)

    # Panel 3: 2D Model from Radial Profile
    ax3 = fig.add_subplot(gs[0, 2])
    im3 = ax3.imshow(model_2d, origin="lower", cmap="inferno", norm=norm)
    ax3.set_title(f"2D Model from Radial Profile\n(Reconstructed in {t_radial*1000:.1f} ms)", fontsize=11, fontweight="bold")
    ax3.set_xlabel("X (px)")
    ax3.set_ylabel("Y (px)")
    fig.colorbar(im3, ax=ax3, shrink=0.8, label="Model Flux (DN/s)")

    # Panel 4: Residual Map (Stamp - 2D Model)
    ax4 = fig.add_subplot(gs[0, 3])
    r_lim = np.nanpercentile(np.abs(res_radial[valid_eval]), 98)
    im4 = ax4.imshow(res_radial, origin="lower", cmap="coolwarm", vmin=-r_lim, vmax=r_lim)
    ax4.set_title(f"Residual: Stamp - 2D Radial Model\nRMS (r>{core_rad}px) = {rms_radial:.3f} DN/s", fontsize=11, fontweight="bold")
    ax4.set_xlabel("X (px)")
    ax4.set_ylabel("Y (px)")
    fig.colorbar(im4, ax=ax4, shrink=0.8, label="Residual (DN/s)")

    # Panel 5: Raw 2-Sigma Thresholding (Residual > 2 * sigma_bkg)
    ax5 = fig.add_subplot(gs[1, 0])
    im5 = ax5.imshow(raw_mask_global, origin="lower", cmap="binary")
    ax5.set_title(f"Raw 2-Sigma Detection Mask\n(Threshold > 2 * {bkg_sigma:.4f} DN/s)\nFlagged: {np.sum(raw_mask_global):,} px", fontsize=11, fontweight="bold")
    ax5.set_xlabel("X (px)")
    ax5.set_ylabel("Y (px)")

    # Panel 6: Morphological Erosion + Dilation Mask (No Protection)
    ax6 = fig.add_subplot(gs[1, 1])
    im6 = ax6.imshow(dilated_global, origin="lower", cmap="binary")
    ax6.set_title(f"After Erosion (2x2) + Dilation (3x3)\n(Unprotected: Spikes Flagged)\nMasked: {np.sum(dilated_global):,} px", fontsize=11, fontweight="bold")
    ax6.set_xlabel("X (px)")
    ax6.set_ylabel("Y (px)")

    # Panel 7: Final Protected Contaminant Mask (Core + Spike Protection)
    ax7 = fig.add_subplot(gs[1, 2])
    mask_rgb = np.zeros((*stamp.shape, 3), dtype=float)
    # Background image in gray
    stamp_normed = (stamp - v_min) / max(v_max - v_min, 1e-6)
    stamp_normed = np.clip(stamp_normed, 0, 1)
    mask_rgb[:, :, 0] = stamp_normed * 0.7
    mask_rgb[:, :, 1] = stamp_normed * 0.7
    mask_rgb[:, :, 2] = stamp_normed * 0.7
    # Highlight contaminants in red
    mask_rgb[final_mask_protected_global, 0] = 1.0
    mask_rgb[final_mask_protected_global, 1] = 0.15
    mask_rgb[final_mask_protected_global, 2] = 0.15
    # Highlight protected spikes in cyan
    mask_rgb[spike_mask & (~core_mask), 0] = 0.1
    mask_rgb[spike_mask & (~core_mask), 1] = 0.85
    mask_rgb[spike_mask & (~core_mask), 2] = 0.85
    im7 = ax7.imshow(mask_rgb, origin="lower")
    ax7.set_title(f"Protected Mask (Spikes=Cyan, Contams=Red)\nContaminants: {np.sum(final_mask_protected_global):,} px", fontsize=11, fontweight="bold")
    ax7.set_xlabel("X (px)")
    ax7.set_ylabel("Y (px)")

    # Panel 8: Cleaned / Masked Stamp
    ax8 = fig.add_subplot(gs[1, 3])
    cleaned_stamp = stamp.copy()
    cleaned_stamp[final_mask_protected_global] = np.nan
    im8 = ax8.imshow(cleaned_stamp, origin="lower", cmap="inferno", norm=norm)
    ax8.set_title("Masked Stamp (Ready for Stacking)\nSpikes & Core Preserved", fontsize=11, fontweight="bold")
    ax8.set_xlabel("X (px)")
    ax8.set_ylabel("Y (px)")
    fig.colorbar(im8, ax=ax8, shrink=0.8, label="Cleaned Flux (DN/s)")

    fig.suptitle(
        f"Roman WFI SCA01: Radial Profile 2D Model & 2-Sigma Masking Test | {tier_label.upper()} Star (ID: {source_id})",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )

    plot_path = output_dir / f"test_radial_profile_masking_{tier_label}.png"
    plt.savefig(plot_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved plot: {plot_path}")

    return {
        "tier": tier_label,
        "mag": mag,
        "size": sz,
        "time_moffat_ms": t_moffat * 1000.0,
        "time_radial_ms": t_radial * 1000.0,
        "rms_moffat": rms_moffat,
        "rms_radial": rms_radial,
        "bkg_sigma": bkg_sigma,
        "raw_flagged_px": int(np.sum(raw_mask_global)),
        "dilated_px": int(np.sum(dilated_global)),
        "protected_contams_px": int(np.sum(final_mask_protected_global)),
        "plot_path": str(plot_path),
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Loading ASDF file: {ASDF_PATH}")
    l2_data = load_l2_image(ASDF_PATH, calibrate=True)
    df = pd.read_csv(CATALOG_PATH)

    results = []

    # 1. Bright Star
    df_bright = df[df["tier"] == "bright"]
    if not df_bright.empty:
        print("\n=== Testing BRIGHT Star ===")
        res_b = run_test_for_star(l2_data, df_bright.iloc[0], "bright", OUTPUT_DIR)
        results.append(res_b)

    # 2. Medium Star 1
    df_medium = df[df["tier"] == "medium"]
    if not df_medium.empty:
        print("\n=== Testing MEDIUM Star (Star 1) ===")
        res_m1 = run_test_for_star(l2_data, df_medium.iloc[0], "medium", OUTPUT_DIR)
        results.append(res_m1)

        if len(df_medium) > 1:
            print("\n=== Testing MEDIUM Star (Star 2) ===")
            res_m2 = run_test_for_star(l2_data, df_medium.iloc[1], "medium_star2", OUTPUT_DIR)
            results.append(res_m2)

    # Print Summary Table
    print("\n" + "=" * 80)
    print(f"{'Tier':<14} | {'Size':<9} | {'T_Moffat':<10} | {'T_Radial':<10} | {'RMS_Moffat':<10} | {'RMS_Radial':<10}")
    print("-" * 80)
    for r in results:
        print(
            f"{r['tier']:<14} | {r['size']}x{r['size']:<5} | "
            f"{r['time_moffat_ms']:<8.1f}ms | {r['time_radial_ms']:<8.1f}ms | "
            f"{r['rms_moffat']:<10.3f} | {r['rms_radial']:<10.3f}"
        )
    print("=" * 80)


if __name__ == "__main__":
    main()
