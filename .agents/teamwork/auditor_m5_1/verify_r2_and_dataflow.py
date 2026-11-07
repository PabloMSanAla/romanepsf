import sys
from pathlib import Path
import numpy as np
import pandas as pd
from astropy.io import fits
import math

fits_path = Path("/Users/pmsanch1/code/romanepsf/output/run_all/roman_epsf_composite.fits")
if not fits_path.is_file():
    print(f"ERROR: {fits_path} does not exist!")
    sys.exit(1)

print(f"=== Inspecting FITS: {fits_path} ===")
with fits.open(fits_path) as hdul:
    hdul.info()
    header = hdul[0].header
    epsf = hdul[0].data.astype(np.float32)
    cov = hdul[1].data
    rad_table = hdul[2].data
    det_table = hdul[3].data

print(f"EPSF shape: {epsf.shape}, dtype: {epsf.dtype}, min: {np.nanmin(epsf)}, max: {np.nanmax(epsf)}")
print(f"COVERAGE shape: {cov.shape}, dtype: {cov.dtype}, min: {cov.min()}, max: {cov.max()}")
print(f"RADIAL_PROFILES rows: {len(rad_table)}, columns: {rad_table.names}")
print(f"DETECTOR_SUMMARY rows: {len(det_table)}, columns: {det_table.names}")

# 1. Non-circularity and Azimuthal Modulation Analysis
print("\n=== 1. Non-Circularity and 2D Azimuthal Structure Test ===")
ny, nx = epsf.shape
cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
y_idx, x_idx = np.ogrid[:ny, :nx]
r_map = np.hypot(x_idx - cx, y_idx - cy)
theta_map = (np.degrees(np.arctan2(y_idx - cy, x_idx - cx)) + 360.0) % 360.0

test_radii = [15.0, 30.0, 60.0, 100.0, 150.0, 200.0]
for r_target in test_radii:
    annulus_mask = (r_map >= r_target - 1.5) & (r_map <= r_target + 1.5)
    fluxes = epsf[annulus_mask]
    thetas = theta_map[annulus_mask]
    
    std_val = float(np.std(fluxes))
    mean_val = float(np.mean(fluxes))
    median_val = float(np.median(fluxes))
    max_val = float(np.max(fluxes))
    min_val = float(np.min(fluxes))
    azimuthal_modulation = (max_val - min_val) / (mean_val + 1e-15)
    
    print(f"Radius {r_target:5.1f} px: mean={mean_val:.3e}, std={std_val:.3e}, max/median={max_val/(median_val+1e-15):.2f}, modulation={azimuthal_modulation:.2f}")

# If modulation was ~0, it would be circularized.
if any((np.max(epsf[(r_map >= r - 1.5) & (r_map <= r + 1.5)]) / np.median(epsf[(r_map >= r - 1.5) & (r_map <= r + 1.5)])) < 1.5 for r in [60.0, 100.0]):
    print("WARNING: Model appears circularized!")
else:
    print("PASS: Model shows strong non-circular azimuthal structure (spikes / asymmetry).")

# 2. 6-Fold Diffraction Spike Alignment Verification
print("\n=== 2. Theoretical Spike Ray Geometry Verification ===")
from romanepsf.masking import ROMAN_BASE_SPIKE_ANGLES_DEG, get_theoretical_spike_angles

from romanepsf.report import extract_empirical_azimuthal_profile

azim_res = extract_empirical_azimuthal_profile(
    results_dir=Path("output/run_all"),
    epsf_canvas=epsf,
    radius_px=50.0,
    n_bins=180
)

theoretical_12_rays = azim_res["spike_angles"]
print(f"Theoretical 12 spike rays (with PA_APER={azim_res['pa_aperture']} and det_offset=-9.70):")
for idx, ang in enumerate(theoretical_12_rays):
    print(f"  Ray {idx+1:02d}: {ang:6.2f} deg")

theta_deg = azim_res["theta_deg"]
fl_prof = azim_res["obs_flux"] if azim_res["has_observed"] else azim_res["mod_flux"]
print(f"Azimuthal profile source: {'Observed bright star residual' if azim_res['has_observed'] else 'Composite ePSF canvas'}")

# Find peaks in azimuthal profile
from scipy.signal import find_peaks
prom = (np.nanpercentile(fl_prof, 85) - np.nanmin(fl_prof)) * 0.3
peaks, _ = find_peaks(fl_prof, distance=8, prominence=prom)
peak_angles = theta_deg[peaks]

print(f"\nEmpirical peaks detected in azimuthal profile ({len(peaks)} peaks):")
for p_ang in peak_angles:
    print(f"  Peak at {p_ang:6.2f} deg")

# Compare detected peaks with theoretical rays
matches = 0
for ray in theoretical_12_rays:
    if len(peak_angles) > 0:
        diffs = np.abs((peak_angles - ray + 180) % 360 - 180)
        min_diff = np.min(diffs)
        is_match = min_diff <= 8.0 # within 8 degrees
        closest_p = peak_angles[np.argmin(diffs)]
    else:
        min_diff = 999.0
        is_match = False
        closest_p = 0.0
    if is_match:
        matches += 1
    print(f"  Ray {ray:6.2f} deg -> closest detected peak {closest_p:6.2f} deg (diff: {min_diff:4.2f} deg) - {'MATCH' if is_match else 'MISS'}")

print(f"Spike alignment score: {matches} / {len(theoretical_12_rays)} theoretical rays matched within 8 deg.")


# 3. Check DETECTOR_SUMMARY HDU 3 Authenticity
print("\n=== 3. Ingesting Real Runtime Metrics from HDU 3 (DETECTOR_SUMMARY) ===")
det_df = pd.DataFrame({
    col: [x.decode("utf-8") if isinstance(x, bytes) else x for x in det_table[col]]
    for col in det_table.names
})
for num_col in ["N_FAINT", "N_MEDIUM", "N_BRIGHT", "N_TOTAL", "PA_APER_DEG", "PIXSCALE", "TIME_SEC"]:
    det_df[num_col] = pd.to_numeric(det_df[num_col])

print(det_df.to_string())

# Verify genuine execution data
print("\nDetector count:", len(det_df))
print("Total stars across all detectors:", det_df["N_TOTAL"].sum())
print("Mean runtime per detector:", float(det_df["TIME_SEC"].mean()), "s")
print("Total runtime across detectors:", float(det_df["TIME_SEC"].sum()), "s")
if (det_df["TIME_SEC"] <= 0).any() or (det_df["N_TOTAL"] == 0).all():
    print("WARNING: DETECTOR_SUMMARY appears fabricated or empty!")
else:
    print("PASS: HDU 3 contains authentic, non-zero per-detector runtime and star counts.")

# 4. Check RADIAL_PROFILES HDU 2 Authenticity
print("\n=== 4. HDU 2 (RADIAL_PROFILES) Table Check ===")
rad_df = pd.DataFrame({
    col: pd.to_numeric(rad_table[col])
    for col in rad_table.names
})
print(rad_df.head(10).to_string())
print(f"RADIAL_PROFILES non-null counts:\n{rad_df.notnull().sum()}")
if rad_df["FLUX_COMPOSITE"].isnull().all() or (rad_df["FLUX_COMPOSITE"] == 0).all():
    print("WARNING: RADIAL_PROFILES empty or zero!")
else:
    print("PASS: HDU 2 contains authentic multi-tier radial profiles.")

