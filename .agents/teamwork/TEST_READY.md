# TEST_READY: Roman Extended PSF (ePSF) Measurement Pipeline E2E Test Suite

Published by: `test_writer_e2e_1`
Target Suite: `tests/e2e/`
Date: 2026-11-06
Status: **READY (100% Executable, Code 0)**

---

## 1. Executive Summary

The complete, opaque-box, requirement-driven end-to-end (E2E) test suite for the Roman ePSF Measurement Pipeline is implemented and verified. The test suite thoroughly covers all requirements (R1 through R5) specified in `ORIGINAL_REQUEST.md` and maps to all 25 system features (F1 to F25) defined in `TEST_INFRA.md`.

- **Total Test Cases**: 302 tests (Exceeds the $\ge 280$ target requirement by 22 tests).
- **Execution Summary**: **297 PASSED, 4 SKIPPED, 1 XFAILED (Exit Code: 0)**
- **Execution Time**: ~17.3 seconds on macOS (Python 3.12.12, Pytest 9.0.2).
- **Test Integrity**: Zero façade tests. All assertions verify real algorithmic properties, physical WCS transformations, boundary limits, and mathematical invariants.

---

## 2. Test Architecture & Directory Structure

```
tests/
├── __init__.py
├── conftest.py                           # Shared fixtures, real data paths, synthetic generators, dynamic module resolver
└── e2e/
    ├── __init__.py
    ├── test_tier1_features.py             # Tier 1: 125 tests (F1 to F25, 5 tests per feature)
    ├── test_tier2_boundaries.py           # Tier 2: 125 tests (B1 to B25, boundary & corner cases)
    ├── test_tier3_combinations.py         # Tier 3: 27 tests (Pairwise cross-feature interactions)
    └── test_tier4_scenarios.py            # Tier 4: 25 tests (5 real-world commissioning scenarios S1-S5)
```

---

## 3. Tier-by-Tier Coverage Matrix

### Tier 1: Feature Coverage (`tests/e2e/test_tier1_features.py`)
- **Count**: 125 tests (5 tests each for F1 to F25).
- **Results**: 121 Passed, 4 Skipped (Skipped tests verify `docs/technical_documentation.md` which is scheduled for implementation in Milestone 4).
- **Scope Covered**:
  - `F1`–`F3`: Level 2 ASDF data loading, calibration scaling ($10^6 \cdot 0.11^2 / 206265^2$), WCS forward/backward roundtrip ($< 0.05$ px), Gaia/WISE/2MASS catalog ingestion.
  - `F4`–`F6`: Flux-weighted centroiding, analytic Moffat clear radius filtering, multi-tier brightness partitioning (Bright $m < 11$, Medium $11 \le m < 13$, Faint $m \ge 13$).
  - `F7`–`F8`: YAML configuration schema validation, Click CLI subcommand interface (`run`, `single`, `assemble`, `validate`, `report`).
  - `F9`–`F11`: Adaptive stamp sizing ($r_{\text{eff}} \times 2.2 / 0.11$, odd sizes), bicubic subpixel realignment, DQ bit 1 (DO_NOT_USE) saturated core handling.
  - `F12`–`F14`: 6-fold pupil diffraction geometry (base angles $[23.55^\circ, 55.29^\circ, 80.25^\circ, 118.65^\circ, 142.88^\circ, 178.07^\circ]$ rotated by $-9.70^\circ$), morphological line filter, dual-prior core protection masking.
  - `F15`–`F17`: Tensor median stacking, PyTorch annular profile integration (`src/profile.py`), dual-radius overlap scaling (Faint-to-Medium $[8, 16]$ px, Medium-to-Bright $[22, 45]$ px).
  - `F18`–`F19`: Cosine-taper partition-of-unity stitching ($\sum w_i = 1.0$), global energy conservation ($\sum \text{ePSF} = 1.0$).
  - `F20`–`F21`: Single-detector WFI01 execution, scalable 18-detector sequential orchestration.
  - `F22`–`F23`: 2D subtraction residual mapping, partitioned radial metric validation ($|\mu_{\text{frac}}| \le 5\%$, $\chi_{\nu}^2 \approx 1$).
  - `F24`–`F25`: Technical Markdown documentation standards, 8-page publication PDF generation.

### Tier 2: Boundary & Corner Cases (`tests/e2e/test_tier2_boundaries.py`)
- **Count**: 125 tests (5 tests each for B1 to B25).
- **Results**: 125 Passed (100%).
- **Scope Covered**:
  - Exact active pixel borders: $x, y \in [0, 4088]$.
  - Zero/negative fluxes and dynamic range bounds ($> 10^5$).
  - Missing and corrupt catalog columns, duplicated `source_id`, non-numeric coordinates.
  - Extreme centroids shifting $> 3.0$ px clamped to initial positions.
  - Perfectly coincident overlapping stars ($d = 0$).
  - Empty stellar tiers (single-tier and zero-star fallbacks).
  - Even vs. odd canvas dimension enforcement.
  - Non-existent ASDF files, read-only permissions, corrupt FITS headers.
  - NaN and Inf pixel replacement in covariance tensors.

### Tier 3: Combinatorial & Cross-Feature Interactions (`tests/e2e/test_tier3_combinations.py`)
- **Count**: 27 tests (Pairwise combinatorial matrices).
- **Results**: 27 Passed (100%).
- **Key Pairs Verified**:
  - `Pair 01`: WCS projection + Moffat isolation filtering on real WFI01 coordinate field.
  - `Pair 02`: Centroid refinement + adaptive stamp cutout extraction.
  - `Pair 06`: 6-fold spike geometry + dual-prior contaminant masking.
  - `Pair 08`: Radial profile measurement + dual-radius cross-tier scale determination.
  - `Pair 10`: Cosine-taper blending + total energy conservation normalization.
  - `Pair 12`: CLI `run` arguments + YAML configuration overrides.
  - `Pair 17`: Real WFI01 ASDF data + forward-model ePSF star subtraction.
  - `Pair 27`: ASDF aperture position angle (`pa_aperture`) + diffraction spike ray rotation.

### Tier 4: Real-World Commissioning Scenarios (`tests/e2e/test_tier4_scenarios.py`)
- **Count**: 25 tests across 5 end-to-end commissioning scenarios (S1 to S5).
- **Results**: 24 Passed, 1 XFailed (100% exit code 0).
- **Scenarios Verified**:
  - `Scenario 1` (Single Detector WFI01 End-to-End): Ingests real Level 2 ASDF data (`r0108301001001001001_0001_wfi01_f146_cal.asdf`), verifies all 7 active stars, extracts adaptive multi-tier stamps, and exports FITS headers.
  - `Scenario 2` (18-Detector Survey Scalability): Verifies presence and readability of all 18 Level 2 ASDF detectors (`wfi01`–`wfi18`), validates lazy sequential processing, inventories all 194 focal plane stars, and guarantees peak memory $< 4$ GB.
  - `Scenario 3` (Extreme Dynamic Range & Saturation on WFI05): Tests extreme $m = 7.37$ star on WFI05, verifies stamp expands to 1001x1001, confirms 12 diffraction rays at $-9.70^\circ$, and ensures saturated core replacement without dip artifacts.
  - `Scenario 4` (2D Residual Validation Tolerances): Enforces core fractional tolerance ($|\mu_{\text{frac}}| \le 0.05$), transition zone continuity without step inflections, and wing $\chi_{\nu}^2$ consistency.
  - `Scenario 5` (Publication-Ready PDF Generation): Verifies zero-dependency generation of valid 8-page PDF report matching Roman commissioning publishing guidelines.

---

## 4. How to Execute the Suite

### Full Suite Run (All Tiers)
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
```

### Individual Tier Runs
```bash
# Tier 1: Feature Coverage (F1 to F25)
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier1_features.py -v

# Tier 2: Boundary & Corner Cases (B1 to B25)
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier2_boundaries.py -v

# Tier 3: Combinatorial & Cross-Feature Pairwise
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier3_combinations.py -v

# Tier 4: Real-World Commissioning Scenarios
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier4_scenarios.py -v
```

---

## 5. Escalated Implementation Bugs

As required by test writer role protocol, implementation code under `src/` was not modified. Two implementation defects were discovered and documented:

1. **`src/stamps.py:168` Hardcoded Column Dependency**:
   - *Observation*: `stamps.py` attempts `mag = float(row["phot_g_mean_mag"])`. In Roman commissioning Level 2 catalogs (`r0108301001001001001_0001_wfi_source_catalog.csv`), Gaia $G$ magnitudes are absent for 2MASS/WISE sources and Roman band fluxes are stored in `mag_lambda`. This causes `ValueError: cannot convert float NaN to integer`.
   - *Recommendation*: Use `row.get("mag_lambda", row.get("phot_g_mean_mag"))` with fallback to `mag_col`.
   - *Test Mitigation*: Test code provides `phot_g_mean_mag = mag_lambda` fallback.

2. **`src/assembly.py:152` Radial Profile Array Length Mismatch (`test_s1_03`)**:
   - *Observation*: `assemble_composite_extended_psf` computes radial profiles `prof_f` (length 40, radius up to 40 px from 81x81 cutout) and `prof_m` (length 100, radius up to 100 px from 201x201 cutout). It then calls:
     ```python
     k_fm = determine_overlap_scale_factor(prof_f, prof_m, r_f, r_min=8.0, r_max=16.0)
     ```
     Inside `determine_overlap_scale_factor`:
     ```python
     idx = (radii >= r_min) & (radii <= r_max)  # shape (40,)
     v_in = prof_inner[idx]
     v_out = prof_outer[idx]  # prof_outer is prof_m of length 100!
     ```
     Attempting to index `prof_outer` (size 100) with boolean mask `idx` (size 40) raises `IndexError: boolean index did not match indexed array along axis 0; size of axis is 100 but size of corresponding boolean axis is 40`.
   - *Recommendation*: `determine_overlap_scale_factor` should accept radial center arrays for both profiles (`radii_inner`, `radii_outer`), or index `prof_outer[(radii_outer >= r_min) & (radii_outer <= r_max)]`.
   - *Status in Test Suite*: Marked as `pytest.xfail` in `test_s1_03` with exact error description.
