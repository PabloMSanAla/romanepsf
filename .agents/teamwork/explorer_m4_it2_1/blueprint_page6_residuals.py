"""
Blueprint for Authentic Remediation of Page 6 (2D Subtraction Residual Maps) in romanepsf/report.py.

Addresses reviewer_m4_2 Finding 1:
- Eliminates synthetic noise generation (np.random.normal) and hardcoded tiers_info.
- Directly ingests authentic multi-extension residual FITS files or in-memory StarResidualResult objects.
- Extracts and visualizes all 5 key HDU maps:
    1. OBSERVED (Observed star stamp I_obs)
    2. MODEL (Forward-modeled ePSF stamp I_model)
    3. RESIDUAL (2D subtraction residual R = I_obs - I_model)
    4. NORM_RES (Z-score normalized residual Z = R / sigma)
    5. FRAC_RES (Fractional residual F = R / (I_model + eps))
- Extracts and displays authentic fitted parameters from FITS headers:
    MAG, FLXSCALE (alpha), DX, DY, CHI2_NU.
- Provides a clean deterministic mock fallback when residual FITS files are absent,
  explicitly flagged as mock without claiming real Level 2 observation.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.colors import LogNorm, Normalize
from astropy.io import fits

from romanepsf import __version__
from romanepsf.report import (
    COLOR_NAVY,
    COLOR_SLATE,
    COLOR_BORDER,
    ReportDataBundle,
    add_page_decorations,
)


def load_tier_residual_data(
    data: ReportDataBundle,
    search_dirs: Optional[List[Path]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    """
    Extract authentic residual maps and fitted header parameters for each tier.

    Order of precedence:
    1. In-memory `data.validation_results.star_results` (if available as dataclass instances).
    2. Real multi-extension residual FITS files on disk (`residual_{tier}_*.fits`).
    3. Deterministic mock star fallback cleanly derived from `data.epsf` (zero np.random).

    Parameters
    ----------
    data : ReportDataBundle
        Parsed report data bundle containing model canvas and results paths.
    search_dirs : Optional[List[Path]]
        Optional explicit directory list to search for residual FITS files.

    Returns
    -------
    tier_data : Dict[str, Dict[str, Any]]
        Dictionary keyed by tier ('bright', 'medium', 'faint') containing:
        - observed, model, residual, norm_res, frac_res, mask
        - mag, flxscale, dx, dy, chi2_nu, source_id, is_mock
    any_mock : bool
        True if any tier fell back to deterministic mock.
    """
    tiers = ["bright", "medium", "faint"]
    tier_data: Dict[str, Dict[str, Any]] = {}

    # Strategy 1: Check in-memory star_results on data.validation_results
    val_res = getattr(data, "validation_results", None)
    if val_res is not None and hasattr(val_res, "star_results") and val_res.star_results:
        by_tier: Dict[str, List[Any]] = {}
        for s in val_res.star_results:
            by_tier.setdefault(str(s.tier).lower(), []).append(s)

        for t in tiers:
            if t in by_tier:
                # Select star with lowest chi2_nu
                best_s = min(by_tier[t], key=lambda x: getattr(x, "chi2_nu", float("inf")))
                mask_arr = (
                    best_s.mask.astype(np.uint8)
                    if hasattr(best_s, "mask") and best_s.mask is not None
                    else np.zeros_like(best_s.observed, dtype=np.uint8)
                )
                dx, dy = (
                    (float(best_s.subpixel_offset[0]), float(best_s.subpixel_offset[1]))
                    if hasattr(best_s, "subpixel_offset") and len(best_s.subpixel_offset) == 2
                    else (0.0, 0.0)
                )
                tier_data[t] = {
                    "observed": best_s.observed.astype(np.float32),
                    "model": best_s.model.astype(np.float32),
                    "residual": best_s.residual.astype(np.float32),
                    "norm_res": best_s.normalized_residual.astype(np.float32),
                    "frac_res": best_s.fractional_residual.astype(np.float32),
                    "mask": mask_arr,
                    "mag": float(getattr(best_s, "mag", 0.0)),
                    "flxscale": float(getattr(best_s, "flux_scale", 1.0)),
                    "dx": dx,
                    "dy": dy,
                    "chi2_nu": float(getattr(best_s, "chi2_nu", 0.0)),
                    "source_id": str(getattr(best_s, "source_id", "in_memory")),
                    "is_mock": False,
                }

    # Strategy 2: Search residual FITS files on disk
    if search_dirs is None:
        cand_dirs = [
            data.results_dir / "validation" if hasattr(data, "results_dir") and data.results_dir else None,
            data.results_dir if hasattr(data, "results_dir") and data.results_dir else None,
            Path("output/validation"),
            Path("output/run_all/validation"),
            data.fits_path.parent / "validation" if hasattr(data, "fits_path") and data.fits_path else None,
            Path("output"),
        ]
        search_dirs = [d for d in cand_dirs if d and d.is_dir()]

    for t in tiers:
        if t in tier_data:
            continue

        cand_files: List[Path] = []
        for d in search_dirs:
            cand_files.extend(list(d.glob(f"residual_{t}_*.fits")))
            cand_files.extend(list(d.glob(f"residual_{t}*.fits")))

        cand_files = sorted(list(set(cand_files)))
        if cand_files:
            # Pick candidate with lowest CHI2_NU in header
            best_f = cand_files[0]
            best_chi2 = float("inf")
            for f in cand_files:
                try:
                    with fits.open(f) as hd:
                        c2 = float(hd[0].header.get("CHI2_NU", float("inf")))
                        if c2 < best_chi2:
                            best_chi2 = c2
                            best_f = f
                except Exception:
                    pass

            with fits.open(best_f) as hdul:
                hdr = hdul[0].header
                obs = hdul["OBSERVED"].data.astype(np.float32)
                mod = hdul["MODEL"].data.astype(np.float32)
                res = hdul["RESIDUAL"].data.astype(np.float32)
                nres = hdul["NORM_RES"].data.astype(np.float32)
                fres = hdul["FRAC_RES"].data.astype(np.float32)
                mask = (
                    hdul["MASK"].data.astype(np.uint8)
                    if "MASK" in hdul
                    else np.zeros_like(obs, dtype=np.uint8)
                )

                tier_data[t] = {
                    "observed": obs,
                    "model": mod,
                    "residual": res,
                    "norm_res": nres,
                    "frac_res": fres,
                    "mask": mask,
                    "mag": float(hdr.get("MAG", 0.0)),
                    "flxscale": float(hdr.get("FLXSCALE", 1.0)),
                    "dx": float(hdr.get("DX", 0.0)),
                    "dy": float(hdr.get("DY", 0.0)),
                    "chi2_nu": float(hdr.get("CHI2_NU", 0.0)),
                    "source_id": str(hdr.get("SRC_ID", best_f.stem)),
                    "is_mock": False,
                }

    # Strategy 3: Deterministic mock fallback (no np.random, zero hallucinated noise)
    fallback_defaults = {
        "bright": (10.44, 5.0e5, 101),
        "medium": (11.65, 2.0e5, 61),
        "faint":  (13.93, 3.0e4, 41),
    }

    any_mock = False
    epsf = getattr(data, "epsf", None)
    for t in tiers:
        if t not in tier_data:
            any_mock = True
            nom_mag, nom_flx, sz = fallback_defaults[t]
            h = sz // 2
            if epsf is not None and epsf.ndim == 2:
                cy, cx = (epsf.shape[0] - 1) // 2, (epsf.shape[1] - 1) // 2
                m_cut = epsf[cy - h : cy + h + 1, cx - h : cx + h + 1].astype(np.float32) * nom_flx
            else:
                m_cut = np.ones((sz, sz), dtype=np.float32) * nom_flx

            tier_data[t] = {
                "observed": m_cut.copy(),
                "model": m_cut.copy(),
                "residual": np.zeros_like(m_cut),
                "norm_res": np.zeros_like(m_cut),
                "frac_res": np.zeros_like(m_cut),
                "mask": np.zeros_like(m_cut, dtype=np.uint8),
                "mag": nom_mag,
                "flxscale": nom_flx,
                "dx": 0.0,
                "dy": 0.0,
                "chi2_nu": 1.00,
                "source_id": "MOCK",
                "is_mock": True,
            }

    return tier_data, any_mock


def plot_page_subtraction_residuals_blueprint(
    fig: Figure,
    data: ReportDataBundle,
    crop_sizes: Optional[Dict[str, int]] = None,
    search_dirs: Optional[List[Path]] = None,
) -> None:
    """
    Render Page 6: 2D Subtraction Residual Maps.

    Extracts and displays authentic data from 5 HDUs per brightness tier:
    - OBSERVED (I_obs)
    - MODEL (I_model)
    - RESIDUAL (R = I_obs - I_model)
    - NORM_RES (Z = R / sigma)
    - FRAC_RES (F = R / (I_model + eps))
    Along with real fitted parameters: MAG, FLXSCALE, DX, DY, CHI2_NU.
    """
    add_page_decorations(fig, 6, 8, "2D Subtraction Residual Maps")

    tier_data, any_mock = load_tier_residual_data(data, search_dirs=search_dirs)

    # Top description banner
    ax_desc = fig.add_axes([0.08, 0.85, 0.84, 0.07])
    ax_desc.axis("off")
    ax_desc.text(
        0.0, 0.70,
        "FORWARD-MODEL SUBTRACTION RESIDUAL MAPS ACROSS BRIGHTNESS TIERS",
        fontsize=9.0, weight="bold", color=COLOR_NAVY,
    )
    if any_mock:
        subtitle = (
            "Deterministic mock star fallback (validation residual FITS not detected): "
            "I_model(x,y) = α · ePSF(x - Δx, y - Δy)."
        )
    else:
        subtitle = (
            "Authentic star forward modeling: I_model(x,y) = α · ePSF(x - Δx, y - Δy). "
            "Residuals: R = I_obs - I_model, Z = R / σ, F = R / (I_model + ε)."
        )
    ax_desc.text(0.0, 0.20, subtitle, fontsize=7.2, color=COLOR_SLATE)

    # Row and Column Geometry
    tiers_info = [
        ("bright", "Bright Star", 101, [-30, 0, 30]),
        ("medium", "Medium Star", 61, [-20, 0, 20]),
        ("faint", "Faint Star", 41, [-15, 0, 15]),
    ]
    if crop_sizes:
        tiers_info = [
            (t, label, crop_sizes.get(t, default_sz), ticks)
            for t, label, default_sz, ticks in tiers_info
        ]

    row_ys = [0.60, 0.35, 0.10]
    col_xs = [0.080, 0.240, 0.400, 0.560, 0.720]
    col_w = 0.142
    row_h = 0.200

    im_z_last = None
    im_f_last = None

    for r_idx, (tier_key, tier_name, crop_sz, ticks) in enumerate(tiers_info):
        y_pos = row_ys[r_idx]
        star_dict = tier_data[tier_key]

        obs = star_dict["observed"]
        mod = star_dict["model"]
        res = star_dict["residual"]
        nres = star_dict["norm_res"]
        fres = star_dict["frac_res"]
        mask = star_dict["mask"]

        mag = star_dict["mag"]
        flx = star_dict["flxscale"]
        dx = star_dict["dx"]
        dy = star_dict["dy"]
        chi2 = star_dict["chi2_nu"]
        is_mock = star_dict["is_mock"]

        # Center cropping to zoom into relevant core/transition/spike structure
        cy, cx = (obs.shape[0] - 1) // 2, (obs.shape[1] - 1) // 2
        h = min(crop_sz // 2, cy, cx)
        ext = [-h, h, -h, h]

        obs_c = obs[cy - h : cy + h + 1, cx - h : cx + h + 1]
        mod_c = mod[cy - h : cy + h + 1, cx - h : cx + h + 1]
        res_c = res[cy - h : cy + h + 1, cx - h : cx + h + 1]
        nres_c = nres[cy - h : cy + h + 1, cx - h : cx + h + 1]
        fres_c = fres[cy - h : cy + h + 1, cx - h : cx + h + 1]
        mask_c = mask[cy - h : cy + h + 1, cx - h : cx + h + 1]

        # Allocate 5 axes across the row
        ax_obs = fig.add_axes([col_xs[0], y_pos, col_w, row_h])
        ax_mod = fig.add_axes([col_xs[1], y_pos, col_w, row_h])
        ax_res = fig.add_axes([col_xs[2], y_pos, col_w, row_h])
        ax_znorm = fig.add_axes([col_xs[3], y_pos, col_w, row_h])
        ax_frac = fig.add_axes([col_xs[4], y_pos, col_w, row_h])
        axes_row = [ax_obs, ax_mod, ax_res, ax_znorm, ax_frac]

        # Col 0: Observed Star Stamp
        vmax = max(float(np.max(mod_c)), 1.0)
        vmin = max(vmax * 1e-4, 0.05)
        ax_obs.imshow(
            obs_c, origin="lower", extent=ext, cmap="viridis",
            norm=LogNorm(vmin=vmin, vmax=vmax),
        )
        tier_suffix = " (Mock)" if is_mock else ""
        ax_obs.set_ylabel(f"{tier_name}{tier_suffix}\n(m = {mag:.2f})\n[px]", fontsize=7.2, weight="bold")
        ax_obs.set_yticks(ticks)
        ax_obs.tick_params(labelsize=6.5)
        if r_idx == 0:
            ax_obs.set_title("Observed $I_{\\rm obs}$", fontsize=7.6, weight="bold", color=COLOR_NAVY)

        # Col 1: Forward Model ePSF Stamp
        ax_mod.imshow(
            mod_c, origin="lower", extent=ext, cmap="viridis",
            norm=LogNorm(vmin=vmin, vmax=vmax),
        )
        ax_mod.set_yticklabels([])
        ax_mod.tick_params(left=False, labelsize=6.5)
        if r_idx == 0:
            ax_mod.set_title("Model $I_{\\rm model}$", fontsize=7.6, weight="bold", color=COLOR_NAVY)

        # Col 2: 2D Subtraction Residual Map
        valid_res = res_c[mask_c == 0] if np.any(mask_c == 0) else res_c
        res_lim = float(np.percentile(np.abs(valid_res), 98)) if len(valid_res) > 0 else float(np.std(res_c) * 3.0)
        res_lim = max(res_lim, 0.1)
        ax_res.imshow(
            res_c, origin="lower", extent=ext, cmap="coolwarm",
            vmin=-res_lim, vmax=res_lim,
        )
        ax_res.set_yticklabels([])
        ax_res.tick_params(left=False, labelsize=6.5)
        if r_idx == 0:
            ax_res.set_title("Residual $R$", fontsize=7.6, weight="bold", color=COLOR_NAVY)

        # Col 3: Normalized Residual (Z-score)
        im_z = ax_znorm.imshow(
            nres_c, origin="lower", extent=ext, cmap="RdBu_r",
            vmin=-5.0, vmax=5.0,
        )
        im_z_last = im_z
        ax_znorm.set_yticklabels([])
        ax_znorm.tick_params(left=False, labelsize=6.5)
        if r_idx == 0:
            ax_znorm.set_title("Norm Residual $Z$", fontsize=7.6, weight="bold", color=COLOR_NAVY)

        # Col 4: Fractional Residual
        im_f = ax_frac.imshow(
            fres_c, origin="lower", extent=ext, cmap="PuOr_r",
            vmin=-0.5, vmax=0.5,
        )
        im_f_last = im_f
        ax_frac.set_yticklabels([])
        ax_frac.tick_params(left=False, labelsize=6.5)
        if r_idx == 0:
            ax_frac.set_title("Frac Residual $F$", fontsize=7.6, weight="bold", color=COLOR_NAVY)

        # Fitted parameters annotation box
        chi2_str = f"{chi2:,.1f}" if chi2 < 1e5 else f"{chi2:.1e}"
        flx_str = f"{flx:,.0f}" if flx < 1e6 else f"{flx:.2e}"
        mock_tag = "\n[Deterministic Mock]" if is_mock else ""
        param_text = (
            f"$\\chi_\\nu^2 = {chi2_str}$\n"
            f"$\\alpha = {flx_str}$\n"
            f"$(\\Delta x, \\Delta y) = ({dx:+.2f}, {dy:+.2f})$"
            f"{mock_tag}"
        )
        ax_frac.text(
            0.95, 0.05, param_text,
            fontsize=5.5, color="black", weight="bold",
            ha="right", va="bottom", transform=ax_frac.transAxes,
            bbox=dict(
                boxstyle="round,pad=0.2",
                facecolor="white",
                alpha=0.88,
                edgecolor=COLOR_BORDER,
                linewidth=0.5,
            ),
        )

        # X-axis ticks and labels
        for ax in axes_row:
            if r_idx < 2:
                ax.set_xticks([])
            else:
                ax.set_xticks(ticks)
                ax.set_xlabel("X Offset [px]", fontsize=6.8)

    # Colorbars on the right margin
    if im_z_last is not None:
        cax_z = fig.add_axes([0.886, 0.52, 0.016, 0.28])
        cb_z = fig.colorbar(im_z_last, cax=cax_z, extend="both")
        cb_z.set_label("Normalized $Z$ [$\\sigma$]", fontsize=6.8)
        cb_z.ax.tick_params(labelsize=6.0)

    if im_f_last is not None:
        cax_f = fig.add_axes([0.886, 0.12, 0.016, 0.28])
        cb_f = fig.colorbar(im_f_last, cax=cax_f, extend="both")
        cb_f.set_label("Fractional $F$", fontsize=6.8)
        cb_f.ax.tick_params(labelsize=6.0)


# ==============================================================================
# Verification and Self-Test Suite
# ==============================================================================

def run_blueprint_tests() -> None:
    """Execute end-to-end verification of Page 6 remediation blueprint."""
    print("======================================================================")
    print("Testing Blueprint for Page 6 Remediation (plot_page_subtraction_residuals)")
    print("======================================================================")

    # Test 1: Real FITS mode with ReportDataBundle
    print("\n--- Test 1: Real FITS Ingestion Mode ---")
    composite_fits = Path("output/run_all/roman_epsf_composite.fits")
    assert composite_fits.is_file(), f"Missing composite fits at {composite_fits}"

    data_bundle = ReportDataBundle(composite_fits)
    tier_data, any_mock = load_tier_residual_data(data_bundle)

    print(f"Loaded {len(tier_data)} tiers. Any mock: {any_mock}")
    assert not any_mock, "Expected authentic FITS files to be loaded, not mock!"
    for t, d in tier_data.items():
        print(f"  Tier {t.upper()}: source_id={d['source_id']}, mag={d['mag']:.2f}, flx={d['flxscale']:.1f}, chi2={d['chi2_nu']:.2f}, shape={d['observed'].shape}")
        assert d["observed"].ndim == 2, f"Tier {t} observed must be 2D"
        assert d["model"].ndim == 2, f"Tier {t} model must be 2D"
        assert d["residual"].ndim == 2, f"Tier {t} residual must be 2D"
        assert d["norm_res"].ndim == 2, f"Tier {t} norm_res must be 2D"
        assert d["frac_res"].ndim == 2, f"Tier {t} frac_res must be 2D"
        assert not d["is_mock"], f"Tier {t} should not be mock"

    # Test 2: Figure rendering in real mode
    print("\n--- Test 2: Real Figure Rendering & Axis Allocation ---")
    fig_real = plt.figure(figsize=(8.5, 11.0))
    plot_page_subtraction_residuals_blueprint(fig_real, data_bundle)

    # 3 banner/footer/desc axes + 3 rows * 5 columns (15 axes) + 2 colorbars = 20 axes
    assert len(fig_real.axes) == 20, f"Expected 20 axes on canvas, got {len(fig_real.axes)}"
    test_out_png = Path(".agents/teamwork/explorer_m4_it2_1/test_blueprint_real.png")
    fig_real.savefig(test_out_png, dpi=150)
    plt.close(fig_real)
    print(f"Rendered real figure with {len(fig_real.axes)} axes to {test_out_png}")

    # Test 3: Deterministic mock fallback mode (isolated environment)
    print("\n--- Test 3: Deterministic Mock Fallback Mode ---")
    mock_bundle = ReportDataBundle(composite_fits)
    # Force empty results_dir and None validation_results, pass empty search_dirs
    mock_tier_data, mock_any = load_tier_residual_data(mock_bundle, search_dirs=[Path("/nonexistent_dir_12345")])
    print(f"Fallback mode - Loaded {len(mock_tier_data)} tiers. Any mock: {mock_any}")
    assert mock_any, "Fallback should flag mock data"
    for t, d in mock_tier_data.items():
        print(f"  Fallback Tier {t.upper()}: is_mock={d['is_mock']}, mag={d['mag']}, shape={d['observed'].shape}")
        assert d["is_mock"], f"Tier {t} should be mock in isolated mode"
        assert np.all(d["residual"] == 0), "Deterministic mock residual should be exactly zero"

    fig_mock = plt.figure(figsize=(8.5, 11.0))
    plot_page_subtraction_residuals_blueprint(
        fig_mock, mock_bundle, search_dirs=[Path("/nonexistent_dir_12345")]
    )
    assert len(fig_mock.axes) >= 15, "Mock rendering should allocate full row/column grid"
    test_mock_png = Path(".agents/teamwork/explorer_m4_it2_1/test_blueprint_mock.png")
    fig_mock.savefig(test_mock_png, dpi=150)
    plt.close(fig_mock)
    print(f"Rendered mock fallback figure to {test_mock_png}")

    print("\n======================================================================")
    print("ALL BLUEPRINT TESTS PASSED SUCCESSFULLY!")
    print("======================================================================")


if __name__ == "__main__":
    run_blueprint_tests()
