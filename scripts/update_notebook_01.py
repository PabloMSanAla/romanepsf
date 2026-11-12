"""
Script to generate the updated Tutorial 1 notebook (01_stamp_extraction_masking_tutorial.ipynb)
with complete profile residual methods, var_poisson weighting, Gaia companion masking,
erosion-dilation contaminant detection, method comparisons, and 3-panel visualization.
"""

import json
from pathlib import Path
import nbformat as nbf

nb = nbf.v4.new_notebook()

cells = []

# ==============================================================================
# Cell 0: Header & Introduction
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell(r"""# Tutorial 1: Postage Stamp Extraction, Sub-pixel Alignment, Profile Residual Methods, and Spike-Preserving Masking

In this tutorial, you will learn the complete preprocessing and masking pipeline for measuring the extended Point Spread Function (ePSF) of the Roman Space Telescope:

1. **Adaptive Postage Stamp Extraction & Poisson Variance**: Dynamically sizing cutouts based on stellar brightness tiers (**Bright**, **Medium**, and **Faint**) and extracting the Poisson noise variance array (`var_poisson`) directly from Roman Level 2 ASDF files.
2. **Sub-pixel Centering & Alignment**: Aligning stellar centroids to the exact sub-pixel grid center using spline interpolation to eliminate smearing of diffraction spikes and core features.
3. **Background Subtraction**: Robust estimation of local background flux in peripheral annuli.
4. **Multiple Profile Residual Methods**:
   - **Method 1: 2-Iteration AstroPhot Moffat Fitting (`method='moffat'`)**: Fast Levenberg-Marquardt fitting of a 2D Moffat profile weighted by Level 2 Poisson variance (`var_poisson`). In iteration 2, the fit mask is updated to exclude initially detected contaminants and neighbor Gaia companions.
   - **Method 2: 2D Sérsic Profile Fitting (`method='sersic'`)**: Levenberg-Marquardt fitting of a 2D circularly symmetric Sérsic profile $I(r) = I_e \exp(-b_n((r/R_e)^{1/n} - 1))$, modeling extended wings and broad diffuse backgrounds.
   - **Method 3: Compound Sérsic + Moffat Fitting (`method='compound'`)**: Simultaneous fitting of both core Moffat and extended Sérsic components.
   - **Method 4: Physical Model Fitting (`method='superback'` / `method='stpsf'`)**: Forward-modeling Roman SUPERBACK optical PSF (via `rosalia.superback_pytorch`) for bright stars and instrumental PSF (via `stpsf.WFI`) for medium stars.
   - **Method 5: Gaussian Unsharp Masking (`method='unsharp'`)**: Non-parametric high-pass filtering isolating compact contaminants and diffraction spikes without parametric profile assumptions.
   - **Faint Star Strategy**: Bypassing profile fitting and contaminant masking to preserve faint stellar wings and core flux for direct stacking.
5. **Neighbor Gaia Companion Masking**: Analytically calculating circular aperture exclusion radii using `get_psf_extension_moffat(mag, depth=28.0)` and masking nearby stars.
6. **Dual-Prior Diffraction Spike Protection**:
   - **Theoretical dual-set priors**: 24 spike rays derived from Roman's secondary mirror spider assembly and pupil facets rotated by aperture position angle (`roll_ref`) and detector clocking.
   - **Empirical angle refinement & morphological filtering**: Fine-tuning candidate rays along observed ridge peaks on residual maps.
7. **Erosion-Dilation & MTO2 Contaminant Masking**:
   - Sigma-clipped detection: $\\text{threshold} = \\text{median} + 1.5 \\times \\text{std}$
   - Morphological opening ($1 \\times 1$ erosion) and dilation ($3 \\times 3$) or MTO2 Max-Tree deblending.
   - Strict invariant: excluded pixels never overlap protected diffraction spikes or central core.
8. **Method Comparison & Publication Visualizations**:
   - Side-by-side comparison of residual maps and masks across methods on the same star.
   - Standard 4-panel visualization: Normal Stamp, Moffat Residual, Sérsic Residual, and Normal + Uniform Yellow Mask Overlay."""))

# ==============================================================================
# Cell 1: Environment & Imports
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize
import cv2

%matplotlib inline

# Resolve repository root whether running from repo root or notebooks/
repo_root = Path.cwd()
if repo_root.name == "notebooks":
    repo_root = repo_root.parent

if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import romanepsf as rep

print(f"romanepsf version: {rep.__version__}")
print(f"Repository root: {repo_root}")"""))

# ==============================================================================
# Cell 2: Step 1 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""## Step 1: Load Roman Level 2 Dataset, Stellar Catalog, and Gaia Astrometry

We load the simulated commissioning Level 2 ASDF dataset for detector `wfi01` (PID 1083), the pre-filtered tiered stellar catalog, and query neighbor Gaia stars within the detector footprint."""))

# ==============================================================================
# Cell 3: Step 1 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""# Paths to dataset, catalog, and configuration
l2_path = "/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf"

config_path = repo_root / "configs" / "default.yaml"
catalog_path = repo_root / "output" / "run_all" / "wfi01_stars_tiered.csv"
if not catalog_path.exists():
    catalog_path = repo_root / "output" / "wfi01_stars_tiered.csv"

# Load config and calibrated Level 2 data
cfg = rep.load_config(str(config_path))
l2 = rep.load_l2_image(l2_path, calibrate=True)
stars_df = pd.read_csv(catalog_path)

# Query and project Gaia companion stars for this detector
gaia_df = rep.query_gaia_for_detector(l2, mag_limit=20.0, cache_dir=str(repo_root / "cache"))
gaia_pix = rep.project_catalog_to_pixels(l2, gaia_df)

print(f"Detector: {l2.detector} | Filter: {l2.filter_name}")
print(f"Science image shape: {l2.data.shape} | Pixel scale: {l2.pixel_scale:.4f} arcsec/pixel")
print(f"Poisson variance array (var_poisson) loaded: {l2.var_poisson is not None}")
if l2.var_poisson is not None:
    print(f"  var_poisson shape: {l2.var_poisson.shape} | dtype: {l2.var_poisson.dtype}")
print(f"Total tiered stars on {l2.detector}: {len(stars_df)}")
print(f"Total Gaia reference stars in active area: {len(gaia_pix)}")
display(stars_df[["source_id", "tier", "mag_lambda", "peak_flux", "x", "y"]].head(10))"""))

# ==============================================================================
# Cell 4: Step 2 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""## Step 2: Choose Stellar Brightness Tier and Profile Method

Configure the stellar brightness tier and profile fitting method below:

- **Brightness Tiers**:
  - `'bright'` ($m < 11.0$): Extended PSF wings and 24 diffraction spikes out to hundreds of pixels. Core saturated.
  - `'medium'` ($11.0 \\le m < 13.0$): Moderately bright transition stars bridging core and outer wings.
  - `'faint'` ($m \\ge 13.0$): Unsaturated core stars ($r < 1.5''$). Profile fitting and contaminant masking are skipped.
- **Methods**:
  - `'moffat'`: 2-iteration AstroPhot Moffat fitting weighted with `var_poisson`, updating the mask with erosion-dilation.
  - `'superback'`: Forward-modeled Roman SUPERBACK optical PSF (via `rosalia.superback_pytorch`) for bright stars.
  - `'stpsf'`: Forward-modeled Roman STPSF instrumental PSF (via `stpsf.WFI`) for medium stars.
  - `'unsharp'`: Gaussian unsharp masking residual ($I_{\\text{obs}} - I_{\\text{smooth}}$).
  - `'mto2'`: Semantically-informed Max-Tree Object Representation & Deblending ([MTO2](https://github.com/m-faezi/MTO2)) to detect and mask sources that are not the main star stamp.
  - `'auto'`: Dispatches `'moffat'` by default."""))

# ==============================================================================
# Cell 5: Step 2 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""# >>> SELECT TIER AND METHOD HERE <<<
SELECTED_TIER = "bright"      # 'bright', 'medium', or 'faint'
SELECTED_METHOD = "moffat"    # 'moffat', 'superback', 'stpsf', 'unsharp', 'mto2', or 'auto'

tier_candidates = stars_df[stars_df["tier"] == SELECTED_TIER].reset_index(drop=True)
print(f"Available '{SELECTED_TIER}' stars on {l2.detector}: {len(tier_candidates)}")

# Select first candidate star in this tier
target_star = tier_candidates.iloc[0]
print(f"Selected Star ID: {target_star['source_id']}")
print(f"  Coordinates: RA={target_star['ra']:.5f}°, Dec={target_star['dec']:.5f}°")
print(f"  Pixel position: ({target_star['x']:.2f}, {target_star['y']:.2f})")
print(f"  Magnitude (F146): {target_star['mag_lambda']:.2f} | Peak flux: {target_star['peak_flux']:.1f} DN/s")
print(f"  Active Method: {SELECTED_METHOD.upper()}")"""))

# ==============================================================================
# Cell 6: Step 3 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""## Step 3: Adaptive Postage Stamp Extraction & Poisson Variance (`var_poisson`)

We calculate the adaptive cutout size based on the expected PSF extension and extract:
1. Science flux cutout (`raw_stamp`)
2. Data quality mask (`raw_dq`)
3. Poisson noise variance cutout (`raw_vp`) from `l2.var_poisson`"""))

# ==============================================================================
# Cell 7: Step 3 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""# 1. Determine adaptive cutout size
stamp_sz = rep.get_adaptive_stamp_size(
    mag=target_star["mag_lambda"],
    tier=SELECTED_TIER,
    max_size=cfg.stamps.sizes.bright_max,
    pixel_scale=l2.pixel_scale,
)
print(f"Calculated adaptive cutout size: {stamp_sz} x {stamp_sz} pixels ({stamp_sz * l2.pixel_scale:.1f} x {stamp_sz * l2.pixel_scale:.1f} arcsec)")

# 2. Extract raw science flux, DQ mask, and var_poisson cutouts
center_xy = (float(target_star["x"]), float(target_star["y"]))
dq_bad = rep.get_dq_mask(l2.dq, cfg.stamps.dq_flags_to_mask)

raw_stamp, (ix, iy) = rep.extract_cutout(l2.data, center_xy, stamp_sz, fill_value=np.nan)
raw_dq, _ = rep.extract_cutout(dq_bad.astype(np.uint8), center_xy, stamp_sz, fill_value=1)
raw_dq = raw_dq.astype(bool)

raw_vp = None
if getattr(l2, "var_poisson", None) is not None:
    raw_vp, _ = rep.extract_cutout(l2.var_poisson, center_xy, stamp_sz, fill_value=np.nan)

print(f"Extracted integer grid center: ({ix}, {iy})")
print(f"Sub-pixel centroid offset: dx={center_xy[0] - ix:+.3f} px, dy={center_xy[1] - iy:+.3f} px")
if raw_vp is not None:
    print(f"Extracted var_poisson cutout: shape {raw_vp.shape}, median variance = {np.nanmedian(raw_vp):.3e} (MJy/sr)^2")"""))

# ==============================================================================
# Cell 8: Step 4 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""## Step 4: Sub-pixel Centering & Background Subtraction

The star's continuous centroid $(x, y)$ generally falls on fractional pixel coordinates. We apply continuous spline interpolation shifting by $(-\\Delta x, -\\Delta y)$ to position the stellar peak precisely at the grid center $((N-1)/2, (N-1)/2)$, followed by local sky background estimation and subtraction."""))

# ==============================================================================
# Cell 9: Step 4 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""subpixel_offset = (center_xy[0] - ix, center_xy[1] - iy)
aligned_data, aligned_mask = rep.recenter_and_align_stamp(raw_stamp, raw_dq, subpixel_offset)

# Estimate and subtract local background
bkg_val, bkg_rms = rep.estimate_stamp_background(aligned_data, aligned_mask, method="annulus")
aligned_sub = rep.subtract_stamp_background(aligned_data, bkg_val)

print(f"Estimated local background: {bkg_val:.3f} MJy/sr (RMS: {bkg_rms:.3f})")
print(f"Aligned stamp shape: {aligned_sub.shape}")"""))

# ==============================================================================
# Cell 10: Step 5 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""## Step 5: Profile Fitting & Residual Map Methods

To isolate non-stellar contaminants and companion stars from the primary star, the pipeline supports multiple residual strategies:

### 1. 2-Iteration AstroPhot Moffat Fitting (`method='moffat'`)
Fits a 2D circularly symmetric Moffat profile:
$$I_{\\text{moffat}}(r) = \\frac{I_0}{\\left(1 + (r / R_d)^2\\right)^n} + b$$
- Weighted by Poisson noise variance (`var_poisson`).
- Central core ($r \\le r_{\\text{core}}$) and neighbor Gaia stars are masked during the fit.
- **Iteration 1**: Initial fit and contaminant detection.
- **Iteration 2**: Re-fit with updated mask excluding initial contaminants, producing the final refined residual.

### 2. Forward Physical Model Fitting (`method='superback'` / `method='stpsf'`)
- **SUPERBACK** (from `rosalia.superback_pytorch`): Chromatic optical PSF generated from pupil geometry and optical path differences for bright stars.
- **STPSF** (from `stpsf.WFI`): Instrumental Roman WFI PSF models for medium stars.
- Evaluated on image pixels with weighted least-squares amplitude and sub-pixel alignment.

### 3. Gaussian Unsharp Masking (`method='unsharp'`)
Computes high-pass residuals:
$$\\Delta I = I_{\\text{obs}} - G_\\sigma \\ast I_{\\text{obs}}$$
without parametric assumptions.

### 4. Neighbor Gaia Companion Masking
Computes circular aperture exclusion radii using `get_psf_extension_moffat(mag, depth=28.0)`."""))

# ==============================================================================
# Cell 11: Step 5 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""# Compute neighbor Gaia companion mask using get_psf_extension_moffat
core_rad = 6.0 if SELECTED_TIER == "bright" else 4.0
comp_mask = rep.mask_gaia_companion_stars(
    aligned_sub.shape,
    ((stamp_sz - 1) / 2.0, (stamp_sz - 1) / 2.0),
    gaia_pix,
    target_center_xy=center_xy,
    pixel_scale=l2.pixel_scale,
    depth=28.0,
    core_exclusion_radius_px=core_rad,
)
print(f"Neighbor Gaia stars masked in stamp: {np.sum(comp_mask):,} pixels")

# Demonstrate AstroPhot 2D Moffat fit with var_poisson weighting
moffat_img, moffat_model = rep.fit_moffat_model(
    aligned_sub,
    dq_mask=aligned_mask,
    mask=comp_mask,
    min_radius=core_rad,
    max_radius=min(max((stamp_sz - 1) * 0.2, 30.0), 100.0),
    variance=raw_vp,
    engine="astrophot",
)
moffat_residual = aligned_sub - moffat_img
print(f"Moffat fit completed. Residual range: [{np.nanmin(moffat_residual):.2e}, {np.nanmax(moffat_residual):.2e}] MJy/sr")

# Demonstrate 2D Sérsic profile fit
sersic_img, sersic_model = rep.fit_sersic_model(
    aligned_sub,
    dq_mask=aligned_mask,
    mask=comp_mask,
    min_radius=core_rad,
    max_radius=min(max((stamp_sz - 1) * 0.2, 30.0), 100.0),
    variance=raw_vp,
    engine="astrophot",
)
sersic_residual = aligned_sub - sersic_img
print(f"Sérsic fit completed. Residual range: [{np.nanmin(sersic_residual):.2e}, {np.nanmax(sersic_residual):.2e}] MJy/sr")

# Demonstrate Compound Sérsic + Moffat fit
compound_img, compound_model = rep.fit_sersic_moffat_model(
    aligned_sub,
    dq_mask=aligned_mask,
    mask=comp_mask,
    min_radius=core_rad,
    max_radius=min(max((stamp_sz - 1) * 0.2, 30.0), 100.0),
    variance=raw_vp,
)
compound_residual = aligned_sub - compound_img
print(f"Compound fit completed. Residual range: [{np.nanmin(compound_residual):.2e}, {np.nanmax(compound_residual):.2e}] MJy/sr")"""))

# ==============================================================================
# Cell 12: Step 6 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell(r"""## Step 6: Dual-Prior Spike Protection & Erosion-Dilation Contaminant Masking

Roman's secondary mirror spider struts and pupil facets produce **24 diffraction spikes** (dual 12-ray sets).
To strictly protect genuine spikes while masking external contaminants:
1. **Theoretical Spike Priors**: All 24 rays rotated by `roll_ref` and detector alignment offset (`-9.70°`).
2. **Empirical Refinement**: Radial line maximization snapping rays to observed peaks within $\pm 3.5^\circ$.
3. **Erosion-Dilation Contaminant Masking**:
   $$\\text{threshold} = \\text{median} + 1.5 \\times \\text{std}$$
   $$\\text{mask} = \\text{dilate}(\\text{erode}(\\text{residual} > \\text{threshold}, \\, 1\\times 1), \\, 3\\times 3)$$
   $$\\text{mask}[\\text{protected\\_spikes} > 0] = 0$$
   Plus circular apertures for neighbor Gaia stars."""))

# ==============================================================================
# Cell 13: Step 6 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""pa_aperture = float(getattr(l2, "pa_aperture", l2.meta.get("roll_ref", -110.02)))
cfg.spikes.spike_order = "both"  # Dual-12 rays (all 24 spikes)

final_mask, protected_spikes, residual_map = rep.mask_contaminants_with_spikes_protected(
    aligned_sub,
    dq_mask=aligned_mask,
    pa_aperture=pa_aperture,
    cfg=cfg.spikes,
    tier=SELECTED_TIER,
    companion_stars=gaia_pix,
    target_center_xy=center_xy,
    pixel_scale=l2.pixel_scale,
    companion_depth=28.0,
    method=SELECTED_METHOD,
    detector=l2.detector,
    bandpass=l2.filter_name,
    var_poisson=raw_vp,
    n_iterations=2,
)

cleaned_stamp = aligned_sub.copy()
cleaned_stamp[final_mask] = np.nan

print(f"Total pixels in stamp: {aligned_sub.size:,}")
print(f"Protected spike & core pixels: {np.sum(protected_spikes):,} ({100*np.sum(protected_spikes)/aligned_sub.size:.1f}%)")
print(f"Total masked pixels: {np.sum(final_mask):,} ({100*np.sum(final_mask)/aligned_sub.size:.1f}%)")
print(f"Contaminant overlap inside protected spikes: {np.sum(final_mask & protected_spikes & ~aligned_mask)} (MUST BE 0)")"""))

# ==============================================================================
# Cell 14: Step 7 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""## Step 7: Method Comparison on the Same Star

Here we execute the four primary methods side-by-side on the exact same star cutout to compare:
1. **2-Iteration AstroPhot Moffat** (`method='moffat'` with `var_poisson`)
2. **2D Sérsic Profile** (`method='sersic'`)
3. **Compound Sérsic + Moffat** (`method='compound'`)
4. **Physical Model** (`method='superback'` for bright, `'stpsf'` for medium)
5. **Gaussian Unsharp Masking** (`method='unsharp'`)
6. **MTO2 Max-Tree Deblending** (`method='mto2'`)"""))

# ==============================================================================
# Cell 15: Step 7 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""methods_to_compare = [
    "moffat",
    "sersic",
    "compound",
    "superback" if SELECTED_TIER == "bright" else "stpsf",
    "unsharp",
    "mto2",
]
comparison_results = {}

for m in methods_to_compare:
    mask_m, prot_m, res_m = rep.mask_contaminants_with_spikes_protected(
        aligned_sub,
        dq_mask=aligned_mask,
        pa_aperture=pa_aperture,
        cfg=cfg.spikes,
        tier=SELECTED_TIER,
        companion_stars=gaia_pix,
        target_center_xy=center_xy,
        pixel_scale=l2.pixel_scale,
        method=m,
        detector=l2.detector,
        bandpass=l2.filter_name,
        var_poisson=raw_vp,
        n_iterations=2,
    )
    comparison_results[m] = {"mask": mask_m, "prot": prot_m, "residual": res_m}
    print(f"Method '{m.upper()}': Masked = {100*np.sum(mask_m)/mask_m.size:.1f}%, Protected = {100*np.sum(prot_m)/prot_m.size:.1f}%")

# Plot 6x3 comparison figure
n_methods = len(methods_to_compare)
fig, axes = plt.subplots(n_methods, 3, figsize=(15, 4.0 * n_methods))

pos_flux = aligned_sub[np.isfinite(aligned_sub) & (aligned_sub > 0)]
vmin = max(np.percentile(pos_flux, 2), 1e-4) if len(pos_flux) > 0 else 1e-4
vmax = max(np.percentile(pos_flux, 99.8), 1e-2) if len(pos_flux) > 0 else 1.0
norm = LogNorm(vmin=vmin, vmax=vmax)

for row_idx, m in enumerate(methods_to_compare):
    res_img = comparison_results[m]["residual"]
    mask_img = comparison_results[m]["mask"]
    prot_img = comparison_results[m]["prot"]
    
    # Col 1: Normal Stamp
    im1 = axes[row_idx, 0].imshow(np.maximum(aligned_sub, 1e-4), origin="lower", cmap="inferno", norm=norm)
    axes[row_idx, 0].set_title(f"Method: {m.upper()}\\nNormal Stamp", fontsize=10.5, fontweight="bold")
    axes[row_idx, 0].set_ylabel("Y (pixels)")
    plt.colorbar(im1, ax=axes[row_idx, 0], fraction=0.046, pad=0.03, label="Flux (MJy/sr)")
    
    # Col 2: Residual Map (Matching Stretch)
    im2 = axes[row_idx, 1].imshow(np.maximum(res_img, 1e-4), origin="lower", cmap="inferno", norm=norm)
    axes[row_idx, 1].set_title(f"{m.upper()} Residual Map\\nSame LogNorm Stretch", fontsize=10.5, fontweight="bold")
    plt.colorbar(im2, ax=axes[row_idx, 1], fraction=0.046, pad=0.03, label="Flux (MJy/sr)")
    
    # Col 3: Normal + Mask Overlay (Uniform Yellow)
    axes[row_idx, 2].imshow(np.maximum(aligned_sub, 1e-4), origin="lower", cmap="inferno", norm=norm)
    overlay = np.zeros((*aligned_sub.shape, 4), dtype=float)
    overlay[mask_img] = [1.0, 0.92, 0.0, 0.55]  # Uniform vivid yellow
    axes[row_idx, 2].imshow(overlay, origin="lower")
    axes[row_idx, 2].set_title(f"{m.upper()} Normal + Mask Overlay\\nMasked: {100*np.sum(mask_img)/mask_img.size:.1f}%", fontsize=10.5, fontweight="bold")
    cb_dummy = plt.colorbar(im1, ax=axes[row_idx, 2], fraction=0.046, pad=0.03)
    cb_dummy.ax.set_visible(False)

for c in range(3):
    axes[n_methods - 1, c].set_xlabel("X (pixels)")

plt.suptitle(f"Comparison of Profile Residual & Masking Methods ({SELECTED_TIER.capitalize()} Star)", fontsize=13, fontweight="bold", y=0.995)
plt.tight_layout()
fig"""))

# ==============================================================================
# Cell 16: Step 8 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""## Step 8: Publication-Quality 4-Panel Diagnostic

We display the 4-panel diagnostic layout matching the Roman ePSF validation report and masking gallery:
1. **Normal Stamp**: LogNorm stretched flux showing primary core and extended diffraction spikes.
2. **Moffat Residual Map**: 2-iteration AstroPhot Moffat profile residual $\\Delta I = I_{\\text{obs}} - I_{\\text{moffat}}$.
3. **Sérsic Residual Map**: 2D Sérsic profile residual $\\Delta I = I_{\\text{obs}} - I_{\\text{sersic}}$.
4. **Normal + Mask Overlay**: Stamp flux with a semi-transparent uniform yellow overlay highlighting masked contaminants and Gaia companion stars, with spikes and core strictly preserved."""))

# ==============================================================================
# Cell 17: Step 8 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""fig, axes = plt.subplots(1, 4, figsize=(19, 5.0), dpi=140)
fig.patch.set_facecolor("#0e1117")

pos_flux = aligned_sub[np.isfinite(aligned_sub) & (aligned_sub > 0)]
vmin = max(np.percentile(pos_flux, 2), 1e-4) if len(pos_flux) > 0 else 1e-4
vmax = max(np.percentile(pos_flux, 99.8), 1e-2) if len(pos_flux) > 0 else 1.0
norm = LogNorm(vmin=vmin, vmax=vmax)

# Panel 1: Normal Stamp
ax1 = axes[0]
ax1.set_facecolor("#161b22")
im1 = ax1.imshow(np.maximum(aligned_sub, 1e-4), origin="lower", cmap="inferno", norm=norm)
ax1.set_title(f"1. Normal Stamp\\n{SELECTED_TIER.capitalize()} Star ({l2.detector})", color="#e6edf3", fontsize=10.5, fontweight="bold")
ax1.tick_params(colors="#8b949e", labelsize=8)
cb1 = plt.colorbar(im1, ax=ax1, fraction=0.046, pad=0.03)
cb1.ax.tick_params(colors="#8b949e", labelsize=7.5)
cb1.set_label("Flux (MJy/sr)", color="#8b949e", fontsize=8)

# Panel 2: Moffat Residual Map
ax2 = axes[1]
ax2.set_facecolor("#161b22")
im2 = ax2.imshow(np.maximum(moffat_residual, 1e-4), origin="lower", cmap="inferno", norm=norm)
ax2.set_title("2. AstroPhot Moffat Residual\\n$\\Delta I = I_{obs} - I_{moffat}$", color="#e6edf3", fontsize=10.5, fontweight="bold")
ax2.tick_params(colors="#8b949e", labelsize=8)
cb2 = plt.colorbar(im2, ax=ax2, fraction=0.046, pad=0.03)
cb2.ax.tick_params(colors="#8b949e", labelsize=7.5)
cb2.set_label("Residual (MJy/sr)", color="#8b949e", fontsize=8)

# Panel 3: Sérsic Residual Map
ax3 = axes[2]
ax3.set_facecolor("#161b22")
im3 = ax3.imshow(np.maximum(sersic_residual, 1e-4), origin="lower", cmap="inferno", norm=norm)
ax3.set_title("3. 2D Sérsic Residual\\n$\\Delta I = I_{obs} - I_{sersic}$", color="#e6edf3", fontsize=10.5, fontweight="bold")
ax3.tick_params(colors="#8b949e", labelsize=8)
cb3 = plt.colorbar(im3, ax=ax3, fraction=0.046, pad=0.03)
cb3.ax.tick_params(colors="#8b949e", labelsize=7.5)
cb3.set_label("Residual (MJy/sr)", color="#8b949e", fontsize=8)

# Panel 4: Normal + Mask Overlay
ax4 = axes[3]
ax4.set_facecolor("#161b22")
ax4.imshow(np.maximum(aligned_sub, 1e-4), origin="lower", cmap="inferno", norm=norm)
overlay = np.zeros((*aligned_sub.shape, 4), dtype=float)
overlay[final_mask] = [1.0, 0.92, 0.0, 0.55]
ax4.imshow(overlay, origin="lower")
ax4.set_title(f"4. Normal + Mask Overlay\\nMasked: {100*np.sum(final_mask)/final_mask.size:.1f}% | Spikes: {100*np.sum(protected_spikes)/final_mask.size:.1f}%", color="#e6edf3", fontsize=10.5, fontweight="bold")
ax4.tick_params(colors="#8b949e", labelsize=8)
cb4 = plt.colorbar(im1, ax=ax4, fraction=0.046, pad=0.03)
cb4.ax.set_visible(False)

plt.tight_layout()
fig"""))

# ==============================================================================
# Cell 18: Step 9 Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""## Step 9: Multi-Tier Comparative Gallery (Bright, Medium, Faint)

Finally, we process one star from each tier simultaneously with the updated methods to compare their morphology and masking behavior across brightness regimes."""))

# ==============================================================================
# Cell 19: Step 9 Code
# ==============================================================================
cells.append(nbf.v4.new_code_cell("""def process_single_star_pipeline(row, l2_data, config, gaia_table):
    tier = str(row["tier"]).lower()
    mag = float(row["mag_lambda"])
    cx, cy = float(row["x"]), float(row["y"])
    
    sz = rep.get_adaptive_stamp_size(mag, tier, max_size=config.stamps.sizes.bright_max, pixel_scale=l2_data.pixel_scale)
    raw_stamp, (ix, iy) = rep.extract_cutout(l2_data.data, (cx, cy), sz, fill_value=np.nan)
    dq_bad = rep.get_dq_mask(l2_data.dq, config.stamps.dq_flags_to_mask)
    raw_dq, _ = rep.extract_cutout(dq_bad.astype(np.uint8), (cx, cy), sz, fill_value=1)
    
    raw_vp = None
    if getattr(l2_data, "var_poisson", None) is not None:
        raw_vp, _ = rep.extract_cutout(l2_data.var_poisson, (cx, cy), sz, fill_value=np.nan)
        
    aligned_data, aligned_mask = rep.recenter_and_align_stamp(raw_stamp, raw_dq.astype(bool), (cx - ix, cy - iy))
    bkg_val, _ = rep.estimate_stamp_background(aligned_data, aligned_mask, method="annulus")
    aligned_sub = rep.subtract_stamp_background(aligned_data, bkg_val)
    
    pa_aperture = float(getattr(l2_data, "pa_aperture", l2_data.meta.get("roll_ref", -110.02)))
    
    final_mask, protected, residual = rep.mask_contaminants_with_spikes_protected(
        aligned_sub,
        dq_mask=aligned_mask,
        pa_aperture=pa_aperture,
        cfg=config.spikes,
        tier=tier,
        companion_stars=gaia_table,
        target_center_xy=(cx, cy),
        pixel_scale=l2_data.pixel_scale,
        method="moffat",
        detector=l2_data.detector,
        bandpass=l2_data.filter_name,
        var_poisson=raw_vp,
        n_iterations=2,
    )
    return aligned_sub, residual, final_mask, protected

tiers = ["bright", "medium", "faint"]
gallery = {}
for t in tiers:
    cand = stars_df[stars_df["tier"].str.lower() == t].iloc[0]
    gallery[t] = process_single_star_pipeline(cand, l2, cfg, gaia_pix)

fig, axes = plt.subplots(3, 3, figsize=(15, 13), dpi=120)
fig.patch.set_facecolor("#0e1117")

for row_idx, t in enumerate(tiers):
    orig, res, mask, prot = gallery[t]
    cand = stars_df[stars_df["tier"].str.lower() == t].iloc[0]
    
    pos = orig[np.isfinite(orig) & (orig > 0)]
    vmin = max(np.percentile(pos, 2), 1e-4) if len(pos) > 0 else 1e-4
    vmax = max(np.percentile(pos, 99.8), 1e-2) if len(pos) > 0 else 1.0
    norm = LogNorm(vmin=vmin, vmax=vmax)
    
    # Col 1: Normal Stamp
    ax1 = axes[row_idx, 0]
    ax1.set_facecolor("#161b22")
    im1 = ax1.imshow(np.maximum(orig, 1e-4), origin="lower", cmap="inferno", norm=norm)
    ax1.set_title(f"{t.capitalize()} Star (mag={cand['mag_lambda']:.2f})\\nNormal Stamp ({orig.shape[0]}x{orig.shape[1]} px)", fontsize=10.5, color="#e6edf3", fontweight="bold", pad=5)
    ax1.set_ylabel("Y (pixels)", color="#8b949e")
    ax1.tick_params(colors="#8b949e", labelsize=8)
    cb1 = plt.colorbar(im1, ax=ax1, fraction=0.046, pad=0.03)
    cb1.ax.tick_params(colors="#8b949e", labelsize=7.5)
    
    # Col 2: Residual Map
    ax2 = axes[row_idx, 1]
    ax2.set_facecolor("#161b22")
    im2 = ax2.imshow(np.maximum(res, 1e-4), origin="lower", cmap="inferno", norm=norm)
    res_label = "Direct Pass-Through" if t == "faint" else "2-Iter Moffat Residual"
    ax2.set_title(f"{t.capitalize()} — {res_label}\\nSame LogNorm Stretch", fontsize=10.5, color="#e6edf3", fontweight="bold", pad=5)
    ax2.tick_params(colors="#8b949e", labelsize=8)
    cb2 = plt.colorbar(im2, ax=ax2, fraction=0.046, pad=0.03)
    cb2.ax.tick_params(colors="#8b949e", labelsize=7.5)
    
    # Col 3: Normal + Mask Overlay
    ax3 = axes[row_idx, 2]
    ax3.set_facecolor("#161b22")
    ax3.imshow(np.maximum(orig, 1e-4), origin="lower", cmap="inferno", norm=norm)
    overlay = np.zeros((*orig.shape, 4), dtype=float)
    overlay[mask] = [1.0, 0.92, 0.0, 0.55]
    ax3.imshow(overlay, origin="lower")
    mask_label = "No Contaminant Masking" if t == "faint" else f"Masked: {100*np.sum(mask)/mask.size:.1f}%"
    ax3.set_title(f"{t.capitalize()} — Normal + Mask Overlay\\n{mask_label}", fontsize=10.5, color="#e6edf3", fontweight="bold", pad=5)
    ax3.tick_params(colors="#8b949e", labelsize=8)
    cb3 = plt.colorbar(im1, ax=ax3, fraction=0.046, pad=0.03)
    cb3.ax.set_visible(False)

for c in range(3):
    axes[2, c].set_xlabel("X (pixels)", color="#8b949e")

plt.suptitle("Stellar Stamp & Masking Comparison Across Brightness Tiers (Roman WFI)", fontsize=13, color="#58a6ff", fontweight="bold", y=0.99)
plt.tight_layout()
fig"""))

# ==============================================================================
# Cell 20: Conclusion Markdown
# ==============================================================================
cells.append(nbf.v4.new_markdown_cell("""### Key Takeaways & Pipeline Methods:
- **Profile Residual Methods**:
  - `method='moffat'`: 2-iteration AstroPhot Moffat fitting weighted with Level 2 `var_poisson` yields smooth residuals across high dynamic ranges and converges rapidly.
  - `method='superback'` / `method='stpsf'`: Physical model forward-fitting provides high fidelity to the true Roman optical and detector pupil physics.
  - `method='unsharp'`: Unsharp masking offers a robust non-parametric fallback when profile convergence is challenging.
  - `tier='faint'`: Profile subtraction and contaminant masking are omitted to preserve central flux for empirical PSF core reconstruction.
- **Dual-Prior Protection**: Theoretical dual-12 rays combined with empirical refinement and morphological filtering strictly preserve Roman's 24 diffraction spikes and central core.
- **Neighbor Gaia Masking**: `get_psf_extension_moffat` analytically calculates aperture radii at 28 mag/arcsec$^2$ depth, cleanly excising contamination from nearby field stars."""))

nb["cells"] = cells

# Save notebook
out_path = Path("notebooks/01_stamp_extraction_masking_tutorial.ipynb")
with open(out_path, "w", encoding="utf-8") as f:
    nbf.write(nb, f)

print(f"SUCCESS: Written {len(cells)} cells to {out_path}")
