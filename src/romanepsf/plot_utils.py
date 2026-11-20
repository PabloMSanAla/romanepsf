"""
Plotting and Radial Profile Persistence Utilities for Roman ePSF Pipeline.

Provides:
1. compute_subpixel_composite_radial_profile:
   - High-fidelity radial profile extraction down to 0.1 pixels using 10x subpixel
     oversampling in the core (< 6 px) and logarithmic outer binning (6 - 500 px).
2. save_radial_profiles_data:
   - Persists all normalized individual star profiles and the composite profile
     into a compressed NPZ archive (~1-6 MB for 1k-10k stars).
3. generate_diagnostic_plots:
   - Automatically renders Plot 1 (1D radial profile comparison) and Plot 2 (2D full
     composite ePSF canvas with core zoom inset) at the conclusion of pipeline runs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.patches import Circle
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import numpy as np
from scipy.ndimage import map_coordinates
from romanepsf.profile import get_geometric_radial_bins

logger = logging.getLogger("romanepsf.plot_utils")


def compute_subpixel_composite_radial_profile(
    epsf_model: np.ndarray,
    sub_r_max: float = 6.0,
    oversample: int = 10,
    r_max_native: float = 500.0,
    growth_rate: float = 1.03,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute subpixel radial profile of composite ePSF model from 0.1 px to r_max_native px.
    Uses 10x subpixel interpolation for r in [0.10, sub_r_max] px and geometric radial bins beyond.
    """
    ny, nx = epsf_model.shape
    cy, cx = (ny - 1.0) / 2.0, (nx - 1.0) / 2.0

    # 1. Subpixel core evaluation (r from 0.10 to sub_r_max px) using bilinear interpolation (order=1)
    sub_sz = int(2 * sub_r_max * oversample + 1)
    u_ref = np.linspace(-sub_r_max, sub_r_max, sub_sz)
    uu_ref, vv_ref = np.meshgrid(u_ref, u_ref)
    r_sub_ref = np.hypot(uu_ref, vv_ref)

    x_samp = cx + uu_ref
    y_samp = cy + vv_ref
    epsf_sub = map_coordinates(epsf_model, [y_samp, x_samp], order=1, mode="constant", cval=0.0)

    r_core_bins = get_geometric_radial_bins(r_min=0.10, r_max=sub_r_max, growth_rate=growth_rate)
    r_core_centers = np.sqrt(r_core_bins[:-1] * r_core_bins[1:])
    f_core_prof = []
    for i in range(len(r_core_centers)):
        in_b = (r_sub_ref >= r_core_bins[i]) & (r_sub_ref < r_core_bins[i + 1])
        if np.any(in_b):
            vals = epsf_sub[in_b]
            f_core_prof.append(float(np.median(vals)))
        else:
            f_core_prof.append(np.nan)

    r_core = np.array(r_core_centers)
    f_core = np.array(f_core_prof)
    valid_c = np.isfinite(f_core) & (f_core > 0)
    r_core = r_core[valid_c]
    f_core = f_core[valid_c]

    # 2. Outer profile from sub_r_max px to r_max_native px
    gy, gx = np.ogrid[:ny, :nx]
    r_epsf = np.hypot(gx - cx, gy - cy)
    r_outer_bins = get_geometric_radial_bins(r_min=sub_r_max, r_max=r_max_native, growth_rate=growth_rate)
    r_outer_centers = np.sqrt(r_outer_bins[:-1] * r_outer_bins[1:])
    f_outer_prof = []
    for i in range(len(r_outer_centers)):
        in_b = (r_epsf >= r_outer_bins[i]) & (r_epsf < r_outer_bins[i + 1])
        if np.any(in_b):
            vals = epsf_model[in_b]
            f_outer_prof.append(float(np.median(vals)))
        else:
            f_outer_prof.append(np.nan)

    r_outer = np.array(r_outer_centers)
    f_outer = np.array(f_outer_prof)
    valid_o = np.isfinite(f_outer) & (f_outer > 0)
    r_outer = r_outer[valid_o]
    f_outer = f_outer[valid_o]

    r_ref = np.concatenate([r_core, r_outer])
    f_ref = np.concatenate([f_core, f_outer])
    return r_ref, f_ref


def extract_stamp_1d_radial_profile(
    stamp_data: np.ndarray,
    stamp_mask: Optional[np.ndarray] = None,
    oversample: int = 1,
    r_bins: Optional[np.ndarray] = None,
    growth_rate: float = 1.03,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Extract 1D radial profile from a 2D postage stamp array on valid unmasked pixels.
    Supports logarithmic/geometric binning growing at growth_rate (default 1.03x).
    Subpixel spline interpolation is performed for r < 3.0 px to capture continuous
    core surface brightness down to 0.10 px even on native 1x detector pixel stamps.
    """
    ny, nx = stamp_data.shape
    cy, cx = (ny - 1.0) / 2.0, (nx - 1.0) / 2.0
    valid = np.isfinite(stamp_data) & (stamp_data > 0)
    if stamp_mask is not None:
        valid &= (~stamp_mask)

    if not np.any(valid):
        return np.array([]), np.array([])

    ovs = max(1, int(oversample))

    # For stamps without hardware oversampling (ovs <= 1), evaluate subpixel core via spline interpolation
    if ovs <= 1:
        sub_r_max = min(3.5, float(min(nx, ny) - 1) / 2.0)
        sub_ovs = 10
        sub_sz = int(2 * sub_r_max * sub_ovs + 1)
        u_sub = np.linspace(-sub_r_max, sub_r_max, sub_sz)
        uu_sub, vv_sub = np.meshgrid(u_sub, u_sub)
        r_sub = np.hypot(uu_sub, vv_sub)

        clean_data = np.where(valid, stamp_data, 0.0)
        x_samp = cx + uu_sub
        y_samp = cy + vv_sub
        stamp_sub = map_coordinates(clean_data, [y_samp, x_samp], order=1, mode="constant", cval=0.0)

        if stamp_mask is not None:
            mask_sub = map_coordinates(stamp_mask.astype(float), [y_samp, x_samp], order=0, mode="constant", cval=1.0) > 0.5
        else:
            mask_sub = np.zeros_like(stamp_sub, dtype=bool)

        valid_sub = (stamp_sub > 0) & (~mask_sub)
        r_val_core = r_sub[valid_sub]
        f_val_core = stamp_sub[valid_sub]

        # Native pixel grid outside subpixel core (r >= sub_r_max)
        grid_y, grid_x = np.ogrid[:ny, :nx]
        r_native = np.hypot(grid_x - cx, grid_y - cy)
        outer_mask = valid & (r_native >= sub_r_max)
        r_val = np.concatenate([r_val_core, r_native[outer_mask]])
        f_val = np.concatenate([f_val_core, stamp_data[outer_mask]])
    else:
        grid_y, grid_x = np.ogrid[:ny, :nx]
        r_px = np.hypot(grid_x - cx, grid_y - cy)
        r_native = r_px / float(ovs)
        r_val = r_native[valid]
        f_val = stamp_data[valid]

    if r_bins is None:
        max_r = min(float(nx) / (2.0 * ovs), 500.0)
        r_bins = get_geometric_radial_bins(r_min=0.10, r_max=max(max_r, 1.0), growth_rate=growth_rate)

    r_centers = np.sqrt(r_bins[:-1] * r_bins[1:])
    f_prof = []
    r_out = []

    # Bin indices
    bin_idx = np.digitize(r_val, r_bins) - 1
    for i in range(len(r_centers)):
        match = bin_idx == i
        if np.any(match):
            med = float(np.median(f_val[match]))
            if np.isfinite(med) and med > 0:
                r_out.append(r_centers[i])
                f_prof.append(med)

    return np.array(r_out, dtype=np.float32), np.array(f_prof, dtype=np.float32)


def save_radial_profiles_data(
    output_npz_path: Union[str, Path],
    composite_epsf: np.ndarray,
    pooled_stamps: Dict[str, List[Any]],
    diagnostics: Optional[Dict[str, Any]] = None,
    pixel_scale: float = 0.11,
    growth_rate: float = 1.03,
) -> Path:
    """
    Extract, normalize, and save all individual star profiles and the master composite
    curve into a compressed NPZ file (~1-6 MB) using geometric radial bins.
    """
    output_npz = Path(output_npz_path)
    output_npz.parent.mkdir(parents=True, exist_ok=True)
    diag = diagnostics or {}

    # 1. Master composite curve (down to 0.1 px)
    r_comp, f_comp = compute_subpixel_composite_radial_profile(composite_epsf, growth_rate=growth_rate)

    # 2. Standard evaluation grid with geometric spacing
    r_grid = get_geometric_radial_bins(r_min=0.10, r_max=500.0, growth_rate=growth_rate).astype(np.float32)

    # Normalization overlap ranges
    norm_ranges = {
        "faint": (3.0, 12.0),
        "medium": (8.0, 25.0),
        "bright": (25.0, 60.0),
    }

    star_fluxes_list: List[np.ndarray] = []
    star_tiers_list: List[str] = []
    star_ids_list: List[str] = []

    for tier in ["bright", "medium", "faint"]:
        stamps = pooled_stamps.get(tier, [])
        fit_r_min, fit_r_max = norm_ranges.get(tier, (5.0, 20.0))

        for s in stamps:
            # Handle StellarStamp object or dictionary
            s_data = getattr(s, "data", None) if hasattr(s, "data") else s.get("data")
            s_mask = getattr(s, "mask", None) if hasattr(s, "mask") else s.get("mask")
            s_id = getattr(s, "source_id", "0") if hasattr(s, "source_id") else s.get("source_id", "0")
            s_ovs = getattr(s, "oversample", 1) if hasattr(s, "oversample") else s.get("oversample", 1)

            if s_data is None:
                continue

            r_s, f_s = extract_stamp_1d_radial_profile(s_data, s_mask, oversample=s_ovs, growth_rate=growth_rate)
            if len(r_s) < 3 or not np.any(f_s > 0):
                continue

            # Align/normalize to reference composite profile
            comp_vals = np.interp(r_s, r_comp, f_comp)
            in_range = (r_s >= fit_r_min) & (r_s <= fit_r_max) & np.isfinite(f_s) & (f_s > 0)
            if np.sum(in_range) >= 2:
                scale_ratio = np.median(comp_vals[in_range] / f_s[in_range])
            else:
                valid_all = np.isfinite(f_s) & (f_s > 0)
                scale_ratio = np.median(comp_vals[valid_all] / f_s[valid_all]) if np.any(valid_all) else 1.0

            f_s_norm = f_s * float(scale_ratio)

            # Map onto standard evaluation grid
            prof_grid = np.full_like(r_grid, np.nan, dtype=np.float32)
            cover = (r_grid >= np.min(r_s)) & (r_grid <= np.max(r_s))
            if np.any(cover):
                prof_grid[cover] = np.interp(r_grid[cover], r_s, f_s_norm)

            star_fluxes_list.append(prof_grid)
            star_tiers_list.append(tier)
            star_ids_list.append(str(s_id))

    star_fluxes_arr = (
        np.array(star_fluxes_list, dtype=np.float32)
        if star_fluxes_list
        else np.zeros((0, len(r_grid)), dtype=np.float32)
    )
    star_tiers_arr = np.array(star_tiers_list, dtype=object)
    star_ids_arr = np.array(star_ids_list, dtype=object)

    np.savez_compressed(
        output_npz,
        r_composite=r_comp.astype(np.float32),
        f_composite=f_comp.astype(np.float32),
        r_grid=r_grid,
        star_fluxes=star_fluxes_arr,
        star_tiers=star_tiers_arr,
        star_ids=star_ids_arr,
        k_fm=float(diag.get("k_fm", -1.0) or -1.0),
        k_mb=float(diag.get("k_mb", -1.0) or -1.0),
        blend_fm_start=float(diag.get("blend_fm_start", 10.0) or 10.0),
        blend_fm_end=float(diag.get("blend_fm_end", 18.0) or 18.0),
        blend_mb_start=float(diag.get("blend_mb_start", 30.0) or 30.0),
        blend_mb_end=float(diag.get("blend_mb_end", 48.0) or 48.0),
        pixel_scale=float(pixel_scale),
    )
    logger.info(
        f"Saved {len(star_fluxes_list)} normalized stellar radial profiles to: {output_npz} "
        f"({output_npz.stat().st_size / (1024*1024):.2f} MB)"
    )
    return output_npz


def generate_diagnostic_plots(
    profiles_data_or_path: Union[str, Path, Dict[str, Any]],
    composite_epsf: np.ndarray,
    output_dir: Union[str, Path],
    sca_name: str = "WFI01",
    pixel_scale: float = 0.11,
    dpi: int = 300,
) -> Dict[str, Path]:
    """
    Generate and save Plot 1 (Radial Profile Comparison) and Plot 2 (2D Composite ePSF Canvas).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from romanepsf.config import normalize_sca_id
    sca_str = normalize_sca_id(sca_name)

    # 1. Load profiles data
    if isinstance(profiles_data_or_path, (str, Path)):
        npz = np.load(str(profiles_data_or_path), allow_pickle=True)
        r_composite = npz["r_composite"]
        f_composite = npz["f_composite"]
        r_grid = npz["r_grid"]
        star_fluxes = npz["star_fluxes"]
        star_tiers = npz["star_tiers"]
        star_ids = npz["star_ids"]
        k_fm = float(npz.get("k_fm", -1.0))
        k_mb = float(npz.get("k_mb", -1.0))
        blend_fm_start = float(npz.get("blend_fm_start", 10.0))
        blend_fm_end = float(npz.get("blend_fm_end", 18.0))
        blend_mb_start = float(npz.get("blend_mb_start", 30.0))
        blend_mb_end = float(npz.get("blend_mb_end", 48.0))
    else:
        d = profiles_data_or_path
        r_composite = d["r_composite"]
        f_composite = d["f_composite"]
        r_grid = d["r_grid"]
        star_fluxes = d["star_fluxes"]
        star_tiers = d["star_tiers"]
        star_ids = d.get("star_ids", np.arange(len(star_tiers)))
        k_fm = float(d.get("k_fm", -1.0))
        k_mb = float(d.get("k_mb", -1.0))
        blend_fm_start = float(d.get("blend_fm_start", 10.0))
        blend_fm_end = float(d.get("blend_fm_end", 18.0))
        blend_mb_start = float(d.get("blend_mb_start", 30.0))
        blend_mb_end = float(d.get("blend_mb_end", 48.0))

    n_stars_total = len(star_tiers)
    n_faint = int(np.sum(star_tiers == "faint"))
    n_med = int(np.sum(star_tiers == "medium"))
    n_bright = int(np.sum(star_tiers == "bright"))

    # ==============================================================================
    # PLOT 1: Resulting 1D Radial Profile with Individual Profiles in Background
    # ==============================================================================
    fig1, ax1 = plt.subplots(figsize=(11, 7.5), dpi=dpi)
    fig1.patch.set_facecolor("#0e1117")
    ax1.set_facecolor("#161b22")

    tier_colors = {
        "faint": ("#4caf50", 0.18, 0.85),
        "medium": ("#2196f3", 0.22, 0.85),
        "bright": ("#ff9800", 0.35, 1.0),
    }

    # Plot normalized profiles directly spanning [10^-11, 10^-2]
    f_comp_plot = f_composite

    # Plot individual normalized star profiles in background
    for i in range(n_stars_total):
        t = str(star_tiers[i])
        col, alpha_val, lw = tier_colors.get(t, ("#888888", 0.15, 0.8))
        f_vals = star_fluxes[i]
        valid = np.isfinite(f_vals) & (f_vals > 0)
        if np.any(valid):
            ax1.plot(r_grid[valid], f_vals[valid], color=col, alpha=alpha_val, linewidth=lw)

    # Legend proxy handles
    ax1.plot([], [], color="#4caf50", alpha=0.75, linewidth=1.4, label=f"Faint Stars ({n_faint} stars)")
    ax1.plot([], [], color="#2196f3", alpha=0.75, linewidth=1.4, label=f"Medium Stars ({n_med} stars)")
    ax1.plot([], [], color="#ff9800", alpha=0.85, linewidth=1.4, label=f"Bright Stars ({n_bright} stars)")

    # Transition blending zones
    fm_sec_start = blend_fm_start * pixel_scale
    fm_sec_end = blend_fm_end * pixel_scale
    mb_sec_start = blend_mb_start * pixel_scale
    mb_sec_end = blend_mb_end * pixel_scale
    ax1.axvspan(
        blend_fm_start,
        blend_fm_end,
        color="#00e5ff",
        alpha=0.12,
        label=f"Faint-Medium Blend (${blend_fm_start:.0f}-{blend_fm_end:.0f}$ px / ${fm_sec_start:.1f}-{fm_sec_end:.1f}''$)",
    )
    ax1.axvspan(
        blend_mb_start,
        blend_mb_end,
        color="#ffd600",
        alpha=0.12,
        label=f"Medium-Bright Blend (${blend_mb_start:.0f}-{blend_mb_end:.0f}$ px / ${mb_sec_start:.1f}-{mb_sec_end:.1f}''$)",
    )

    # Foreground: Final Composite ePSF profile
    ax1.plot(r_composite, f_comp_plot, color="#ffffff", linewidth=3.0, label="Final Composite ePSF (Multi-Tier Blend)")
    ax1.plot(r_composite, f_comp_plot, color="#00e5ff", linewidth=1.6, linestyle="--")

    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlim(0.1, 520.0)
    ax1.set_ylim(1e-11, 1.0)

    ax1.set_xlabel("Radius from Centroid (pixels, 0.11\"/px)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1.set_ylabel("Normalized Surface Brightness (pixel$^{-1}$)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1.tick_params(colors="#8b949e", labelsize=10.5, which="both")
    ax1.grid(True, which="both", color="#30363d", alpha=0.4, linestyle=":")

    ax1_top = ax1.twiny()
    ax1_top.set_xscale("log")
    ax1_top.set_xlim(0.1 * pixel_scale, 520.0 * pixel_scale)
    ax1_top.set_xlabel("Radius from Centroid (arcseconds)", color="#e6edf3", fontsize=12, labelpad=8)
    ax1_top.tick_params(colors="#8b949e", labelsize=10.5, which="both")

    ax1.set_title(
        f"Roman Space Telescope Extended PSF: Multi-Tier Radial Profile ({sca_name.upper()})\n"
        f"(Subpixel Oversampled Composite Model down to 0.1 px vs. {n_stars_total} Contributing Stars)",
        color="#58a6ff", fontsize=13, fontweight="bold", pad=16,
    )

    leg = ax1.legend(loc="upper right", frameon=True, facecolor="#161b22", edgecolor="#30363d", fontsize=9.2)
    for text in leg.get_texts():
        text.set_color("#e6edf3")

    plot1_path = out_dir / f"plot1_{sca_str}_psf_radial_profiles.png"
    fig1.savefig(str(plot1_path), dpi=dpi, bbox_inches="tight", facecolor=fig1.get_facecolor(), edgecolor="none")
    plot1_canon = out_dir / "plot1_psf_radial_profiles.png"
    if plot1_canon != plot1_path:
        import shutil
        shutil.copyfile(plot1_path, plot1_canon)
    plt.close(fig1)
    logger.info(f"Generated Plot 1: {plot1_path}")

    # ==============================================================================
    # PLOT 2: The Entire 2D Composite Extended PSF Canvas
    # ==============================================================================
    fig2, ax2 = plt.subplots(figsize=(10, 10), dpi=dpi)
    fig2.patch.set_facecolor("#0e1117")
    ax2.set_facecolor("#161b22")

    canvas_size = composite_epsf.shape[0]
    half_canvas = (canvas_size - 1.0) / 2.0
    extent_arcsec = [
        -half_canvas * pixel_scale, half_canvas * pixel_scale,
        -half_canvas * pixel_scale, half_canvas * pixel_scale,
    ]

    vmin_2d = 1e-11
    vmax_2d = 1e-2
    norm_2d = LogNorm(vmin=vmin_2d, vmax=vmax_2d)

    scaled_epsf = composite_epsf

    im2 = ax2.imshow(
        np.maximum(scaled_epsf, vmin_2d),
        origin="lower",
        cmap="inferno",
        norm=norm_2d,
        extent=extent_arcsec,
    )

    # Highlight annular blending circles
    circle_fm1 = Circle((0, 0), blend_fm_start * pixel_scale, fill=False, edgecolor="#00e5ff", linestyle="--", linewidth=1.0, alpha=0.7)
    circle_fm2 = Circle((0, 0), blend_fm_end * pixel_scale, fill=False, edgecolor="#00e5ff", linestyle="-", linewidth=1.0, alpha=0.7)
    circle_mb1 = Circle((0, 0), blend_mb_start * pixel_scale, fill=False, edgecolor="#ffd600", linestyle="--", linewidth=1.0, alpha=0.7)
    circle_mb2 = Circle((0, 0), blend_mb_end * pixel_scale, fill=False, edgecolor="#ffd600", linestyle="-", linewidth=1.0, alpha=0.7)
    ax2.add_patch(circle_fm1)
    ax2.add_patch(circle_fm2)
    ax2.add_patch(circle_mb1)
    ax2.add_patch(circle_mb2)

    ax2.set_xlabel("Relative RA / Horizontal Offset (arcsec)", color="#e6edf3", fontsize=11, labelpad=6)
    ax2.set_ylabel("Relative Dec / Vertical Offset (arcsec)", color="#e6edf3", fontsize=11, labelpad=6)
    ax2.tick_params(colors="#8b949e", labelsize=9.5)
    ax2.set_title(
        f"Roman Space Telescope Synthesized 2D Extended PSF ({canvas_size}x{canvas_size} px, {canvas_size*pixel_scale:.1f}\"x{canvas_size*pixel_scale:.1f}\")\n"
        f"Composite Model for {sca_name.upper()} | Filter F146",
        color="#58a6ff", fontsize=12, fontweight="bold", pad=10,
    )

    cb2 = plt.colorbar(im2, ax=ax2, fraction=0.046, pad=0.03)
    cb2.ax.tick_params(colors="#8b949e", labelsize=8.5)
    cb2.set_label("Normalized Surface Brightness / pixel (Sum = 1.0)", color="#e6edf3", fontsize=10)

    # Central Core Inset Zoom (45x45 native pixels = 5.0"x5.0")
    ax_inset = inset_axes(ax2, width="28%", height="28%", loc="upper right", borderpad=1.2)
    ax_inset.set_facecolor("#161b22")
    core_rad_inset = min(22, canvas_size // 4)
    c_mid = canvas_size // 2
    core_cutout = scaled_epsf[
        c_mid - core_rad_inset : c_mid + core_rad_inset + 1,
        c_mid - core_rad_inset : c_mid + core_rad_inset + 1,
    ]
    extent_inset = [
        -core_rad_inset * pixel_scale, core_rad_inset * pixel_scale,
        -core_rad_inset * pixel_scale, core_rad_inset * pixel_scale,
    ]
    ax_inset.imshow(
        np.maximum(core_cutout, vmin_2d),
        origin="lower",
        cmap="inferno",
        norm=LogNorm(vmin=vmin_2d, vmax=vmax_2d),
        extent=extent_inset,
    )
    ax_inset.set_title(f"Core Zoom ({2*core_rad_inset+1}x{2*core_rad_inset+1} px)", color="#e6edf3", fontsize=8.5, fontweight="bold", pad=3)
    ax_inset.tick_params(colors="#8b949e", labelsize=7)
    for spine in ax_inset.spines.values():
        spine.set_edgecolor("#58a6ff")
        spine.set_linewidth(1.5)

    info_text = (
        f"Canvas: {canvas_size} x {canvas_size} px\n"
        f"Field of View: {canvas_size*pixel_scale:.1f}\" x {canvas_size*pixel_scale:.1f}\"\n"
        f"Detector: {sca_name.upper()}\n"
        f"Filter: F146 ({pixel_scale:.2f}\"/px)\n"
        f"Total Stars: {n_stars_total} [B:{n_bright}, M:{n_med}, F:{n_faint}]\n"
        f"Dynamic Range: > 10$^6$\n"
        f"Annular Blends: [{blend_fm_start:.0f}, {blend_fm_end:.0f}] & [{blend_mb_start:.0f}, {blend_mb_end:.0f}] px"
    )
    ax2.text(
        0.03, 0.04, info_text, transform=ax2.transAxes, color="#e6edf3", fontsize=8.5,
        verticalalignment="bottom",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#161b22", edgecolor="#30363d", alpha=0.9),
    )

    plot2_path = out_dir / f"plot2_{sca_str}_entire_composite_psf.png"
    fig2.savefig(str(plot2_path), dpi=dpi, bbox_inches="tight", facecolor=fig2.get_facecolor(), edgecolor="none")
    plot2_canon = out_dir / "plot2_entire_composite_psf.png"
    if plot2_canon != plot2_path:
        import shutil
        shutil.copyfile(plot2_path, plot2_canon)
    plt.close(fig2)
    logger.info(f"Generated Plot 2: {plot2_path}")

    return {
        "plot1": plot1_path,
        "plot2": plot2_path,
    }
