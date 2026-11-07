"""
Verification script for Page 4 radial profiles missing tier flux columns patch.
Tests against:
1. tests/adversarial_novel_edgecase_stress.py::test_adv_radial_profiles_missing_tier_flux_columns
2. Additional adversarial edge cases (missing FLUX_COMPOSITE, None in columns, None in header keys)
3. Nominal production data regression check.
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import romanepsf.report as rep
from tests.adversarial_novel_edgecase_stress import test_adv_radial_profiles_missing_tier_flux_columns


def get_patched_plot_fn():
    """Patched version of plot_page_radial_profiles."""
    def patched_plot_page_radial_profiles(fig, data):
        rep.add_page_decorations(fig, 4, 8, "Cross-Tier Overlap Normalization")
        ax_prof = fig.add_axes([0.08, 0.52, 0.84, 0.38])

        if not data.radial_profiles.empty and "RADIUS_PX" in data.radial_profiles:
            df_p = data.radial_profiles
            r_px = pd.to_numeric(df_p["RADIUS_PX"], errors="coerce").to_numpy(dtype=float)
            n_r = len(r_px)
            f_comp = pd.to_numeric(df_p["FLUX_COMPOSITE"], errors="coerce").to_numpy(dtype=float) if "FLUX_COMPOSITE" in df_p else np.full(n_r, np.nan)
            f_faint = pd.to_numeric(df_p["FLUX_FAINT"], errors="coerce").to_numpy(dtype=float) if "FLUX_FAINT" in df_p else np.full(n_r, np.nan)
            f_med = pd.to_numeric(df_p["FLUX_MED_SCALED"], errors="coerce").to_numpy(dtype=float) if "FLUX_MED_SCALED" in df_p else np.full(n_r, np.nan)
            f_bright = pd.to_numeric(df_p["FLUX_BRIGHT_SCALED"], errors="coerce").to_numpy(dtype=float) if "FLUX_BRIGHT_SCALED" in df_p else np.full(n_r, np.nan)
        else:
            r_px = np.logspace(0, 2.7, 300)
            f_comp = 0.06 / (1.0 + (r_px / 2.5)**2)**1.3
            f_faint = f_comp * (1.0 + 0.02 * np.sin(np.linspace(0, 10, len(r_px))))
            f_med = f_comp * (1.0 + 0.03 * np.cos(np.linspace(0, 12, len(r_px))))
            f_bright = f_comp * (1.0 + 0.04 * np.sin(np.linspace(0, 8, len(r_px))))

        mask_f = (r_px <= 25.0) & (f_faint > 0)
        mask_m = (r_px >= 7.0) & (r_px <= 50.0) & (f_med > 0)
        mask_b = (r_px >= 20.0) & (f_bright > 0)

        ax_prof.plot(r_px[mask_f], f_faint[mask_f], color=rep.COLOR_BLUE, alpha=0.7, linestyle="--", linewidth=1.4, label="Faint Tier (Core r < 8 px)")
        ax_prof.plot(r_px[mask_m], f_med[mask_m], color=rep.COLOR_AMBER, alpha=0.7, linestyle="-.", linewidth=1.4, label=f"Medium Tier (Scaled k_FM={float(data.header.get('SCALE_FM') or 0.1937):.4f})")
        ax_prof.plot(r_px[mask_b], f_bright[mask_b], color=rep.COLOR_CRIMSON, alpha=0.6, linestyle=":", linewidth=1.4, label=f"Bright Tier (Scaled k_MB={float(data.header.get('SCALE_MB') or 0.0255):.4f})")
        ax_prof.plot(r_px, f_comp, color="#1A202C", linewidth=2.0, label="Composite Extended PSF (Unit Flux)")

        ax_prof.axvline(8.0, color=rep.COLOR_AMBER, linestyle=":", linewidth=1.2)
        ax_prof.axvline(22.0, color=rep.COLOR_CRIMSON, linestyle=":", linewidth=1.2)

        ax_prof.axvspan(8.0, 16.0, color=rep.COLOR_AMBER, alpha=0.15, label="Faint-Med Overlap [8, 16] px")
        ax_prof.axvspan(22.0, 45.0, color=rep.COLOR_CRIMSON, alpha=0.15, label="Med-Bright Overlap [22, 45] px")

        ax_prof.set_xscale("log")
        ax_prof.set_yscale("log")
        ax_prof.set_xlim(1.0, 500.0)
        ax_prof.set_ylim(1e-7, 1e-1)
        ax_prof.set_xlabel("Radius r [pixels] (1 pixel = 0.110 arcsec)")
        ax_prof.set_ylabel("Surface Brightness [Fractional Flux / pixel]")
        ax_prof.set_title("Multi-Tier Extended Radial Surface Brightness Profile", fontsize=9.5, weight="bold", color=rep.COLOR_NAVY)
        ax_prof.grid(True, which="both", linestyle=":", alpha=0.5)
        ax_prof.legend(loc="upper right", framealpha=0.9, fontsize=7.2)

        ax_prof.text(8.2, 2e-2, "Med Saturation\nr ≈ 8 px", color=rep.COLOR_AMBER, fontsize=7.2, weight="bold")
        ax_prof.text(22.5, 3e-3, "Bright Saturation\nr ≈ 22 px", color=rep.COLOR_CRIMSON, fontsize=7.2, weight="bold")

        # Bottom Left: Blending weights
        ax_ratio = fig.add_axes([0.08, 0.10, 0.40, 0.34])
        r_sub = np.linspace(5, 50, 100)
        w_faint = np.clip((18.0 - r_sub) / (18.0 - 10.0), 0.0, 1.0)
        w_faint = 0.5 * (1.0 + np.cos(np.pi * (1.0 - w_faint)))
        w_faint[r_sub < 10.0] = 1.0
        w_faint[r_sub > 18.0] = 0.0

        w_bright = np.clip((r_sub - 30.0) / (48.0 - 30.0), 0.0, 1.0)
        w_bright = 0.5 * (1.0 - np.cos(np.pi * w_bright))
        w_bright[r_sub < 30.0] = 0.0
        w_bright[r_sub > 48.0] = 1.0

        w_med = 1.0 - w_faint - w_bright

        ax_ratio.plot(r_sub, w_faint, color=rep.COLOR_BLUE, linewidth=1.6, label="w_Faint (Core)")
        ax_ratio.plot(r_sub, w_med, color=rep.COLOR_AMBER, linewidth=1.6, label="w_Medium (Transition)")
        ax_ratio.plot(r_sub, w_bright, color=rep.COLOR_CRIMSON, linewidth=1.6, label="w_Bright (Wings)")
        ax_ratio.plot(r_sub, w_faint + w_med + w_bright, color="black", linestyle="--", linewidth=1.0, label="Sum ≡ 1.0 (Partition)")

        ax_ratio.set_title("Partition-of-Unity Cosine Annular Blending", fontsize=8.5, weight="bold", color=rep.COLOR_NAVY)
        ax_ratio.set_xlabel("Radius r [pixels]")
        ax_ratio.set_ylabel("Tier Blending Weight w_i(r)")
        ax_ratio.set_ylim(-0.05, 1.15)
        ax_ratio.grid(True, linestyle=":", alpha=0.6)
        ax_ratio.legend(loc="center right", fontsize=6.8)

        # Bottom Right: Methodology box
        ax_info = fig.add_axes([0.52, 0.10, 0.40, 0.34])
        ax_info.axis("off")
        ax_info.add_patch(rep.patches.FancyBboxPatch(
            (0, 0), 1, 1, boxstyle="round,pad=0.02,rounding_size=0.03",
            facecolor=rep.COLOR_BG_CARD, edgecolor=rep.COLOR_BORDER, linewidth=1.0
        ))
        ax_info.text(0.04, 0.92, "CROSS-TIER OVERLAP & INVARIANTS", fontsize=8.0, weight="bold", color=rep.COLOR_NAVY)
        k_fm_val = float(data.header.get("K_FM") or 0.193659)
        k_mb_val = float(data.header.get("K_MB") or 0.025527)
        info_txt = (
            "• Strict Scientific Invariant (Requirement R2):\n"
            "  1D radial profiles are strictly reserved for determining saturation\n"
            "  plateaus and deriving cross-tier scale factors k_FM and k_MB.\n"
            "  Radial circularization or azimuthal averaging of the 2D ePSF canvas\n"
            "  is strictly prohibited.\n\n"
            "• Overlap Annulus 1 (Faint / Medium):\n"
            "  Calibration interval: [8.0, 16.0] px\n"
            f"  Scale factor: k_FM = {k_fm_val:.6f} ± 0.000412\n"
            "  Cosine transition region: [10.0, 18.0] px\n\n"
            "• Overlap Annulus 2 (Medium / Bright):\n"
            "  Calibration interval: [22.0, 45.0] px\n"
            f"  Scale factor: k_MB = {k_mb_val:.6f} ± 0.000084\n"
            "  Cosine transition region: [30.0, 48.0] px\n\n"
            "• Seamless Cosine Transition:\n"
            "  W(r) = 0.5 · [1 + cos(π · (r - r_0) / (r_1 - r_0))]\n"
            "  Ensures continuous derivatives and smooth flux decay."
        )
        ax_info.text(0.04, 0.86, info_txt, fontsize=6.8, color="#2D3748", linespacing=1.3, va="top")

    return patched_plot_page_radial_profiles


def main():
    print("=== 1. Testing Novel Adversarial Stress Case: Missing Tier Flux Columns ===")
    patched_fn = get_patched_plot_fn()
    import tests.adversarial_novel_edgecase_stress as adv_mod
    adv_mod.plot_page_radial_profiles = patched_fn
    rep.plot_page_radial_profiles = patched_fn

    try:
        adv_mod.test_adv_radial_profiles_missing_tier_flux_columns()
        print("PASS: test_adv_radial_profiles_missing_tier_flux_columns executed cleanly!")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        sys.exit(1)

    print("\n=== 2. Testing Additional Edge Cases ===")
    # Edge case 2a: Missing FLUX_COMPOSITE as well
    class MockMissingComp:
        header = {}
        radial_profiles = pd.DataFrame({"RADIUS_PX": np.linspace(1, 100, 50)})
    fig = plt.figure()
    patched_fn(fig, MockMissingComp())
    plt.close(fig)
    print("PASS: Edge Case 2a (missing FLUX_COMPOSITE) handled cleanly!")

    # Edge case 2b: Dirty DataFrame with None and string corrupted entries
    class MockCorrupted:
        header = {"SCALE_FM": None, "SCALE_MB": None, "K_FM": None, "K_MB": None}
        radial_profiles = pd.DataFrame({
            "RADIUS_PX": [1.0, 2.0, "bad", None, 5.0],
            "FLUX_COMPOSITE": [0.1, None, 0.05, "invalid", 0.01],
            "FLUX_FAINT": [0.1, 0.08, None, "str", 0.005],
            "FLUX_MED_SCALED": [None, 0.08, 0.05, None, 0.01],
            "FLUX_BRIGHT_SCALED": [None, None, None, None, 0.01],
        })
    fig = plt.figure()
    patched_fn(fig, MockCorrupted())
    plt.close(fig)
    print("PASS: Edge Case 2b (corrupted types & None values) handled cleanly!")

    # Edge case 2c: Empty DataFrame fallback
    class MockEmpty:
        header = {}
        radial_profiles = pd.DataFrame()
    fig = plt.figure()
    patched_fn(fig, MockEmpty())
    plt.close(fig)
    print("PASS: Edge Case 2c (empty DataFrame fallback) handled cleanly!")

    print("\n=== 3. Testing Real FITS Production Data Regression ===")
    fits_path = Path("output/run_all/roman_epsf_composite.fits")
    if fits_path.exists():
        bundle = rep.ReportDataBundle(fits_path)
        fig = plt.figure()
        patched_fn(fig, bundle)
        plt.close(fig)
        print(f"PASS: Real FITS ({fits_path}) rendered Page 4 successfully!")
    else:
        print(f"SKIP: FITS path {fits_path} not found.")

    print("\nALL VERIFICATION TESTS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
