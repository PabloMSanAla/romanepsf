import sys
import numpy as np
import pandas as pd
from pathlib import Path

from romanepsf import loader, catalog, stamps, assembly
from romanepsf.masking import mask_contaminants_with_spikes_protected

print("Python executable:", sys.executable)

data_dir = Path("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors")
cat_path = data_dir / "code" / "r0108301001001001001_0001_wfi_source_catalog.csv"

# Load catalog
print(f"Reading catalog from {cat_path}...")
full_cat = pd.read_csv(cat_path, low_memory=False)

# ==============================================================================
# TEST 1: Defect 1 - WFI01 k_MB and Radial Monotonicity across [30, 48] px
# ==============================================================================
print("\n" + "="*70)
print("TEST 1: Defect 1 Verification on WFI01")
print("="*70)

wfi01_asdf = data_dir / "r0108301001001001001_0001_wfi01_f146_cal.asdf"
print(f"Loading WFI01 from {wfi01_asdf}...")
l2_wfi01 = loader.load_l2_image(wfi01_asdf, calibrate=True)

ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2_wfi01)
cand01 = full_cat[(np.abs(full_cat["ra"] - ra_c) < rad) & (np.abs(full_cat["dec"] - dec_c) < rad)].copy()
cand01["phot_g_mean_mag"] = cand01["phot_g_mean_mag"].fillna(cand01["mag_lambda"])
proj01 = catalog.project_catalog_to_pixels(l2_wfi01, cand01, margin_px=25)
tiered01 = catalog.assign_stellar_tiers(proj01, bright_limit=11.0, faint_limit=13.0)

print(f"Projected stars on WFI01: {len(tiered01)}")
tier_counts01 = tiered01["tier"].value_counts().to_dict()
print(f"Tier counts: {tier_counts01}")

stamps01 = stamps.process_star_stamps(l2_wfi01, tiered01)
print(f"Extracted stamps: Bright={len(stamps01['bright'])}, Medium={len(stamps01['medium'])}, Faint={len(stamps01['faint'])}")

epsf01, diag01 = assembly.assemble_composite_extended_psf(stamps01, output_size=501)
k_fm01 = diag01["k_fm"]
k_mb01 = diag01["k_mb"]
print(f"WFI01 Diagnostics: k_fm = {k_fm01:.6f}, k_mb = {k_mb01:.6f}")

# Assertion 1: 0.010 < k_mb < 0.100
assert k_mb01 is not None, "k_mb is None on WFI01!"
assert 0.010 < k_mb01 < 0.100, f"FAILED: k_mb = {k_mb01} is outside [0.010, 0.100]!"
print(f"PASS: 0.010 < k_mb < 0.100 (k_mb = {k_mb01:.6f})")

# Check radial profile across [30, 48] px
c = 250  # center of 501x501 canvas
r_centers01, prof_epsf01, _ = assembly.measure_radial_profile_1d(epsf01, rmax=60)
mask_blend = (r_centers01 >= 30.0) & (r_centers01 <= 48.0)
r_blend = r_centers01[mask_blend]
prof_blend = prof_epsf01[mask_blend]

print("\nRadial profile across blend zone [30, 48] px:")
for r_val, f_val in zip(r_blend, prof_blend):
    print(f"  r = {r_val:5.1f} px: flux = {f_val:.8e}")

flux_30 = epsf01[c, c + 30]
flux_48 = epsf01[c, c + 48]
print(f"\nCenter slice horizontal: epsf[250, 280] (r=30) = {flux_30:.8e}")
print(f"Center slice horizontal: epsf[250, 298] (r=48) = {flux_48:.8e}")
assert flux_48 < flux_30, f"FAILED: Flux surge! flux(r=48) = {flux_48} >= flux(r=30) = {flux_30}"

# Check strictly monotonic decay across the blend zone in the radial profile
diffs = np.diff(prof_blend)
print("Flux differences between adjacent radii in [30, 48] px:", diffs)
assert np.all(diffs <= 0.0), f"FAILED: Radial profile not strictly monotonically decaying in [30, 48] px: {diffs}"
print(f"PASS: Monotonic decay verified across [30, 48] px! Ratio flux(r=48)/flux(r=30) = {prof_blend[-1]/prof_blend[0]:.4f}")


# ==============================================================================
# TEST 2: Defect 2 - False Halo Contaminant Over-masking on Medium Stars
# ==============================================================================
print("\n" + "="*70)
print("TEST 2: Defect 2 Verification on Medium Star Stamps")
print("="*70)

med_stamps = stamps01["medium"]
print(f"Number of medium stamps on WFI01: {len(med_stamps)}")

for idx, s in enumerate(med_stamps):
    sz = s.data.shape[0]
    cy, cx = (sz - 1) / 2.0, (sz - 1) / 2.0
    gy, gx = np.ogrid[:sz, :sz]
    r_grid = np.sqrt((gx - cx)**2 + (gy - cy)**2)
    annulus_22_45 = (r_grid >= 22.0) & (r_grid <= 45.0)
    
    # Check fraction masked in annulus [22, 45] px
    masked_pixels = s.mask[annulus_22_45]
    mask_frac = np.mean(masked_pixels)
    print(f"Medium Stamp {idx} (source_id={s.source_id}, mag={s.mag:.2f}, size={sz}x{sz}):")
    print(f"  Mask fraction in [22, 45] px: {mask_frac * 100:.2f}% ({np.sum(masked_pixels)}/{len(masked_pixels)} pixels)")
    assert mask_frac < 0.05, f"FAILED: Mask fraction {mask_frac * 100:.2f}% >= 5% in [22, 45] px!"
    print(f"  PASS: Mask fraction < 5%")

# Empirical companion detection test: inject an off-axis companion into real WFI01 medium star
print("\nTesting off-axis companion detection on real WFI01 medium star stamp...")
s_med0 = med_stamps[0]
data0 = s_med0.data.copy()
sz0 = data0.shape[0]
cx0, cy0 = (sz0 - 1) / 2.0, (sz0 - 1) / 2.0
gy0, gx0 = np.ogrid[:sz0, :sz0]
r_grid0 = np.hypot(gx0 - cx0, gy0 - cy0)

# Companion at r=25 px (angle=40 deg, outside 6-fold spikes)
comp_x0 = cx0 + 25.0 * np.cos(np.radians(40.0))
comp_y0 = cy0 + 25.0 * np.sin(np.radians(40.0))
comp_r0 = np.hypot(gx0 - comp_x0, gy0 - comp_y0)

# Inject faint companion with peak 15 MJy/sr (companion is 250x fainter than primary core, but distinct from halo 2.5 MJy/sr)
companion_star = (15.0 * np.exp(-comp_r0**2 / (2.0 * 1.5**2))).astype(np.float32)
data_injected = data0 + companion_star

mask_inj, prot_inj, res_inj = mask_contaminants_with_spikes_protected(
    data_injected,
    dq_mask=None,
    pa_aperture=l2_wfi01.pa_aperture,
    tier="medium",
)

px_x0, px_y0 = int(round(comp_x0)), int(round(comp_y0))
comp_masked = mask_inj[px_y0, px_x0]
print(f"Real stamp + companion injection: companion peak masked = {comp_masked}")
assert comp_masked, "FAILED: Injected companion was not detected and masked!"

halo_clean_inj = (r_grid0 >= 22.0) & (r_grid0 <= 45.0) & (comp_r0 > 8.0)
halo_masked_frac_inj = np.mean(mask_inj[halo_clean_inj])
print(f"Surrounding halo mask fraction (excluding companion): {halo_masked_frac_inj * 100:.2f}%")
assert halo_masked_frac_inj < 0.05, f"FAILED: Halo over-masked: {halo_masked_frac_inj * 100:.2f}%"
print("PASS: Off-axis companion detected and halo preserved (<5% masked)!")


# ==============================================================================
# TEST 3: Defect 3 - Missing Bright Tier on WFI02
# ==============================================================================
print("\n" + "="*70)
print("TEST 3: Defect 3 Verification on WFI02")
print("="*70)

wfi02_asdf = data_dir / "r0108301001001001001_0001_wfi02_f146_cal.asdf"
print(f"Loading WFI02 from {wfi02_asdf}...")
l2_wfi02 = loader.load_l2_image(wfi02_asdf, calibrate=True)

ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2_wfi02)
cand02 = full_cat[(np.abs(full_cat["ra"] - ra_c) < rad) & (np.abs(full_cat["dec"] - dec_c) < rad)].copy()
cand02["phot_g_mean_mag"] = cand02["phot_g_mean_mag"].fillna(cand02["mag_lambda"])
proj02 = catalog.project_catalog_to_pixels(l2_wfi02, cand02, margin_px=25)
tiered02 = catalog.assign_stellar_tiers(proj02, bright_limit=11.0, faint_limit=13.0)

print(f"Projected stars on WFI02: {len(tiered02)}")
tier_counts02 = tiered02["tier"].value_counts().to_dict()
print(f"Tier counts: {tier_counts02}")
assert tier_counts02.get("bright", 0) == 0, "WFI02 should have 0 bright stars in catalog!"

stamps02 = stamps.process_star_stamps(l2_wfi02, tiered02)
print(f"Extracted stamps: Bright={len(stamps02['bright'])}, Medium={len(stamps02['medium'])}, Faint={len(stamps02['faint'])}")
assert len(stamps02["bright"]) == 0, "WFI02 bright stamp list should be empty!"

try:
    epsf02, diag02 = assembly.assemble_composite_extended_psf(stamps02, output_size=501)
    print("Clean assembly executed without exception!")
except ValueError as e:
    raise AssertionError(f"FAILED: assemble_composite_extended_psf raised ValueError on WFI02: {e}")

print(f"epsf02 shape: {epsf02.shape}")
print(f"epsf02 sum (total flux): {np.sum(epsf02):.8f}")
print(f"epsf02 center peak: {epsf02[250, 250]:.8e}")
print(f"k_fm = {diag02['k_fm']}, k_mb = {diag02['k_mb']}")

assert epsf02.shape == (501, 501), f"Unexpected shape {epsf02.shape}"
assert np.isclose(np.sum(epsf02), 1.0, atol=1e-5), f"Total flux not normalized: {np.sum(epsf02)}"
assert epsf02[250, 250] > 0.0, "Center peak is zero or negative!"
assert diag02["k_fm"] is not None and diag02["k_fm"] > 0.0, f"k_fm invalid: {diag02['k_fm']}"
assert diag02["k_mb"] is None, f"k_mb should be None for 2-tier assembly, got {diag02['k_mb']}"
print("PASS: WFI02 2-tier assembly verified! Shape (501, 501), sum=1.0, k_mb=None")

print("\n" + "="*70)
print("ALL EMPIRICAL TESTS PASSED SUCCESSFULLY!")
print("="*70)
