# Independent Review Report — Reviewer M1-2: Milestone 1 Verification

**Agent**: Reviewer M1-2 (Milestone 1 Independent Reviewer & Adversarial Critic)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m1_2/`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Recipient**: Parent Orchestrator (`e80d314a-b5a0-43fb-be2e-ceabc982347e`)  

---

## Review Summary

**Verdict**: **APPROVE**  
**Integrity Status**: **CLEAN (Zero Integrity Violations Found)**  
**Overall Risk Assessment**: **LOW**  

---

## 1. Observation

### 1.1 Direct Inspection of Implementation Artifacts
Direct source code inspection was conducted across all files within Milestone 1 scope:
- `/Users/pmsanch1/code/romanepsf/pyproject.toml`:
  - PEP 517/621 setuptools configuration declaring entry point `romanepsf = "romanepsf.cli:cli"` (line 46).
  - Package discovery config `[tool.setuptools.packages.find] where = ["src"]` (lines 51-53).
  - Declares all 12 required dependencies (`numpy`, `scipy`, `astropy`, `photutils`, `roman_datamodels`, `asdf`, `pandas`, `pyyaml`, `click`, `matplotlib`, `torch`, `gwcs`).
- `/Users/pmsanch1/code/romanepsf/configs/default.yaml`:
  - 101 lines containing 11 distinct operational sections: `pipeline`, `environment`, `data`, `catalog`, `tiers`, `stamps`, `spikes`, `profile`, `assembly`, `validation`, `reporting`.
  - Configured with commissioning paths: detectors dir `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors` and catalog path `.../r0108301001001001001_0001_wfi_source_catalog.csv` (lines 18-19).
- `/Users/pmsanch1/code/romanepsf/src/romanepsf/config.py`:
  - Hierarchical dataclasses (`PipelineConfig`, `CatalogSection`, `TiersSection`, `AssemblySection`, etc.) with `load_config()`.
  - Supports dot-notation dictionary overrides via `_apply_dot_overrides()` (lines 357-374).
  - Logical constraint enforcement in `validate()` (lines 273-304): `bright_limit < faint_limit`, odd positive `canvas_size`, valid overlap interval ordering, and positive `roundtrip_tolerance_arcsec`.
  - Hardware device resolution in `resolve_device()` (lines 18-61) handling `auto`, `mps`, `cuda`, and `cpu`.
- `/Users/pmsanch1/code/romanepsf/src/romanepsf/loader.py`:
  - `load_l2_image(asdf_path, calibrate=True)` (lines 162-299) opens ASDF files using `roman_datamodels.open`.
  - Enforces active science dimensions `(4088, 4088)` against `ACTIVE_SHAPE` (line 200).
  - Multiplies flux and error by `conversion_megajanskys` when `calibrate=True` (lines 261-267) while retaining raw counts in `raw_data`.
  - Calculates physical AB zero point `zp_ab = -2.5 * log10(flux_1dns_jy / 3631.0)` (lines 244-246).
  - Full Roman DQ bitmask decoding with 14 flags (`DO_NOT_USE`, `SATURATED`, etc.) and `get_effective_mask()` combining DQ with non-finite pixel values (lines 116-143).
- `/Users/pmsanch1/code/romanepsf/src/romanepsf/catalog.py`:
  - `sanitize_source_catalog()` (lines 51-125): deduplicates columns, resolves `phot_g_mean_mag_AB` collision, validates coordinate ranges $[0, 360]$ and $[-90, 90]$, and filters out unphysical solar system objects ($m < 0$).
  - `project_catalog_to_pixels()` (lines 257-362): vectorizes `wcs.backward_transform`, excludes margin boundary ($50$ px), and verifies forward roundtrip $\Delta\theta < 0.5''$ via `wcs(x, y)`.
  - `refine_stellar_centroids()` (lines 364-464): calculates background-subtracted first moments, sets NaN/saturated pixel weights to 0, and bounds shift divergence at `max_shift_px = 3.0`.
  - `filter_isolated_stars()` (lines 466-556): prioritizes brighter stars by sorting ascending in magnitude, computing Moffat extensions down to $28\ \text{mag}/\text{arcsec}^2$, and enforcing $1.3\times$ clearance.
  - `assign_stellar_tiers()` (lines 558-614): partitions stars into `'bright'` ($< 11.0$), `'medium'` ($[11.0, 13.0)$), and `'faint'` ($\ge 13.0$).
- `/Users/pmsanch1/code/romanepsf/src/romanepsf/cli.py`:
  - Click group with all 7 required subcommands: `run`, `single`, `catalog`, `stamps`, `assemble`, `validate`, `report`.
  - Supports global options `--config`, `--device`, `--log-level`, `--verbose`, `--version`.
  - The `catalog` subcommand connects end-to-end with `loader` and `catalog` modules to process real detector data.
- Backward compatibility modules:
  - `/Users/pmsanch1/code/romanepsf/src/loader.py` re-exports `romanepsf.loader`.
  - `/Users/pmsanch1/code/romanepsf/src/catalog.py` re-exports `romanepsf.catalog`.

### 1.2 Independent Test Suite Execution
The unit test suite was executed in the designated `rosalia-dev` Python environment:
- Command:
  `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
- Verbatim Result:
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
  Note: `test_real_asdf_smoke` successfully loaded and validated real data from `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf`.

### 1.3 Live CLI Subcommand Execution on Real Commissioning Data
- Command:
  `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli catalog --detector wfi01 --output-csv output/wfi01_test_tiered.csv`
- Verbatim Output:
  ```
  2026-11-06 01:36:04 [INFO] [romanepsf] Processing catalog for detector WFI01
  2026-11-06 01:36:06 [INFO] [romanepsf] Processed 5 verified stars saved to output/wfi01_test_tiered.csv
  ```
- Resulting CSV inspection (`output/wfi01_test_tiered.csv`):
  5 isolated stars were identified on WFI01 with all 3 tiers represented:
  - 1 bright star ($m_{\text{F146}} = 10.438$)
  - 2 medium stars ($m_{\text{F146}} = 11.651, 12.323$)
  - 2 faint stars ($m_{\text{F146}} = 13.935, 13.983$)
  - Measured astrometric roundtrip discrepancies $\Delta\theta \approx 3.6\times 10^{-6}$ to $2.5\times 10^{-5}$ arcseconds (all well below the 0.5 arcsecond threshold).
  - Centroid shifts: $1.15$ to $2.55$ px (all within the 3.0 px divergence limit).

### 1.4 E2E Test Suite Status
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/TEST_READY.md` was checked and does not exist. As specified in `PROJECT.md`, E2E test suite validation is scheduled for Milestone 5.

---

## 2. Logic Chain

1. **Active Integrity Audit**:
   - Source code was searched for hardcoded test fixtures, dummy return values, bypassed logic, or fake verification artifacts.
   - All components perform legitimate mathematical calculations (GWCS transforms, first-moment centroiding with background estimation, analytic Moffat calculations, photometric unit conversions).
   - Conclusion: **Zero integrity violations**.

2. **Interface Contract Verification (`PROJECT.md § Interface Contracts`)**:
   - **Contract 1**: `load_l2_image(asdf_path: Path, calibrate: bool = True) -> RomanL2Data`
     - Evaluated: Returns `RomanL2Data` dataclass with attributes `data: np.ndarray (4088, 4088)`, `dq: np.ndarray (4088, 4088)`, `err: np.ndarray (4088, 4088)`, `wcs`, `pa_aperture: float`, `pixel_scale: float = 0.11`, `conversion_factor: float`. Verified in `src/romanepsf/loader.py:46-61` and tested in `test_loader.py:57-78`.
     - Status: **PASSED**.
   - **Contract 2**: `project_catalog_to_pixels(l2_data: RomanL2Data, catalog_df: pd.DataFrame, margin_px: int = 50, tolerance_arcsec: float = 0.5) -> pd.DataFrame`
     - Evaluated: Returns DataFrame containing `[source_id, ra, dec, mag_lambda, x, y, detector]` with verified roundtrip coordinates. Verified in `src/romanepsf/catalog.py:257-362` and tested in `test_catalog.py:74-124`.
     - Status: **PASSED**.
   - **Contract 3**: `assign_stellar_tiers(df: pd.DataFrame, bright_limit: float = 11.0, faint_limit: float = 13.0) -> pd.DataFrame`
     - Evaluated: Adds column `'tier'` with values `'bright'`, `'medium'`, `'faint'`. Verified in `src/romanepsf/catalog.py:558-614` and tested in `test_catalog.py:226-245`.
     - Status: **PASSED**.

3. **Adversarial & Boundary Stress Testing**:
   - An independent adversarial harness was executed to stress-test boundary and corrupt inputs:
     - Empty catalog DataFrame: properly handled without uncaught exceptions.
     - Out-of-bounds celestial coordinates (`ra < 0`, `ra > 360`, `dec < -90`, `dec > 90`, `NaN`, strings): cleanly filtered out.
     - Stars near detector border ($x=0, y=0$): centroid refinement bounded within array boundaries without indexing errors.
     - Arrays containing NaNs and Infs: `get_effective_mask()` combines non-finite pixels with DQ flags; centroid weights ignore non-finite values.
     - Coincident star pairs at identical pixel coordinates: brightest star preserved, duplicate fainter star rejected.
     - Faint extreme magnitude ($m = 35.0$): Moffat extension formula correctly clamped to 0.0.
     - Dot-notation configuration overrides: correctly updates nested fields without altering unaffected defaults.

4. **Code Quality & Packaging**:
   - `pyproject.toml` correctly establishes package metadata and entry points.
   - Clean separation of concerns between data loading (`loader.py`), astrometric processing (`catalog.py`), configuration management (`config.py`), and CLI interface (`cli.py`).
   - Backward-compatibility re-exports provided in `src/loader.py` and `src/catalog.py`.

---

## 3. Caveats

1. **Downstream CLI Subcommands**:
   - The CLI subcommands `stamps`, `assemble`, `validate`, and `report` import modules scheduled for Milestone 2, 3, and 4 (`stamps.py`, `assembly.py`, `validation.py`, `report.py`). In Milestone 1, unit tests verify CLI options parsing and subcommand dispatch using mock handlers, which is appropriate and avoids premature stubs.
2. **Offline Mode Default**:
   - Source catalog projection defaults to using the precomputed commissioning catalog (`PID1083`) and local cache files. The online Gaia TAP query fallback via `astroquery` is preserved as a fallback.

---

## 4. Conclusion

- **Milestone 1 Objectives**: 100% achieved.
  - Package structure, dependencies, and entry points verified.
  - 11-section YAML configuration schema and dataclass validator verified.
  - Level 2 ASDF loader, active dimension validation (4088x4088), DQ bitmasking, and photometric calibration verified against real commissioning data.
  - Catalog deduplication, forward roundtrip WCS verification ($\Delta\theta < 0.5''$), centroid refinement, isolation filtering, and tier partitioning verified.
  - 7-subcommand Click CLI framework verified.
  - 41 unit tests passing independently.
- **Verdict**: **APPROVE**. Milestone 1 is production-ready for Milestone 2 (`stamps.py`, `masking.py`, `assembly.py`).

---

## 5. Verification Method

To independently reproduce and verify this review, execute the following commands:

```bash
# 1. Verify package version and module imports
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
import romanepsf
from romanepsf import load_config, load_l2_image, project_catalog_to_pixels, assign_stellar_tiers
print('Roman ePSF Version:', romanepsf.__version__)
"

# 2. Run complete unit test suite (41 tests)
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/unit/ -v

# 3. Test CLI top-level and subcommand help
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli --help
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli catalog --help

# 4. Test live catalog extraction and tiering on commissioning detector WFI01
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli catalog \
    --detector wfi01 \
    --output-csv /Users/pmsanch1/code/romanepsf/output/wfi01_test_tiered.csv

# 5. Invalidation condition:
# If any unit test in tests/unit/ fails or if the catalog command fails to produce a tiered CSV on WFI01, this approval is invalidated.
```
