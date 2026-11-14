"""
Publication-Quality Visualization Script for Roman Space Telescope ePSF Pipeline:
Plot 1: 1D Radial Profile of Resulting Composite ePSF Constructed via Ensemble Median,
        with all contributing individual star profiles in background (quality-filtered & normalized)
Plot 2: Full 2D Composite Extended PSF Model Canvas (1025x1025, 113"x113" FOV) with Core Zoom Inset
Plot 3: Forward Modeling Subtraction for 1 Bright, 1 Medium, and 1 Faint Star
        (Native resolution forward modeling, identical scale across all 4 panels)
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
from scipy.ndimage import map_coordinates

from romanepsf.loader import load_l2_image
from romanepsf.stamps import (
    extract_cutout,
    estimate_stamp_background,
    subtract_stamp_background,
    recenter_and_align_stamp,
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
    bin_width_native: float = 0.1,
    growth_rate: float = 1.03,
) -> tuple:
    """Compute 1D azimuthal radial profile from 2D stamp array on valid unmasked pixels with geometric log spacing."""
    ny, nx = stamp_data.shape
    cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
    grid_y, grid_x = np.ogrid[:ny, :nx]
    r_px = np.hypot(grid_x - cx, grid_y - cy)
    r_native = r_px / oversample

    valid = np.isfinite(stamp_data) & (stamp_data > 0)
    if mask is not None:
        valid &= (~mask)

    if not np.any(valid):
        return np.array([]), np.array([])

    r_valid = r_native[valid]
    f_valid = stamp_data[valid]

    # Subpixel geometric radial binning starting at 0.1 px
    max_r = min(r_max_native, float(np.max(r_valid)))
    if max_r <= 0.15:
        return np.array([]), np.array([])

    from romanepsf.profile import get_geometric_radial_bins
    bin_edges = get_geometric_radial_bins(r_min=0.10, r_max=max_r, growth_rate=growth_rate)
    bin_centers = np.sqrt(bin_edges[:-1] * bin_edges[1:])
    bin_idx = np.digitize(r_valid, bin_edges) - 1

    r_prof = []
    f_prof = []
    for b in range(len(bin_centers)):
        in_bin = bin_idx == b
        if np.sum(in_bin) >= 1:
            r_prof.append(float(bin_centers[b]))
            f_prof.append(float(np.median(f_valid[in_bin])))

    return np.array(r_prof), np.array(f_prof)


def main():
    print("=== Generating Roman ePSF Pipeline Visualizations (Subpixel Oversampling down to 0.1 px) ===")
    out_dir = Path("output/plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config("configs/default.yaml")

    # 1. Load Composite Extended PSF FITS
    fits_path = Path("output/run_all/roman_epsf_composite.fits")
    if not fits_path.exists():
        fits_path = Path("output/roman_epsf_composite.fits")
    if not fits_path.exists():
        fits_matches = list(Path("output").glob("roman_epsf_*_composite.fits"))
        if fits_matches:
            fits_path = fits_matches[0]
    if not fits_path.exists():
        raise FileNotFoundError(f"Cannot find composite ePSF FITS in output/")

    # Check for pre-computed radial profiles archive (.npz) for fast instantaneous rendering
    npz_candidates = [
        Path("output/roman_epsf_radial_profiles.npz"),
        Path(f"output/{fits_path.stem.replace('_composite', '')}_radial_profiles.npz"),
        Path(f"output/roman_epsf_{fits_path.name.split('_')[2] if len(fits_path.name.split('_')) > 2 else 'wfi01'}_radial_profiles.npz"),
    ]
    cached_npz = next((p for p in npz_candidates if p.is_file()), None)

    if cached_npz is not None:
        print(f"Discovered precomputed radial profiles cache: {cached_npz}!")
        print("Rendering Plot 1 and Plot 2 instantaneously from cached profiles...")
        from romanepsf.plot_utils import generate_diagnostic_plots
        with fits.open(fits_path) as hdul:
            epsf_model = hdul[0].data.astype(np.float32)
            header = hdul[0].header
        pix_s = float(header.get("PIXSCALE", 0.11))
        det_name = str(header.get("DETECTOR", "WFI01"))
        plots_dict = generate_diagnostic_plots(
            profiles_data_or_path=cached_npz,
            composite_epsf=epsf_model,
            output_dir=out_dir,
            sca_name=det_name,
            pixel_scale=pix_s,
        )
        print(f"Generated Plot 1: {plots_dict['plot1']}")
        print(f"Generated Plot 2: {plots_dict['plot2']}")
        print("Done rendering Plots 1 & 2 from cache.")
        return

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

    # Subpixel radial profile of composite ePSF model from 0.1 px to 500 px
    ny_e, nx_e = epsf_model.shape
    cy_e, cx_e = (ny_e - 1) / 2.0, (nx_e - 1) / 2.0

    # 1. Subpixel core evaluation (r from 0.10 to 6.0 px with 10x oversampling)
    sub_r_max = 6.0
    O_ref = 10
    sub_sz = int(2 * sub_r_max * O_ref + 1)
    u_ref = np.linspace(-sub_r_max, sub_r_max, sub_sz)
    uu_ref, vv_ref = np.meshgrid(u_ref, u_ref)
    r_sub_ref = np.hypot(uu_ref, vv_ref)

    x_samp = cx_e + uu_ref
    y_samp = cy_e + vv_ref
    epsf_sub = map_coordinates(epsf_model, [y_samp, x_samp], order=3, mode="constant", cval=0.0)

    r_core_bins = np.logspace(np.log10(0.10), np.log10(sub_r_max), 60)
    r_core_centers = 0.5 * (r_core_bins[:-1] + r_core_bins[1:])
    f_core_prof = []
    for i in range(len(r_core_centers)):
        in_b = (r_sub_ref >= r_core_bins[i]) & (r_sub_ref < r_core_bins[i + 1])
        f_core_prof.append(float(np.median(epsf_sub[in_b])) if np.any(in_b) else np.nan)

    r_core = np.array(r_core_centers)
    f_core = np.array(f_core_prof)
    valid_c = np.isfinite(f_core) & (f_core > 0)
    r_core = r_core[valid_c]
    f_core = f_core[valid_c]

    # 2. Outer profile from 6.0 px to 500 px
    gy_e, gx_e = np.ogrid[:ny_e, :nx_e]
    r_epsf = np.hypot(gx_e - cx_e, gy_e - cy_e)
    r_outer_bins = np.logspace(np.log10(sub_r_max), np.log10(500.0), 160)
    r_outer_centers = 0.5 * (r_outer_bins[:-1] + r_outer_bins[1:])
    f_outer_prof = []
    for i in range(len(r_outer_centers)):
        in_b = (r_epsf >= r_outer_bins[i]) & (r_epsf < r_outer_bins[i + 1])
        f_outer_prof.append(float(np.median(epsf_model[in_b])) if np.any(in_b) else np.nan)

    r_outer = np.array(r_outer_centers)
    f_outer = np.array(f_outer_prof)
    valid_o = np.isfinite(f_outer) & (f_outer > 0)
    r_outer = r_outer[valid_o]
    f_outer = f_outer[valid_o]

    r_ref = np.concatenate([r_core, r_outer])
    f_ref = np.concatenate([f_core, f_outer])

    # 2. Load Star Catalog and Apply Quality Filtering
    tiered_csv = Path("output/run_all/all_stars_tiered.csv")
    if not tiered_csv.exists():
        tiered_csv = Path("output/all_stars_tiered.csv")
    stars_raw_df = pd.read_csv(tiered_csv)
    print(f"Loaded {len(stars_raw_df)} stars from catalog.")

    # Quality filter: reject edge stars, dead pixels, non-detections, and bad centroids
    edge = (
        (stars_raw_df["x"] >= 64.0) & (stars_raw_df["x"] <= 4024.0) &
        (stars_raw_df["y"] >= 64.0) & (stars_raw_df["y"] <= 4024.0) &
        pd.notna(stars_raw_df["mag_lambda"])
    )
    q_faint = (
        (stars_raw_df["tier"].str.lower() == "faint") &
        (stars_raw_df["peak_flux"] > 80.0) &
        (stars_raw_df["centroid_shift_px"] < 1.5) & edge
    )
    q_med = (
        (stars_raw_df["tier"].str.lower() == "medium") &
        (stars_raw_df["peak_flux"] > 80.0) &
        (stars_raw_df["centroid_shift_px"] < 2.0) & edge
    )
    q_bright = (
        (stars_raw_df["tier"].str.lower() == "bright") &
        (stars_raw_df["peak_flux"] > 80.0) &
        (stars_raw_df["centroid_shift_px"] < 2.5) & edge
    )
    stars_df = stars_raw_df[q_faint | q_med | q_bright].copy()
    print(f"Retained {len(stars_df)} quality-verified stars across detectors:")
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

    # Extract cutouts, mask invalid/saturated pixels, and measure 1D radial profiles
    print("\nExtracting cutouts, applying DQ masking, and measuring individual 1D profiles...")
    star_profiles = {"bright": [], "medium": [], "faint": []}
    all_normalized_curves = []
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

        # STRICT QUALITY & SATURATION MASKING:
        # Mask NaNs, non-finite values, and DQ bit 0 (DO_NOT_USE) or bit 1 (SATURATED)
        bad_mask = (~np.isfinite(raw_cutout)) | ((raw_dq & 1) > 0) | ((raw_dq & 2) > 0)

        bkg_val, bkg_rms = estimate_stamp_background(raw_cutout, mask=bad_mask, method="annulus")
        flux_sub = subtract_stamp_background(raw_cutout, bkg_val)

        sub_dx = cx - ix
        sub_dy = cy - iy

        O_tier = 10 if tier == "faint" else (4 if tier == "medium" else 1)
        bin_w = 0.1 if tier in ["faint", "medium"] else 0.5

        # Subpixel alignment with oversampling preserving true bad pixel masks
        aligned_flux, aligned_mask = recenter_and_align_stamp(flux_sub, bad_mask, (sub_dx, sub_dy), oversample=O_tier)

        # Measure 1D radial profile strictly on valid, unmasked pixels down to 0.1 px
        r_star, f_star = compute_fast_radial_profile(
            aligned_flux, mask=aligned_mask, r_max_native=min(sz // 2, 500), oversample=O_tier, bin_width_native=bin_w
        )

        if len(r_star) >= 4 and np.any(f_star > 0):
            # Normalization scale factor Ai matching star profile to reference ePSF curve
            comp_vals = np.interp(r_star, r_ref, f_ref)
            fit_range = {"faint": (3.0, 12.0), "medium": (8.0, 25.0), "bright": (25.0, 60.0)}[tier]
            valid_fit = (r_star >= fit_range[0]) & (r_star <= fit_range[1]) & (f_star > 0) & (comp_vals > 0)

            if np.sum(valid_fit) >= 3:
                scale_factor = float(np.median(f_star[valid_fit] / comp_vals[valid_fit]))
            else:
                scale_factor = float(np.median(f_star / comp_vals)) if np.any(comp_vals > 0) else 1.0

            if scale_factor > 0 and np.isfinite(scale_factor):
                f_norm = f_star / scale_factor

                # Filter valid radial range per tier (bright starts at 10 px outside saturation)
                if tier == "faint":
                    valid_plot = (r_star >= np.min(r_star)) & (r_star <= 24.0) & (f_norm > 0)
                elif tier == "medium":
                    valid_plot = (r_star >= np.min(r_star)) & (r_star <= 80.0) & (f_norm > 0)
                else:  # bright
                    valid_plot = (r_star >= 10.0) & (r_star <= 450.0) & (f_norm > 0)

                if np.any(valid_plot):
                    r_p = r_star[valid_plot]
                    f_p = f_norm[valid_plot]
                    star_profiles[tier].append((r_p, f_p))
                    all_normalized_curves.append((r_p, f_p))

        # Pick one representative star per tier for Plot 3 (evaluated at native resolution)
        if tier not in sample_stars_for_plot3:
            if O_tier == 1:
                nat_flux, nat_mask = aligned_flux, aligned_mask
            else:
                nat_flux, nat_mask = recenter_and_align_stamp(flux_sub, bad_mask, (sub_dx, sub_dy), oversample=1)
            if tier == "bright" and (sz >= 201 or "WFI05" in det or idx == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": nat_flux, "mask": nat_mask,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms,
                }
            elif tier == "medium" and ("WFI02" in det or len(sample_stars_for_plot3.get("medium", {})) == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": nat_flux, "mask": nat_mask,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms,
                }
            elif tier == "faint" and ("WFI10" in det or len(sample_stars_for_plot3.get("faint", {})) == 0):
                sample_stars_for_plot3[tier] = {
                    "row": row, "flux": nat_flux, "mask": nat_mask,
                    "cx": cx, "cy": cy, "det": det, "mag": mag, "sz": sz, "bkg_rms": bkg_rms,
                }

    print(f"Profile counts: Bright={len(star_profiles['bright'])}, Medium={len(star_profiles['medium'])}, Faint={len(star_profiles['faint'])}")

    # ==============================================================================
    # COMPOSITE PROFILE FROM SYNTHESIZED MODEL & MULTI-TIER ENSEMBLE
    # ==============================================================================
    print("Preparing master composite profile from pipeline synthesis...")
    r_composite_master = r_ref
    f_composite_master = f_ref

    # ==============================================================================
    # PLOT 1: Resulting 1D Radial Profile with Individual Profiles in Background
    # ==============================================================================
    print("\nRendering Plot 1: 1D Radial Profile Comparison (Composite ePSF vs Individual Stars)...")
    fig1, ax1 = plt.subplots(figsize=(11, 7.5), dpi=300)
    fig1.patch.set_facecolor("#0e1117")
    ax1.set_facecolor("#161b22")

    # Background: Individual profiles from all stars with low alpha (already normalized to composite)
    # Faint tier
    for r_s, f_s in star_profiles["faint"]:
        ax1.plot(r_s, f_s, color="#4caf50", alpha=0.18, linewidth=0.85)
    # Medium tier
    for r_s, f_s in star_profiles["medium"]:
        ax1.plot(r_s, f_s, color="#2196f3", alpha=0.22, linewidth=0.85)
    # Bright tier
    for r_s, f_s in star_profiles["bright"]:
        ax1.plot(r_s, f_s, color="#ff9800", alpha=0.35, linewidth=1.0)

    # Dummy lines for legend for background individual stars
    ax1.plot([], [], color="#4caf50", alpha=0.7, linewidth=1.4, label=f"Faint Stars ({len(star_profiles['faint'])} stars, r < 24 px)")
    ax1.plot([], [], color="#2196f3", alpha=0.7, linewidth=1.4, label=f"Medium Stars ({len(star_profiles['medium'])} stars, r < 80 px)")
    ax1.plot([], [], color="#ff9800", alpha=0.8, linewidth=1.4, label=f"Bright Stars ({len(star_profiles['bright'])} stars, r ≥ 10 px)")

    # Transition blending zones (shaded bands)
    ax1.axvspan(10.0, 18.0, color="#00e5ff", alpha=0.12, label="Faint-Medium Blend ($10-18$ px / $1.1-2.0''$)")
    ax1.axvspan(30.0, 48.0, color="#ffd600", alpha=0.12, label="Medium-Bright Blend ($30-48$ px / $3.3-5.3''$)")

    # Foreground: Final Composite ePSF profile
    ax1.plot(r_composite_master, f_composite_master, color="#ffffff", linewidth=3.0, label="Final Composite ePSF (Multi-Tier Blend)")
    ax1.plot(r_composite_master, f_composite_master, color="#00e5ff", linewidth=1.6, linestyle="--")

    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlim(0.1, 520.0)
    ax1.set_ylim(1e-9, 1e-1)

    ax1.set_xlabel("Radius from Centroid (pixels, 0.11\"/px)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1.set_ylabel("Normalized Surface Brightness (pixel$^{-1}$)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1.tick_params(colors="#8b949e", labelsize=10.5, which="both")
    ax1.grid(True, which="both", color="#30363d", alpha=0.4, linestyle=":")

    # Top twin axis for radius in arcseconds
    ax1_top = ax1.twiny()
    ax1_top.set_xscale("log")
    ax1_top.set_xlim(0.1 * pixel_scale, 520.0 * pixel_scale)
    ax1_top.set_xlabel("Radius from Centroid (arcseconds)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1_top.tick_params(colors="#8b949e", labelsize=10.5, which="both")

    ax1.set_title(
        "Roman Space Telescope Extended PSF: Multi-Tier Radial Profile Synthesis\n"
        f"(Subpixel Oversampled Composite Model down to 0.1 px vs. {len(stars_df)} Quality-Verified Stars)",
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

    # Inset zoom of central core (45x45 native pixels = 5.0"x5.0")
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
    # Note: "dont oversample when doing the substraction for now. preserve the same scale for all 4 plots"
    print("\nRendering Plot 3: Forward Modeling & Subtraction on 1 Bright, 1 Medium, 1 Faint Star (Native Resolution)...")
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

        # Forward model the star directly using fit_star_to_model (native resolution)
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

        # For bright star with huge 1001x1001 stamp, zoom to central 251x251 for clear visual comparison
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
        "(Representative Stars Across WFI Detectors | Native Resolution Forward Modeling)",
        color="#58a6ff", fontsize=14, fontweight="bold", y=0.98
    )

    p3_path = out_dir / "plot3_forward_modeling_subtraction.png"
    fig3.savefig(str(p3_path), dpi=300, bbox_inches="tight", facecolor=fig3.get_facecolor(), edgecolor="none")
    plt.close(fig3)
    print(f"Saved Plot 3 to {p3_path}")

    print("\nSUCCESS: All 3 plots successfully regenerated in output/plots/:")
    print(f"  1. {p1_path}")
    print(f"  2. {p2_path}")
    print(f"  3. {p3_path}")


if __name__ == "__main__":
    main()
