#!/usr/bin/env python3
"""
Debug Diagnostics and Photometric Visualizations for Roman ePSF Pipeline.
-------------------------------------------------------------------------
Implements high-fidelity debug figures when running with --debug X:
1. Figure 1: Masking procedure 4 panels (image, radial model, residual, image+mask)
   all plotted with the same scale in AB mag/arcsec^2 using the photometric conversion.
2. Figure 2: 2 panels showing masked image with overlaid geometric profile apertures
   and the measured radial profile in AB mag/arcsec^2.
3. Figure 3: Profile normalization showing unnormalized vs normalized profile
   and the shaded overlap normalization region relative to the mean profile.
4. Figure 4: Model PSF 2D canvas with core zoom inset (scaled 10^-2 to 10^11).
5. Figure 5: Final composite radial profile with all normalized star profiles (scaled 10^-2 to 10^11).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize
from matplotlib.patches import Circle, Patch
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import numpy as np

logger = logging.getLogger("romanepsf.debug_plots")


def convert_to_ab_mag_arcsec2(
    flux_arr: np.ndarray,
    conversion_factor: float = 1.0,
    is_calibrated: bool = True,
) -> np.ndarray:
    """
    Convert flux image or profile into surface brightness in AB mag / arcsec^2:
        SB = 20.472 - 2.5 * log10(I_MJy_sr)

    Parameters
    ----------
    flux_arr : np.ndarray
        Input 2D array or 1D profile of flux values.
    conversion_factor : float, default 1.0
        Photometric conversion factor (conversion_megajanskys) to MJy/sr.
    is_calibrated : bool, default True
        If True, flux_arr is already in MJy/sr. If False, multiplied by conversion_factor.

    Returns
    -------
    mag_arr : np.ndarray
        Surface brightness in AB mag / arcsec^2 with NaNs for non-positive pixels.
    """
    arr = np.asarray(flux_arr, dtype=np.float64)
    if not is_calibrated and conversion_factor > 0:
        flux_mjy = np.where(arr > 0, arr * conversion_factor, np.nan)
    else:
        flux_mjy = np.where(arr > 0, arr, np.nan)

    with np.errstate(divide="ignore", invalid="ignore"):
        mag_arr = 20.472 - 2.5 * np.log10(flux_mjy)

    return mag_arr.astype(np.float32)


def generate_debug_figure1_masking_procedure(
    stamp: np.ndarray,
    radial_model: np.ndarray,
    residual: np.ndarray,
    final_mask: np.ndarray,
    conversion_factor: float,
    output_path: Path,
    star_info: Optional[Dict[str, Any]] = None,
    is_calibrated: bool = True,
    dq_mask: Optional[np.ndarray] = None,
) -> Path:
    """
    Figure 1: Masking procedure in 4 panels with identical magnitude scale:
    (image, radial model, residual, image + mask & quality flags overlay).
    Mask is overlaid in semi-transparent cyan (alpha~0.5) and quality flags in green (alpha~0.5).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    info = star_info or {}
    source_id = str(info.get("source_id", "Star"))
    tier = str(info.get("tier", "unknown")).upper()
    mag = float(info.get("mag", 0.0))

    if dq_mask is None and star_info is not None:
        dq_mask = star_info.get("dq_mask", None)

    if dq_mask is not None:
        is_dq = dq_mask.astype(bool)
        is_contam = final_mask.astype(bool) & (~is_dq)
    else:
        is_dq = np.zeros_like(final_mask, dtype=bool)
        is_contam = final_mask.astype(bool)

    # Convert to AB mag / arcsec^2
    mag_img = convert_to_ab_mag_arcsec2(stamp, conversion_factor, is_calibrated)
    mag_mod = convert_to_ab_mag_arcsec2(radial_model, conversion_factor, is_calibrated)
    mag_res = convert_to_ab_mag_arcsec2(np.abs(residual), conversion_factor, is_calibrated)

    # Establish common magnitude dynamic range from the valid star image
    valid_mags = mag_img[np.isfinite(mag_img)]
    if len(valid_mags) > 0:
        vmin = max(float(np.nanpercentile(valid_mags, 0.5)), 8.0)
        vmax = min(float(np.nanpercentile(valid_mags, 99.5)), 28.5)
    else:
        vmin, vmax = 12.0, 28.0

    if vmin >= vmax:
        vmax = vmin + 5.0

    fig, axes = plt.subplots(1, 4, figsize=(22, 5.5), facecolor="#0e1117")
    cmap = plt.cm.magma_r.copy()
    try:
        cmap = cmap.with_extremes(bad="#1a1e24")
    except AttributeError:
        cmap.set_bad(color="#1a1e24")

    titles = [
        "1. Calibrated Image",
        "2. Radial Model (2D)",
        "3. Residual (|Image - Model|)",
        "4. Mask & DQ Overlay (alpha=0.5)",
    ]
    data_list = [mag_img, mag_mod, mag_res, mag_img]

    for idx, (ax, data, title) in enumerate(zip(axes, data_list, titles)):
        ax.set_facecolor("#161b22")
        im = ax.imshow(data, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax)
        ax.set_title(title, color="#58a6ff", fontsize=12, fontweight="bold", pad=8)
        ax.set_xlabel("X (pixels)", color="#e6edf3", fontsize=10)
        if idx == 0:
            ax.set_ylabel("Y (pixels)", color="#e6edf3", fontsize=10)
        ax.tick_params(colors="#8b949e", labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#30363d")

        # In panel 4: overlay cyan mask and green quality flags with alpha=0.5
        if idx == 3:
            ny, nx = stamp.shape
            if np.any(is_contam):
                overlay_cyan = np.zeros((ny, nx, 4), dtype=np.float32)
                overlay_cyan[is_contam] = [0.0, 0.9, 1.0, 0.5]  # Entire mask with cyan, alpha=0.5
                ax.imshow(overlay_cyan, origin="lower")

            if np.any(is_dq):
                overlay_green = np.zeros((ny, nx, 4), dtype=np.float32)
                overlay_green[is_dq] = [0.0, 0.9, 0.2, 0.5]  # Quality flags with green, alpha=0.5
                ax.imshow(overlay_green, origin="lower")

            comps = info.get("gaia_companions", [])
            for comp in comps:
                circ = Circle(
                    (comp["x"], comp["y"]),
                    comp["radius_px"],
                    fill=False,
                    edgecolor="#ffd600",
                    linestyle="--",
                    linewidth=1.4,
                )
                ax.add_patch(circ)
                ax.plot(comp["x"], comp["y"], "+", color="#ffd600", markersize=7, markeredgewidth=1.3)

            legend_elements = []
            if np.any(is_contam):
                legend_elements.append(Patch(facecolor=(0.0, 0.9, 1.0, 0.5), edgecolor="#00e5ff", label="Mask (Cyan, $\\alpha=0.5$)"))
            if np.any(is_dq):
                legend_elements.append(Patch(facecolor=(0.0, 0.9, 0.2, 0.5), edgecolor="#00e676", label="Quality Flags (Green, $\\alpha=0.5$)"))
            if len(comps) > 0:
                legend_elements.append(plt.Line2D([0], [0], color="#ffd600", linestyle="--", linewidth=1.4, label=f"Gaia Companions ({len(comps)})"))
            if legend_elements:
                ax.legend(handles=legend_elements, loc="upper right", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8.0)

    # Shared colorbar
    cbar_ax = fig.add_axes([0.92, 0.15, 0.015, 0.7])
    cbar = fig.colorbar(im, cax=cbar_ax)
    cbar.set_label("Surface Brightness (AB mag / arcsec$^2$)", color="#e6edf3", fontsize=11, labelpad=10)
    cbar.ax.tick_params(colors="#8b949e", labelsize=9)
    # Note: smaller mag = brighter, so label top
    cbar.ax.invert_yaxis()

    fig.suptitle(
        f"Debug Figure 1: Masking Procedure | {tier} Star (ID: {source_id}, Mag: {mag:.2f}) [Common Scale]",
        color="#ffffff",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )

    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    logger.info(f"Generated Debug Figure 1: {output_path}")
    return output_path


def generate_debug_figure2_apertures_and_profile(
    stamp: np.ndarray,
    mask: np.ndarray,
    rad_bins: np.ndarray,
    rad_centers: np.ndarray,
    rad_flux: np.ndarray,
    conversion_factor: float,
    output_path: Path,
    star_info: Optional[Dict[str, Any]] = None,
    is_calibrated: bool = True,
    center_xy: Optional[Tuple[float, float]] = None,
    dq_mask: Optional[np.ndarray] = None,
) -> Path:
    """
    Figure 2: 2 panels:
    - Left: Calibrated image with overlaid concentric profile apertures,
      contaminant mask (cyan, alpha=0.5), and quality flags (green, alpha=0.5).
    - Right: Radial profile in surface brightness (AB mag / arcsec^2).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    info = star_info or {}
    source_id = str(info.get("source_id", "Star"))
    tier = str(info.get("tier", "unknown")).upper()
    mag = float(info.get("mag", 0.0))

    ny, nx = stamp.shape
    cx = center_xy[0] if center_xy else (nx - 1.0) / 2.0
    cy = center_xy[1] if center_xy else (ny - 1.0) / 2.0

    if dq_mask is None and star_info is not None:
        dq_mask = star_info.get("dq_mask", None)

    if dq_mask is not None:
        is_dq = dq_mask.astype(bool)
        is_contam = mask.astype(bool) & (~is_dq)
    else:
        is_dq = np.zeros_like(mask, dtype=bool)
        is_contam = mask.astype(bool)

    # Use full stamp so sources below masks can be seen
    mag_img = convert_to_ab_mag_arcsec2(stamp, conversion_factor, is_calibrated)
    prof_mag = convert_to_ab_mag_arcsec2(rad_flux, conversion_factor, is_calibrated)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7), facecolor="#0e1117")

    # Panel 1: Image with Overlaid Geometric Apertures and Masks
    ax1.set_facecolor("#161b22")
    valid_mags = mag_img[np.isfinite(mag_img)]
    vmin = max(float(np.nanpercentile(valid_mags, 0.5)), 8.0) if len(valid_mags) else 12.0
    vmax = min(float(np.nanpercentile(valid_mags, 99.5)), 28.5) if len(valid_mags) else 28.0
    cmap = plt.cm.magma_r.copy()
    try:
        cmap = cmap.with_extremes(bad="#1a1e24")
    except AttributeError:
        cmap.set_bad(color="#1a1e24")

    im1 = ax1.imshow(mag_img, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax)
    ax1.set_title("Image with Profile Annuli, Mask (Cyan) & DQ (Green) Overlaid", color="#58a6ff", fontsize=12, fontweight="bold", pad=8)
    ax1.set_xlabel("X (pixels)", color="#e6edf3", fontsize=10)
    ax1.set_ylabel("Y (pixels)", color="#e6edf3", fontsize=10)
    ax1.tick_params(colors="#8b949e", labelsize=9)

    # Overlay cyan contaminant mask (alpha=0.5)
    if np.any(is_contam):
        overlay_cyan = np.zeros((ny, nx, 4), dtype=np.float32)
        overlay_cyan[is_contam] = [0.0, 0.9, 1.0, 0.5]
        ax1.imshow(overlay_cyan, origin="lower")

    # Overlay green quality flags (alpha=0.5)
    if np.any(is_dq):
        overlay_green = np.zeros((ny, nx, 4), dtype=np.float32)
        overlay_green[is_dq] = [0.0, 0.9, 0.2, 0.5]
        ax1.imshow(overlay_green, origin="lower")

    # Draw subset of concentric geometric circles (sample every 6th bin to prevent visual saturation)
    sub_bins = rad_bins[::6] if len(rad_bins) > 12 else rad_bins
    for r in sub_bins:
        if r <= max(nx, ny):
            circ = Circle((cx, cy), r, fill=False, edgecolor="#00e5ff", alpha=0.35, linewidth=0.8, linestyle=":")
            ax1.add_patch(circ)

    # Highlight centroid
    ax1.plot(cx, cy, "+", color="#00e5ff", markersize=10, markeredgewidth=1.5, label="Centroid")

    # Overlay Gaia companion star circular apertures
    comps = info.get("gaia_companions", [])
    for comp in comps:
        circ = Circle(
            (comp["x"], comp["y"]),
            comp["radius_px"],
            fill=False,
            edgecolor="#ffd600",
            linestyle="--",
            linewidth=1.4,
        )
        ax1.add_patch(circ)
        ax1.plot(comp["x"], comp["y"], "+", color="#ffd600", markersize=7, markeredgewidth=1.3)

    legend_elements = [
        plt.Line2D([0], [0], color="#00e5ff", marker="+", linestyle="none", markersize=10, markeredgewidth=1.5, label="Centroid"),
    ]
    if np.any(is_contam):
        legend_elements.append(Patch(facecolor=(0.0, 0.9, 1.0, 0.5), edgecolor="#00e5ff", label="Mask (Cyan, $\\alpha=0.5$)"))
    if np.any(is_dq):
        legend_elements.append(Patch(facecolor=(0.0, 0.9, 0.2, 0.5), edgecolor="#00e676", label="Quality Flags (Green, $\\alpha=0.5$)"))
    if len(comps) > 0:
        legend_elements.append(plt.Line2D([0], [0], color="#ffd600", linestyle="--", linewidth=1.4, label=f"Gaia Companions ({len(comps)})"))

    ax1.legend(handles=legend_elements, loc="upper right", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8.0)

    cbar1 = fig.colorbar(im1, ax=ax1, shrink=0.85)
    cbar1.set_label("AB mag / arcsec$^2$", color="#e6edf3", fontsize=10)
    cbar1.ax.tick_params(colors="#8b949e", labelsize=8.5)
    cbar1.ax.invert_yaxis()

    # Panel 2: Measured Radial Profile in AB mag / arcsec^2
    ax2.set_facecolor("#161b22")
    valid_p = np.isfinite(prof_mag) & (rad_centers > 0)
    if np.any(valid_p):
        r_plot = rad_centers[valid_p]
        m_plot = prof_mag[valid_p]
        ax2.plot(r_plot, m_plot, color="#00e5ff", lw=2.2, marker="o", markersize=3, label="Radial Profile")

        ax2.set_xscale("log")
        ax2.set_xlabel("Radius from Centroid (pixels)", color="#e6edf3", fontsize=11, labelpad=8)
        ax2.set_ylabel("Surface Brightness (AB mag / arcsec$^2$)", color="#e6edf3", fontsize=11, labelpad=8)
        ax2.set_title("Radial Surface Brightness Profile", color="#58a6ff", fontsize=12, fontweight="bold", pad=8)
        ax2.tick_params(colors="#8b949e", labelsize=9.5, which="both")
        ax2.grid(True, which="both", color="#30363d", alpha=0.4, linestyle=":")

        # Invert y-axis: brighter magnitudes (smaller numbers) at the top!
        y_top = max(float(np.min(m_plot)) - 1.0, 8.0)
        y_bottom = min(float(np.max(m_plot)) + 1.0, 30.0)
        ax2.set_ylim(y_bottom, y_top)

        leg2 = ax2.legend(loc="upper right", facecolor="#161b22", edgecolor="#30363d", fontsize=9.5)
        for t in leg2.get_texts():
            t.set_color("#e6edf3")

    fig.suptitle(
        f"Debug Figure 2: Profile Annuli & Surface Brightness | {tier} Star (ID: {source_id}, Mag: {mag:.2f})",
        color="#ffffff",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )

    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    logger.info(f"Generated Debug Figure 2: {output_path}")
    return output_path


def generate_debug_figure3_profile_normalization(
    star_profiles: List[Dict[str, Any]],
    mean_reference_profile: Tuple[np.ndarray, np.ndarray],
    norm_ranges: Dict[str, Tuple[float, float]],
    output_path: Path,
) -> Path:
    """
    Figure 3: Show individual star profiles (unnormalized and normalized)
    alongside the mean reference profile, highlighting the annular normalization fitting region.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    r_mean, f_mean = mean_reference_profile

    fig, ax = plt.subplots(figsize=(12, 7.5), facecolor="#0e1117")
    ax.set_facecolor("#161b22")

    tier_colors = {
        "bright": "#ff7b72",
        "medium": "#d2a8ff",
        "faint": "#7ee787",
    }

    # 1. Shaded Normalization Annular Ranges
    norm_added = False
    for t_name, (r_lo, r_hi) in norm_ranges.items():
        col = tier_colors.get(t_name, "#58a6ff")
        ax.axvspan(r_lo, r_hi, color=col, alpha=0.12, label=f"Norm Zone: {t_name.title()} [{r_lo:.0f}-{r_hi:.0f} px]")

    # 2. Plot Reference Mean Profile
    if len(r_mean) > 0 and np.any(f_mean > 0):
        ax.plot(r_mean, f_mean, color="#ffffff", lw=2.8, label="Mean Reference Profile (X Stars)")
        ax.plot(r_mean, f_mean, color="#00e5ff", lw=1.5, linestyle="--")

    # 3. Plot Unnormalized & Normalized Profiles per Star
    for s_idx, sp in enumerate(star_profiles):
        tier = sp.get("tier", "faint").lower()
        col = tier_colors.get(tier, "#58a6ff")
        r_s = sp["radii"]
        f_raw = sp["flux_raw"]
        f_norm = sp["flux_norm"]
        sid = str(sp.get("source_id", s_idx))
        scale_val = sp.get("scale_factor", 1.0)

        valid_raw = np.isfinite(f_raw) & (f_raw > 0)
        valid_norm = np.isfinite(f_norm) & (f_norm > 0)

        if np.any(valid_raw):
            ax.plot(
                r_s[valid_raw],
                f_raw[valid_raw],
                color=col,
                linestyle=":",
                lw=1.2,
                alpha=0.6,
                label=f"Star {sid} ({tier}) Unnormalized" if s_idx < 3 else None,
            )
        if np.any(valid_norm):
            ax.plot(
                r_s[valid_norm],
                f_norm[valid_norm],
                color=col,
                linestyle="-",
                lw=1.8,
                alpha=0.9,
                label=f"Star {sid} ({tier}) Normalized (Scale={scale_val:.2e})" if s_idx < 3 else None,
            )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.1, 520.0)
    ax.set_ylim(1e-11, 1e-2)

    ax.set_xlabel("Radius from Centroid (pixels)", color="#e6edf3", fontsize=11, labelpad=8)
    ax.set_ylabel("Surface Brightness (pixel$^{-1}$)", color="#e6edf3", fontsize=11, labelpad=8)
    ax.set_title(
        "Debug Figure 3: Radial Profile Normalization & Overlap Calibration\n"
        "(Unnormalized Dotted vs. Normalized Solid Curves in Shaded Fitting Zones) [Scale: $10^{-11}$ to $10^{-2}$]",
        color="#58a6ff",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.tick_params(colors="#8b949e", labelsize=9.5, which="both")
    ax.grid(True, which="both", color="#30363d", alpha=0.4, linestyle=":")

    leg = ax.legend(loc="upper right", facecolor="#161b22", edgecolor="#30363d", fontsize=8.5)
    for text in leg.get_texts():
        text.set_color("#e6edf3")

    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    logger.info(f"Generated Debug Figure 3: {output_path}")
    return output_path


def generate_debug_figure4_model_psf(
    composite_epsf: np.ndarray,
    output_path: Path,
    sca_name: str = "WFI01",
    pixel_scale: float = 0.11,
) -> Path:
    """
    Figure 4: Model PSF 2D canvas with core zoom inset, scaled from 10^-11 to 10^-2.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 10), facecolor="#0e1117")
    ax.set_facecolor("#161b22")

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

    im = ax.imshow(
        np.maximum(scaled_epsf, vmin_2d),
        origin="lower",
        cmap="inferno",
        norm=norm_2d,
        extent=extent_arcsec,
    )

    ax.set_title(
        f"Debug Figure 4: Model PSF Canvas ({sca_name.upper()})\n"
        f"Dimension: {canvas_size}x{canvas_size} px ({canvas_size * pixel_scale:.1f}\" x {canvas_size * pixel_scale:.1f}\") "
        f"[Scale: $10^{{-11}}$ to $10^{{-2}}$]",
        color="#58a6ff",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("Offset $\\Delta x$ (arcseconds)", color="#e6edf3", fontsize=11, labelpad=8)
    ax.set_ylabel("Offset $\\Delta y$ (arcseconds)", color="#e6edf3", fontsize=11, labelpad=8)
    ax.tick_params(colors="#8b949e", labelsize=9.5)
    for spine in ax.spines.values():
        spine.set_color("#30363d")

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    cbar.set_label("Normalized ePSF Amplitude ($10^{-2}$ to $10^{11}$)", color="#e6edf3", fontsize=10.5, labelpad=10)
    cbar.ax.tick_params(colors="#8b949e", labelsize=9)

    # Inset core zoom
    ax_inset = inset_axes(ax, width="28%", height="28%", loc="upper right", borderpad=1.2)
    ax_inset.set_facecolor("#0e1117")
    core_rad_inset = min(15, int(half_canvas))
    cy, cx = int(round(half_canvas)), int(round(half_canvas))
    core_cutout = scaled_epsf[cy - core_rad_inset : cy + core_rad_inset + 1, cx - core_rad_inset : cx + core_rad_inset + 1]
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

    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    logger.info(f"Generated Debug Figure 4: {output_path}")
    return output_path


def generate_debug_figure5_final_profile(
    r_composite: np.ndarray,
    f_composite: np.ndarray,
    star_profiles: List[Dict[str, Any]],
    output_path: Path,
    sca_name: str = "WFI01",
    pixel_scale: float = 0.11,
) -> Path:
    """
    Figure 5: Final composite profile with all normalized star profiles in background,
    scaled from 10^-2 to 10^11.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 7.5), facecolor="#0e1117")
    ax.set_facecolor("#161b22")

    tier_palette = {
        "bright": ("#ff7b72", "Bright Stars"),
        "medium": ("#d2a8ff", "Medium Stars"),
        "faint": ("#7ee787", "Faint Stars"),
    }
    seen_tiers = set()

    for s in star_profiles:
        t = s.get("tier", "faint").lower()
        color, label = tier_palette.get(t, ("#8b949e", "Star"))
        lbl = label if t not in seen_tiers else None
        seen_tiers.add(t)

        r_s = s["radii"]
        f_norm = s["flux_norm"]
        valid = np.isfinite(f_norm) & (f_norm > 0)
        if np.any(valid):
            ax.plot(r_s[valid], f_norm[valid], color=color, alpha=0.35, lw=1.2, label=lbl)

    # Master Composite Curve
    if len(r_composite) > 0 and np.any(f_composite > 0):
        ax.plot(r_composite, f_composite, color="#ffffff", lw=3.0, label="Final Composite ePSF")
        ax.plot(r_composite, f_composite, color="#00e5ff", lw=1.6, linestyle="--")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.1, 520.0)
    ax.set_ylim(1e-11, 1e-2)

    ax.set_xlabel("Radius from Centroid (pixels, 0.11\"/px)", color="#e6edf3", fontsize=11, labelpad=8)
    ax.set_ylabel("Normalized Surface Brightness (pixel$^{-1}$)", color="#e6edf3", fontsize=11, labelpad=8)
    ax.tick_params(colors="#8b949e", labelsize=9.5, which="both")
    ax.grid(True, which="both", color="#30363d", alpha=0.4, linestyle=":")

    ax.set_title(
        f"Debug Figure 5: Final Composite Profile & Contributing Stars ({sca_name.upper()})\n"
        f"[Scale: $10^{{-11}}$ to $10^{{-2}}$ | Total Normalized Stars: {len(star_profiles)}]",
        color="#58a6ff",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )

    leg = ax.legend(loc="upper right", facecolor="#161b22", edgecolor="#30363d", fontsize=9.5)
    for text in leg.get_texts():
        text.set_color("#e6edf3")

    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    logger.info(f"Generated Debug Figure 5: {output_path}")
    return output_path


def generate_all_debug_plots(
    pooled_stamps: Dict[str, List[Any]],
    composite_epsf: np.ndarray,
    diagnostics: Dict[str, Any],
    output_dir: Union[str, Path],
    sca_name: str = "WFI01",
    pixel_scale: float = 0.11,
    growth_rate: float = 1.03,
) -> Dict[str, Path]:
    """
    Generate the complete 5-figure debug diagnostic suite when --debug X is specified.
    Stores all figures in output_dir/debug/.

    Figures generated:
    1. debug_1_masking_procedure.png (4 panels: image, radial model, residual, image+mask in AB mag/arcsec^2)
    2. debug_2_apertures_and_profile.png (2 panels: masked image with concentric geometric annuli, radial profile in AB mag/arcsec^2)
    3. debug_3_profile_normalization.png (unnormalized vs normalized curves with shaded fitting regions relative to reference mean profile)
    4. debug_4_model_psf.png (2D model PSF canvas + core zoom inset, scaled 10^-11 to 10^-2)
    5. debug_5_final_profile_normalized.png (composite curve + all contributing star profiles, scaled 10^-11 to 10^-2)

    Additionally generates per-star diagnostic figures for individual star inspection.
    """
    from romanepsf.assembly import measure_radial_profile_1d, get_geometric_radial_bins

    out_p = Path(output_dir)
    debug_dir = out_p if out_p.name == "debug" else (out_p / "debug")
    debug_dir.mkdir(parents=True, exist_ok=True)

    generated_files: Dict[str, Path] = {}

    # Extract 1D radial profile of the final composite ePSF model
    r_c, prof_c = measure_radial_profile_1d(
        composite_epsf,
        growth_rate=growth_rate,
    )[:2]

    # Master composite radial curve directly spans [10^-11, 10^-2]
    prof_c_scaled = prof_c

    # Resolve overlap scale factors and annular normalization boundaries
    r_fm_min = float(diagnostics.get("r_fm_min", 25.0))
    r_fm_max = float(diagnostics.get("r_fm_max", 40.0))
    r_mb_min = float(diagnostics.get("r_mb_min", 100.0))
    r_mb_max = float(diagnostics.get("r_mb_max", 160.0))

    norm_ranges = {
        "faint": (2.0, 15.0),
        "medium": (r_fm_min, r_fm_max),
        "bright": (r_mb_min, r_mb_max),
    }

    star_profiles_list: List[Dict[str, Any]] = []
    all_star_items: List[Tuple[str, Any]] = []

    for tier_name in ["bright", "medium", "faint"]:
        for stamp in pooled_stamps.get(tier_name, []):
            all_star_items.append((tier_name, stamp))

    # Process individual star profiles and generate Figures 1 & 2 per star
    representative_star_idx = 0
    # Prefer bright star for canonical representation, then medium, then faint
    for idx, (tier_name, _) in enumerate(all_star_items):
        if tier_name == "bright":
            representative_star_idx = idx
            break
        elif tier_name == "medium" and representative_star_idx == 0:
            representative_star_idx = idx

    for idx, (tier_name, stamp) in enumerate(all_star_items):
        sid = getattr(stamp, "source_id", None) or f"{tier_name}_{idx}"
        dbg = getattr(stamp, "debug_info", None) or {}

        stamp_img = dbg.get("raw_stamp", stamp.data)
        mask = dbg.get("unaligned_mask", stamp.mask)
        res_map = dbg.get("residual", np.zeros_like(stamp_img))
        rad_mod = dbg.get("radial_model", stamp_img)
        conv = float(dbg.get("conversion_factor", 1.0))
        is_cal = bool(dbg.get("is_calibrated", True))
        center_xy = dbg.get("center_stamp", None)
        mag_val = float(getattr(stamp, "mag", 0.0))

        star_meta = {
            "source_id": sid,
            "tier": tier_name,
            "mag": mag_val,
            "gaia_companions": dbg.get("gaia_companions", []),
            "dq_mask": dbg.get("dq_mask", None),
        }

        # Measure 1D profile for the star stamp
        r_s, f_s = measure_radial_profile_1d(
            stamp.data,
            mask=stamp.mask,
            growth_rate=growth_rate,
        )[:2]

        rad_bins_s = get_geometric_radial_bins(
            r_min=0.5,
            r_max=int(min(stamp_img.shape) / 2.0),
            growth_rate=growth_rate,
        )

        # Scale star profile to align with the scaled composite profile in its normalization zone
        fit_r_min, fit_r_max = norm_ranges.get(tier_name, (5.0, 25.0))
        comp_interp = np.interp(r_s, r_c, prof_c_scaled)
        in_range = (r_s >= fit_r_min) & (r_s <= fit_r_max) & np.isfinite(f_s) & (f_s > 0)
        if np.sum(in_range) >= 2:
            star_scale = float(np.median(comp_interp[in_range] / f_s[in_range]))
        else:
            valid_all = np.isfinite(f_s) & (f_s > 0)
            star_scale = float(np.median(comp_interp[valid_all] / f_s[valid_all])) if np.any(valid_all) else 1.0

        f_norm = f_s * star_scale

        sp_dict = {
            "source_id": sid,
            "tier": tier_name,
            "radii": r_s,
            "flux_raw": f_s,
            "flux_norm": f_norm,
            "scale_factor": star_scale,
            "norm_range": (fit_r_min, fit_r_max),
        }
        star_profiles_list.append(sp_dict)

        # Generate Figure 1 for star
        fig1_star_path = debug_dir / f"debug_1_masking_procedure_{tier_name}_{sid}.png"
        generate_debug_figure1_masking_procedure(
            stamp=stamp_img,
            radial_model=rad_mod,
            residual=res_map,
            final_mask=mask,
            conversion_factor=conv,
            output_path=fig1_star_path,
            star_info=star_meta,
            is_calibrated=is_cal,
        )

        # Generate Figure 2 for star
        fig2_star_path = debug_dir / f"debug_2_apertures_and_profile_{tier_name}_{sid}.png"
        generate_debug_figure2_apertures_and_profile(
            stamp=stamp_img,
            mask=mask,
            rad_bins=rad_bins_s,
            rad_centers=r_s,
            rad_flux=f_s,
            conversion_factor=conv,
            output_path=fig2_star_path,
            star_info=star_meta,
            is_calibrated=is_cal,
            center_xy=center_xy,
        )

        # Generate Figure 3 per star
        fig3_star_path = debug_dir / f"debug_3_profile_normalization_{tier_name}_{sid}.png"
        generate_debug_figure3_profile_normalization(
            star_profiles=[sp_dict],
            mean_reference_profile=(r_c, prof_c_scaled),
            norm_ranges={tier_name: (fit_r_min, fit_r_max)},
            output_path=fig3_star_path,
        )

        # Canonical / representative assignment
        if idx == representative_star_idx:
            fig1_canon = debug_dir / "debug_1_masking_procedure.png"
            generate_debug_figure1_masking_procedure(
                stamp=stamp_img,
                radial_model=rad_mod,
                residual=res_map,
                final_mask=mask,
                conversion_factor=conv,
                output_path=fig1_canon,
                star_info=star_meta,
                is_calibrated=is_cal,
            )
            generated_files["debug_1_masking_procedure"] = fig1_canon

            fig2_canon = debug_dir / "debug_2_apertures_and_profile.png"
            generate_debug_figure2_apertures_and_profile(
                stamp=stamp_img,
                mask=mask,
                rad_bins=rad_bins_s,
                rad_centers=r_s,
                rad_flux=f_s,
                conversion_factor=conv,
                output_path=fig2_canon,
                star_info=star_meta,
                is_calibrated=is_cal,
                center_xy=center_xy,
            )
            generated_files["debug_2_apertures_and_profile"] = fig2_canon

    # Figure 3: Multi-Star Composite Normalization Summary
    fig3_path = debug_dir / "debug_3_profile_normalization.png"
    generate_debug_figure3_profile_normalization(
        star_profiles=star_profiles_list,
        mean_reference_profile=(r_c, prof_c_scaled),
        norm_ranges=norm_ranges,
        output_path=fig3_path,
    )
    generated_files["debug_3_profile_normalization"] = fig3_path

    # Figure 4: Model PSF Canvas (scaled 10^-2 to 10^11)
    fig4_path = debug_dir / "debug_4_model_psf.png"
    generate_debug_figure4_model_psf(
        composite_epsf=composite_epsf,
        output_path=fig4_path,
        sca_name=sca_name,
        pixel_scale=pixel_scale,
    )
    generated_files["debug_4_model_psf"] = fig4_path

    # Figure 5: Final Composite Profile with All Normalized Stars (scaled 10^-2 to 10^11)
    fig5_path = debug_dir / "debug_5_final_profile_normalized.png"
    generate_debug_figure5_final_profile(
        r_composite=r_c,
        f_composite=prof_c_scaled,
        star_profiles=star_profiles_list,
        output_path=fig5_path,
        sca_name=sca_name,
        pixel_scale=pixel_scale,
    )
    generated_files["debug_5_final_profile_normalized"] = fig5_path

    logger.info(
        f"Completed all debug diagnostic plots in {debug_dir} "
        f"for {len(all_star_items)} stars across tiers."
    )
    return generated_files


__all__ = [
    "convert_to_ab_mag_arcsec2",
    "generate_debug_figure1_masking_procedure",
    "generate_debug_figure2_apertures_and_profile",
    "generate_debug_figure3_profile_normalization",
    "generate_debug_figure4_model_psf",
    "generate_debug_figure5_final_profile",
    "generate_all_debug_plots",
]
