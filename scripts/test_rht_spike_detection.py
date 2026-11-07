"""
Star-Centered Rolling Hough Transform (RHT) Spike Detection & Masking Test.

Applies:
  1. Sharp mask (unsharp high-pass filtering via normalized Gaussian convolution)
  2. Star-Centered Radial Rolling Hough Transform with antipodal symmetry folding
  3. Peak detection to identify empirical diffraction spike angles
  4. 2D Spike Mask generation and overlay on science stamps across bright, medium, and faint stars.
"""

from typing import Tuple, Optional, Sequence
import numpy as np
import pandas as pd
from scipy.ndimage import map_coordinates, gaussian_filter
from scipy.signal import find_peaks
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_pdf import PdfPages
from pathlib import Path

from romanepsf.loader import load_l2_image
from romanepsf.stamps import (
    extract_cutout,
    estimate_stamp_background,
    subtract_stamp_background,
    get_adaptive_stamp_size,
)
from romanepsf.masking import (
    compute_unsharp_mask_residual,
    get_all_spike_angles,
    mask_gaia_companion_stars,
)
from romanepsf.catalog import project_catalog_to_pixels


def radial_hough_transform(
    sharp_image: np.ndarray,
    center: Tuple[float, float],
    r_min: float = 8.0,
    r_max: Optional[float] = None,
    num_angles: int = 720,
    symmetric_fold: bool = True,
    corridor_half_width_px: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute Star-Centered Radial Rolling Hough Transform (RHT) along rays radiating from center.

    Parameters
    ----------
    sharp_image : np.ndarray
        2D high-pass unsharp flux image.
    center : (cx, cy)
        Stellar centroid in pixel coordinates.
    r_min : float, default 8.0
        Inner radius to avoid the saturated core.
    r_max : float, optional
        Outer radius for integration.
    num_angles : int, default 720
        Number of angular samples in [0, 360).
    symmetric_fold : bool, default True
        If True, adds antipodal rays (theta and theta + 180 deg) to exploit
        physical opposing spider strut symmetry and suppress asymmetric contaminants.
    corridor_half_width_px : float, default 1.0
        Half-width for transverse integration across the ray.

    Returns
    -------
    angles_deg : np.ndarray
        Angle grid in degrees [0, 360).
    rht_power : np.ndarray
        Normalized RHT accumulator intensity as a function of angle.
    """
    ny, nx = sharp_image.shape
    cx, cy = center
    if r_max is None:
        r_max = min(cx, cy, nx - cx - 1, ny - cy - 1) * 0.9

    thetas_deg = np.linspace(0, 360.0, num_angles, endpoint=False)
    num_radial = max(int(r_max - r_min), 15)
    radii = np.linspace(r_min, r_max, num_radial)

    clean_sharp = np.nan_to_num(sharp_image, nan=0.0)
    
    # We sample 3 parallel lines across width: [-w, 0, +w]
    offsets = [-corridor_half_width_px, 0.0, corridor_half_width_px] if corridor_half_width_px > 0 else [0.0]
    
    rht_power = np.zeros(num_angles, dtype=np.float64)

    for i, th_deg in enumerate(thetas_deg):
        th = np.radians(th_deg)
        cos_t, sin_t = np.cos(th), np.sin(th)
        perp_x, perp_y = -sin_t, cos_t
        
        line_sum = 0.0
        for off in offsets:
            xs = cx + radii * cos_t + off * perp_x
            ys = cy + radii * sin_t + off * perp_y
            v = map_coordinates(clean_sharp, [ys, xs], order=1, mode="constant", cval=0.0)
            # Accumulate positive high-pass flux along ray
            line_sum += np.sum(np.maximum(v, 0.0))
            
        rht_power[i] = line_sum / (len(offsets) * num_radial)

    if symmetric_fold:
        half_shift = num_angles // 2
        rht_power = 0.5 * (rht_power + np.roll(rht_power, half_shift))

    # Normalize power to [0, 1]
    p_min, p_max = np.min(rht_power), np.max(rht_power)
    if p_max > p_min:
        rht_norm = (rht_power - p_min) / (p_max - p_min)
    else:
        rht_norm = rht_power

    return thetas_deg, rht_norm


def detect_spikes_rht(
    sharp_image: np.ndarray,
    center: Tuple[float, float],
    r_min: float = 8.0,
    r_max: Optional[float] = None,
    min_peak_distance_deg: float = 6.0,
    prominence_rel: float = 0.15,
    symmetric_fold: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Detect empirical spike angles from RHT angular power spectrum peaks.
    """
    angles_deg, rht_power = radial_hough_transform(
        sharp_image,
        center,
        r_min=r_min,
        r_max=r_max,
        num_angles=720,
        symmetric_fold=symmetric_fold,
    )
    
    dist_bins = int(round(min_peak_distance_deg / (360.0 / len(angles_deg))))
    prominence = max(prominence_rel * (np.percentile(rht_power, 85) - np.percentile(rht_power, 15)), 0.02)
    
    if symmetric_fold:
        # Find peaks in [0, 180) and expand antipodally to [0, 360)
        idx_180 = len(angles_deg) // 2
        angles_180 = angles_deg[:idx_180]
        power_180 = rht_power[:idx_180]
        
        pad = 20
        wrapped_power = np.concatenate([power_180[-pad:], power_180, power_180[:pad]])
        peaks, _ = find_peaks(wrapped_power, distance=dist_bins, prominence=prominence)
        
        valid_peaks_180 = []
        for p in peaks:
            idx = p - pad
            if 0 <= idx < len(angles_180):
                valid_peaks_180.append(idx)
                
        base_angles = angles_180[valid_peaks_180]
        detected_angles = np.sort(np.unique(np.concatenate([base_angles, (base_angles + 180.0) % 360.0])))
    else:
        pad = 30
        wrapped_power = np.concatenate([rht_power[-pad:], rht_power, rht_power[:pad]])
        peaks, _ = find_peaks(wrapped_power, distance=dist_bins, prominence=prominence)
        valid_peaks = []
        for p in peaks:
            idx = p - pad
            if 0 <= idx < len(angles_deg):
                valid_peaks.append(idx)
        detected_angles = angles_deg[valid_peaks]
        
    return detected_angles, angles_deg, rht_power


def create_rht_spike_mask(
    shape: Tuple[int, int],
    center: Tuple[float, float],
    detected_angles_deg: np.ndarray,
    sharp_image: Optional[np.ndarray] = None,
    angular_half_width_deg: float = 1.8,
    spike_width_px: float = 6.0,
    r_min: float = 6.0,
    r_max: Optional[float] = None,
    adaptive_flux_filter: bool = True,
) -> np.ndarray:
    """
    Create 2D binary spike mask from detected RHT angles.
    """
    ny, nx = shape
    cx, cy = center
    gy, gx = np.ogrid[:ny, :nx]
    dx = gx - cx
    dy = gy - cy
    r = np.hypot(dx, dy)
    
    if r_max is None:
        r_max = np.hypot(cx, cy)
        
    pixel_angles = (np.degrees(np.arctan2(dy, dx)) + 360.0) % 360.0
    
    spike_mask = np.zeros(shape, dtype=bool)
    
    for ang in detected_angles_deg:
        ang_rad = np.radians(ang)
        cos_a, sin_a = np.cos(ang_rad), np.sin(ang_rad)
        
        # Angular difference
        ang_diff = np.abs((pixel_angles - ang + 180.0) % 360.0 - 180.0)
        
        # Perpendicular distance to ray
        # line passes through (cx, cy) along direction (cos_a, sin_a)
        # signed perpendicular distance = dx * (-sin_a) + dy * cos_a
        d_perp = np.abs(-dx * sin_a + dy * cos_a)
        d_along = dx * cos_a + dy * sin_a
        
        in_corridor = (ang_diff <= angular_half_width_deg) | (d_perp <= (spike_width_px / 2.0))
        in_ray = in_corridor & (d_along >= r_min) & (r <= r_max)
        
        if adaptive_flux_filter and sharp_image is not None:
            # Require positive sharp flux or close to ray axis (within 1.5 px)
            close_axis = d_perp <= 1.5
            pos_flux = sharp_image > 0.0
            in_ray &= (close_axis | pos_flux)
            
        spike_mask |= in_ray
        
    return spike_mask


def test_rht_on_stars():
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "rht_spike_detection_results.pdf"
    
    df = pd.read_csv("output/run_all/all_stars_tiered.csv")
    
    # Test cases: 2 bright stars, 1 medium star, 1 faint star
    test_stars = [
        {"det": "WFI01", "tier": "bright", "desc": "Bright Star with Multi-Order Spikes & 13 Gaia Companions"},
        {"det": "WFI05", "tier": "bright", "desc": "Brightest Roman Commissioning Star (mag=7.37)"},
        {"det": "WFI02", "tier": "medium", "desc": "Medium Star with Spikes & Neighbor"},
        {"det": "WFI05", "tier": "faint", "desc": "Faint Star (Low-SNR Spikes Verification)"},
    ]
    
    print(f"=== Running Sharp Mask + RHT Spike Detection Test on {len(test_stars)} Stars ===")
    
    loaded_l2 = {}
    loaded_gaia = {}
    
    results = []
    
    for star_spec in test_stars:
        det = star_spec["det"]
        tier = star_spec["tier"]
        
        if det not in loaded_l2:
            cal_path = f"/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_{det.lower()}_f146_cal.asdf"
            l2 = load_l2_image(cal_path)
            g = pd.read_csv(f"cache/gaia_dr3_{det.lower()}_g20.csv")
            g_pix = project_catalog_to_pixels(l2, g)
            loaded_l2[det] = l2
            loaded_gaia[det] = g_pix
            
        l2 = loaded_l2[det]
        gaia_pix = loaded_gaia[det]
        
        sub = df[(df["detector"] == det) & (df["tier"].str.lower() == tier)]
        row = sub.iloc[0]
        
        cx, cy = float(row["x"]), float(row["y"])
        mag = float(row["mag_lambda"])
        source_id = row.get("source_id", "Star")
        
        sz = get_adaptive_stamp_size(mag, tier, max_size=1001, pixel_scale=0.11)
        raw_cutout, (ix, iy) = extract_cutout(l2.data, (cx, cy), sz, fill_value=np.nan)
        raw_dq, _ = extract_cutout(l2.dq, (cx, cy), sz, fill_value=1)
        dq_mask = (raw_dq & 1) > 0
        
        core_rad = 6.0 if tier == "bright" else 4.0
        if tier == "faint":
            half_idx = (sz - 1) // 2
            gy, gx = np.indices((sz, sz))
            r_c = np.hypot(gx - half_idx, gy - half_idx)
            valid_core = (r_c <= core_rad) & np.isfinite(raw_cutout) & (raw_cutout > 0)
            dq_mask[valid_core] = False
            
        bkg_val, _ = estimate_stamp_background(raw_cutout, mask=dq_mask, method="annulus")
        flux_sub = subtract_stamp_background(raw_cutout, bkg_val)
        
        # 1. Compute Sharp Mask (Unsharp Residual)
        sharp_sigma = min(max(sz / 50.0, 4.0), 7.0)
        unsharp_res = compute_unsharp_mask_residual(flux_sub, sigma=sharp_sigma, dq_mask=dq_mask)
        
        # 2. RHT Spike Detection
        half = (sz - 1) / 2.0
        r_min = core_rad + 2.0
        r_max = min(half * 0.90, 350.0)
        
        det_angles, angles_grid, rht_power = detect_spikes_rht(
            unsharp_res,
            (half, half),
            r_min=r_min,
            r_max=r_max,
            min_peak_distance_deg=6.0,
            prominence_rel=0.20,
            symmetric_fold=True,
        )
        
        # Theoretical angles for comparison
        net_rot = float(getattr(l2, "pa_aperture", l2.meta.get("roll_ref", -110.02))) - 9.70
        theo_angles = get_all_spike_angles(net_rot)
        
        # 3. Create RHT Spike Mask
        rht_spike_mask = create_rht_spike_mask(
            flux_sub.shape,
            (half, half),
            det_angles,
            sharp_image=unsharp_res,
            angular_half_width_deg=1.8,
            spike_width_px=6.0,
            r_min=r_min,
            r_max=r_max,
            adaptive_flux_filter=False,
        )
        
        # Include central core in protection
        gy, gx = np.ogrid[:sz, :sz]
        r_pix = np.hypot(gx - half, gy - half)
        rht_spike_mask |= (r_pix <= core_rad)
        
        # Contaminants detection outside RHT spike mask
        clean_outside = (~rht_spike_mask) & (~dq_mask) & np.isfinite(unsharp_res)
        from astropy.stats import sigma_clipped_stats
        import cv2
        _, med, std = sigma_clipped_stats(unsharp_res[clean_outside], sigma=3.0, maxiters=5)
        raw_contam = (unsharp_res > med + 1.5 * std).astype(np.uint8)
        contam_clean = cv2.dilate(cv2.erode(raw_contam, np.ones((1, 1), np.uint8)), np.ones((3, 3), np.uint8)).astype(bool)
        contam_clean[rht_spike_mask] = False
        
        # Circular Gaia companions
        comp_mask = mask_gaia_companion_stars(
            flux_sub.shape,
            (half, half),
            gaia_pix,
            target_center_xy=(cx, cy),
            pixel_scale=0.11,
            depth=28.0,
            core_exclusion_radius_px=core_rad,
        )
        
        final_full_mask = contam_clean | comp_mask | dq_mask | (~np.isfinite(flux_sub))
        
        print(f"Star {det} {tier.capitalize()} (mag={mag:.2f}, {sz}x{sz}):")
        print(f"  -> RHT detected {len(det_angles)} spike rays")
        print(f"  -> RHT Spike Mask covers: {np.sum(rht_spike_mask):,} pixels ({100*np.sum(rht_spike_mask)/flux_sub.size:.1f}%)")
        print(f"  -> Final Mask covers: {np.sum(final_full_mask):,} pixels ({100*np.sum(final_full_mask)/flux_sub.size:.1f}%)")
        
        results.append({
            "spec": star_spec,
            "det": det,
            "tier": tier,
            "mag": mag,
            "sz": sz,
            "flux": flux_sub,
            "unsharp": unsharp_res,
            "angles_grid": angles_grid,
            "rht_power": rht_power,
            "det_angles": det_angles,
            "theo_angles": theo_angles,
            "rht_spike_mask": rht_spike_mask,
            "final_full_mask": final_full_mask,
        })
        
    # Render Multi-Page PDF & PNGs
    print(f"\nRendering diagnostic visualization to {pdf_path}...")
    with PdfPages(str(pdf_path)) as pdf:
        for idx, res in enumerate(results):
            fig = plt.figure(figsize=(18, 10), dpi=150)
            fig.patch.set_facecolor("#0e1117")
            
            gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.0], hspace=0.32, wspace=0.25, top=0.91, bottom=0.08, left=0.06, right=0.95)
            
            flux = res["flux"]
            unsharp = res["unsharp"]
            spike_mask = res["rht_spike_mask"]
            full_mask = res["final_full_mask"]
            sz = res["sz"]
            tier_str = res["tier"].capitalize()
            det = res["det"]
            mag = res["mag"]
            
            # Stretch
            pos_flux = flux[np.isfinite(flux) & (flux > 0)]
            vmin = np.percentile(pos_flux, 2) if len(pos_flux) > 0 else 1e-4
            vmax = np.percentile(pos_flux, 99.8) if len(pos_flux) > 0 else 1.0
            norm_flux = LogNorm(vmin=max(vmin, 1e-4), vmax=max(vmax, 1e-2))
            
            # Panel 1: Normal Stamp
            ax1 = fig.add_subplot(gs[0, 0])
            ax1.set_facecolor("#161b22")
            im1 = ax1.imshow(np.maximum(flux, 1e-4), origin="lower", cmap="inferno", norm=norm_flux)
            ax1.set_title(f"1. Normal Stamp ({det} {tier_str}, mag={mag:.2f})\nSize: {sz}x{sz} pixels", color="#e6edf3", fontsize=11, fontweight="bold")
            ax1.tick_params(colors="#8b949e", labelsize=8)
            cb1 = plt.colorbar(im1, ax=ax1, fraction=0.046, pad=0.03)
            cb1.ax.tick_params(colors="#8b949e", labelsize=7.5)
            cb1.set_label("Flux (MJy/sr)", color="#8b949e", fontsize=8)
            
            # Panel 2: Sharp Mask (Unsharp Residual)
            ax2 = fig.add_subplot(gs[0, 1])
            ax2.set_facecolor("#161b22")
            clean_unsharp = np.maximum(unsharp, 1e-4)
            im2 = ax2.imshow(clean_unsharp, origin="lower", cmap="inferno", norm=norm_flux)
            ax2.set_title(f"2. Sharp Mask (Unsharp High-Pass)\nDiffuse Halo Removed, Spikes Isolated", color="#e6edf3", fontsize=11, fontweight="bold")
            ax2.tick_params(colors="#8b949e", labelsize=8)
            cb2 = plt.colorbar(im2, ax=ax2, fraction=0.046, pad=0.03)
            cb2.ax.tick_params(colors="#8b949e", labelsize=7.5)
            cb2.set_label("High-Pass Flux", color="#8b949e", fontsize=8)
            
            # Panel 3: RHT Angular Power Spectrum
            ax3 = fig.add_subplot(gs[0, 2])
            ax3.set_facecolor("#161b22")
            ax3.plot(res["angles_grid"], res["rht_power"], color="#58a6ff", lw=1.6, label="RHT Power Spectrum $RHT(\\theta)$")
            
            # Mark theoretical angles
            for t_idx, tang in enumerate(res["theo_angles"]):
                lbl = "Theoretical 24 Rays" if t_idx == 0 else ""
                ax3.axvline(tang, color="#3fb950", ls="--", lw=0.9, alpha=0.55, label=lbl)
                
            # Mark detected RHT peaks
            p_angles = res["det_angles"]
            p_powers = [res["rht_power"][np.argmin(np.abs(res["angles_grid"] - a))] for a in p_angles]
            ax3.plot(p_angles, p_powers, "ro", markersize=5.5, label=f"RHT Detected Spikes ({len(p_angles)})")
            
            ax3.set_xlim(0, 360)
            ax3.set_ylim(-0.05, 1.1)
            ax3.set_xlabel("Angle $\\theta$ (degrees)", color="#8b949e", fontsize=9)
            ax3.set_ylabel("Normalized RHT Power", color="#8b949e", fontsize=9)
            ax3.set_title(f"3. Star-Centered RHT Spectrum\nDetected {len(p_angles)} Rays vs 24 Nominal", color="#e6edf3", fontsize=11, fontweight="bold")
            ax3.tick_params(colors="#8b949e", labelsize=8)
            ax3.legend(loc="upper right", fontsize=8, facecolor="#0e1117", edgecolor="#30363d", labelcolor="#c9d1d9")
            ax3.grid(True, color="#30363d", ls=":", alpha=0.5)
            
            # Panel 4: RHT Spike Mask
            ax4 = fig.add_subplot(gs[1, 0])
            ax4.set_facecolor("#161b22")
            im4 = ax4.imshow(spike_mask.astype(int), origin="lower", cmap="Blues_r")
            ax4.set_title(f"4. RHT Diffraction Spike Mask\nPreserved Spike Area: {100*np.sum(spike_mask)/flux.size:.1f}%", color="#e6edf3", fontsize=11, fontweight="bold")
            ax4.tick_params(colors="#8b949e", labelsize=8)
            cb4 = plt.colorbar(im4, ax=ax4, fraction=0.046, pad=0.03)
            cb4.ax.tick_params(colors="#8b949e", labelsize=7.5)
            cb4.set_label("Spike Protected (1=Yes)", color="#8b949e", fontsize=8)
            
            # Panel 5: Normal Stamp + RHT Spike Overlay
            ax5 = fig.add_subplot(gs[1, 1])
            ax5.set_facecolor("#161b22")
            ax5.imshow(np.maximum(flux, 1e-4), origin="lower", cmap="inferno", norm=norm_flux)
            
            # Overlay RHT spike rays in cyan
            spike_overlay = np.zeros((*flux.shape, 4), dtype=float)
            spike_overlay[spike_mask] = [0.0, 0.95, 0.95, 0.45] # cyan overlay
            ax5.imshow(spike_overlay, origin="lower")
            ax5.set_title(f"5. Normal Stamp + RHT Spikes (Cyan)\nSpikes Faithfully Traced from Center", color="#e6edf3", fontsize=11, fontweight="bold")
            ax5.tick_params(colors="#8b949e", labelsize=8)
            cb5 = plt.colorbar(im1, ax=ax5, fraction=0.046, pad=0.03)
            cb5.ax.tick_params(colors="#8b949e", labelsize=7.5)
            cb5.set_label("Flux (MJy/sr)", color="#8b949e", fontsize=8)
            
            # Panel 6: Final Full Mask Overlay (Spikes Preserved, Contaminants & Comps in Yellow)
            ax6 = fig.add_subplot(gs[1, 2])
            ax6.set_facecolor("#161b22")
            ax6.imshow(np.maximum(flux, 1e-4), origin="lower", cmap="inferno", norm=norm_flux)
            
            mask_overlay = np.zeros((*flux.shape, 4), dtype=float)
            mask_overlay[full_mask] = [1.0, 0.92, 0.0, 0.55] # yellow overlay
            ax6.imshow(mask_overlay, origin="lower")
            ax6.set_title(f"6. Final Clean Mask (Yellow)\nContaminants & Comps Masked: {100*np.sum(full_mask)/flux.size:.1f}%", color="#e6edf3", fontsize=11, fontweight="bold")
            ax6.tick_params(colors="#8b949e", labelsize=8)
            cb6 = plt.colorbar(im1, ax=ax6, fraction=0.046, pad=0.03)
            cb6.ax.tick_params(colors="#8b949e", labelsize=7.5)
            cb6.set_label("Flux (MJy/sr)", color="#8b949e", fontsize=8)
            
            fig.suptitle(
                f"Roman Spike Detection via Sharp Mask + RHT — Case {idx+1}: {res['spec']['desc']}",
                fontsize=13.5, color="#58a6ff", fontweight="bold", y=0.965
            )
            
            det_str = res["det"].lower()
            tier_str_file = res["tier"].lower()
            png_path = out_dir / f"rht_spike_test_star_{idx+1}_{det_str}_{tier_str_file}.png"
            fig.savefig(str(png_path), dpi=150, facecolor=fig.get_facecolor(), edgecolor="none")
            print(f"Saved PNG preview to {png_path}")
            
            pdf.savefig(fig, facecolor=fig.get_facecolor(), edgecolor="none")
            plt.close(fig)
            
    print(f"\nSUCCESS: Generated {pdf_path} ({pdf_path.stat().st_size / 1024:.1f} KB, {len(results)} pages)")


if __name__ == "__main__":
    test_rht_on_stars()
