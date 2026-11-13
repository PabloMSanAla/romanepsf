"""
Publication-Quality Visualization Script for Roman Space Telescope ePSF Pipeline:
Plot 1: 1D Radial Profile of Resulting Composite ePSF with all contributing individual star profiles in background (lower alpha, 4x oversampled for faint/medium)
Plot 2: Full 2D Composite Extended PSF Model Canvas (1025x1025, 113"x113" FOV) with 4x Oversampled Core Inset
Plot 3: Forward Modeling Subtraction for 1 Bright, 1 Medium, and 1 Faint Star (4x oversampled subpixel modeling, identical scale across all 4 panels)
"""

import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from astropy.io import fits
from scipy.ndimage import shift
from scipy.optimize import minimize

from romanepsf.loader import load_l2_image
from romanepsf.stamps import (
    extract_cutout,
    estimate_stamp_background,
    subtract_stamp_background,
    recenter_and_align_stamp,
    downsample_oversampled_stamp,
    get_adaptive_stamp_size,
    StellarStamp,
)
from romanepsf.catalog import project_catalog_to_pixels
from romanepsf.assembly import measure_radial_profile_1d
from romanepsf.validation import fit_star_to_model
from romanepsf.config import load_config


def compute_fast_radial_profile(
    stamp_data: np.ndarray,
    mask: np.ndarray = None,
    r_max_native: float = 500.0,
    oversample: float = 1.0,
    bin_width_native: float = 1.0,
) -> tuple:
    """Compute fast 1D azimuthal radial profile in native pixel units with optional subpixel binning."""
    ny, nx = stamp_data.shape
    cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
    grid_y, grid_x = np.ogrid[:ny, :nx]
    r_px = np.hypot(grid_x - cx, grid_y - cy)
    r_native = r_px / oversample

    valid = np.isfinite(stamp_data) & (stamp_data > 0)
    if mask is not None:
        valid &= (~mask)

    if not np.any(valid):
        return np.array([1.0]), np.array([np.nan])

    r_valid = r_native[valid]
    f_valid = stamp_data[valid]

    # Subpixel binning in native pixel units
    bin_edges = np.arange(bin_width_native / 2.0, r_max_native + bin_width_native, bin_width_native)
    bin_idx = np.digitize(r_valid, bin_edges) - 1

    unique_bins = np.unique(bin_idx)
    unique_bins = unique_bins[(unique_bins >= 0) & (unique_bins < len(bin_edges))]

    flux_prof = []
    r_prof = []
    for b in unique_bins:
        in_bin = bin_idx == b
        if np.sum(in_bin) >= 3:
            flux_prof.append(float(np.median(f_valid[in_bin])))
            r_prof.append(float(bin_edges[b]))

    return np.array(r_prof), np.array(flux_prof)


def main():
    print("=== Generating Roman ePSF Pipeline Visualizations (4x Oversampled Faint & Medium) ===")
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

    # Compute Wide Composite ePSF 1D Radial Profile
    print("Measuring radial profile of the final 2D composite ePSF...")
    r_comp_wide, f_comp_wide = compute_fast_radial_profile(epsf_model, r_max_native=canvas_size // 2, oversample=1.0, bin_width_native=1.0)

    # Extract cutouts, oversample faint & medium by 4x, and measure 1D radial profiles
    print("\nExtracting star cutouts and measuring individual 1D radial profiles (4x oversampled for faint & medium)...")
    star_profiles = {"bright": [], "medium": [], "faint": []}
    sample_stars_for_plot3 = {}
    faint_stamps_4x = []
    medium_stamps_4x = []

    faint_crop_sz_4x = 177   # (45 - 1) * 4 + 1
    medium_crop_sz_4x = 361  # (91 - 1) * 4 + 1

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

        osamp = 4 if tier in ["faint", "medium"] else 1
        bin_w = 0.25 if osamp > 1 else 1.0

        # Subpixel alignment (oversampled 4x for faint and medium)
        aligned_flux, aligned_mask = recenter_and_align_stamp(flux_sub, dq_bad, (sub_dx, sub_dy), oversample=osamp)

        # Collect normalized oversampled stamps for 4x core model stacking
        if tier == "faint" and aligned_flux.shape[0] >= faint_crop_sz_4x:
            c_f = aligned_flux.shape[0] // 2
            h_f = faint_crop_sz_4x // 2
            f_crop = aligned_flux[c_f - h_f : c_f + h_f + 1, c_f - h_f : c_f + h_f + 1]
            f_sum = np.sum(f_crop[f_crop > 0])
            if f_sum > 0:
                faint_stamps_4x.append(f_crop / f_sum)
        elif tier == "medium" and aligned_flux.shape[0] >= medium_crop_sz_4x:
            c_m = aligned_flux.shape[0] // 2
            h_m = medium_crop_sz_4x // 2
            m_crop = aligned_flux[c_m - h_m : c_m + h_m + 1, c_m - h_m : c_m + h_m + 1]
            m_sum = np.sum(m_crop[m_crop > 0])
            if m_sum > 0:
                medium_stamps_4x.append(m_crop / m_sum)

        # Measure 1D radial profile of this individual star
        r_star, f_star = compute_fast_radial_profile(
            aligned_flux, mask=aligned_mask, r_max_native=min(sz // 2, 500), oversample=osamp, bin_width_native=bin_w
        )

        if len(r_star) > 0 and np.any(f_star > 0):
            # Optimal normalization scale factor Ai matching star profile to composite ePSF:
            comp_vals = np.interp(r_star, r_comp_wide, f_comp_wide)
            fit_range = {"faint": (1.0, 10.0), "medium": (8.0, 25.0), "bright": (20.0, 60.0)}[tier]
            valid_fit = (r_star >= fit_range[0]) & (r_star <= fit_range[1]) & (f_star > 0) & (comp_vals > 0)

            if np.sum(valid_fit) >= 3:
                scale_factor = float(np.median(f_star[valid_fit] / comp_vals[valid_fit]))
            else:
                pos_f = aligned_flux[aligned_flux > 0]
                scale_factor = float(np.sum(pos_f)) if len(pos_f) > 0 else 1.0

            if scale_factor > 0 and np.isfinite(scale_factor):
                f_norm = f_star / scale_factor

                # Filter valid radial range per tier
                if tier == "faint":
                    valid_plot = (r_star >= 0.25) & (r_star <= 24.0) & (f_norm > 0)
                elif tier == "medium":
                    valid_plot = (r_star >= 0.75) & (r_star <= 80.0) & (f_norm > 0)
                else:  # bright
                    valid_plot = (r_star >= 6.0) & (r_star <= 450.0) & (f_norm > 0)

                if np.any(valid_plot):
                    star_profiles[tier].append((r_star[valid_plot], f_norm[valid_plot]))

        # Pick one representative star per tier for Plot 3
        if tier not in sample_stars_for_plot3:
            # Also get native 1x aligned flux for Plot 3
            if osamp > 1:
                aligned_flux_native, aligned_mask_native = recenter_and_align_stamp(flux_sub, dq_bad, (sub_dx, sub_dy), oversample=1)
            else:
                aligned_flux_native, aligned_mask_native = aligned_flux, aligned_mask

            if tier == "bright" and (sz >= 201 or "WFI05" in det or idx == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": aligned_flux_native, "mask": aligned_mask_native,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms,
                    "sub_offset": (sub_dx, sub_dy)
                }
            elif tier == "medium" and ("WFI02" in det or len(sample_stars_for_plot3.get("medium", {})) == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": aligned_flux_native, "mask": aligned_mask_native,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms,
                    "sub_offset": (sub_dx, sub_dy)
                }
            elif tier == "faint" and ("WFI10" in det or len(sample_stars_for_plot3.get("faint", {})) == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": aligned_flux_native, "mask": aligned_mask_native,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms,
                    "sub_offset": (sub_dx, sub_dy)
                }

    print(f"Normalized profile counts: Bright={len(star_profiles['bright'])}, Medium={len(star_profiles['medium'])}, Faint={len(star_profiles['faint'])}")

    # ==============================================================================
    # 4X OVERSAMPLED CORE MODEL SYNTHESIS
    # ==============================================================================
    print("Synthesizing 4x oversampled core ePSF model from faint and medium star ensembles...")
    psf_faint_4x = np.nanmedian(faint_stamps_4x, axis=0) if faint_stamps_4x else None
    psf_medium_4x = np.nanmedian(medium_stamps_4x, axis=0) if medium_stamps_4x else None

    # Embed faint 4x into medium 4x shape (361x361) and blend with smooth raised-cosine
    ny_c, nx_c = medium_crop_sz_4x, medium_crop_sz_4x
    cx_c, cy_c = (nx_c - 1) / 2.0, (ny_c - 1) / 2.0
    grid_y, grid_x = np.ogrid[:ny_c, :nx_c]
    r_nat_c = np.hypot(grid_x - cx_c, grid_y - cy_c) / 4.0

    if psf_faint_4x is not None and psf_medium_4x is not None:
        f_emb = np.zeros((ny_c, nx_c), dtype=np.float32)
        h_f = faint_crop_sz_4x // 2
        f_emb[int(cy_c - h_f) : int(cy_c + h_f + 1), int(cx_c - h_f) : int(cx_c + h_f + 1)] = psf_faint_4x

        w_blend = 0.5 * (1.0 + np.cos(np.pi * (r_nat_c - 10.0) / (18.0 - 10.0)))
        w_blend[r_nat_c <= 10.0] = 1.0
        w_blend[r_nat_c >= 18.0] = 0.0

        psf_core_4x = w_blend * f_emb + (1.0 - w_blend) * psf_medium_4x * k_fm
    elif psf_faint_4x is not None:
        psf_core_4x = psf_faint_4x
    else:
        # Fallback to crop from 2D composite ePSF oversampled by 4x
        c_mid = canvas_size // 2
        crop_nat = epsf_model[c_mid - 45 : c_mid + 46, c_mid - 45 : c_mid + 46]
        psf_core_4x, _ = recenter_and_align_stamp(crop_nat, np.zeros_like(crop_nat, dtype=bool), (0, 0), oversample=4)

    # Measure 4x radial profile of the synthesized core
    r_comp_4x, f_comp_4x = compute_fast_radial_profile(psf_core_4x, oversample=4.0, bin_width_native=0.25)

    # Scale 4x core profile to match composite profile in blend range [10, 18] px
    match_zone = (r_comp_4x >= 10.0) & (r_comp_4x <= 18.0)
    if np.any(match_zone):
        ref_vals = np.interp(r_comp_4x[match_zone], r_comp_wide, f_comp_wide)
        core_scale = float(np.median(ref_vals / f_comp_4x[match_zone]))
        f_comp_4x *= core_scale
        psf_core_4x *= core_scale

    # Splice 4x oversampled core profile with wide outer profile for master composite curve
    r_master_core = r_comp_4x[r_comp_4x <= 18.0]
    f_master_core = f_comp_4x[r_comp_4x <= 18.0]
    r_master_wide = r_comp_wide[r_comp_wide > 18.0]
    f_master_wide = f_comp_wide[r_comp_wide > 18.0]
    r_composite_master = np.concatenate([r_master_core, r_master_wide])
    f_composite_master = np.concatenate([f_master_core, f_master_wide])

    # ==============================================================================
    # PLOT 1: Resulting 1D Radial Profile with 4x Oversampled Stars in Background
    # ==============================================================================
    print("\nRendering Plot 1: 1D Radial Profile Comparison (4x Oversampled Faint & Medium)...")
    fig1, ax1 = plt.subplots(figsize=(11, 7.5), dpi=300)
    fig1.patch.set_facecolor("#0e1117")
    ax1.set_facecolor("#161b22")

    # Background: Individual profiles from all stars with low alpha (already normalized to composite)
    # Faint tier (4x oversampled, 0.25 px bins)
    for r_s, f_s in star_profiles["faint"]:
        ax1.plot(r_s, f_s, color="#4caf50", alpha=0.14, linewidth=0.8)
    # Medium tier (4x oversampled, 0.25 px bins)
    for r_s, f_s in star_profiles["medium"]:
        ax1.plot(r_s, f_s, color="#2196f3", alpha=0.18, linewidth=0.8)
    # Bright tier (1x native, 1.0 px bins)
    for r_s, f_s in star_profiles["bright"]:
        ax1.plot(r_s, f_s, color="#ff9800", alpha=0.30, linewidth=1.0)

    # Dummy lines for legend for background individual stars
    ax1.plot([], [], color="#4caf50", alpha=0.7, linewidth=1.4, label=f"Faint Stars ({len(star_profiles['faint'])} stars, 4x Oversampled [0.25 px], r < 24 px)")
    ax1.plot([], [], color="#2196f3", alpha=0.7, linewidth=1.4, label=f"Medium Stars ({len(star_profiles['medium'])} stars, 4x Oversampled [0.25 px], 0.75 < r < 80 px)")
    ax1.plot([], [], color="#ff9800", alpha=0.8, linewidth=1.4, label=f"Bright Stars ({len(star_profiles['bright'])} stars, Native [1.0 px], r ≥ 6 px)")

    # Transition blending zones (shaded bands)
    ax1.axvspan(10.0, 18.0, color="#00e5ff", alpha=0.12, label="Faint-Medium Blend ($10-18$ px / $1.1-2.0''$)")
    ax1.axvspan(30.0, 48.0, color="#ffd600", alpha=0.12, label="Medium-Bright Blend ($30-48$ px / $3.3-5.3''$)")

    # Foreground: Final Composite ePSF profile with 4x oversampled core
    ax1.plot(r_composite_master, f_composite_master, color="#ffffff", linewidth=3.0, label="Final Composite ePSF (4x Oversampled Core + Wide Halo)")
    ax1.plot(r_composite_master, f_composite_master, color="#00e5ff", linewidth=1.6, linestyle="--")

    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlim(0.2, 520.0)
    ax1.set_ylim(1e-9, 1e-1)

    ax1.set_xlabel("Radius from Centroid (native pixels, 0.11\"/px)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1.set_ylabel("Normalized Surface Brightness (pixel$^{-1}$)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1.tick_params(colors="#8b949e", labelsize=10.5, which="both")
    ax1.grid(True, which="both", color="#30363d", alpha=0.4, linestyle=":")

    # Top twin axis for radius in arcseconds
    ax1_top = ax1.twiny()
    ax1_top.set_xscale("log")
    ax1_top.set_xlim(0.2 * pixel_scale, 520.0 * pixel_scale)
    ax1_top.set_xlabel("Radius from Centroid (arcseconds)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1_top.tick_params(colors="#8b949e", labelsize=10.5, which="both")

    ax1.set_title(
        "Roman Space Telescope Extended PSF: Multi-Tier Radial Profile Synthesis\n"
        f"(Master ePSF with 4x Subpixel Oversampling vs. {len(stars_df)} Contributing Stars Across 18 SCAs)",
        color="#58a6ff", fontsize=13, fontweight="bold", pad=16
    )

    leg = ax1.legend(loc="upper right", frameon=True, facecolor="#161b22", edgecolor="#30363d", fontsize=9.2)
    for text in leg.get_texts():
        text.set_color("#e6edf3")

    p1_path = out_dir / "plot1_psf_radial_profiles.png"
    fig1.savefig(str(p1_path), dpi=300, bbox_inches="tight", facecolor=fig1.get_facecolor(), edgecolor="none")
    plt.close(fig1)
    print(f"Saved Plot 1 to {p1_path}")

    # ==============================================================================
    # PLOT 2: The Entire 2D Composite Extended PSF Canvas with 4x Oversampled Inset
    # ==============================================================================
    print("\nRendering Plot 2: Entire 2D Extended PSF Model (with 4x Oversampled Core Inset)...")
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
        "Full Multi-Tier Composite Model Across All 18 SCAs | Filter F146 (4x Oversampled Core)",
        color="#58a6ff", fontsize=12, fontweight="bold", pad=10
    )

    # Colorbar
    cb2 = plt.colorbar(im2, ax=ax2, fraction=0.046, pad=0.03)
    cb2.ax.tick_params(colors="#8b949e", labelsize=8.5)
    cb2.set_label("Normalized Surface Brightness / pixel (Sum = 1.0)", color="#e6edf3", fontsize=10)

    # Inset zoom: 4x Oversampled Core (181x181 subpixels = 45x45 native pixels = 5.0"x5.0")
    ax_inset = inset_axes(ax2, width="30%", height="30%", loc="upper right", borderpad=1.2)
    ax_inset.set_facecolor("#161b22")
    core_rad_nat = 22  # native pixels
    core_rad_sub = core_rad_nat * 4  # 88 subpixels
    c_sub = psf_core_4x.shape[0] // 2
    core_cutout_4x = psf_core_4x[c_sub - core_rad_sub : c_sub + core_rad_sub + 1, c_sub - core_rad_sub : c_sub + core_rad_sub + 1]
    extent_inset = [-core_rad_nat * pixel_scale, core_rad_nat * pixel_scale, -core_rad_nat * pixel_scale, core_rad_nat * pixel_scale]
    ax_inset.imshow(np.maximum(core_cutout_4x, 1e-4), origin="lower", cmap="inferno", norm=LogNorm(vmin=1e-4, vmax=vmax_2d), extent=extent_inset)
    ax_inset.set_title("Core Zoom (4x Oversampled: 0.0275\"/px)", color="#e6edf3", fontsize=8.5, fontweight="bold", pad=3)
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
        f"Core Sampling: 4x Oversampled (0.0275\"/px)\n"
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
    print("\nRendering Plot 3: Forward Modeling & Subtraction on 1 Bright, 1 Medium, 1 Faint Star (4x Oversampled Subpixel Modeling)...")
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

        # Forward model the star
        if t in ["faint", "medium"]:
            # Forward model using the 4x oversampled model shifted at subpixel scale and block-integrated to native pixels
            h_s = s_sz // 2
            c_sub = psf_core_4x.shape[0] // 2
            h_sub = h_s * 4

            # Crop or embed 4x core model to match star stamp FOV
            if c_sub >= h_sub:
                crop_4x = psf_core_4x[c_sub - h_sub : c_sub + h_sub + 1, c_sub - h_sub : c_sub + h_sub + 1].copy()
            else:
                crop_4x = np.zeros((2 * h_sub + 1, 2 * h_sub + 1), dtype=np.float32)
                crop_4x[h_sub - c_sub : h_sub + c_sub + 1, h_sub - c_sub : h_sub + c_sub + 1] = psf_core_4x

            # Fit optimal subpixel shift (dy, dx in native pixels, shifted by 4x in oversampled grid)
            def _sub_loss(coords):
                sy, sx = coords
                s_shifted = shift(crop_4x, [sy * 4.0, sx * 4.0], order=3, mode="constant", cval=0.0)
                s_native = downsample_oversampled_stamp(s_shifted, oversample=4)
                v = np.isfinite(s_flux) & (~s_mask) & (s_flux > 0)
                denom = float(np.sum(s_native[v]**2))
                if denom <= 1e-12:
                    return 1e12
                a = max(float(np.sum(s_flux[v] * s_native[v])) / denom, 0.0)
                return float(np.sum((s_flux[v] - a * s_native[v])**2))

            opt = minimize(_sub_loss, [0.0, 0.0], method="Powell", bounds=[(-1.5, 1.5), (-1.5, 1.5)], options={"maxiter": 20})
            best_dy, best_dx = float(opt.x[0]), float(opt.x[1])

            best_shifted_4x = shift(crop_4x, [best_dy * 4.0, best_dx * 4.0], order=3, mode="constant", cval=0.0)
            best_model_native = downsample_oversampled_stamp(best_shifted_4x, oversample=4)

            v_fit = np.isfinite(s_flux) & (~s_mask)
            denom = float(np.sum(best_model_native[v_fit]**2))
            alpha = float(np.sum(s_flux[v_fit] * best_model_native[v_fit])) / denom if denom > 1e-12 else 1.0

            obs = s_flux
            mod = alpha * best_model_native
            res = obs - mod
            dx, dy = best_dx, best_dy
            display_sz = s_sz
        else:
            # Bright star forward modeling using wide composite ePSF
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
            alpha = res_result.flux_scale
            dx, dy = res_result.subpixel_offset

            # Zoom central 251x251 for bright star
            if s_sz > 301:
                h_sub = 125
                c_s = s_sz // 2
                obs = obs[c_s - h_sub : c_s + h_sub + 1, c_s - h_sub : c_s + h_sub + 1]
                mod = mod[c_s - h_sub : c_s + h_sub + 1, c_s - h_sub : c_s + h_sub + 1]
                res = res[c_s - h_sub : c_s + h_sub + 1, c_s - h_sub : c_s + h_sub + 1]
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
        model_title_prefix = "4x Oversampled Model" if t in ["faint", "medium"] else "Forward-Modeled ePSF"
        ax2.set_title(f"{model_title_prefix} ($I_{{model}}$)\nScale $\\alpha={alpha:.2e}$, Shift=({dx:+.2f}, {dy:+.2f}) px",
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
        "(Representative Stars Across WFI Detectors | 4x Oversampled Subpixel Modeling on Faint & Medium)",
        color="#58a6ff", fontsize=14, fontweight="bold", y=0.98
    )

    p3_path = out_dir / "plot3_forward_modeling_subtraction.png"
    fig3.savefig(str(p3_path), dpi=300, bbox_inches="tight", facecolor=fig3.get_facecolor(), edgecolor="none")
    plt.close(fig3)
    print(f"Saved Plot 3 to {p3_path}")

    print("\nSUCCESS: All 3 plots successfully regenerated with 4x oversampling in output/plots/:")
    print(f"  1. {p1_path}")
    print(f"  2. {p2_path}")
    print(f"  3. {p3_path}")


if __name__ == "__main__":
    main()
