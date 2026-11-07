# Independent Review & Adversarial Critic Report — Reviewer M1-1

**Agent**: Reviewer M1-1 (Milestone 1 Independent Reviewer & Adversarial Critic)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m1_1/`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Recipient**: Sub-Orchestrator M1 (`e80d314a-b5a0-43fb-be2e-ceabc982347e`)  

---

## Review Summary

**Verdict**: **APPROVE**  
**Integrity Status**: **CLEAN (Zero Integrity Violations Found)**  
**Overall Risk Assessment**: **LOW**  

---

## 1. Observation

### 1.1 Direct Source Code & Architectural Review
A line-by-line inspection was conducted across all files implemented for Milestone 1:

1. **`pyproject.toml`**:
   - Modern PEP 517/621 setuptools configuration declaring package layout `[tool.setuptools.packages.find] where = ["src"]` (lines 51-53).
   - CLI script entry point correctly mapped: `romanepsf = "romanepsf.cli:cli"` (line 46).
   - Core runtime dependencies specified: `numpy>=1.24.0`, `scipy>=1.10.0`, `astropy>=5.3.0`, `photutils>=1.8.0`, `roman_datamodels>=0.19.0`, `asdf>=2.15.0`, `pandas>=2.0.0`, `pyyaml>=6.0`, `click>=8.0.0`, `matplotlib>=3.7.0`, `torch>=2.0.0`, `gwcs>=0.19.0` (lines 24-37).

2. **`configs/default.yaml`**:
   - 101 lines encompassing 11 structured sections: `pipeline`, `environment`, `data`, `catalog`, `tiers`, `stamps`, `spikes`, `profile`, `assembly`, `validation`, `reporting`.
   - Data locations point directly to real commissioning storage:
     - `detectors_dir`: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors` (line 18)
     - `catalog_path`: `.../PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv` (line 19)

3. **`src/romanepsf/config.py`**:
   - Strongly typed dataclass schema matching all configuration sections.
   - Robust configuration loader `load_config(config_path, overrides, validate=True)` (lines 376-425) supporting dot-notation overrides (e.g. `assembly.canvas_size`).
   - Strict validation logic in `PipelineConfig.validate()` (lines 273-304):
     - `bright_limit < faint_limit`
     - `canvas_size % 2 == 1` and `canvas_size > 0`
     - Overlap interval consistency (`r_min < r_max`, `blend_start < blend_end`)
     - Positive astrometric tolerance (`roundtrip_tolerance_arcsec > 0`)
   - Hardware device resolution (`resolve_device`) supporting `auto` (MPS -> CUDA -> CPU), `mps`, `cuda`, and `cpu` with graceful fallbacks (lines 18-61).

4. **`src/romanepsf/loader.py`**:
   - `load_l2_image(asdf_path, calibrate=True, validate_shape=True) -> RomanL2Data` (lines 162-299).
   - Employs official `roman_datamodels.open` to extract data arrays and optical metadata.
   - Enforces active science dimensions `(4088, 4088)` against `ACTIVE_SHAPE = (4088, 4088)` (line 19).
   - Multiplies flux and errors by `conversion_megajanskys` to MJy/sr when `calibrate=True`, while retaining raw count rates in `raw_data`.
   - Derives physical AB zero point from pixel area and conversion factor: $m_{\text{AB}} = -2.5 \log_{10}(\text{flux}_{1\,\text{DN/s}} / 3631.0)$ (lines 244-246).
   - Implements full Roman DQ bitmask decoding with 14 flags (`DO_NOT_USE`, `SATURATED`, `DROPOUT`, etc.) and `get_effective_mask` combining DQ with non-finite values (lines 116-143).

5. **`src/romanepsf/catalog.py`**:
   - `sanitize_source_catalog` (lines 51-125): deduplicates columns, resolves `phot_g_mean_mag_AB` collision without mutating or creating 2D DataFrame slices, validates coordinates $[0, 360]$ and $[-90, 90]$, and drops solar system bodies ($m < 0$).
   - `project_catalog_to_pixels` (lines 257-362): vectorizes `wcs.backward_transform`, applies boundary margin exclusion (default $50$ px), and executes mandatory forward roundtrip verification $\Delta\theta < 0.5''$ using `wcs(x, y)`.
   - `refine_stellar_centroids` (lines 364-464): calculates background-subtracted 2D first moments, sets NaN/saturated pixel weights to 0, and limits shift divergence to `max_shift_px = 3.0` px before falling back to catalog coordinates.
   - `get_psf_extension_moffat` (lines 21-49): exact analytical inversion of Moffat radial profile down to $28\ \text{mag}/\text{arcsec}^2$.
   - `filter_isolated_stars` (lines 466-556): sorts stars ascending in magnitude (brightest first) and enforces pairwise Moffat clearance with safety factor 1.3, preserving the brighter star and rejecting blended companions.
   - `assign_stellar_tiers` (lines 558-614): partitions stars into `'bright'` ($< 11.0$), `'medium'` ($[11.0, 13.0)$), and `'faint'` ($\ge 13.0$).

6. **`src/romanepsf/cli.py`**:
   - Click group exposing all 7 required subcommands: `run`, `single`, `catalog`, `stamps`, `assemble`, `validate`, `report` (lines 117-549).
   - Global options supported: `--config`, `--device`, `--log-level`, `--verbose`, `--version`.
   - The `catalog` subcommand executes end-to-end on real commissioning files.

7. **Backward-Compatibility Modules**:
   - `src/loader.py` and `src/catalog.py` cleanly re-export symbols from `romanepsf.loader` and `romanepsf.catalog`, ensuring compatibility with both package structures.

---

### 1.2 Tool Commands and Execution Results

1. **Unit Test Suite Execution**:
   - Command:
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
   - Output:
     ```
     ============================= test session starts ==============================
     platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python
     cachedir: .pytest_cache
     rootdir: /Users/pmsanch1/code/romanepsf
     configfile: pyproject.toml
     plugins: anyio-4.12.1, zarr-3.1.5
     collected 41 items

     tests/unit/test_catalog.py::test_sanitize_catalog_duplicate_columns PASSED [  2%]
     tests/unit/test_catalog.py::test_sanitize_catalog_filters_solar_system_bodies PASSED [  4%]
     tests/unit/test_catalog.py::test_forward_roundtrip_wcs_in_footprint PASSED [  7%]
     tests/unit/test_catalog.py::test_forward_roundtrip_wcs_out_of_footprint_rejection PASSED [  9%]
     tests/unit/test_catalog.py::test_edge_margin_filtering PASSED            [ 12%]
     tests/unit/test_catalog.py::test_refine_stellar_centroids_synthetic_peak PASSED [ 14%]
     tests/unit/test_catalog.py::test_refine_stellar_centroids_zero_flux_fallback PASSED [ 17%]
     tests/unit/test_catalog.py::test_filter_isolated_stars_pair_rejection PASSED [ 19%]
     tests/unit/test_catalog.py::test_filter_isolated_stars_isolated_pair PASSED [ 21%]
     tests/unit/test_catalog.py::test_assign_stellar_tiers PASSED             [ 24%]
     tests/unit/test_cli.py::test_cli_help PASSED                             [ 26%]
     tests/unit/test_cli.py::test_subcommand_help[run] PASSED                 [ 29%]
     tests/unit/test_cli.py::test_subcommand_help[single] PASSED              [ 31%]
     tests/unit/test_cli.py::test_subcommand_help[catalog] PASSED             [ 34%]
     tests/unit/test_cli.py::test_subcommand_help[stamps] PASSED              [ 36%]
     tests/unit/test_cli.py::test_subcommand_help[assemble] PASSED            [ 39%]
     tests/unit/test_cli.py::test_subcommand_help[validate] PASSED            [ 41%]
     tests/unit/test_cli.py::test_subcommand_help[report] PASSED              [ 43%]
     tests/unit/test_cli.py::test_cli_single_invocation_mock PASSED           [ 46%]
     tests/unit/test_cli.py::test_cli_run_invocation_mock PASSED              [ 48%]
     tests/unit/test_cli.py::test_cli_device_override PASSED                  [ 51%]
     tests/unit/test_cli.py::test_cli_invalid_option PASSED                   [ 53%]
     tests/unit/test_config.py::test_default_config_instantiation PASSED      [ 56%]
     tests/unit/test_config.py::test_load_config_from_valid_yaml PASSED       [ 58%]
     tests/unit/test_config.py::test_load_config_nonexistent_file PASSED      [ 60%]
     tests/unit/test_config.py::test_load_config_invalid_yaml PASSED          [ 63%]
     tests/unit/test_config.py::test_config_validation_tier_limits PASSED     [ 65%]
     tests/unit/test_config.py::test_config_validation_canvas_size_even PASSED [ 68%]
     tests/unit/test_config.py::test_config_validation_overlap_ranges PASSED  [ 70%]
     tests/unit/test_config.py::test_resolve_device_selection PASSED          [ 73%]
     tests/unit/test_config.py::test_config_to_dict_and_roundtrip PASSED      [ 75%]
     tests/unit/test_config.py::test_path_attribute_conversion PASSED         [ 78%]
     tests/unit/test_loader.py::test_load_l2_image_mock PASSED                [ 80%]
     tests/unit/test_loader.py::test_load_l2_image_uncalibrated PASSED        [ 82%]
     tests/unit/test_loader.py::test_active_science_dimensions PASSED         [ 85%]
     tests/unit/test_loader.py::test_get_dq_mask_default_flags PASSED         [ 87%]
     tests/unit/test_loader.py::test_get_dq_mask_custom_flags PASSED          [ 90%]
     tests/unit/test_loader.py::test_zero_point_ab_calculation PASSED         [ 92%]
     tests/unit/test_loader.py::test_loader_file_not_found PASSED             [ 95%]
     tests/unit/test_loader.py::test_metadata_dictionary_contents PASSED      [ 97%]
     tests/unit/test_loader.py::test_real_asdf_smoke PASSED                   [100%]

     ============================== 41 passed in 4.84s ==============================
     ```
   - Exit code: 0 (100% pass rate).

2. **E2E Test Infrastructure Execution (M1 Features F1-F8)**:
   - Command:
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier1_features.py -k "TestFeature01 or TestFeature02 or TestFeature03 or TestFeature04 or TestFeature05 or TestFeature06 or TestFeature07 or TestFeature08" -v`
   - Result: `40 passed, 85 deselected in 3.84s` (Exit code 0).
   - Command (Tier 2 Boundaries B1-B8):
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/test_tier2_boundaries.py -k "TestBoundary01 or TestBoundary02 or TestBoundary03 or TestBoundary04 or TestBoundary05 or TestBoundary06 or TestBoundary07 or TestBoundary08" -v`
   - Result: `40 passed, 85 deselected in 2.13s` (Exit code 0).

3. **Adversarial Stress Test Suite Execution (`tests/test_adversarial_m1.py`)**:
   - Command:
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_adversarial_m1.py -v`
   - Result: `14 passed in 1.38s` (Exit code 0).

4. **Live CLI Execution on Real Commissioning Dataset**:
   - Command:
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/romanepsf catalog --detector wfi01 --output-csv output/test_run_wfi01.csv`
   - Result:
     ```
     2026-11-06 01:38:29 [INFO] [romanepsf] Processing catalog for detector WFI01
     2026-11-06 01:38:31 [INFO] [romanepsf] Processed 5 verified stars saved to output/test_run_wfi01.csv
     ```
   - Inspection of `output/test_run_wfi01.csv`:
     5 verified isolated stars across all 3 tiers:
     - 1 bright star ($m_{\text{F146}} = 10.438$)
     - 2 medium stars ($m_{\text{F146}} = 11.651, 12.323$)
     - 2 faint stars ($m_{\text{F146}} = 13.935, 13.983$)
     - Subpixel roundtrip discrepancy $\Delta\theta \le 2.5\times 10^{-5}$ arcseconds.
     - Refined centroid shifts: $1.16$ to $2.55$ px.

---

## 2. Logic Chain

1. **Integrity & Authenticity**:
   - The codebase was analyzed for hardcoded outputs, shortcut implementations, or fake test verifications.
   - All modules implement real algorithms:
     - GWCS spherical forward/backward transformation.
     - Analytical Moffat profile inversion based on $I(r) = I_0 [1 + (r/\alpha)^2]^{-\beta}$.
     - Background-subtracted 2D centroid moments with 10th-percentile background estimation.
     - Real Roman Level 2 ASDF reading and photometric conversion factor multiplication.
   - Independent reproduction of catalog processing on real commissioning files yields identical verified star outputs.
   - Conclusion: **Zero integrity violations**.

2. **Interface Contract Conformance (`PROJECT.md § Interface Contracts`)**:
   - **Contract 1: Loader (`loader.py`)**:
     `load_l2_image(asdf_path: Path, calibrate: bool = True) -> RomanL2Data`
     Returns `RomanL2Data` with attributes: `data: np.ndarray (4088, 4088)`, `dq: np.ndarray (4088, 4088)`, `err: np.ndarray (4088, 4088)`, `wcs: gwcs.WCS`, `pa_aperture: float`, `pixel_scale: float = 0.11`, `conversion_factor: float`.
     *Status: PASS*.
   - **Contract 2: Catalog (`catalog.py`)**:
     `project_catalog_to_pixels(l2_data: RomanL2Data, catalog_df: pd.DataFrame, margin_px: int = 50, tolerance_arcsec: float = 0.5) -> pd.DataFrame`
     Returns DataFrame containing `[source_id, ra, dec, mag_lambda, x, y, detector]` with verified roundtrip coordinates.
     *Status: PASS*.
   - **Contract 3: Tiers (`catalog.py`)**:
     `assign_stellar_tiers(df: pd.DataFrame, bright_limit: float = 11.0, faint_limit: float = 13.0) -> pd.DataFrame`
     Adds column `'tier'` with values `'bright'`, `'medium'`, `'faint'`.
     *Status: PASS*.

3. **Adversarial & Stress-Testing Findings**:
   - Evaluated empty inputs across `project_catalog_to_pixels`, `refine_stellar_centroids`, `filter_isolated_stars`, and `assign_stellar_tiers`: All return cleanly structured empty DataFrames without unhandled exceptions.
   - Evaluated pathological pixel cutouts in `refine_stellar_centroids` (all NaNs, negative values, flat zero arrays): Algorithm safely falls back to catalog coordinates with `centroid_shift_px = 0.0`.
   - Evaluated invalid configuration overrides in `config.py` (inverted tiers, even canvas sizes, inverted overlap ranges): Proper `ValueError` exceptions are raised with descriptive diagnostic messages.
   - Evaluated celestial coordinates far outside the detector footprint (e.g. celestial pole): Completely excluded by both margin boundary and forward roundtrip check.

4. **Code Quality and Conventions**:
   - Clean modular layout under `src/romanepsf/`.
   - Re-exports in `src/loader.py` and `src/catalog.py` ensure backward-compatibility.
   - Zero linter/syntax errors; all unit and boundary tests execute cleanly without unexpected warnings.

---

## 3. Caveats

1. **Downstream Pipeline Modules**:
   - Subcommands `run`, `single`, `stamps`, `assemble`, `validate`, and `report` call modules scheduled for implementation in Milestones 2, 3, and 4 (`stamps.py`, `masking.py`, `assembly.py`, `pipeline.py`, `validation.py`, `report.py`). Milestone 1 CLI unit tests mock these dispatch entry points, confirming CLI argument parsing and error propagation without prematurely building downstream logic.
2. **Precomputed vs Online Gaia Query**:
   - The catalog ingestion pipeline defaults to offline operation using the precomputed commissioning catalog `r0108301001001001001_0001_wfi_source_catalog.csv` and local cache files. The online Gaia DR3 query via `astroquery.gaia` is preserved as a fallback.

---

## 4. Conclusion

- **Milestone 1 Deliverables**:
  - `pyproject.toml` and package configuration: COMPLETE & VERIFIED.
  - `configs/default.yaml` and `src/romanepsf/config.py`: COMPLETE & VERIFIED.
  - `src/romanepsf/loader.py`: COMPLETE & VERIFIED.
  - `src/romanepsf/catalog.py`: COMPLETE & VERIFIED.
  - `src/romanepsf/cli.py` (7 subcommands): COMPLETE & VERIFIED.
  - `tests/unit/` (41 passing tests): COMPLETE & VERIFIED.
- **Integrity**: Fully verified authentic implementation with zero facades or hardcoded shortcuts.
- **Verdict**: **APPROVE**. Milestone 1 is production-ready for Milestone 2.

---

## 5. Verification Method

To independently reproduce this verification:

```bash
# 1. Verify package entry points and version
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "import romanepsf; print('Roman ePSF:', romanepsf.__version__)"

# 2. Run unit test suite (41 tests)
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/unit/ -v

# 3. Run adversarial test suite (14 tests)
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/test_adversarial_m1.py -v

# 4. Run CLI catalog command on commissioning detector WFI01
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/romanepsf catalog --detector wfi01 --output-csv /Users/pmsanch1/code/romanepsf/output/test_run_wfi01.csv

# Invalidation conditions:
# Approval is invalidated if any unit test in tests/unit/ fails, or if WFI01 catalog extraction fails to output verified stars across all three tiers.
```
