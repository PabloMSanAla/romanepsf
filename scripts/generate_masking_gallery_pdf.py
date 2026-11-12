"""
Generate Publication-Quality PDF Report Demonstrating Gaia Companion Masking,
Moffat & Sérsic Profile Residual Fitting, MTO2 Max-Tree Object Representation & Deblending,
and Roman Diffraction Spike Protection.

Visualizes 4 panels per star:
  1. Normal: Log stretched stamp flux
  2. Moffat Residual Map: 2-iteration AstroPhot Moffat profile residual (delta I = I_obs - I_moffat)
  3. Sérsic Residual Map: 2D Sérsic profile residual (delta I = I_obs - I_sersic)
  4. Normal + Mask Overlay: Stamp flux with semi-transparent uniform yellow overlay highlighting
     MTO2 max-tree segmented contaminant sources & circular Gaia companion apertures, strictly
     preserving Roman diffraction spikes and stellar core.
"""

import argparse
import os
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from scipy.ndimage import label
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_pdf import PdfPages

from romanepsf.loader import load_l2_image, RomanL2Data
from romanepsf.catalog import (
    project_catalog_to_pixels,
    query_gaia_for_detector,
    get_psf_extension_moffat,
)
from romanepsf.stamps import (
    get_adaptive_stamp_size,
    extract_cutout,
    estimate_stamp_background,
    subtract_stamp_background,
)
from romanepsf.masking import (
    mask_contaminants_with_spikes_protected,
    mask_gaia_companion_stars,
    fit_moffat_model,
    fit_sersic_model,
)
from romanepsf.config import load_config


def select_sample_stars(tiered_catalog_path: str, n_bright: int = 10, n_medium: int = 8, n_faint: int = 2):
    """Select a representative set of ~20 stars (mostly bright and medium, plus faint) across detectors."""
    df = pd.read_csv(tiered_catalog_path)
    
    # Priority detectors with cached Gaia data
    preferred_detectors = ["WFI01", "WFI02", "WFI04", "WFI05", "WFI09", "WFI10", "WFI12"]
    
    selected_rows = []
    
    for tier, count in [("bright", n_bright), ("medium", n_medium), ("faint", n_faint)]:
        sub = df[df["tier"].str.lower() == tier].copy()
        # Sort by preferred detectors first, then magnitude
        sub["is_pref"] = sub["detector"].isin(preferred_detectors)
        sub = sub.sort_values(by=["is_pref", "mag_lambda"], ascending=[False, True])
        
        # Pick stars from different detectors if possible
        picked = []
        used_dets = set()
        for _, row in sub.iterrows():
            det = row["detector"]
            if det not in used_dets:
                picked.append(row)
                used_dets.add(det)
                if len(picked) == count:
                    break
        
        # If not enough, fill from remaining
        if len(picked) < count:
            for _, row in sub.iterrows():
                if not any(r["source_id"] == row["source_id"] for r in picked):
                    picked.append(row)
                    if len(picked) == count:
                        break
        selected_rows.extend(picked)
        
    return pd.DataFrame(selected_rows)


def main():
    parser = argparse.ArgumentParser(description="Generate PDF masking report across sample stars.")
    parser.add_argument("--method", type=str, default="moffat", choices=["moffat", "sersic", "compound", "mto2", "superback", "stpsf", "unsharp"], help="Primary residual subtraction method")
    parser.add_argument("--contaminant-detector", type=str, default="mto2", choices=["mto2", "erosion_dilation"], help="Contaminant detection algorithm")
    parser.add_argument("--n-bright", type=int, default=10, help="Number of bright stars")
    parser.add_argument("--n-medium", type=int, default=8, help="Number of medium stars")
    parser.add_argument("--n-faint", type=int, default=2, help="Number of faint stars")
    parser.add_argument("--output-pdf", type=str, default=None, help="Custom output PDF path")
    args = parser.parse_args()

    print(f"=== Starting Roman ePSF Masking PDF Generator (Fitting: Moffat & Sérsic, Detector: {args.contaminant_detector.upper()}) ===")
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = Path(args.output_pdf) if args.output_pdf else out_dir / "gaia_masking_gallery.pdf"
    
    cfg = load_config("configs/default.yaml")
    cfg.spikes.spike_order = "both"
    cfg.spikes.contaminant_detector = args.contaminant_detector
    
    tiered_csv = Path("output/run_all/all_stars_tiered.csv")
    if not tiered_csv.exists():
        tiered_csv = Path("output/all_stars_tiered.csv")
    if not tiered_csv.exists():
        raise FileNotFoundError("Could not locate all_stars_tiered.csv")
        
    sample_df = select_sample_stars(str(tiered_csv), n_bright=args.n_bright, n_medium=args.n_medium, n_faint=args.n_faint)
    print(f"Selected {len(sample_df)} stars across tiers:")
    for tier in ["bright", "medium", "faint"]:
        cnt = len(sample_df[sample_df["tier"].str.lower() == tier])
        dets = sample_df[sample_df["tier"].str.lower() == tier]["detector"].tolist()
        print(f"  - {tier.capitalize()}: {cnt} stars (Detectors: {dets})")

    # Cache loaded detectors and Gaia catalogs to avoid reloading
    loaded_l2 = {}
    loaded_gaia = {}
    
    def get_detector_data(det_name: str):
        det_lower = det_name.lower()
        if det_lower not in loaded_l2:
            cal_path = f"/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_{det_lower}_f146_cal.asdf"
            print(f"Loading detector {det_name} from {os.path.basename(cal_path)}...")
            l2 = load_l2_image(cal_path)
            loaded_l2[det_lower] = l2
            
            # Load Gaia catalog
            gaia_df = query_gaia_for_detector(l2, mag_limit=20.0, cache_dir="cache")
            gaia_pix = project_catalog_to_pixels(l2, gaia_df)
            loaded_gaia[det_lower] = gaia_pix
            print(f"  -> {len(gaia_pix)} Gaia stars in active area for {det_name}")
            
        return loaded_l2[det_lower], loaded_gaia[det_lower]

    processed_stars = []
    
    for idx, (_, row) in enumerate(sample_df.iterrows()):
        det = str(row["detector"])
        mag = float(row["mag_lambda"])
        tier = str(row["tier"]).lower()
        cx, cy = float(row["x"]), float(row["y"])
        source_id = row.get("source_id", f"Star_{idx+1}")
        
        l2, gaia_pix = get_detector_data(det)
        
        sz = get_adaptive_stamp_size(mag, tier, max_size=1001, pixel_scale=0.11)
        raw_cutout, (ix, iy) = extract_cutout(l2.data, (cx, cy), sz, fill_value=np.nan)
        raw_dq, _ = extract_cutout(l2.dq, (cx, cy), sz, fill_value=1)
        vp_cutout = None
        if getattr(l2, "var_poisson", None) is not None:
            vp_cutout, _ = extract_cutout(l2.var_poisson, (cx, cy), sz, fill_value=np.nan)
        
        dq_mask = (raw_dq & 1) > 0  # Saturated or bad
        core_rad = 6.0 if tier == "bright" else 4.0
        
        # Protect faint cores from DQ bit 1
        if tier == "faint":
            half = (sz - 1) // 2
            gy, gx = np.indices((sz, sz))
            r_c = np.hypot(gx - half, gy - half)
            valid_core = (r_c <= core_rad) & np.isfinite(raw_cutout) & (raw_cutout > 0)
            dq_mask[valid_core] = False
            
        bkg_val, bkg_rms = estimate_stamp_background(raw_cutout, mask=dq_mask, method="annulus")
        flux_sub = subtract_stamp_background(raw_cutout, bkg_val)
        
        roll_ref = float(getattr(l2, "pa_aperture", l2.meta.get("roll_ref", -110.02)))
        
        # Find companion stars inside stamp for stats and exclusion
        half = (sz - 1) // 2
        dx = gaia_pix["x"] - cx
        dy = gaia_pix["y"] - cy
        dist = np.hypot(dx, dy)
        in_stamp = (dist > core_rad) & (np.abs(dx) <= half + 10) & (np.abs(dy) <= half + 10)
        n_comps = int(np.sum(in_stamp))

        # Compute companion circular mask separately for fitting exclusion and reporting
        comp_only_mask = mask_gaia_companion_stars(
            flux_sub.shape,
            ((sz - 1) / 2.0, (sz - 1) / 2.0),
            gaia_pix,
            target_center_xy=(cx, cy),
            pixel_scale=l2.pixel_scale,
            depth=28.0,
            core_exclusion_radius_px=core_rad,
        )

        # 1. Fit Moffat profile & detect contaminants with MTO2
        final_mask, protected_spikes, res_moffat = mask_contaminants_with_spikes_protected(
            flux_sub,
            dq_mask=dq_mask,
            pa_aperture=roll_ref,
            cfg=cfg.spikes,
            tier=tier,
            companion_stars=gaia_pix,
            target_center_xy=(cx, cy),
            pixel_scale=l2.pixel_scale,
            companion_depth=28.0,
            method="moffat",
            contaminant_detector=args.contaminant_detector,
            detector=det,
            bandpass="F146",
            var_poisson=vp_cutout,
            n_iterations=2,
        )

        # 2. Fit Sérsic profile
        if tier == "faint":
            res_sersic = flux_sub.copy()
        else:
            sersic_img, _ = fit_sersic_model(
                flux_sub,
                dq_mask=dq_mask,
                max_radius=min(max(half * 0.4, 30.0), 100.0),
                min_radius=core_rad,
                mask=comp_only_mask,
                variance=vp_cutout,
                bkg_rms=bkg_rms,
                engine="astrophot",
            )
            res_sersic = (flux_sub - sersic_img).astype(np.float32)

        masked_pct = 100.0 * np.sum(final_mask) / flux_sub.size
        prot_pct = 100.0 * np.sum(protected_spikes) / flux_sub.size
        comp_masked_px = int(np.sum(comp_only_mask))

        # Count isolated contaminant source islands
        contam_pixels = final_mask & (~protected_spikes)
        if dq_mask is not None:
            contam_pixels &= (~dq_mask)
        contam_pixels &= np.isfinite(flux_sub)
        _, n_islands = label(contam_pixels)
        
        print(f"[{idx+1:02d}/{len(sample_df)}] {tier.upper():6s} Star {source_id} ({det}, mag={mag:.2f}, {sz}x{sz}): "
              f"Masked={masked_pct:.1f}%, Prot={prot_pct:.1f}%, Comps={n_comps} ({comp_masked_px} px), Islands={n_islands}")
              
        processed_stars.append({
            "idx": idx + 1,
            "source_id": source_id,
            "detector": det,
            "tier": tier,
            "mag": mag,
            "size": sz,
            "flux": flux_sub,
            "res_moffat": res_moffat,
            "res_sersic": res_sersic,
            "final_mask": final_mask,
            "protected_spikes": protected_spikes,
            "comp_mask": comp_only_mask,
            "n_comps": n_comps,
            "n_islands": n_islands,
            "masked_pct": masked_pct,
            "prot_pct": prot_pct,
        })

    # Render Multi-Page PDF
    print(f"\nRendering PDF report to {pdf_path}...")
    stars_per_page = 3
    num_pages = int(np.ceil(len(processed_stars) / stars_per_page))
    
    with PdfPages(str(pdf_path)) as pdf:
        for page_idx in range(num_pages):
            page_stars = processed_stars[page_idx * stars_per_page : (page_idx + 1) * stars_per_page]
            n_rows = len(page_stars)
            
            fig, axes = plt.subplots(n_rows, 4, figsize=(18.5, 4.4 * n_rows), dpi=150)
            if n_rows == 1:
                axes = np.expand_dims(axes, 0)
                
            fig.patch.set_facecolor("#0e1117")
            
            for row_idx, star in enumerate(page_stars):
                flux = star["flux"]
                res_m = star["res_moffat"]
                res_s = star["res_sersic"]
                mask = star["final_mask"]
                comp_mask = star["comp_mask"]
                star_tier = star["tier"].lower()
                tier_str = star["tier"].capitalize()
                
                # Flux normalization
                pos_flux = flux[np.isfinite(flux) & (flux > 0)]
                vmin = np.percentile(pos_flux, 2) if len(pos_flux) > 0 else 1e-4
                vmax = np.percentile(pos_flux, 99.8) if len(pos_flux) > 0 else 1.0
                if vmin <= 0:
                    vmin = 1e-4
                if vmax <= vmin:
                    vmax = vmin * 100.0
                norm_flux = LogNorm(vmin=max(vmin, 1e-4), vmax=max(vmax, 1e-2))
                
                # ----------------- Panel 1: Normal Stamp -----------------
                ax_norm = axes[row_idx, 0]
                ax_norm.set_facecolor("#161b22")
                clean_disp = np.maximum(flux, 1e-4)
                im1 = ax_norm.imshow(clean_disp, origin="lower", cmap="inferno", norm=norm_flux)
                ax_norm.set_title(
                    f"#{star['idx']} {tier_str} Star ({star['detector']}, mag={star['mag']:.2f})\nNormal Stamp ({star['size']}x{star['size']} px)",
                    fontsize=10.0, color="#e6edf3", fontweight="bold", pad=6
                )
                ax_norm.tick_params(colors="#8b949e", labelsize=7.5)
                cb1 = plt.colorbar(im1, ax=ax_norm, fraction=0.046, pad=0.03)
                cb1.ax.tick_params(colors="#8b949e", labelsize=7.0)
                cb1.set_label("Flux (MJy/sr)", color="#8b949e", fontsize=7.5)
                
                # ----------------- Panel 2: Moffat Residual Map -----------------
                ax_res_m = axes[row_idx, 1]
                ax_res_m.set_facecolor("#161b22")
                clean_res_m = np.maximum(res_m, 1e-4)
                im2 = ax_res_m.imshow(clean_res_m, origin="lower", cmap="inferno", norm=norm_flux)
                if star_tier == "faint":
                    res_m_title = (
                        rf"Faint Tier: Moffat Skipped" "\n"
                        rf"Pass-Through [{norm_flux.vmin:.1e}, {norm_flux.vmax:.1e}]"
                    )
                else:
                    res_m_title = (
                        rf"2-Iter AstroPhot Moffat Residual" "\n"
                        rf"$\Delta I = I_{{obs}} - I_{{moffat}}$"
                    )
                ax_res_m.set_title(res_m_title, fontsize=10.0, color="#e6edf3", fontweight="bold", pad=6)
                ax_res_m.tick_params(colors="#8b949e", labelsize=7.5)
                cb2 = plt.colorbar(im2, ax=ax_res_m, fraction=0.046, pad=0.03)
                cb2.ax.tick_params(colors="#8b949e", labelsize=7.0)
                cb2.set_label("Residual (MJy/sr)", color="#8b949e", fontsize=7.5)

                # ----------------- Panel 3: Sérsic Residual Map -----------------
                ax_res_s = axes[row_idx, 2]
                ax_res_s.set_facecolor("#161b22")
                clean_res_s = np.maximum(res_s, 1e-4)
                im3 = ax_res_s.imshow(clean_res_s, origin="lower", cmap="inferno", norm=norm_flux)
                if star_tier == "faint":
                    res_s_title = (
                        rf"Faint Tier: Sérsic Skipped" "\n"
                        rf"Pass-Through [{norm_flux.vmin:.1e}, {norm_flux.vmax:.1e}]"
                    )
                else:
                    res_s_title = (
                        rf"AstroPhot 2D Sérsic Residual" "\n"
                        rf"$\Delta I = I_{{obs}} - I_{{sersic}}$"
                    )
                ax_res_s.set_title(res_s_title, fontsize=10.0, color="#e6edf3", fontweight="bold", pad=6)
                ax_res_s.tick_params(colors="#8b949e", labelsize=7.5)
                cb3 = plt.colorbar(im3, ax=ax_res_s, fraction=0.046, pad=0.03)
                cb3.ax.tick_params(colors="#8b949e", labelsize=7.0)
                cb3.set_label("Residual (MJy/sr)", color="#8b949e", fontsize=7.5)
                
                # ----------------- Panel 4: Normal + Mask Overlay (Uniform Yellow) -----------------
                ax_mask = axes[row_idx, 3]
                ax_mask.set_facecolor("#161b22")
                ax_mask.imshow(clean_disp, origin="lower", cmap="inferno", norm=norm_flux)
                
                # RGBA overlay: entire mask in uniform vivid yellow
                overlay = np.zeros((*flux.shape, 4), dtype=float)
                overlay[mask] = [1.0, 0.92, 0.0, 0.55]
                ax_mask.imshow(overlay, origin="lower")
                
                if star_tier == "faint":
                    mask_title = (
                        f"Normal + Mask (Faint: No Masking)\n"
                        f"Retained: 100% | DQ/NaN: {star['masked_pct']:.1f}%"
                    )
                else:
                    det_name = args.contaminant_detector.upper()
                    comp_info = f" | {star['n_comps']} Gaia Comps" if star['n_comps'] > 0 else ""
                    mask_title = (
                        f"Normal + {det_name} Mask Overlay{comp_info}\n"
                        f"Masked: {star['masked_pct']:.1f}% ({star['n_islands']} objs) | Spikes: {star['prot_pct']:.1f}%"
                    )
                ax_mask.set_title(mask_title, fontsize=10.0, color="#e6edf3", fontweight="bold", pad=6)
                ax_mask.tick_params(colors="#8b949e", labelsize=7.5)
                
                # Dummy colorbar for alignment
                cb4 = plt.colorbar(im1, ax=ax_mask, fraction=0.046, pad=0.03)
                cb4.ax.set_visible(False)
                
            plt.subplots_adjust(top=0.92, bottom=0.05, hspace=0.35, wspace=0.25, left=0.04, right=0.96)
            method_header = f"Moffat & Sérsic Profile Fits + {args.contaminant_detector.upper()} Deblending | Spikes & Cores Protected"
                
            fig.suptitle(
                f"Roman ePSF Masking Gallery — Page {page_idx+1} of {num_pages}\n"
                f"({method_header})",
                fontsize=13, color="#58a6ff", fontweight="bold", y=0.97
            )
            
            # Save page as high-res PNG preview
            page_png = out_dir / f"gaia_masking_gallery_p{page_idx+1}.png"
            fig.savefig(str(page_png), dpi=150, facecolor=fig.get_facecolor(), edgecolor="none")
            
            # Also save mto2-named preview if method or detector is mto2
            if args.method == "mto2" or args.contaminant_detector == "mto2":
                mto2_png = out_dir / f"mto2_masking_gallery_p{page_idx+1}.png"
                shutil.copyfile(page_png, mto2_png)
                
            print(f"Saved page {page_idx+1} preview to {page_png}")
                
            pdf.savefig(fig, facecolor=fig.get_facecolor(), edgecolor="none")
            plt.close(fig)
            
    print(f"SUCCESS: Generated {pdf_path} ({os.path.getsize(pdf_path) / 1024:.1f} KB, {num_pages} pages)")
    
    # Save copies to mto2_masking_gallery.pdf and report.pdf
    if args.method == "mto2" or args.contaminant_detector == "mto2":
        mto2_pdf = out_dir / "mto2_masking_gallery.pdf"
        report_pdf = out_dir / "report.pdf"
        shutil.copyfile(pdf_path, mto2_pdf)
        shutil.copyfile(pdf_path, report_pdf)
        print(f"Copied report to {mto2_pdf} and {report_pdf}")


if __name__ == "__main__":
    main()
