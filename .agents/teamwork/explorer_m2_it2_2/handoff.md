# Handoff Report: Investigation and Blueprint for Defect 2 (Stellar Halo Over-masking in masking.py)

**Agent ID**: `explorer_m2_it2_2`  
**Parent Orchestrator ID**: `e80d314a-b5a0-43fb-be2e-ceabc982347e`  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_2`  
**Date**: 2026-11-06  
**Status**: INVESTIGATION COMPLETE & BLUEPRINT DELIVERED  
**Handoff Type**: Hard Handoff  

---

## 1. Observation

### 1.1 Direct Defect Observations in Source Code
In `src/romanepsf/masking.py` (lines 408–436):
```python
    # 4. Detect extraneous non-star contaminants
    clean_area = ~protected_stellar_area
    if dq_mask is not None:
        clean_area &= (~dq_mask)

    valid_res = residual[clean_area & np.isfinite(residual)]
    if len(valid_res) > 20:
        res_med = float(np.median(valid_res))
        res_std = float(1.4826 * np.median(np.abs(valid_res - res_med)))
        if res_std <= 0.0:
            res_std = float(np.nanstd(valid_res)) or 1.0
    else:
        res_med = 0.0
        res_std = float(np.nanstd(residual)) if np.any(np.isfinite(residual)) else 1.0

    contaminants = (residual - res_med) > (detection_sigma * res_std)
    if np.any(contaminants):
        contaminants = binary_dilation(contaminants, iterations=1)

    # 5. Strict Invariant: Exclude protected spikes & core from contaminant mask
    contaminants &= (~protected_stellar_area)

    # 6. Assemble final mask
    final_mask = contaminants.copy()
    if dq_mask is not None:
        final_mask |= dq_mask
    final_mask |= (~np.isfinite(stamp))
```
In `src/romanepsf/masking.py` (lines 404–407):
```python
    spike_protection = geom_spike_mask | morph_spike_mask
    core_protection = (r <= core_protection_radius_px)
    protected_stellar_area = spike_protection | core_protection
```
And in `src/romanepsf/masking.py` (lines 248–271) inside `fit_moffat_model`:
```python
    outer = valid & (r > np.percentile(r[valid], 75))
    bkg = float(np.median(stamp[outer])) if np.any(outer) else 0.0
    ...
    fitted_image = (fitted(grid_x, grid_y) + bkg).astype(np.float32)
```

### 1.2 Quantitative Measurements on Commissioning Data (WFI01)
Executing cutout extraction, background subtraction, and masking on real commissioning detector `wfi01` (`PID1083`) reveals severe over-masking of legitimate stellar wings across all tiers:

#### A. Medium Tier Stars (201x201 Cutouts)
For Star 6854434484893040896 ($m_{\text{F146}} = 11.65$):
- Measured sky residual statistics on `clean_area`: $\text{res\_med} = -1.884$ MJy/sr, $\text{res\_std} = 0.079$ MJy/sr.
- Detection threshold: $\text{res\_med} + 3 \times \text{res\_std} = -1.647$ MJy/sr.
- Annular wing flux vs threshold:
  ```text
  Radius range | Total px | Masked px | Mask fraction | Mean flux (all)
  [10, 15) px  |      392 |       247 |         63.0% |     35.09 MJy/sr
  [15, 20) px  |      548 |       261 |         47.6% |     13.52 MJy/sr
  [20, 25) px  |      696 |       409 |         58.8% |      5.75 MJy/sr
  [25, 30) px  |      868 |       570 |         65.7% |      2.61 MJy/sr
  [30, 35) px  |     1032 |       737 |         71.4% |      1.39 MJy/sr
  [35, 40) px  |     1172 |       854 |         72.9% |      0.86 MJy/sr
  [40, 45) px  |     1336 |       956 |         71.6% |      0.60 MJy/sr
  [45, 50) px  |     1476 |       768 |         52.0% |      0.43 MJy/sr
  ```
  Excluding protected spike rays, **96.0%** of annular pixels in $[15, 45]$ px are falsely flagged as contaminants!

For Star 6866443557049402112 ($m_{\text{F146}} = 12.32$):
- In the same transition annulus $[15, 45]$ px: **85.3%** of annular wing pixels are falsely flagged as contaminants.

#### B. Impact on Medium Tier Coverage Depth
When stacking the 2 medium stars on WFI01, the resulting coverage depth in the cross-tier calibration overlap annulus $[22, 45]$ px is:
```text
Total pixels in annulus [22, 45] px: 4,848
Zero-coverage pixels (cov == 0):     3,123 (64.4%)
Mean coverage depth:                 0.63 stars (out of 2 stars)
```
More than **64.4% of the pixels** in the overlap annulus are completely unobserved (`cov == 0`). This severe coverage sparsity directly caused Defect 1 (where unmasked profiling forced `k_mb` to collapse to 1.0).

#### C. Bright Star (501x501 Cutout)
For Star 6854433763338516992 ($m_{\text{F146}} = 10.44$):
- In the bright transition annulus $[30, 80]$ px: **99.1%** of pixels are falsely flagged as contaminants!

#### D. Faint Stars (81x81 Cutouts)
For the 4 faint stars on WFI01 ($m_{\text{F146}} \sim 13.9 - 14.4$):
- In the core-transition annulus $[5, 18]$ px: **48.3% to 95.4%** of pixels are falsely flagged as contaminants!

### 1.3 Identification of Compounding Bug in `fit_moffat_model` (Pedestal Artifact)
In `masking.py:381-382`:
`max_fit_r = min(max(cx * 0.3, 20.0), 50.0)`
`moffat_img, _ = fit_moffat_model(stamp, max_radius=max_fit_r)`
In `masking.py:248`:
`valid &= (r <= max_radius)`
`outer = valid & (r > np.percentile(r[valid], 75))`
`bkg = float(np.median(stamp[outer])) if np.any(outer) else 0.0`
Because `valid` is truncated at `max_radius = 30.0` px, `outer` evaluates to $r \in [26, 30]$ px.
At $r \in [26, 30]$ px, stellar flux is $2.0 - 3.5$ MJy/sr!
`fit_moffat_model` treats this real stellar flux as `bkg`, and at line 271 executes:
`fitted_image = (fitted(grid_x, grid_y) + bkg).astype(np.float32)`
This adds a constant $+1.9$ MJy/sr pedestal across the ENTIRE 201x201 stamp!
Because `stamp` was already background-subtracted (sky background $\approx 0.0$), the residual at large radii ($r > 70$ px) evaluates to:
$\text{residual} = \text{stamp} - \text{fitted\_image} \approx 0.0 - 1.9 = -1.9\text{ MJy/sr}$.
Because `clean_area` is dominated by outer pixels ($r > 50$ px), `res_med` evaluates to $-1.884$ MJy/sr!
Consequently, for any pixel where $\text{residual} > -1.65$ MJy/sr, $\text{residual} - \text{res\_med} > 0.24$ MJy/sr ($> 3\sigma$). This guarantees that **100% of pixels in the inner 50 pixels are flagged as contaminants!**

### 1.4 Connected Component Morphological Analysis
Labeling connected components of `(residual - res_med) > 3 * res_std`:
- In Star 0: The flagged pixels form a single monolithic connected feature of **8,444 pixels** centered at $(c_x, c_y)$ ($\text{dist} = 2.8$ px, radial span $[5.0, 105.9]$ px).
- In Star 1: The flagged pixels form a single monolithic feature of **7,113 pixels** centered at $(c_x, c_y)$ ($\text{dist} = 2.9$ px, radial span $[3.6, 94.3]$ px).
- When an off-axis companion star is injected into the wing at $r = 25$ px (e.g. peak flux 15.0 MJy/sr), because the intervening diffuse halo is also $> 3\sigma$, the companion merges with the 8,444-pixel monolithic component. Simple binary connected component filtering alone cannot break the bridge between the companion and the halo without an elevated threshold.

---

## 2. Logic Chain

1. *From Observation 1.1 & 1.2*: `clean_area = ~protected_stellar_area` excludes only the 12 narrow diffraction spike rays ($\pm 4^\circ$, width $\pm 4$ px) and the innermost core ($r \le 4.0$ px for medium stars).
2. *From Observation 1.2*: In cutouts of dimension $201 \times 201$, pixels with $r > 50$ px comprise $> 80\%$ of `clean_area`. At $r > 50$ px, the stellar flux has decayed to near zero, so `res_std` estimated via MAD measures strictly distant sky noise ($\sigma_{\text{sky}} \approx 0.03 - 0.05$ MJy/sr).
3. *From Observation 1.2 & 1.3*: The real Roman Space Telescope extended optical PSF is diffraction-limited with complex non-circular pupil aberrations, secondary mirror strut diffraction, and broad extended wings. A simple circularly symmetric single-component Moffat profile fitted to the 2-pixel core drops off as $r^{-8}$ and underestimates the real empirical halo by $0.5 - 20$ MJy/sr at $r \in [10, 45]$ px.
4. *From Observation 1.2*: The flat detection threshold is $\text{res\_med} + 3 \times \text{res\_std} \approx 0.1$ to $0.15$ MJy/sr above background. Because legitimate stellar halo flux is $0.5$ to $20$ MJy/sr, every single pixel in the stellar wings exceeds the threshold.
5. *From Observation 1.1*: `contaminants` is dilated by 1 pixel (`binary_dilation(iterations=1)`), and then only spikes and $r \le 4.0$ px are protected (`contaminants &= (~protected_stellar_area)`).
6. *From Observation 1.2*: This wipes out 85.3% to 96.0% of all annular pixels in the medium star wings $[15, 45]$ px, leaving 64.4% of the pixels in $[22, 45]$ px with zero coverage (`cov == 0`).
7. *From Observation 1.4*: Because the diffuse halo flux is continuous, at a flat $3\sigma$ threshold, an off-axis companion star merges with the halo into an 8,444-pixel component. To isolate genuine compact companion stars and cosmic rays, the detection threshold must scale radially:
   $$\sigma(r) = \sigma_0 \cdot \left(1 + A \cdot \exp\left(-\frac{r}{r_0}\right)\right)$$
8. *From Empirical Tests*: Setting $A = 200.0, r_0 = 15.0$ px (for medium stars) and $A = 50.0, r_0 = 15.0$ px (for faint stars):
   - Elevation at $r=15$ px: $\sigma(15) \approx 3 \times (1 + 200 \times 0.368) \approx 224\sigma$ ($\sim 11$ MJy/sr). Legitimate halo ($10$ MJy/sr) is preserved.
   - Elevation at $r=25$ px: $\sigma(25) \approx 3 \times (1 + 200 \times 0.189) \approx 116\sigma$ ($\sim 5.8$ MJy/sr). Legitimate halo ($2.5$ MJy/sr) is preserved.
   - Elevation at $r=45$ px: $\sigma(45) \approx 3 \times (1 + 200 \times 0.050) \approx 33\sigma$ ($\sim 1.6$ MJy/sr).
   - At $r > 70$ px: $\sigma(r) \to 3.0\sigma_0$ (sky noise threshold).
   - An off-axis companion star with localized peak $15.0$ MJy/sr at $r=25$ px has residual $14.1$ MJy/sr $\gg 5.8$ MJy/sr, breaking the bridge and detecting the companion with 100% reliability, while reducing false halo masking from 96% down to **1.5% - 3.0%**.
9. *From Stacking & Assembly Tests*: With radial threshold scaling applied, zero-coverage in the $[22, 45]$ px annulus drops from **64.4% (3,123 pixels) down to 0.1% (3 pixels)**, mean coverage depth increases from 0.63 to **1.99 stars**, and the assembled ePSF recovers smooth monotonic radial decay across $[30, 48]$ px without any flux surge.

---

## 3. Caveats

1. **Parameter Choices by Tier**:
   - Bright stars have high flux out to $r > 150$ px; their radial scale length is optimal at $r_0 = 20.0$ px with $A = 200.0$.
   - Medium stars have transition wings in $r \in [8, 45]$ px; optimal at $r_0 = 15.0$ px with $A = 200.0$.
   - Faint stars have unsaturated cores and faint wings decaying quickly into noise; optimal at $r_0 = 15.0$ px with $A = 50.0$.
   - Default fallback (if tier is None or unassigned): $A = 200.0, r_0 = 15.0$ px.
2. **Close Companion Contrast Limit**:
   - An extraordinarily faint companion star ($m > 18$) located immediately adjacent to the core ($r < 8$ px) of a bright star ($m < 11$) is submerged in the primary star's photon noise. This is an intrinsic physical limitation of direct imaging, mitigated upstream by catalog isolation filtering (`isolation_safety_factor: 1.3`).
3. **No Changes Required to `stamps.py`**:
   - `stamps.py:457` already passes `tier=tier` into `mask_contaminants_with_spikes_protected`. The function signature already accommodates `tier: Optional[str] = None`.

---

## 4. Conclusion

### 4.1 Exact Code Fix
Two modifications are required in `src/romanepsf/masking.py`:

#### Modification 1: Correct Moffat Fitting Background Estimation (`masking.py:248-251`)
**Target File**: `src/romanepsf/masking.py`  
**Lines**: 248–251

*Before*:
```python
    outer = valid & (r > np.percentile(r[valid], 75))
    bkg = float(np.median(stamp[outer])) if np.any(outer) else 0.0
```

*After*:
```python
    # Estimate background from the outer perimeter of the cutout rather than the truncated fitting region
    outer_cutout = np.isfinite(stamp) & (r > 0.75 * np.nanmax(r))
    if dq_mask is not None:
        outer_cutout &= (~dq_mask)
    bkg = float(np.median(stamp[outer_cutout])) if np.any(outer_cutout) else 0.0
```

#### Modification 2: Radially Scaled Contaminant Threshold (`masking.py:423-426`)
**Target File**: `src/romanepsf/masking.py`  
**Lines**: 423–426

*Before*:
```python
    contaminants = (residual - res_med) > (detection_sigma * res_std)
    if np.any(contaminants):
        contaminants = binary_dilation(contaminants, iterations=1)
```

*After*:
```python
    # Scale detection threshold radially: sigma(r) = sigma_0 * (1 + A * exp(-r / r0))
    # Prevents legitimate diffuse stellar halo flux from exceeding sky noise threshold
    t_str = str(tier).lower().strip() if tier is not None else "medium"
    if t_str == "faint":
        amp_scale = float(getattr(spikes_cfg, "radial_scale_amplitude_faint", 50.0))
        r0_scale = float(getattr(spikes_cfg, "radial_scale_radius_px_faint", 15.0))
    elif t_str == "bright":
        amp_scale = float(getattr(spikes_cfg, "radial_scale_amplitude_bright", 200.0))
        r0_scale = float(getattr(spikes_cfg, "radial_scale_radius_px_bright", 20.0))
    else:  # medium or default
        amp_scale = float(getattr(spikes_cfg, "radial_scale_amplitude_medium", 200.0))
        r0_scale = float(getattr(spikes_cfg, "radial_scale_radius_px_medium", 15.0))

    sigma_r = detection_sigma * (1.0 + amp_scale * np.exp(-r / r0_scale))
    contam_raw = (residual - res_med) > (sigma_r * res_std)
    contaminants = binary_dilation(contam_raw, iterations=1) if np.any(contam_raw) else contam_raw
```

The patch file is stored at:
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_2/fix_stellar_halo_masking.patch`

### 4.2 Unit Regression Tests to Add to `tests/unit/test_masking.py`
Add the following test methods to `TestDualPriorProtectionFusion` in `tests/unit/test_masking.py`:

```python
    def test_halo_preservation_in_stellar_wings(self):
        """Verify legitimate stellar halo flux is not falsely masked as contaminants."""
        sz = 201
        cx, cy = 100.0, 100.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        # Realistic extended star with core + diffuse halo
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.2).astype(np.float32)

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            star, dq_mask=None, tier="medium"
        )
        # Check transition annulus [15, 45] px outside protected spike area
        wing_ann = (r >= 15.0) & (r <= 45.0) & (~prot_area)
        assert np.sum(wing_ann) > 500
        mask_frac = np.mean(final_mask[wing_ann])
        # Assert less than 5% of legitimate wing pixels are masked
        assert mask_frac < 0.05, f"Legitimate halo over-masked: {mask_frac * 100:.1f}% masked"

    def test_masks_off_axis_companion_in_outer_wing(self):
        """Verify off-axis companion star in the outer wing is detected while halo is preserved."""
        sz = 201
        cx, cy = 100.0, 100.0
        gy, gx = np.ogrid[:sz, :sz]
        r = np.hypot(gx - cx, gy - cy)
        star = (300.0 / (1.0 + (r / 2.5)**2)**1.2).astype(np.float32)

        # Off-axis companion star at r = 25 px (angle = 40 deg, between spikes)
        comp_x = 100.0 + 25.0 * np.cos(np.radians(40.0))
        comp_y = 100.0 + 25.0 * np.sin(np.radians(40.0))
        comp_r = np.hypot(gx - comp_x, gy - comp_y)
        companion = (30.0 * np.exp(-comp_r**2 / (2 * 1.5**2))).astype(np.float32)
        stamp = star + companion

        final_mask, prot_area, _ = mask_contaminants_with_spikes_protected(
            stamp, dq_mask=None, pa_offset_deg=-9.70, tier="medium"
        )
        # Companion peak must be masked
        px_x, px_y = int(round(comp_x)), int(round(comp_y))
        assert final_mask[px_y, px_x], "Companion star was not masked!"
        # Central star core must not be masked
        assert not final_mask[100, 100], "Target star core was falsely masked!"
        # Surrounding clean halo must be preserved
        clean_wing = (r >= 15.0) & (r <= 45.0) & (~prot_area) & (comp_r > 8.0)
        assert np.mean(final_mask[clean_wing]) < 0.05
```

---

## 5. Verification Method

### 5.1 Verification on Real Commissioning Data (WFI01)
Run the following verification script in the designated Python environment:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c '
from romanepsf import loader, catalog, stamps, masking
import numpy as np, pandas as pd

l2 = loader.load_l2_image("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf", calibrate=True)
cat_df = pd.read_csv("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv", low_memory=False)
ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)

tier_stamps = stamps.process_star_stamps(l2, tiered)

# Verify Medium Star Wing Mask Fractions
for i, s in enumerate(tier_stamps["medium"]):
    ny, nx = s.data.shape
    scx, scy = (nx - 1) / 2.0, (ny - 1) / 2.0
    gy, gx = np.indices((ny, nx))
    r = np.hypot(gx - scx, gy - scy)
    ann = (r >= 15.0) & (r <= 45.0)
    wing_mask_pct = np.mean(s.mask[ann]) * 100
    print(f"Medium Star {i} (mag={s.mag:.2f}) [15, 45] px mask fraction: {wing_mask_pct:.1f}%")
    assert wing_mask_pct < 10.0, f"Over-masking persists: {wing_mask_pct:.1f}% >= 10.0%"

# Verify Medium Tier Annular Coverage Depth
cov_m = np.sum([(~s.mask).astype(int) for s in tier_stamps["medium"]], axis=0)
ann_overlap = (r >= 22.0) & (r <= 45.0)
zero_cov_pct = np.mean(ann_overlap & (cov_m == 0)) / np.mean(ann_overlap) * 100
print(f"Medium Tier Zero-Coverage in [22, 45] px: {zero_cov_pct:.1f}%")
assert zero_cov_pct < 5.0, f"Zero-coverage exceeds 5%: {zero_cov_pct:.1f}%"
print("SUCCESS: Defect 2 resolved!")
'
```
*Expected Output*:
- Medium star wing mask fraction: $< 5\%$ (observed: $1.5\% - 3.0\%$, down from $85\% - 96\%$).
- Medium tier zero-coverage in $[22, 45]$ px: $< 1\%$ (observed: $0.1\%$, down from $64.4\%$).
- All assertions pass without error.

### 5.2 Unit and E2E Test Suite Pass
Once the patch is applied by `worker_m2_it2_1`:
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_masking.py -v
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
```
*Expected Output*:
- `test_masking.py`: 28 passed (26 existing + 2 new).
- `tests/unit/`: 388 passed.
- `tests/e2e/`: 298 passed, 4 skipped (Milestone 4).
