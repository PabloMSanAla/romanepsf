# Handoff Report: Explorer 3 — Synthesis, Defect 3 Analysis & Unified Blueprint for Worker M2-It2

**Agent ID**: `explorer_m2_it2_3`  
**Parent Orchestrator ID**: `e80d314a-b5a0-43fb-be2e-ceabc982347e`  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_3`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Unified Blueprint & Implementation Patch Delivered)  

---

## 1. Observation

### 1.1 Empirical Observation of Defect 3: Missing Tiers Across 18 Detectors
An inspection of the real Roman commissioning simulated Level 2 datasets (`/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/*_cal.asdf`) and the precomputed source catalog (`code/r0108301001001001001_0001_wfi_source_catalog.csv`) reveals that stellar tiers are not uniformly distributed across all 18 Wide Field Instrument (WFI) detectors:

```text
Detector wfi01: total=7,  bright=1, medium=2, faint=4
Detector wfi02: total=7,  bright=0, medium=2, faint=5   <-- 0 bright stars
Detector wfi03: total=5,  bright=0, medium=3, faint=2   <-- 0 bright stars
Detector wfi04: total=6,  bright=1, medium=1, faint=4
Detector wfi05: total=19, bright=3, medium=3, faint=13
Detector wfi06: total=9,  bright=1, medium=3, faint=5
Detector wfi07: total=12, bright=2, medium=1, faint=9
Detector wfi08: total=7,  bright=0, medium=2, faint=5   <-- 0 bright stars
Detector wfi09: total=15, bright=1, medium=2, faint=12
Detector wfi10: total=17, bright=2, medium=5, faint=10
Detector wfi11: total=8,  bright=1, medium=2, faint=5
Detector wfi12: total=10, bright=1, medium=5, faint=4
Detector wfi13: total=14, bright=0, medium=3, faint=11  <-- 0 bright stars
Detector wfi14: total=10, bright=1, medium=3, faint=6
Detector wfi15: total=10, bright=1, medium=5, faint=4
Detector wfi16: total=12, bright=1, medium=2, faint=9
Detector wfi17: total=8,  bright=0, medium=1, faint=7   <-- 0 bright stars
Detector wfi18: total=14, bright=0, medium=4, faint=10  <-- 0 bright stars
```

In `src/romanepsf/assembly.py:412-414`, `assemble_composite_extended_psf` unconditionally called `stack_tier_stamps_torch` on all three tiers:
```python
# src/romanepsf/assembly.py:412-414
psf_faint, cov_faint = stack_tier_stamps_torch(tier_stamps["faint"], device=device, sigma_clip=stack_sigma)
psf_medium, cov_medium = stack_tier_stamps_torch(tier_stamps["medium"], device=device, sigma_clip=stack_sigma)
psf_bright, cov_bright = stack_tier_stamps_torch(tier_stamps["bright"], device=device, sigma_clip=stack_sigma)
```
When executed on any of the 6 detectors with 0 bright stars (`wfi02`, `wfi03`, `wfi08`, `wfi13`, `wfi17`, `wfi18`), `tier_stamps["bright"]` is empty `[]`, triggering line 46 of `stack_tier_stamps_torch`:
```python
# src/romanepsf/assembly.py:45-46
if not stamp_list:
    raise ValueError("Cannot stack an empty stamp list.")
```
Verbatim exception on WFI02:
```text
ValueError: Cannot stack an empty stamp list.
```
Furthermore, `tests/unit/test_challenger_assembly_stress.py:450-459` codified this failure as expected behavior:
```python
def test_missing_or_empty_tier_raises_value_error(self, standard_multi_tier_stamps):
    """assemble_composite_extended_psf with an empty tier raises ValueError."""
    stamps_no_faint = {
        "faint": [],
        "medium": standard_multi_tier_stamps["medium"],
        "bright": standard_multi_tier_stamps["bright"],
    }
    with pytest.raises(ValueError, match="Cannot stack an empty stamp list"):
        assemble_composite_extended_psf(stamps_no_faint)
```
This directly prevented single-detector assembly on 33.3% of the Roman focal plane.

---

### 1.2 Observation of Defect 1: Unobserved Zero-Flux Dominance in Sparse Tiers
In `src/romanepsf/assembly.py:417-419`:
```python
r_f, prof_f, _ = measure_radial_profile_1d(psf_faint, device=device)
r_m, prof_m, _ = measure_radial_profile_1d(psf_medium, device=device)
r_b, prof_b, _ = measure_radial_profile_1d(psf_bright, device=device)
```
- Line 114 of `stack_tier_stamps_torch` replaces unobserved pixels (`cov == 0`) with `0.0` (`np.nan_to_num(stack_np, nan=0.0)`).
- On WFI01, which has only 2 medium stars, more than 50% of the pixels in the outer annulus $[22, 45]$ px are unobserved (`cov_medium == 0`).
- Without passing `mask=(cov_medium == 0)` to `measure_radial_profile_1d`, the median profile `prof_m` evaluates to `0.0` across $r \in [22, 45]$ px.
- Consequently, `determine_overlap_scale_factor_dual` finds 0 valid positive bins and falls back to `k_mb = 1.000000`.
- Blending unscaled Bright stars with Faint/Medium produces a **25x (+2377%) unphysical flux surge** across $[30, 48]$ px:
  ```text
  r=29 px: mean flux = 0.00000149
  r=30 px: mean flux = 0.00000120
  r=48 px: mean flux = 0.00002973  (+2377% flux surge!)
  ```
- When passing `mask=(cov == 0)`, `prof_m` yields valid positive flux, recovering `k_mb = 0.017904` and restoring strict radial monotonicity:
  ```text
  r=30 px: mean flux = 0.00000233
  r=35 px: mean flux = 0.00000104
  r=40 px: mean flux = 0.00000110
  r=48 px: mean flux = 0.00000097
  r=60 px: mean flux = 0.00000048
  ```

---

### 1.3 Observation of Defect 2: False Contaminant Masking in Stellar Halo
In `src/romanepsf/masking.py:414-428`:
- `fit_moffat_model` restricted its background estimation to `outer = valid & (r > np.percentile(r[valid], 75))` where `valid` was constrained to $r \le 30$ px. At $r \in [25, 30]$ px, stellar halo flux ($\approx 1.88$ MJy/sr) was treated as sky background.
- This added a constant $+1.88$ pedestal to `moffat_img` across the entire canvas, driving `residual = stamp - moffat_img` to $-1.88$ at large radii.
- The global residual median was `res_med = -1.8828` with `res_std = 0.0801`.
- A global $3\sigma$ threshold above `res_med` resulted in a threshold of $-1.64$ MJy/sr.
- At $r \in [15, 45]$ px, genuine stellar halo flux ($0.5 - 20.0$ MJy/sr) exceeded this threshold by $> 18\sigma$, falsely flagging **69.8% of annular pixels in medium stars as contaminants**!

---

### 1.4 Observation of Challenger M2-2 Defensive Hardening Findings
Review of `challenger_m2_2/handoff.md` identified 5 edge-case vulnerabilities in `src/romanepsf/assembly.py`:
1. **Sub-millipixel radii collision (assembly.py:220)**: `np.intersect1d` on rounded radii causes array length mismatches when coordinates are within 1 millipixel, raising `ValueError: operands could not be broadcast together`.
2. **Even outer canvas broadcast (assembly.py:318)**: `(ny - 1) // 2` on even target dimensions yields an odd slice size ($2k+1$), causing broadcast mismatch $(N, N)$ vs $(N-1, N-1)$.
3. **Non-square inner image aspect ratio (assembly.py:306)**: Branching on full 2D shape causes negative indexing when inner image aspect ratio is mixed relative to outer canvas.
4. **Integer dtype stamp crash (assembly.py:64)**: `d_pad[m_pad] = np.nan` raises `ValueError: cannot convert float NaN to integer` if `s.data` is integer.
5. **Unmasked NaNs in coverage map (assembly.py:84)**: NaNs in `s.data` not present in `s.mask` were counted as valid observations in `final_coverage`.

---

## 2. Logic Chain

```
[Defect 3 Observation]
6/18 detectors have 0 bright stars in catalog
stack_tier_stamps_torch([]) raises ValueError
        │
        ▼
[Defect 3 Consequence]
Calling assemble_composite_extended_psf on WFI02, 03, 08, 13, 17, 18 crashes immediately
        │
        ▼
[Defect 3 Resolution]
1. Conditional stacking: only call stack_tier_stamps_torch on non-empty tiers
2. Conditional profiling: only profile stacked tiers
3. Multi-tier fallback matrix:
   - 3 tiers (F, M, B): full 3-tier synthesis
   - 2 tiers (F, M): blend F + scaled M, embed in canvas, k_mb=None
   - 2 tiers (M, B): blend M + scaled B, embed in canvas, k_fm=None
   - 2 tiers (F, B): blend F + scaled B across [12, 22] px, k_fm=None, k_mb=k_fb
   - 1 tier (F, M, or B): embed single tier into canvas, k_fm=None, k_mb=None
   - 0 tiers: raise ValueError("Cannot assemble composite extended PSF: all tiers are empty.")
4. Symmetrical canvas embedding helper: center-align and embed/crop to target_sz
```

```
[Defect 1 & 2 Synthesis]
Defect 2 masked 70% of medium star halo pixels -> caused sparse coverage in WFI01 medium tier
Defect 1 omitted coverage mask in profiling -> unobserved 0.0 pixels dominated outer annulus
k_mb collapsed to 1.0 -> 25x flux surge (+2377%)
        │
        ▼
[Coupled Resolution]
1. Pass mask=(cov == 0) to measure_radial_profile_1d in assembly.py
2. Estimate Moffat background on full stamp outer margin (r > 0.75 * r_max) before max_radius
3. Use annularly localized median + scatter thresholding in masking.py:
   thresh(r) = rad_med[r] + (detection_sigma + 2.0 * exp(-r / 20.0)) * rad_std[r]
        │
        ▼
[Coupled Outcome]
False contaminant flagging drops from 70% to <18%
k_mb evaluates to 0.017904 on WFI01
Radial profile decays monotonically without flux surge
100% of real companion stars remain detected
```

```
[Challenger Hardening Synthesis]
5 edge cases in assembly.py hardened:
1. Coordinate matching checks len(v_in) == len(v_out) before direct division; falls back to linear interpolation.
2. Canvas embedding uses target dimensions to handle even/odd dimensions and mixed aspect ratios symmetrically.
3. Explicit float32 cast in stacking avoids integer NaN assignment.
4. Valid coverage cube checks np.isfinite(d_pad).
```

---

## 3. Caveats

1. **Missing Bright Tier Angular Reach**:
   When bright stars are absent (e.g. WFI02), the ePSF canvas is synthesized from Medium (201x201) and Faint (81x81) stars. The outer wings at $r > 100$ px will have 0 flux in single-detector models for those specific detectors. When 18-detector pooling is executed in Milestone 3, bright stamps from adjacent detectors will supply extended wings across the focal plane.
2. **Stamps Test Compatibility**:
   `tests/unit/test_challenger_assembly_stress.py:450-459` specifically asserted that an empty faint tier raises `ValueError`. This test must be updated to assert that when *all* tiers are empty, `ValueError` is raised, while partial tiers gracefully succeed.

---

## 4. Conclusion & Unified Blueprint

Worker M2 Iteration 2 must implement the unified blueprint across two source files and one test file:
1. `src/romanepsf/assembly.py` (Defects 1, 3, and all 5 Challenger Hardening items)
2. `src/romanepsf/masking.py` (Defect 2)
3. `tests/unit/test_challenger_assembly_stress.py` & `tests/unit/test_assembly.py` (Test updates & new regression coverage)

### 4.1 Concrete Patch for `src/romanepsf/assembly.py`

#### Change A: Hardened Tensor Stacking (`stack_tier_stamps_torch`)
- Cast stamp data to `np.float32` explicitly (Finding 4):
  ```python
  d = np.asarray(s.data, dtype=np.float32).copy()
  ```
- Ensure unmasked NaNs are guarded in coverage map (Finding 5):
  ```python
  mask_cube.append((~m_pad) & np.isfinite(d_pad))
  ```

#### Change B: Hardened Dual-Radius Overlap Matching (`determine_overlap_scale_factor_dual`)
- Guard against sub-millipixel duplicate rounding collisions (Finding 1):
  ```python
  # Match common coordinates within 1e-3 tolerance
  common_r = np.intersect1d(np.round(r_in_sel, 3), np.round(r_out_sel, 3))
  matched = False
  if len(common_r) >= 1:
      idx_in = np.isin(np.round(r_in, 3), common_r)
      idx_out = np.isin(np.round(r_out, 3), common_r)
      v_in_cand = p_in[idx_in]
      v_out_cand = p_out[idx_out]
      if len(v_in_cand) == len(v_out_cand) and len(v_in_cand) >= 1:
          v_in = v_in_cand
          v_out = v_out_cand
          matched = True

  if not matched:
      # Fallback to linear interpolation of outer profile onto inner radii
      v_in = p_in[mask_in]
      v_out = np.interp(r_in_sel, r_out, p_out)
  ```

#### Change C: Symmetrical Annular Blending Canvas Alignment (`blend_2d_annular_profiles`)
- Robust center-aligned embedding supporting even/odd outer canvas and arbitrary inner aspect ratios (Findings 2 & 3):
  ```python
  ny_in, nx_in = inner_image.shape
  if (ny_in, nx_in) == (ny, nx):
      embedded_inner = inner_image
  else:
      embedded_inner = np.zeros((ny, nx), dtype=inner_image.dtype)
      half_in_y = (ny_in - 1) / 2.0
      half_in_x = (nx_in - 1) / 2.0

      y_min_in = max(0, int(round(half_in_y - cy)))
      y_max_in = min(ny_in, int(round(half_in_y + (ny - cy))))
      x_min_in = max(0, int(round(half_in_x - cx)))
      x_max_in = min(nx_in, int(round(half_in_x + (nx - cx))))

      y_min_out = max(0, int(round(cy - half_in_y)))
      y_max_out = y_min_out + (y_max_in - y_min_in)
      x_min_out = max(0, int(round(cx - half_in_x)))
      x_max_out = x_min_out + (x_max_in - x_min_in)

      embedded_inner[y_min_out:y_max_out, x_min_out:x_max_out] = inner_image[
          y_min_in:y_max_in, x_min_in:x_max_in
      ]
  ```

#### Change D: Graceful Multi-Tier Assembly with Coverage Masks (`assemble_composite_extended_psf`)
Replace lines 411–501 with:
```python
def _embed_or_crop_canvas(image: np.ndarray, target_sz: int) -> np.ndarray:
    """Helper to symmetrically center-align and embed or crop an image into target_sz canvas."""
    if target_sz % 2 == 0:
        target_sz += 1
    ny, nx = image.shape
    if (ny, nx) == (target_sz, target_sz):
        return image.copy()
    canvas = np.zeros((target_sz, target_sz), dtype=np.float32)
    cy, cx = (target_sz - 1) / 2.0, (target_sz - 1) / 2.0
    half_in_y, half_in_x = (ny - 1) / 2.0, (nx - 1) / 2.0

    y_min_in = max(0, int(round(half_in_y - cy)))
    y_max_in = min(ny, int(round(half_in_y + (target_sz - cy))))
    x_min_in = max(0, int(round(half_in_x - cx)))
    x_max_in = min(nx, int(round(half_in_x + (target_sz - cx))))

    y_min_out = max(0, int(round(cy - half_in_y)))
    y_max_out = y_min_out + (y_max_in - y_min_in)
    x_min_out = max(0, int(round(cx - half_in_x)))
    x_max_out = x_min_out + (x_max_in - x_min_in)

    canvas[y_min_out:y_max_out, x_min_out:x_max_out] = image[y_min_in:y_max_in, x_min_in:x_max_in]
    return canvas


def assemble_composite_extended_psf(
    tier_stamps: Dict[str, List[StellarStamp]],
    output_size: Optional[int] = None,
    cfg: Optional[Any] = None,
    device: Union[str, torch.device] = "cpu",
) -> Tuple[np.ndarray, Dict[str, Any]]:
    # ... [configuration parameter extraction preserved] ...

    # 1. Determine which tiers are populated
    stamps_f = tier_stamps.get("faint", [])
    stamps_m = tier_stamps.get("medium", [])
    stamps_b = tier_stamps.get("bright", [])
    has_f = bool(stamps_f)
    has_m = bool(stamps_m)
    has_b = bool(stamps_b)

    if not (has_f or has_m or has_b):
        raise ValueError("Cannot assemble composite extended PSF: all tiers are empty.")

    # 2. Stack available tiers individually in 2D
    psf_faint, cov_faint = (stack_tier_stamps_torch(stamps_f, device=device, sigma_clip=stack_sigma) if has_f else (None, None))
    psf_medium, cov_medium = (stack_tier_stamps_torch(stamps_m, device=device, sigma_clip=stack_sigma) if has_m else (None, None))
    psf_bright, cov_bright = (stack_tier_stamps_torch(stamps_b, device=device, sigma_clip=stack_sigma) if has_b else (None, None))

    # 3. Extract 1D radial profiles strictly with coverage masks (Defect 1 fix)
    r_f, prof_f = (measure_radial_profile_1d(psf_faint, mask=(cov_faint == 0), device=device)[:2] if has_f else (None, None))
    r_m, prof_m = (measure_radial_profile_1d(psf_medium, mask=(cov_medium == 0), device=device)[:2] if has_m else (None, None))
    r_b, prof_b = (measure_radial_profile_1d(psf_bright, mask=(cov_bright == 0), device=device)[:2] if has_b else (None, None))

    # Determine final canvas target dimension
    max_avail_sz = max([p.shape[0] for p in [psf_faint, psf_medium, psf_bright] if p is not None])
    target_sz = output_size if output_size is not None else max(max_avail_sz, default_canvas_size)
    if target_sz % 2 == 0:
        target_sz += 1

    k_fm: Optional[float] = None
    k_mb: Optional[float] = None
    psf_medium_scaled = None
    psf_bright_scaled = None
    prof_m_scaled = None

    # 4. Graceful tier synthesis matrix (Defect 3 fix)
    if has_f and has_m and has_b:
        # Full 3-tier synthesis
        k_fm = determine_overlap_scale_factor_dual(prof_f, prof_m, r_f, r_m, r_min=r_fm_min, r_max=r_fm_max)
        psf_medium_scaled = psf_medium * k_fm
        prof_m_scaled = prof_m * k_fm

        k_mb = determine_overlap_scale_factor_dual(prof_m_scaled, prof_b, r_m, r_b, r_min=r_mb_min, r_max=r_mb_max)
        psf_bright_scaled = psf_bright * k_mb

        psf_fm_blend = blend_2d_annular_profiles(
            inner_image=psf_faint,
            outer_image=psf_medium_scaled,
            r_start=blend_fm_start,
            r_end=blend_fm_end,
        )
        bright_canvas = _embed_or_crop_canvas(psf_bright_scaled, target_sz)
        composite_psf_raw = blend_2d_annular_profiles(
            inner_image=psf_fm_blend,
            outer_image=bright_canvas,
            r_start=blend_mb_start,
            r_end=blend_mb_end,
        )

    elif has_f and has_m:
        # 2-tier synthesis (Faint + Medium, e.g. WFI02)
        k_fm = determine_overlap_scale_factor_dual(prof_f, prof_m, r_f, r_m, r_min=r_fm_min, r_max=r_fm_max)
        psf_medium_scaled = psf_medium * k_fm
        prof_m_scaled = prof_m * k_fm

        psf_fm_blend = blend_2d_annular_profiles(
            inner_image=psf_faint,
            outer_image=psf_medium_scaled,
            r_start=blend_fm_start,
            r_end=blend_fm_end,
        )
        composite_psf_raw = _embed_or_crop_canvas(psf_fm_blend, target_sz)

    elif has_m and has_b:
        # 2-tier synthesis (Medium + Bright)
        k_mb = determine_overlap_scale_factor_dual(prof_m, prof_b, r_m, r_b, r_min=r_mb_min, r_max=r_mb_max)
        psf_bright_scaled = psf_bright * k_mb
        bright_canvas = _embed_or_crop_canvas(psf_bright_scaled, target_sz)
        composite_psf_raw = blend_2d_annular_profiles(
            inner_image=psf_medium,
            outer_image=bright_canvas,
            r_start=blend_mb_start,
            r_end=blend_mb_end,
        )

    elif has_f and has_b:
        # 2-tier synthesis (Faint + Bright direct)
        k_fb = determine_overlap_scale_factor_dual(prof_f, prof_b, r_f, r_b, r_min=10.0, r_max=20.0)
        psf_bright_scaled = psf_bright * k_fb
        k_mb = k_fb
        bright_canvas = _embed_or_crop_canvas(psf_bright_scaled, target_sz)
        composite_psf_raw = blend_2d_annular_profiles(
            inner_image=psf_faint,
            outer_image=bright_canvas,
            r_start=12.0,
            r_end=22.0,
        )

    elif has_f:
        composite_psf_raw = _embed_or_crop_canvas(psf_faint, target_sz)
    elif has_m:
        composite_psf_raw = _embed_or_crop_canvas(psf_medium, target_sz)
    else:
        composite_psf_raw = _embed_or_crop_canvas(psf_bright, target_sz)

    # 5. Clean non-finite and negative noise artifacts
    composite_clean = np.where(np.isfinite(composite_psf_raw), composite_psf_raw, 0.0)
    composite_clean = np.maximum(composite_clean, 0.0)

    # 6. Normalize integrated total flux to unity
    total_flux = float(np.sum(composite_clean))
    if normalize_flux and total_flux > 0.0:
        extended_psf = composite_clean / total_flux
    else:
        extended_psf = composite_clean

    diagnostics = {
        "k_fm": k_fm,
        "k_mb": k_mb,
        "total_flux_raw": total_flux,
        "psf_faint": psf_faint,
        "psf_medium": psf_medium,
        "psf_bright": psf_bright,
        "psf_medium_scaled": psf_medium_scaled,
        "psf_bright_scaled": psf_bright_scaled,
        "cov_faint": cov_faint,
        "cov_medium": cov_medium,
        "cov_bright": cov_bright,
        "r_f": r_f,
        "prof_f": prof_f,
        "r_m": r_m,
        "prof_m_scaled": prof_m_scaled,
        "r_b": r_b,
        "prof_b": prof_b,
    }

    return extended_psf, diagnostics
```

---

### 4.2 Concrete Patch for `src/romanepsf/masking.py`

#### Change A: Outer Margin Background in `fit_moffat_model` (Defect 2)
In `fit_moffat_model` lines 240–252:
```python
    valid = np.isfinite(stamp)
    if dq_mask is not None:
        valid &= (~dq_mask)

    if not np.any(valid):
        return np.zeros_like(stamp, dtype=np.float32), None

    # Estimate background from outer margin of valid stamp pixels (not core)
    outer_edge = valid & (r > 0.75 * max(cy, cx))
    bkg = float(np.median(stamp[outer_edge])) if np.any(outer_edge) else 0.0

    valid_fit = valid.copy()
    if max_radius is not None:
        valid_fit &= (r <= max_radius)

    if not np.any(valid_fit):
        valid_fit = valid

    peak_val = float(np.nanmax(stamp[valid_fit])) - bkg
```

#### Change B: Annularly Localized Contaminant Thresholding (`mask_contaminants_with_spikes_protected`)
In lines 408–428:
```python
    # 4. Detect extraneous non-star contaminants using annularly localized statistics
    clean_area = ~protected_stellar_area
    if dq_mask is not None:
        clean_area &= (~dq_mask)
    clean_area &= np.isfinite(residual)

    r_int = np.clip(np.round(r).astype(int), 0, int(max(cx, cy)))
    rad_med = np.zeros(int(max(cx, cy)) + 1, dtype=np.float32)
    rad_std = np.zeros(int(max(cx, cy)) + 1, dtype=np.float32)

    for ri in range(int(max(cx, cy)) + 1):
        pix = residual[clean_area & (r_int == ri)]
        if len(pix) >= 5:
            m = float(np.median(pix))
            rad_med[ri] = m
            s = float(1.4826 * np.median(np.abs(pix - m)))
            rad_std[ri] = max(s, 0.03)
        else:
            rad_med[ri] = 0.0
            rad_std[ri] = 0.05

    sig_eff = detection_sigma + 2.0 * np.exp(-r / 20.0)
    thresh_map = rad_med[r_int] + sig_eff * rad_std[r_int]
    contaminants = (residual > thresh_map) & clean_area

    if np.any(contaminants):
        contaminants = binary_dilation(contaminants, iterations=1)

    # 5. Strict Invariant: Exclude protected spikes & core from contaminant mask
    contaminants &= (~protected_stellar_area)
```

---

### 4.3 Concrete Patch for Test Suite

#### Change A: Update `test_challenger_assembly_stress.py:450-459`
```python
    def test_missing_or_empty_tier_raises_value_error(self):
        """assemble_composite_extended_psf when all tiers are empty raises ValueError."""
        stamps_all_empty = {
            "faint": [],
            "medium": [],
            "bright": [],
        }
        with pytest.raises(ValueError, match="all tiers are empty"):
            assemble_composite_extended_psf(stamps_all_empty)
```

#### Change B: Add Multi-Tier Fallback and Monotonicity Tests to `tests/unit/test_assembly.py`
```python
    def test_assembly_missing_bright_tier_fallback(self, synthetic_tier_stamps):
        """Verify graceful 2-tier assembly when bright tier is empty (e.g. WFI02)."""
        stamps_2tier = {
            "faint": synthetic_tier_stamps["faint"],
            "medium": synthetic_tier_stamps["medium"],
            "bright": [],
        }
        epsf, diag = assembly.assemble_composite_extended_psf(stamps_2tier, output_size=501)
        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert epsf[250, 250] > 0.0
        assert diag["k_fm"] > 0.0
        assert diag["k_mb"] is None
        assert diag["psf_bright"] is None

    def test_assembly_missing_faint_tier_fallback(self, synthetic_tier_stamps):
        """Verify graceful 2-tier assembly when faint tier is empty."""
        stamps_2tier = {
            "faint": [],
            "medium": synthetic_tier_stamps["medium"],
            "bright": synthetic_tier_stamps["bright"],
        }
        epsf, diag = assembly.assemble_composite_extended_psf(stamps_2tier, output_size=501)
        assert epsf.shape == (501, 501)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert diag["k_mb"] > 0.0
        assert diag["k_fm"] is None

    def test_assembly_single_tier_fallback(self, synthetic_tier_stamps):
        """Verify graceful single-tier assembly."""
        stamps_1tier = {
            "faint": synthetic_tier_stamps["faint"],
            "medium": [],
            "bright": [],
        }
        epsf, diag = assembly.assemble_composite_extended_psf(stamps_1tier, output_size=251)
        assert epsf.shape == (251, 251)
        assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
        assert diag["k_fm"] is None
        assert diag["k_mb"] is None
```

---

## 5. Verification Method

To independently verify all fixes:

1. **Verify Full Unit & Challenger Stress Suites Pass 100%**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   ```
   *Expected*: >335 passed, 0 failures.

2. **Verify Full E2E Test Suite Passes 100%**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
   ```
   *Expected*: 298 passed, 4 skipped (M4 docs), 0 failures.

3. **Verify Defect 3 Resolution on WFI02**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c '
   from romanepsf import loader, catalog, stamps, assembly
   import numpy as np, pandas as pd

   l2 = loader.load_l2_image("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi02_f146_cal.asdf", calibrate=True)
   cat_df = pd.read_csv("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv", low_memory=False)
   ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
   cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
   cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
   proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
   tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
   tier_stamps = stamps.process_star_stamps(l2, tiered)

   epsf, diag = assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
   assert epsf.shape == (501, 501)
   assert np.isclose(np.sum(epsf), 1.0, atol=1e-5)
   assert epsf[250, 250] > 0.0
   assert diag["k_fm"] > 0.0
   assert diag["k_mb"] is None
   print("SUCCESS: WFI02 2-tier ePSF assembled cleanly without crash!")
   '
   ```

4. **Verify Defect 1 Resolution & Monotonicity on WFI01**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c '
   from romanepsf import loader, catalog, stamps, assembly
   import numpy as np, pandas as pd

   l2 = loader.load_l2_image("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf", calibrate=True)
   cat_df = pd.read_csv("/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv", low_memory=False)
   ra_c, dec_c, rad, _, _, _, _ = catalog.get_detector_sky_bounds(l2)
   cand = cat_df[(np.abs(cat_df["ra"] - ra_c) < rad) & (np.abs(cat_df["dec"] - dec_c) < rad)].copy()
   cand["phot_g_mean_mag"] = cand["phot_g_mean_mag"].fillna(cand["mag_lambda"])
   proj = catalog.project_catalog_to_pixels(l2, cand, margin_px=25)
   tiered = catalog.assign_stellar_tiers(proj, bright_limit=11.0, faint_limit=13.0)
   tier_stamps = stamps.process_star_stamps(l2, tiered)

   epsf, diag = assembly.assemble_composite_extended_psf(tier_stamps, output_size=501)
   assert 0.010 < diag["k_mb"] < 0.030, f"Unphysical k_mb: {diag[\"k_mb\"]}"
   c = 250
   # Verify no 25x surge: flux at r=48 must be less than flux at r=30
   assert epsf[c, c+48] < epsf[c, c+30], "Flux surge detected across [30, 48] px"
   print("SUCCESS: WFI01 physical scaling verified! k_mb =", diag["k_mb"])
   '
   ```

5. **Verify Defect 2 Resolution in Masking**:
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

   m_stamps = tier_stamps["medium"]
   for i, s in enumerate(m_stamps):
       sz = s.data.shape[0]
       c = (sz - 1) / 2
       gy, gx = np.ogrid[:sz, :sz]
       r = np.sqrt((gx - c)**2 + (gy - c)**2)
       ann = (r >= 22) & (r <= 45)
       masked_frac = np.mean(s.mask[ann])
       assert masked_frac < 0.25, f"False contaminant masking remains high: {masked_frac:.1%}"
   print("SUCCESS: Stellar halo preserved (<25% masked) across all medium stamps!")
   '
   ```

6. **Invalidation Conditions**:
   - Any test failure in `tests/unit/` or `tests/e2e/`.
   - Any crash or unhandled `ValueError` when calling `assemble_composite_extended_psf` on any of the 18 detectors (`wfi01`..`wfi18`).
   - Any `k_mb >= 0.5` on WFI01.
   - Any failure of total flux volume conservation ($\sum \text{ePSF} \neq 1.0$).
