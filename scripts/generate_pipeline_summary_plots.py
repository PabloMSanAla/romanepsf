"""
Publication-Quality Visualization Script for Roman Space Telescope ePSF Pipeline:
Plot 1: 1D Radial Profile of Resulting Composite ePSF with all contributing individual star profiles in background (lower alpha)
Plot 2: Full 2D Composite Extended PSF Model Canvas (1025x1025, 113"x113" FOV) with Zoom Inset
Plot 3: Forward Modeling Subtraction for 1 Bright, 1 Medium, and 1 Faint Star
"""

import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize, TwoSlopeNorm
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from astropy.io import fits

from romanepsf.loader import load_l2_image
from romanepsf.stamps import (
    extract_cutout,
    estimate_stamp_background,
    subtract_stamp_background,
    recenter_and_align_stamp,
    get_adaptive_stamp_size,
    StellarStamp,
)
from romanepsf.masking import (
    mask_contaminants_with_spikes_protected,
    mask_gaia_companion_stars,
)
from romanepsf.catalog import query_gaia_for_detector, project_catalog_to_pixels
from romanepsf.assembly import measure_radial_profile_1d
from romanepsf.validation import fit_star_to_model
from romanepsf.config import load_config


def compute_fast_radial_profile(stamp_data: np.ndarray, mask: np.ndarray = None, r_max: int = 500) -> tuple:
    """Compute fast 1D azimuthal radial profile from 2D stamp array."""
    ny, nx = stamp_data.shape
    cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
    grid_y, grid_x = np.ogrid[:ny, :nx]
    r = np.hypot(grid_x - cx, grid_y - cy)

    valid = np.isfinite(stamp_data) & (stamp_data > 0)
    if mask is not None:
        valid &= (~mask)

    if not np.any(valid):
        return np.array([1.0]), np.array([np.nan])

    r_valid = r[valid]
    f_valid = stamp_data[valid]

    # Integer radius binning
    r_int = np.clip(np.round(r_valid).astype(int), 1, r_max)
    unique_r = np.unique(r_int)

    flux_prof = []
    r_prof = []
    for rad in unique_r:
        in_bin = r_int == rad
        if np.sum(in_bin) >= 3:
            flux_prof.append(float(np.median(f_valid[in_bin])))
            r_prof.append(float(rad))

    return np.array(r_prof), np.array(flux_prof)


def main():
    print("=== Generating Roman ePSF Pipeline Visualizations ===")
    out_dir = Path("output/plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config("configs/default.yaml")

    # 1. Load Composite Extended PSF FITS
    fits_path = Path("output/run_all/roman_epsf_composite.fits")
    if not fits_path.exists():
        fits_path = Path("output/roman_epsf_composite.fits")
    if not fits_path.exists():
        raise FileNotFoundError(f"Cannot find {fits_path}")

    print(f"Loading composite ePSF model from {fits_path}...")
    with fits.open(fits_path) as hdul:
        epsf_model = hdul[0].data.astype(np.float32)
        coverage_map = hdul["COVERAGE"].data if "COVERAGE" in hdul else None
        rad_table = hdul["RADIAL_PROFILES"].data if "RADIAL_PROFILES" in hdul else None
        header = hdul[0].header

    pixel_scale = float(header.get("PIXSCALE", 0.11))
    canvas_size = epsf_model.shape[0]
    total_flux = float(np.sum(epsf_model))
    k_fm = float(header.get("K_FM", 0.1936))
    k_mb = float(header.get("K_MB", 0.0255))
    print(f"ePSF Canvas: {canvas_size}x{canvas_size} pixels ({canvas_size * pixel_scale:.1f}\" x {canvas_size * pixel_scale:.1f}\"), Total Flux: {total_flux:.6f}")

    # 2. Load Star Catalog
    tiered_csv = Path("output/run_all/all_stars_tiered.csv")
    if not tiered_csv.exists():
        tiered_csv = Path("output/all_stars_tiered.csv")
    stars_df = pd.read_csv(tiered_csv)
    print(f"Loaded {len(stars_df)} stars from {tiered_csv} across detectors:")
    for tier in ["bright", "medium", "faint"]:
        cnt = len(stars_df[stars_df["tier"].str.lower() == tier])
        print(f"  - {tier.capitalize()}: {cnt} stars")

    # Cache loaded detectors
    loaded_l2 = {}
    loaded_gaia = {}

    def get_l2_and_gaia(det_name: str):
        det_lower = det_name.lower()
        if det_lower not in loaded_l2:
            asdf_file = cfg.data.detectors_dir / f"r0108301001001001001_0001_{det_lower}_f146_cal.asdf"
            l2 = load_l2_image(str(asdf_file), calibrate=True)
            loaded_l2[det_lower] = l2
            cache_file = Path("cache") / f"gaia_dr3_{det_lower}_g20.csv"
            if cache_file.exists():
                try:
                    g_df = pd.read_csv(cache_file)
                    g_pix = project_catalog_to_pixels(l2, g_df)
                    loaded_gaia[det_lower] = g_pix
                except Exception:
                    loaded_gaia[det_lower] = None
            else:
                loaded_gaia[det_lower] = None
        return loaded_l2[det_lower], loaded_gaia[det_lower]

    # Compute Composite ePSF 1D Radial Profile
    print("Measuring radial profile of the final 2D composite ePSF...")
    r_comp, f_comp = compute_fast_radial_profile(epsf_model, r_max=canvas_size // 2)
    comp_prof = {int(round(r)): float(f) for r, f in zip(r_comp, f_comp) if f > 0}

    # Extract cutouts and measure 1D radial profiles for stars across all tiers
    print("\nExtracting star cutouts and measuring individual 1D radial profiles...")
    star_profiles = {"bright": [], "medium": [], "faint": []}
    sample_stars_for_plot3 = {}

    for idx, row in stars_df.iterrows():
        tier = str(row["tier"]).lower()
        det = str(row["detector"])
        mag = float(row["mag_lambda"])
        cx, cy = float(row["x"]), float(row["y"])

        l2, gaia_pix = get_l2_and_gaia(det)
        sz = get_adaptive_stamp_size(mag, tier, max_size=1001, pixel_scale=pixel_scale)

        raw_cutout, (ix, iy) = extract_cutout(l2.data, (cx, cy), sz, fill_value=np.nan)
        raw_dq, _ = extract_cutout(l2.dq, (cx, cy), sz, fill_value=1)
        dq_bad = (raw_dq & 1) > 0

        core_rad = 6.0 if tier == "bright" else 4.0
        if tier == "faint":
            half = (sz - 1) // 2
            gy, gx = np.indices((sz, sz))
            r_c = np.hypot(gx - half, gy - half)
            valid_core = (r_c <= core_rad) & np.isfinite(raw_cutout) & (raw_cutout > 0)
            dq_bad[valid_core] = False

        bkg_val, bkg_rms = estimate_stamp_background(raw_cutout, mask=dq_bad, method="annulus")
        flux_sub = subtract_stamp_background(raw_cutout, bkg_val)

        sub_dx = cx - ix
        sub_dy = cy - iy
        aligned_flux, aligned_mask = recenter_and_align_stamp(flux_sub, dq_bad, (sub_dx, sub_dy))

        # Measure 1D radial profile of this individual star
        r_star, f_star = compute_fast_radial_profile(aligned_flux, mask=aligned_mask, r_max=min(sz // 2, 500))

        if len(r_star) > 0 and np.any(f_star > 0):
            # Optimal normalization scale factor Ai matching star profile to composite ePSF:
            # f_star(r) = Ai * f_comp(r) => Ai = median(f_star / f_comp) in valid SNR tier zone
            fit_range = {"faint": (1, 10), "medium": (8, 25), "bright": (20, 60)}[tier]
            r_fit = [r for r, f in zip(r_star, f_star) if fit_range[0] <= r <= fit_range[1] and int(round(r)) in comp_prof and f > 0]
            if len(r_fit) >= 3:
                ratios = [f_star[r_star == r][0] / comp_prof[int(round(r))] for r in r_fit if comp_prof[int(round(r))] > 0]
                scale_factor = float(np.median(ratios))
            else:
                pos_f = aligned_flux[aligned_flux > 0]
                scale_factor = float(np.sum(pos_f)) if len(pos_f) > 0 else 1.0

            if scale_factor > 0 and np.isfinite(scale_factor):
                f_norm = f_star / scale_factor

                # Exclude saturated core (r < 6) for bright stars and background noise floor for faint stars
                if tier == "faint":
                    valid_plot = (r_star >= 1.0) & (r_star <= 24.0) & (f_norm > 0)
                elif tier == "medium":
                    valid_plot = (r_star >= 3.0) & (r_star <= 80.0) & (f_norm > 0)
                else:  # bright
                    valid_plot = (r_star >= 6.0) & (r_star <= 450.0) & (f_norm > 0)

                if np.any(valid_plot):
                    star_profiles[tier].append((r_star[valid_plot], f_norm[valid_plot]))

        # Pick one representative star per tier for Plot 3
        if tier not in sample_stars_for_plot3:
            if tier == "bright" and (sz >= 201 or "WFI05" in det or idx == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": aligned_flux, "mask": aligned_mask,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms
                }
            elif tier == "medium" and ("WFI02" in det or len(sample_stars_for_plot3.get("medium", {})) == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": aligned_flux, "mask": aligned_mask,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms
                }
            elif tier == "faint" and ("WFI10" in det or len(sample_stars_for_plot3.get("faint", {})) == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": aligned_flux, "mask": aligned_mask,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms
                }

    print(f"Normalized profile counts: Bright={len(star_profiles['bright'])}, Medium={len(star_profiles['medium'])}, Faint={len(star_profiles['faint'])}")

    # ==============================================================================
    # PLOT 1: Resulting 1D Radial Profile with Individual Profiles in Background
    # ==============================================================================
    print("\nRendering Plot 1: 1D Radial Profile Comparison...")
    fig1, ax1 = plt.subplots(figsize=(11, 7.5), dpi=300)
    fig1.patch.set_facecolor("#0e1117")
    ax1.set_facecolor("#161b22")

    # Background: Individual profiles from all stars with low alpha (already normalized to composite)
    # Faint tier
    for r_s, f_s in star_profiles["faint"]:
        ax1.plot(r_s, f_s, color="#4caf50", alpha=0.14, linewidth=0.8)
    # Medium tier
    for r_s, f_s in star_profiles["medium"]:
        ax1.plot(r_s, f_s, color="#2196f3", alpha=0.18, linewidth=0.8)
    # Bright tier
    for r_s, f_s in star_profiles["bright"]:
        ax1.plot(r_s, f_s, color="#ff9800", alpha=0.30, linewidth=1.0)

    # Dummy lines for legend for background individual stars
    ax1.plot([], [], color="#4caf50", alpha=0.7, linewidth=1.4, label=f"Faint Stars ({len(star_profiles['faint'])} normalized profiles, r < 24 px)")
    ax1.plot([], [], color="#2196f3", alpha=0.7, linewidth=1.4, label=f"Medium Stars ({len(star_profiles['medium'])} normalized profiles, 3 < r < 80 px)")
    ax1.plot([], [], color="#ff9800", alpha=0.8, linewidth=1.4, label=f"Bright Stars ({len(star_profiles['bright'])} normalized profiles, r ≥ 6 px)")

    # Transition blending zones (shaded bands)
    ax1.axvspan(10.0, 18.0, color="#00e5ff", alpha=0.12, label="Faint-Medium Blend ($10-18$ px / $1.1-2.0''$)")
    ax1.axvspan(30.0, 48.0, color="#ffd600", alpha=0.12, label="Medium-Bright Blend ($30-48$ px / $3.3-5.3''$)")

    # Foreground: Final Composite ePSF profile
    ax1.plot(r_comp, f_comp, color="#ffffff", linewidth=3.0, label="Final Composite Extended PSF (Master Profile)")
    ax1.plot(r_comp, f_comp, color="#00e5ff", linewidth=1.6, linestyle="--")

    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlim(0.8, 520.0)
    ax1.set_ylim(1e-9, 1e-1)

    ax1.set_xlabel("Radius from Centroid (pixels)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1.set_ylabel("Normalized Surface Brightness (pixel$^{-1}$)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1.tick_params(colors="#8b949e", labelsize=10.5, which="both")
    ax1.grid(True, which="both", color="#30363d", alpha=0.4, linestyle=":")

    # Top twin axis for radius in arcseconds
    ax1_top = ax1.twiny()
    ax1_top.set_xscale("log")
    ax1_top.set_xlim(0.8 * pixel_scale, 520.0 * pixel_scale)
    ax1_top.set_xlabel("Radius from Centroid (arcseconds)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1_top.tick_params(colors="#8b949e", labelsize=10.5, which="both")

    ax1.set_title(
        "Roman Space Telescope Extended PSF: Multi-Tier Radial Profile Synthesis\n"
        f"(Master ePSF vs. {len(stars_df)} Individually Normalized Stars Across All 18 SCAs)",
        color="#58a6ff", fontsize=13, fontweight="bold", pad=16
    )

    leg = ax1.legend(loc="upper right", frameon=True, facecolor="#161b22", edgecolor="#30363d", fontsize=9.5)
    for text in leg.get_texts():
        text.set_color("#e6edf3")

    p1_path = out_dir / "plot1_psf_radial_profiles.png"
    fig1.savefig(str(p1_path), dpi=300, bbox_inches="tight", facecolor=fig1.get_facecolor(), edgecolor="none")
    plt.close(fig1)
    print(f"Saved Plot 1 to {p1_path}")

    # ==============================================================================
    # PLOT 2: The Entire 2D Composite Extended PSF Canvas
    # ==============================================================================
    print("\nRendering Plot 2: Entire 2D Extended PSF Model...")
    fig2, ax2 = plt.subplots(figsize=(10, 10), dpi=300)
    fig2.patch.set_facecolor("#0e1117")
    ax2.set_facecolor("#161b22")

    half_canvas = (canvas_size - 1) / 2.0
    extent_arcsec = [-half_canvas * pixel_scale, half_canvas * pixel_scale, -half_canvas * pixel_scale, half_canvas * pixel_scale]

    vmin_2d = 1e-8
    vmax_2d = float(np.nanmax(epsf_model))
    norm_2d = LogNorm(vmin=vmin_2d, vmax=vmax_2d)

    im2 = ax2.imshow(np.maximum(epsf_model, vmin_2d), origin="lower", cmap="inferno", norm=norm_2d, extent=extent_arcsec)

    # Highlight annular blending circles
    from matplotlib.patches import Circle
    circle_fm1 = Circle((0, 0), 10.0 * pixel_scale, fill=False, edgecolor="#00e5ff", linestyle="--", linewidth=1.0, alpha=0.7)
    circle_fm2 = Circle((0, 0), 18.0 * pixel_scale, fill=False, edgecolor="#00e5ff", linestyle="-", linewidth=1.0, alpha=0.7)
    circle_mb1 = Circle((0, 0), 30.0 * pixel_scale, fill=False, edgecolor="#ffd600", linestyle="--", linewidth=1.0, alpha=0.7)
    circle_mb2 = Circle((0, 0), 48.0 * pixel_scale, fill=False, edgecolor="#ffd600", linestyle="-", linewidth=1.0, alpha=0.7)
    ax2.add_patch(circle_fm1)
    ax2.add_patch(circle_fm2)
    ax2.add_patch(circle_mb1)
    ax2.add_patch(circle_mb2)

    ax2.set_xlabel("Relative RA / Horizontal Offset (arcsec)", color="#e6edf3", fontsize=11, labelpad=6)
    ax2.set_ylabel("Relative Dec / Vertical Offset (arcsec)", color="#e6edf3", fontsize=11, labelpad=6)
    ax2.tick_params(colors="#8b949e", labelsize=9.5)
    ax2.set_title(
        f"Roman Space Telescope Synthesized 2D Extended PSF ({canvas_size}x{canvas_size} px, {canvas_size*pixel_scale:.1f}\"x{canvas_size*pixel_scale:.1f}\")\n"
        "Full Multi-Tier Composite Model Across All 18 SCAs | Filter F146",
        color="#58a6ff", fontsize=12, fontweight="bold", pad=10
    )

    # Colorbar
    cb2 = plt.colorbar(im2, ax=ax2, fraction=0.046, pad=0.03)
    cb2.ax.tick_params(colors="#8b949e", labelsize=8.5)
    cb2.set_label("Normalized Surface Brightness / pixel (Sum = 1.0)", color="#e6edf3", fontsize=10)

    # Inset zoom of central core
    ax_inset = inset_axes(ax2, width="28%", height="28%", loc="upper right", borderpad=1.2)
    ax_inset.set_facecolor("#161b22")
    core_rad_inset = 22  # pixels
    c_mid = canvas_size // 2
    core_cutout = epsf_model[c_mid - core_rad_inset : c_mid + core_rad_inset + 1, c_mid - core_rad_inset : c_mid + core_rad_inset + 1]
    extent_inset = [-core_rad_inset * pixel_scale, core_rad_inset * pixel_scale, -core_rad_inset * pixel_scale, core_rad_inset * pixel_scale]
    ax_inset.imshow(np.maximum(core_cutout, 1e-4), origin="lower", cmap="inferno", norm=LogNorm(vmin=1e-4, vmax=vmax_2d), extent=extent_inset)
    ax_inset.set_title("Core Zoom ($45\\times 45$ px)", color="#e6edf3", fontsize=8.5, fontweight="bold", pad=3)
    ax_inset.tick_params(colors="#8b949e", labelsize=7)
    for spine in ax_inset.spines.values():
        spine.set_edgecolor("#58a6ff")
        spine.set_linewidth(1.5)

    # Metadata text box
    info_text = (
        f"Canvas: {canvas_size} x {canvas_size} px\n"
        f"Field of View: {canvas_size*pixel_scale:.1f}\" x {canvas_size*pixel_scale:.1f}\"\n"
        f"Detectors: All 18 SCAs\n"
        f"Filter: F146 (0.11\"/px)\n"
        f"Total Stars: {len(stars_df)}\n"
        f"Dynamic Range: > 10$^6$\n"
        f"Annular Blends: [10, 18] & [30, 48] px"
    )
    ax2.text(0.03, 0.04, info_text, transform=ax2.transAxes, color="#e6edf3", fontsize=8.5,
             verticalalignment="bottom", bbox=dict(boxstyle="round,pad=0.5", facecolor="#161b22", edgecolor="#30363d", alpha=0.9))

    p2_path = out_dir / "plot2_entire_composite_psf.png"
    fig2.savefig(str(p2_path), dpi=300, bbox_inches="tight", facecolor=fig2.get_facecolor(), edgecolor="none")
    plt.close(fig2)
    print(f"Saved Plot 2 to {p2_path}")

    # ==============================================================================
    # PLOT 3: Forward Modeling Subtraction for 1 Bright, 1 Medium, and 1 Faint Star
    # ==============================================================================
    print("\nRendering Plot 3: Forward Modeling & Subtraction on 1 Bright, 1 Medium, 1 Faint Star...")
    fig3, axes3 = plt.subplots(3, 4, figsize=(18, 13.5), dpi=300)
    fig3.patch.set_facecolor("#0e1117")

    tiers_ordered = ["bright", "medium", "faint"]

    for row_idx, t in enumerate(tiers_ordered):
        star_info = sample_stars_for_plot3[t]
        s_flux = star_info["flux"]
        s_mask = star_info["mask"]
        s_mag = star_info["mag"]
        s_det = star_info["det"]
        s_sz = star_info["sz"]
        s_bkg_rms = star_info["bkg_rms"]

        # Forward model the star using fit_star_to_model
        stamp_obj = StellarStamp(
            source_id=f"sample_{t}",
            tier=t,
            mag=s_mag,
            data=s_flux,
            mask=s_mask,
            center_original=((s_sz - 1) / 2.0, (s_sz - 1) / 2.0),
            size=s_sz,
            bkg_rms=s_bkg_rms,
        )

        res_result = fit_star_to_model(stamp_obj, epsf_model, fit_subpixel_offset=True)

        obs = res_result.observed_stamp
        mod = res_result.model_stamp
        res = res_result.residual_map
        norm_res = res_result.normalized_residual_map
        alpha = res_result.flux_scale
        dx, dy = res_result.subpixel_offset

        # For bright star with huge 1001x1001 stamp, zoom to central 251x251 for clear visual comparison
        if s_sz > 301:
            h_sub = 125
            c_s = s_sz // 2
            obs = obs[c_s - h_sub : c_s + h_sub + 1, c_s - h_sub : c_s + h_sub + 1]
            mod = mod[c_s - h_sub : c_s + h_sub + 1, c_s - h_sub : c_s + h_sub + 1]
            res = res[c_s - h_sub : c_s + h_sub + 1, c_s - h_sub : c_s + h_sub + 1]
            norm_res = norm_res[c_s - h_sub : c_s + h_sub + 1, c_s - h_sub : c_s + h_sub + 1]
            display_sz = 2 * h_sub + 1
        else:
            display_sz = s_sz

        pos_flux = obs[np.isfinite(obs) & (obs > 0)]
        vmin = max(float(np.percentile(pos_flux, 2)), 1e-3) if len(pos_flux) > 0 else 1e-3
        vmax = float(max(np.nanmax(obs), np.nanmax(mod))) if len(pos_flux) > 0 else 1.0
        norm_flux = LogNorm(vmin=vmin, vmax=vmax)

        # ----------------- Col 1: Observed Star -----------------
        ax1 = axes3[row_idx, 0]
        ax1.set_facecolor("#161b22")
        im1 = ax1.imshow(np.maximum(obs, vmin), origin="lower", cmap="inferno", norm=norm_flux)
        ax1.set_title(f"{t.capitalize()} Star: Observed ($I_{{obs}}$)\n{s_det}, mag={s_mag:.2f} ({display_sz}x{display_sz} px)",
                      color="#e6edf3", fontsize=10.5, fontweight="bold", pad=6)
        ax1.tick_params(colors="#8b949e", labelsize=8)
        cb1 = plt.colorbar(im1, ax=ax1, fraction=0.046, pad=0.03)
        cb1.ax.tick_params(colors="#8b949e", labelsize=7.5)
        cb1.set_label("Flux (MJy/sr)", color="#8b949e", fontsize=8)

        # ----------------- Col 2: Forward-Modeled ePSF -----------------
        ax2 = axes3[row_idx, 1]
        ax2.set_facecolor("#161b22")
        im2 = ax2.imshow(np.maximum(mod, vmin), origin="lower", cmap="inferno", norm=norm_flux)
        ax2.set_title(f"Forward-Modeled ePSF ($I_{{model}}$)\nScale $\\alpha={alpha:.2e}$, Shift=({dx:+.2f}, {dy:+.2f}) px",
                      color="#e6edf3", fontsize=10.5, fontweight="bold", pad=6)
        ax2.tick_params(colors="#8b949e", labelsize=8)
        cb2 = plt.colorbar(im2, ax=ax2, fraction=0.046, pad=0.03)
        cb2.ax.tick_params(colors="#8b949e", labelsize=7.5)
        cb2.set_label("Flux (MJy/sr)", color="#8b949e", fontsize=8)

        # ----------------- Col 3: Residual Map (Same Scale) -----------------
        ax3 = axes3[row_idx, 2]
        ax3.set_facecolor("#161b22")
        im3 = ax3.imshow(np.maximum(res, vmin), origin="lower", cmap="inferno", norm=norm_flux)
        ax3.set_title(f"Subtraction Residual ($I_{{obs}} - I_{{model}}$)\nSame Scale [Floor $\\geq$ {vmin:.1e}]",
                      color="#e6edf3", fontsize=10.5, fontweight="bold", pad=6)
        ax3.tick_params(colors="#8b949e", labelsize=8)
        cb3 = plt.colorbar(im3, ax=ax3, fraction=0.046, pad=0.03)
        cb3.ax.tick_params(colors="#8b949e", labelsize=7.5)
        cb3.set_label("Residual (MJy/sr)", color="#8b949e", fontsize=8)

        # ----------------- Col 4: Absolute Residual + Mask Overlay (Same Scale) -----------------
        ax4 = axes3[row_idx, 3]
        ax4.set_facecolor("#161b22")
        im4 = ax4.imshow(np.maximum(np.abs(res), vmin), origin="lower", cmap="inferno", norm=norm_flux)

        # Overlay contaminant mask
        if s_mask is not None:
            if s_sz > 301:
                crop_mask = s_mask[c_s - h_sub : c_s + h_sub + 1, c_s - h_sub : c_s + h_sub + 1]
            else:
                crop_mask = s_mask
            if np.any(crop_mask):
                overlay = np.zeros((*crop_mask.shape, 4), dtype=np.float32)
                overlay[crop_mask] = [0.0, 0.95, 1.0, 0.45]  # Semi-transparent cyan highlight
                ax4.imshow(overlay, origin="lower")

        ax4.set_title(f"Absolute Residual $|I_{{obs}} - I_{{model}}|$ + Mask\nSame Scale | Cyan: Contaminants",
                      color="#e6edf3", fontsize=10.5, fontweight="bold", pad=6)
        ax4.tick_params(colors="#8b949e", labelsize=8)
        cb4 = plt.colorbar(im4, ax=ax4, fraction=0.046, pad=0.03)
        cb4.ax.tick_params(colors="#8b949e", labelsize=7.5)
        cb4.set_label("Abs Residual (MJy/sr)", color="#8b949e", fontsize=8)

    plt.subplots_adjust(top=0.93, bottom=0.05, hspace=0.35, wspace=0.25, left=0.05, right=0.95)
    fig3.suptitle(
        "Roman Space Telescope Extended PSF Forward-Modeling & Subtraction Validation\n"
        "(Representative Bright, Medium, and Faint Stars Across WFI Detectors)",
        color="#58a6ff", fontsize=14, fontweight="bold", y=0.98
    )

    p3_path = out_dir / "plot3_forward_modeling_subtraction.png"
    fig3.savefig(str(p3_path), dpi=300, bbox_inches="tight", facecolor=fig3.get_facecolor(), edgecolor="none")
    plt.close(fig3)
    print(f"Saved Plot 3 to {p3_path}")

    print("\nSUCCESS: All 3 plots successfully generated in output/plots/:")
    print(f"  1. {p1_path}")
    print(f"  2. {p2_path}")
    print(f"  3. {p3_path}")


if __name__ == "__main__":
    main()
