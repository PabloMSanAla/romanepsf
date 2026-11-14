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
from matplotlib.lines import Line2D
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
    gaia_center_xy: Optional[Tuple[float, float]] = None,
) -> Path:
    """
    Figure 2: 3 panels:
    - Panel 1: Calibrated image with overlaid concentric profile apertures,
      contaminant mask (cyan, alpha=0.5), and quality flags (green, alpha=0.5).
    - Panel 2: Core zoom showing the Gaia (RA, Dec) projected center vs the empirical
      measured recentered center, with shift vector and astrometric summary.
    - Panel 3: Radial surface brightness profile in AB mag / arcsec^2.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    info = star_info or {}
    source_id = str(info.get("source_id", "Star"))
    tier = str(info.get("tier", "unknown")).upper()
    mag = float(info.get("mag", 0.0))

    ny, nx = stamp.shape
    if center_xy is not None:
        cx, cy = center_xy
    elif "center_stamp" in info and info["center_stamp"] is not None:
        cx, cy = info["center_stamp"]
    else:
        cx = (nx - 1.0) / 2.0
        cy = (ny - 1.0) / 2.0

    if gaia_center_xy is not None:
        xg, yg = gaia_center_xy
    elif "gaia_center_stamp" in info and info["gaia_center_stamp"] is not None:
        xg, yg = info["gaia_center_stamp"]
    else:
        xg, yg = cx, cy

    dx = cx - xg
    dy = cy - yg
    shift_px_val = info.get("shift_px", None)
    shift_px = float(shift_px_val) if shift_px_val is not None else float(np.hypot(dx, dy))
    pix_scale_val = info.get("pixel_scale", None)
    pix_scale = float(pix_scale_val) if pix_scale_val is not None else 0.11
    shift_mas = shift_px * pix_scale * 1000.0
    ra_val = info.get("gaia_ra", None)
    dec_val = info.get("gaia_dec", None)

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

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(23, 7.2), facecolor="#0e1117")

    # =========================================================================
    # Panel 1: Image with Overlaid Geometric Apertures and Masks
    # =========================================================================
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
    ax1.set_title("1. Apertures, Masks & Centroid", color="#58a6ff", fontsize=12, fontweight="bold", pad=8)
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

    # Gaia companions
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

    # Highlight centers on Panel 1
    has_gaia_pos = (abs(xg - cx) > 1e-4) or (abs(yg - cy) > 1e-4) or (shift_px > 0.01)
    if has_gaia_pos:
        ax1.plot(xg, yg, marker="s", markersize=8, markeredgewidth=1.6, markeredgecolor="#ff9100", markerfacecolor="none", label="Gaia Center")
    ax1.plot(cx, cy, "+", color="#00e5ff", markersize=10, markeredgewidth=1.8, label="Recentered")

    legend_elements1 = [
        plt.Line2D([0], [0], color="#00e5ff", marker="+", linestyle="none", markersize=9, markeredgewidth=1.8, label="Recentered"),
    ]
    if has_gaia_pos:
        legend_elements1.append(plt.Line2D([0], [0], color="#ff9100", marker="s", markerfacecolor="none", linestyle="none", markersize=7, markeredgewidth=1.5, label="Gaia Center"))
    if np.any(is_contam):
        legend_elements1.append(Patch(facecolor=(0.0, 0.9, 1.0, 0.5), edgecolor="#00e5ff", label="Mask (Cyan, $\\alpha=0.5$)"))
    if np.any(is_dq):
        legend_elements1.append(Patch(facecolor=(0.0, 0.9, 0.2, 0.5), edgecolor="#00e676", label="Quality Flags (Green, $\\alpha=0.5$)"))
    if len(comps) > 0:
        legend_elements1.append(plt.Line2D([0], [0], color="#ffd600", linestyle="--", linewidth=1.4, label=f"Gaia Companions ({len(comps)})"))

    ax1.legend(handles=legend_elements1, loc="upper right", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8.0)

    cbar1 = fig.colorbar(im1, ax=ax1, shrink=0.85)
    cbar1.set_label("AB mag / arcsec$^2$", color="#e6edf3", fontsize=10)
    cbar1.ax.tick_params(colors="#8b949e", labelsize=8.5)
    cbar1.ax.invert_yaxis()

    # =========================================================================
    # Panel 2: Gaia Center & Recentered Measure (Core Zoom)
    # =========================================================================
    ax2.set_facecolor("#161b22")
    r_zoom = min(15.0, (nx - 1) / 2.0, (ny - 1) / 2.0)
    x0_z = max(0, int(round(cx - r_zoom)))
    x1_z = min(nx, int(round(cx + r_zoom)) + 1)
    y0_z = max(0, int(round(cy - r_zoom)))
    y1_z = min(ny, int(round(cy + r_zoom)) + 1)
    zoom_crop = mag_img[y0_z:y1_z, x0_z:x1_z]
    v_z = zoom_crop[np.isfinite(zoom_crop)]
    if len(v_z) > 0:
        vz_min = float(np.nanpercentile(v_z, 1.0))
        vz_max = float(np.nanpercentile(v_z, 99.0))
        if vz_max - vz_min < 2.0:
            vz_max = vz_min + 3.0
    else:
        vz_min, vz_max = vmin, vmax

    im2 = ax2.imshow(mag_img, origin="lower", cmap=cmap, vmin=vz_min, vmax=vz_max)
    ax2.set_xlim(cx - r_zoom, cx + r_zoom)
    ax2.set_ylim(cy - r_zoom, cy + r_zoom)
    ax2.set_title("2. Gaia Center vs Recentered Measure", color="#58a6ff", fontsize=12, fontweight="bold", pad=8)
    ax2.set_xlabel("Stamp X (pixels)", color="#e6edf3", fontsize=10)
    ax2.set_ylabel("Stamp Y (pixels)", color="#e6edf3", fontsize=10)
    ax2.tick_params(colors="#8b949e", labelsize=9)

    # Plot Gaia projected center (square with dashed crosshairs)
    ax2.plot(xg, yg, marker="s", markersize=9, markeredgewidth=2.0, markeredgecolor="#ff9100", markerfacecolor="none", label="Gaia (RA, Dec)")
    ax2.axvline(xg, color="#ff9100", linestyle="--", alpha=0.55, linewidth=1.1)
    ax2.axhline(yg, color="#ff9100", linestyle="--", alpha=0.55, linewidth=1.1)

    # Plot empirical measured center (plus with dotted crosshairs)
    ax2.plot(cx, cy, marker="+", markersize=14, markeredgewidth=2.2, color="#00e5ff", label="Recentered Measure")
    ax2.axvline(cx, color="#00e5ff", linestyle=":", alpha=0.55, linewidth=1.1)
    ax2.axhline(cy, color="#00e5ff", linestyle=":", alpha=0.55, linewidth=1.1)

    # Shift arrow if significant
    if shift_px >= 0.05:
        ax2.annotate(
            "",
            xy=(cx, cy),
            xytext=(xg, yg),
            arrowprops=dict(arrowstyle="->", color="#ffd600", lw=2.0, mutation_scale=15),
        )

    # Range scale rings around Gaia center at 1 px and 2 px
    circ_1px = Circle((xg, yg), 1.0, fill=False, edgecolor="#ffffff", linestyle=":", alpha=0.35, linewidth=0.9)
    circ_2px = Circle((xg, yg), 2.0, fill=False, edgecolor="#ffffff", linestyle=":", alpha=0.25, linewidth=0.9)
    ax2.add_patch(circ_1px)
    ax2.add_patch(circ_2px)

    # Astrometric recentering summary card
    ra_str = f"{ra_val:.6f}°" if ra_val is not None else "N/A"
    dec_str = f"{dec_val:.6f}°" if dec_val is not None else "N/A"
    summary_text = (
        f"Gaia RA:  {ra_str}\n"
        f"Gaia Dec: {dec_str}\n"
        f"Gaia (x, y):     ({xg:.2f}, {yg:.2f}) px\n"
        f"Recentered (x,y): ({cx:.2f}, {cy:.2f}) px\n"
        f"Shift (Δx, Δy):  ({dx:+.2f}, {dy:+.2f}) px\n"
        f"Offset |Δr|:     {shift_px:.2f} px ({shift_mas:.1f} mas)"
    )
    ax2.text(
        0.04, 0.04,
        summary_text,
        transform=ax2.transAxes,
        fontsize=8.2,
        fontfamily="monospace",
        color="#ffffff",
        verticalalignment="bottom",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#161b22", edgecolor="#30363d", alpha=0.88),
    )

    ax2.legend(loc="upper right", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8.0)

    cbar2 = fig.colorbar(im2, ax=ax2, shrink=0.85)
    cbar2.set_label("AB mag / arcsec$^2$", color="#e6edf3", fontsize=10)
    cbar2.ax.tick_params(colors="#8b949e", labelsize=8.5)
    cbar2.ax.invert_yaxis()

    # =========================================================================
    # Panel 3: Measured Radial Profile in AB mag / arcsec^2
    # =========================================================================
    ax3.set_facecolor("#161b22")
    valid_p = np.isfinite(prof_mag) & (rad_centers > 0)
    if np.any(valid_p):
        r_plot = rad_centers[valid_p]
        m_plot = prof_mag[valid_p]
        ax3.plot(r_plot, m_plot, color="#00e5ff", lw=2.2, marker="o", markersize=3, label="Radial Profile")

        ax3.set_xscale("log")
        ax3.set_xlabel("Radius from Centroid (pixels)", color="#e6edf3", fontsize=11, labelpad=8)
        ax3.set_ylabel("Surface Brightness (AB mag / arcsec$^2$)", color="#e6edf3", fontsize=11, labelpad=8)
        ax3.set_title("3. Radial Surface Brightness Profile", color="#58a6ff", fontsize=12, fontweight="bold", pad=8)
        ax3.tick_params(colors="#8b949e", labelsize=9.5, which="both")
        ax3.grid(True, which="both", color="#30363d", alpha=0.4, linestyle=":")

        # Invert y-axis: brighter magnitudes (smaller numbers) at the top!
        y_top = max(float(np.min(m_plot)) - 1.0, 8.0)
        y_bottom = min(float(np.max(m_plot)) + 1.0, 30.0)
        ax3.set_ylim(y_bottom, y_top)

        leg3 = ax3.legend(loc="upper right", facecolor="#161b22", edgecolor="#30363d", fontsize=9.5)
        for t in leg3.get_texts():
            t.set_color("#e6edf3")

    fig.suptitle(
        f"Debug Figure 2: Profile Annuli, Centroid Recentering & Radial Profile | {tier} Star (ID: {source_id}, Mag: {mag:.2f})",
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


def generate_debug_figure_spike_process(
    stamp: np.ndarray,
    residual: np.ndarray,
    output_path: Union[str, Path],
    conversion_factor: float = 1.0,
    star_info: Optional[Dict[str, Any]] = None,
    is_calibrated: bool = True,
    center_xy: Optional[Tuple[float, float]] = None,
    theoretical_mask: Optional[np.ndarray] = None,
    corrected_mask: Optional[np.ndarray] = None,
    base_spike_angles: Optional[Sequence[float]] = None,
    refined_spike_angles: Optional[Sequence[float]] = None,
    comp_mask: Optional[np.ndarray] = None,
) -> Path:
    """
    Generate 3-panel spike process diagnostic figure when running with --debug X:
    1. Calibrated Image + Theoretical Spike Mask (the starting point before empirical refinement).
    2. Residual Image + Corrected Spike Mask (the empirical refined mask with morphological dilation).
    3. Plot of Intensity vs Angular Distribution (full-image azimuthal profile across theta in [0, 360) deg),
       excluding data quality flags and neighbor Gaia companion stars,
       annotated with theoretical and corrected spike ray directions.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    info = star_info or {}
    source_id = str(info.get("source_id", "Star"))
    tier = str(info.get("tier", "unknown")).upper()
    mag = float(info.get("mag", 0.0))
    dq_mask = info.get("dq_mask", None)

    ny, nx = stamp.shape
    if center_xy is not None:
        cx, cy = float(center_xy[0]), float(center_xy[1])
    else:
        cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0

    core_rad = float(info.get("core_protection_radius_px", 6.0 if tier == "BRIGHT" else (4.0 if tier == "MEDIUM" else 3.0)))

    spike_details = info.get("spike_details", {}) or {}
    if base_spike_angles is None:
        base_spike_angles = spike_details.get("base_spike_angles", None)
    if refined_spike_angles is None:
        refined_spike_angles = spike_details.get("refined_spike_angles", None)
    if theoretical_mask is None:
        theoretical_mask = spike_details.get("theoretical_spike_mask", None)
    if corrected_mask is None:
        corrected_mask = spike_details.get("corrected_spike_mask", None)

    # Fallback calculation if spike_details not provided
    from romanepsf.masking import (
        get_theoretical_spike_angles,
        refine_spike_angles,
        create_geometric_spike_mask,
        detect_morphological_spikes,
    )
    if base_spike_angles is None or len(base_spike_angles) == 0:
        base_spike_angles = get_theoretical_spike_angles(0.0, detector_offset_deg=-9.70)
    if refined_spike_angles is None or len(refined_spike_angles) == 0:
        refined_spike_angles = refine_spike_angles(residual, (cx, cy), base_spike_angles, r_min=max(core_rad, 15.0))
    if theoretical_mask is None or not np.any(theoretical_mask):
        theoretical_mask = create_geometric_spike_mask((ny, nx), (cx, cy), base_spike_angles, radial_min=core_rad)
    if corrected_mask is None or not np.any(corrected_mask):
        corr_geom = create_geometric_spike_mask((ny, nx), (cx, cy), refined_spike_angles, radial_min=core_rad)
        corr_morph = detect_morphological_spikes(residual, (cx, cy), threshold_sigma=2.0)
        corrected_mask = corr_geom | corr_morph

    # Magnitude conversions in AB mag / arcsec^2
    mag_img = convert_to_ab_mag_arcsec2(stamp, conversion_factor, is_calibrated)
    mag_res = convert_to_ab_mag_arcsec2(np.abs(residual), conversion_factor, is_calibrated)

    valid_mags = mag_img[np.isfinite(mag_img)]
    if len(valid_mags) > 0:
        vmin = max(float(np.nanpercentile(valid_mags, 0.5)), 8.0)
        vmax = min(float(np.nanpercentile(valid_mags, 99.5)), 28.5)
    else:
        vmin, vmax = 12.0, 28.0
    if vmin >= vmax:
        vmax = vmin + 5.0

    fig = plt.figure(figsize=(24, 8.0), facecolor="#0e1117")
    gs = fig.add_gridspec(2, 3, width_ratios=[1.0, 1.0, 1.55], height_ratios=[1.0, 1.0], hspace=0.38, wspace=0.25)

    ax0 = fig.add_subplot(gs[:, 0])
    ax1 = fig.add_subplot(gs[:, 1])
    ax2_top = fig.add_subplot(gs[0, 2])
    ax2_bot = fig.add_subplot(gs[1, 2])

    cmap = plt.cm.magma_r.copy()
    try:
        cmap = cmap.with_extremes(bad="#1a1e24")
    except AttributeError:
        cmap.set_bad(color="#1a1e24")

    # Panel 1: Image + Theoretical Spike Mask
    ax0.set_facecolor("#161b22")
    im0 = ax0.imshow(mag_img, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax)
    if theoretical_mask is not None and np.any(theoretical_mask):
        overlay_theo = np.zeros((ny, nx, 4), dtype=np.float32)
        overlay_theo[theoretical_mask.astype(bool)] = [0.0, 0.85, 1.0, 0.50]  # Cyan overlay
        ax0.imshow(overlay_theo, origin="lower")

    max_ray_len = min(nx, ny) * 0.48
    r_start = max(core_rad, 4.0)
    for ang in base_spike_angles:
        rad = np.radians(ang)
        ax0.plot(
            [cx + r_start * np.cos(rad), cx + max_ray_len * np.cos(rad)],
            [cy + r_start * np.sin(rad), cy + max_ray_len * np.sin(rad)],
            linestyle="--",
            color="#58a6ff",
            linewidth=1.2,
            alpha=0.85,
        )
    ax0.add_patch(Circle((cx, cy), core_rad, fill=False, edgecolor="#e3b341", linestyle=":", linewidth=1.2))
    ax0.plot(cx, cy, "+", color="#ffffff", markersize=6, markeredgewidth=1.2)
    ax0.set_title("1. Calibrated Image + Theoretical Mask\n(Starting Point: Nominal Roll & Spider Prior)", color="#58a6ff", fontsize=11.5, fontweight="bold", pad=8)
    ax0.set_xlabel("X (pixels)", color="#e6edf3", fontsize=10)
    ax0.set_ylabel("Y (pixels)", color="#e6edf3", fontsize=10)
    ax0.tick_params(colors="#8b949e", labelsize=9)
    for s in ax0.spines.values():
        s.set_color("#30363d")
    leg0 = [
        Patch(facecolor=(0.0, 0.85, 1.0, 0.5), edgecolor="#00e5ff", label="Theoretical Mask"),
        Line2D([], [], color="#58a6ff", linestyle="--", linewidth=1.2, label=f"Theoretical Rays ({len(base_spike_angles)})"),
        Line2D([], [], color="#e3b341", linestyle=":", linewidth=1.2, label=f"Core (r <= {core_rad:.1f} px)"),
    ]
    ax0.legend(handles=leg0, loc="upper right", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8.5)

    # Panel 2: Residual + Corrected Spike Mask
    ax1.set_facecolor("#161b22")
    im1 = ax1.imshow(mag_res, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax)
    if corrected_mask is not None and np.any(corrected_mask):
        overlay_corr = np.zeros((ny, nx, 4), dtype=np.float32)
        overlay_corr[corrected_mask.astype(bool)] = [1.0, 0.35, 0.15, 0.50]  # Coral overlay
        ax1.imshow(overlay_corr, origin="lower")

    for ang in refined_spike_angles:
        rad = np.radians(ang)
        ax1.plot(
            [cx + r_start * np.cos(rad), cx + max_ray_len * np.cos(rad)],
            [cy + r_start * np.sin(rad), cy + max_ray_len * np.sin(rad)],
            linestyle="-",
            color="#ff7b72",
            linewidth=1.4,
            alpha=0.9,
        )
    ax1.add_patch(Circle((cx, cy), core_rad, fill=False, edgecolor="#e3b341", linestyle=":", linewidth=1.2))
    ax1.plot(cx, cy, "+", color="#ffffff", markersize=6, markeredgewidth=1.2)
    ax1.set_title("2. Residual Image + Corrected Spike Mask\n(Refined Empirical Ridges & Morphological Spikes)", color="#58a6ff", fontsize=11.5, fontweight="bold", pad=8)
    ax1.set_xlabel("X (pixels)", color="#e6edf3", fontsize=10)
    ax1.tick_params(colors="#8b949e", labelsize=9)
    for s in ax1.spines.values():
        s.set_color("#30363d")
    leg1 = [
        Patch(facecolor=(1.0, 0.35, 0.15, 0.5), edgecolor="#ff7b72", label="Corrected Mask"),
        Line2D([], [], color="#ff7b72", linestyle="-", linewidth=1.4, label=f"Refined Rays ({len(refined_spike_angles)})"),
        Line2D([], [], color="#e3b341", linestyle=":", linewidth=1.2, label=f"Core (r <= {core_rad:.1f} px)"),
    ]
    ax1.legend(handles=leg1, loc="upper right", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8.5)

    # Add colorbar for Panels 1 & 2
    cbar = fig.colorbar(im1, ax=ax1, fraction=0.046, pad=0.04)
    cbar.set_label("Surface Brightness (AB mag / arcsec$^2$)", color="#e6edf3", fontsize=9.5, labelpad=8)
    cbar.ax.tick_params(colors="#8b949e", labelsize=8.5)
    cbar.ax.invert_yaxis()

    # Panel 3: Intensity vs Angular Distribution (split into 0->180 top and 180->360 bottom)
    from romanepsf.profile import measure_angular_profile_torch

    comps = info.get("gaia_companions", [])
    if comp_mask is None:
        comp_mask = info.get("comp_mask", None)

    bin_centers, median_res_flx = measure_angular_profile_torch(
        image=residual,
        center=(cx, cy),
        dq_mask=dq_mask,
        comp_mask=comp_mask,
        companions=comps,
        core_rad=core_rad,
        r_min=1.0,
        r_max=None,
        num_bins=360,
    )

    valid_res = np.isfinite(median_res_flx)
    if np.any(valid_res):
        y_max = max(float(np.nanmax(median_res_flx)), 0.1) * 1.15
        y_min = min(float(np.nanmin(median_res_flx)), -0.05)
    else:
        y_max = 1.0
        y_min = -0.1

    flux_unit = "MJy/sr" if is_calibrated else "DN/s"

    # Panel 3a: Top Panel [0° to 180°]
    ax2_top.set_facecolor("#161b22")
    m_top = (bin_centers >= 0.0) & (bin_centers <= 180.0)
    ax2_top.plot(bin_centers[m_top], median_res_flx[m_top], color="#ffffff", linewidth=1.8, label=r"Residual Flux ($0^\circ \to 180^\circ$)", zorder=4)
    ax2_top.fill_between(bin_centers[m_top], 0, np.maximum(median_res_flx[m_top], 0), color="#58a6ff", alpha=0.25, zorder=3)

    first_theo_top = True
    for ang in base_spike_angles:
        if 0.0 <= ang <= 180.0:
            lbl = "Theoretical Rays" if first_theo_top else None
            ax2_top.axvline(ang, color="#388bfd", linestyle="--", linewidth=1.2, alpha=0.75, zorder=2, label=lbl)
            first_theo_top = False

    first_ref_top = True
    for ang in refined_spike_angles:
        if 0.0 <= ang <= 180.0:
            lbl = "Corrected Rays" if first_ref_top else None
            ax2_top.axvline(ang, color="#ff7b72", linestyle="-", linewidth=1.4, alpha=0.90, zorder=3, label=lbl)
            first_ref_top = False

    ax2_top.set_xlim(0.0, 180.0)
    ax2_top.set_xticks(np.arange(0, 181, 30))
    ax2_top.set_ylim(y_min, y_max)
    ax2_top.set_ylabel(f"Intensity ({flux_unit})", color="#e6edf3", fontsize=9.5)
    ax2_top.set_title(r"3a. Full-Image Azimuthal Intensity: $0^\circ \to 180^\circ$ (Excl. DQ & Gaia Stars)", color="#58a6ff", fontsize=11, fontweight="bold", pad=6)
    ax2_top.tick_params(colors="#8b949e", labelsize=8.5)
    for s in ax2_top.spines.values():
        s.set_color("#30363d")
    ax2_top.grid(True, color="#30363d", linestyle=":", alpha=0.6)
    ax2_top.legend(loc="upper right", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8.0)

    # Panel 3b: Bottom Panel [180° to 360°]
    ax2_bot.set_facecolor("#161b22")
    m_bot = (bin_centers >= 180.0) & (bin_centers <= 360.0)
    ax2_bot.plot(bin_centers[m_bot], median_res_flx[m_bot], color="#ffffff", linewidth=1.8, label=r"Residual Flux ($180^\circ \to 360^\circ$)", zorder=4)
    ax2_bot.fill_between(bin_centers[m_bot], 0, np.maximum(median_res_flx[m_bot], 0), color="#58a6ff", alpha=0.25, zorder=3)

    # Plot opposing half folded (+180 deg) in dotted gold to explicitly visualize symmetry!
    if np.any(m_top):
        ax2_bot.plot(bin_centers[m_top] + 180.0, median_res_flx[m_top], color="#e3b341", linestyle=":", linewidth=1.3, alpha=0.75, label=r"Opposing $0^\circ\to 180^\circ$ Reflected", zorder=3)

    first_theo_bot = True
    for ang in base_spike_angles:
        if 180.0 <= ang <= 360.0:
            lbl = "Theoretical Rays" if first_theo_bot else None
            ax2_bot.axvline(ang, color="#388bfd", linestyle="--", linewidth=1.2, alpha=0.75, zorder=2, label=lbl)
            first_theo_bot = False

    first_ref_bot = True
    for ang in refined_spike_angles:
        if 180.0 <= ang <= 360.0:
            lbl = "Corrected Rays" if first_ref_bot else None
            ax2_bot.axvline(ang, color="#ff7b72", linestyle="-", linewidth=1.4, alpha=0.90, zorder=3, label=lbl)
            first_ref_bot = False

    ax2_bot.set_xlim(180.0, 360.0)
    ax2_bot.set_xticks(np.arange(180, 361, 30))
    ax2_bot.set_ylim(y_min, y_max)
    ax2_bot.set_xlabel(r"Azimuthal Angle $\theta$ (degrees)", color="#e6edf3", fontsize=9.5)
    ax2_bot.set_ylabel(f"Intensity ({flux_unit})", color="#e6edf3", fontsize=9.5)
    ax2_bot.set_title(r"3b. Full-Image Azimuthal Intensity: $180^\circ \to 360^\circ$ (Symmetric Counterparts $\theta + 180^\circ$)", color="#58a6ff", fontsize=11, fontweight="bold", pad=6)
    ax2_bot.tick_params(colors="#8b949e", labelsize=8.5)
    for s in ax2_bot.spines.values():
        s.set_color("#30363d")
    ax2_bot.grid(True, color="#30363d", linestyle=":", alpha=0.6)
    ax2_bot.legend(loc="upper right", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8.0)

    fig.suptitle(
        f"Diffraction Spike Refinement Diagnostic — {tier} Star {source_id} (Mag={mag:.2f})",
        color="#ffffff",
        fontsize=13.5,
        fontweight="bold",
        y=0.98,
    )

    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    logger.info(f"Generated Spike Process Debug Figure: {output_path}")
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
            "gaia_center_stamp": dbg.get("gaia_center_stamp", center_xy),
            "center_stamp": center_xy,
            "gaia_ra": dbg.get("gaia_ra", None),
            "gaia_dec": dbg.get("gaia_dec", None),
            "shift_px": dbg.get("shift_px", None),
            "pixel_scale": dbg.get("pixel_scale", 0.11),
            "gaia_detector_xy": dbg.get("gaia_detector_xy", None),
            "meas_detector_xy": dbg.get("meas_detector_xy", None),
            "spike_details": dbg.get("spike_details", None),
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

        # Generate Spike Process Diagnostic Figure per star
        fig_spike_star_path = debug_dir / f"debug_spike_process_{tier_name}_{sid}.png"
        generate_debug_figure_spike_process(
            stamp=stamp_img,
            residual=res_map,
            output_path=fig_spike_star_path,
            conversion_factor=conv,
            star_info=star_meta,
            is_calibrated=is_cal,
            center_xy=center_xy,
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

            fig_spike_canon = debug_dir / "debug_spike_process.png"
            generate_debug_figure_spike_process(
                stamp=stamp_img,
                residual=res_map,
                output_path=fig_spike_canon,
                conversion_factor=conv,
                star_info=star_meta,
                is_calibrated=is_cal,
                center_xy=center_xy,
            )
            generated_files["debug_spike_process"] = fig_spike_canon

            fig6_canon = debug_dir / "debug_6_spike_process.png"
            generate_debug_figure_spike_process(
                stamp=stamp_img,
                residual=res_map,
                output_path=fig6_canon,
                conversion_factor=conv,
                star_info=star_meta,
                is_calibrated=is_cal,
                center_xy=center_xy,
            )
            generated_files["debug_6_spike_process"] = fig6_canon

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
    "generate_debug_figure_spike_process",
    "generate_all_debug_plots",
]
