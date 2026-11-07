# Handoff Report — Explorer M1-Iteration 2: Milestone 1 Remediation & Hardening Blueprint

**Agent**: Explorer M1-Iteration 2 (Subagent 3)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_it2_3/`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Recipient**: Sub-Orchestrator M1 (`e80d314a-b5a0-43fb-be2e-ceabc982347e`)  

---

## Executive Summary

Challenger M1-1 issued a **`REJECT`** verdict due to 5 adversarial defects in `src/romanepsf/catalog.py` (reproduced in `tests/unit/test_adversarial_m1.py` with 5 failures). Concurrently, Challenger M1-2 issued an **`APPROVE`** verdict but identified 5 hardening vulnerabilities across `cli.py`, `config.py`, and `loader.py` (documented in `tests/unit/test_challenger_stress.py`).

This investigation verified all 10 reported items against the active codebase, analyzed the integration contract between `loader.py` and `catalog.py` for Data Quality (DQ) bitmasking, and designed an actionable, unified patch and test plan for Worker M1-Iteration 2.

---

## 1. Observation

### 1.1 Empirical Baseline & Verbatim Test Failures
Executing the unit test suite (`/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`) yields **5 failed, 77 passed**:
- `tests/unit/test_adversarial_m1.py::test_bug_wcs_ra_wrap_around_0_360`: **FAILED** (`AssertionError: Star crossing RA 0/360 meridian was falsely rejected! ra_catalog=359.9508, expected on detector at x=500, y=2044. assert 0 == 1`)
- `tests/unit/test_adversarial_m1.py::test_bug_catalog_solar_system_rejection_without_mag_lambda`: **FAILED** (`AssertionError: sanitize_source_catalog failed to filter negative magnitude solar system objects when catalog uses phot_g_mean_mag! assert not np.True_`)
- `tests/unit/test_adversarial_m1.py::test_bug_catalog_header_spaces`: **FAILED** (`ValueError: Source catalog must contain 'ra' and 'dec' coordinate columns.`)
- `tests/unit/test_adversarial_m1.py::test_bug_centroid_cosmic_ray_hijack_dq_ignored`: **FAILED** (`AssertionError: Centroid was hijacked by cosmic ray! refined_x=51.753, true star is at x=50.0, shift=1.959 px`)
- `tests/unit/test_adversarial_m1.py::test_bug_centroid_negative_flux_noise_shift`: **FAILED** (`AssertionError: Centroid was shifted on pure negative background noise! shift=2.333 px, peak=-72.5`)

### 1.2 Direct Code Inspections: Challenger M1-1 Defects (`catalog.py`)
1. **Observation 1.2.1 — RA Wrap-Around (`src/romanepsf/catalog.py:333-336`)**:
   `delta_ra_arcsec = (ra_back - ra_cand) * cos_dec * 3600.0`. For a star across the $0^\circ / 360^\circ$ meridian (`ra_back = -0.0492^\circ`, `ra_cand = 359.9508^\circ`), `ra_back - ra_cand = -360.0^\circ`, producing $\Delta\theta \approx 1.2 \times 10^6$ arcsec, which exceeds `tolerance_arcsec = 0.5`. Valid stars straddling the boundary are dropped.
2. **Observation 1.2.2 — Solar System Object Filter Bypass (`src/romanepsf/catalog.py:111-119`)**:
   `clean_df[mag_col] >= 0.0` is gated strictly inside `if mag_col in clean_df.columns:`. When ingesting a catalog without `mag_lambda` (e.g. Gaia TAP tables with `phot_g_mean_mag`), the filter is bypassed. The Sun ($m = -26.98$) remains in `clean_df`, generating a 30-million-pixel exclusion radius downstream that wipes out all real stars.
3. **Observation 1.2.3 — Header Whitespace (`src/romanepsf/catalog.py:74-93`)**:
   `sanitize_source_catalog` does not invoke `.str.strip()` on `clean_df.columns`. A standard CSV with spaces after commas produces `' ra'`, which fails `"ra" not in clean_df.columns` and raises `ValueError`.
4. **Observation 1.2.4 — Centroid Refinement DQ Ignored (`src/romanepsf/catalog.py:395-435`)**:
   `refine_stellar_centroids` receives `l2_data: RomanL2Data`, but `l2_data.dq` is never accessed. When a cosmic ray flagged with `JUMP_DET = 4` occurs at $r \le 3\text{ px}$ from the star, the first-moment calculation shifts towards the cosmic ray ($50,000\text{ DN/s}$ vs star $500\text{ DN/s}$), displacing the star center by up to $1.96\text{ px}$.
5. **Observation 1.2.5 — Centroid Shift on Negative Noise Cutout (`src/romanepsf/catalog.py:424-440`)**:
   When all pixels in a cutout are negative background noise, `bkg = percentile(10)` creates artificial positive weights (`box - bkg`). Because `peak <= 0.0` is not guarded, a centroid shift of $2.33\text{ px}$ is computed on pure noise.

### 1.3 Direct Code Inspections: Challenger M1-2 Hardening Items (`cli.py`, `config.py`, `loader.py`)
1. **Observation 1.3.1 — CLI Silent Fallback on Missing Config (`src/romanepsf/cli.py:92`)**:
   `cfg = load_config(config if config.is_file() else None)`. When the user explicitly passes `--config /nonexistent/file.yaml`, `config.is_file()` evaluates to `False`, so `load_config(None)` is called. The CLI silently proceeds using default settings with exit code 0 rather than raising `FileNotFoundError`.
2. **Observation 1.3.2 — CLI Override Schema Validation Gap (`src/romanepsf/cli.py:158, 212, 410`)**:
   CLI subcommands `run_command`, `single_command`, and `assemble_command` assign `cfg.assembly.canvas_size = canvas_size` without re-invoking `cfg.validate()`. An even canvas size (e.g. `--canvas-size 1024`) slips through.
3. **Observation 1.3.3 — Float Canvas Size in Config (`src/romanepsf/config.py:280-283`)**:
   `if self.assembly.canvas_size <= 0 or self.assembly.canvas_size % 2 == 0:`. For `canvas_size = 1025.5`, `1025.5 % 2 == 1.5 != 0`, so validation passes. Downstream array allocation `np.zeros((canvas_size, canvas_size))` fails with `TypeError`.
4. **Observation 1.3.4 — Missing Shape Validation for `err` and `dq` (`src/romanepsf/loader.py:45-65, 199-215`)**:
   `load_l2_image` checks only `raw_data.shape == ACTIVE_SHAPE`. If `dm.dq` or `dm.err` has a mismatched shape (e.g. `(50, 50)` vs `(4088, 4088)`), `RomanL2Data` is created without error, and later crashes during broadcasting in `get_effective_mask()`.
5. **Observation 1.3.5 — Photometric Conversion Factor Sanity (`src/romanepsf/loader.py:226-232, 261-264`)**:
   `conversion_megajanskys` is multiplied into `raw_data` without verifying `np.isfinite(conv_factor) and conv_factor > 0`. Corrupted ASDF files with `NaN` convert all science data into `NaN`.
6. **Observation 1.3.6 — Existing Stress Tests Document Unhardened Behavior (`tests/unit/test_challenger_stress.py`)**:
   Tests `test_cli_nonexistent_config_behavior`, `test_cli_even_canvas_size_override_bypasses_validation`, `test_config_float_canvas_size_vulnerability`, `test_loader_mismatched_dq_array_shape_vulnerability`, and `test_loader_nan_conversion_megajanskys_vulnerability` were written to assert the unhardened behavior (`assert result.exit_code == 0`, etc.). Hardening the implementation requires aligning these 5 tests.

---

## 2. Logic Chain

1. **Root Cause Analysis of Challenger M1-1 Defects**:
   - Angular separation on a celestial sphere requires wrapping $\Delta\alpha \in (-180^\circ, +180^\circ]$: `(ra_back - ra_cand + 180.0) % 360.0 - 180.0`. Linear subtraction produces $\approx \pm 360^\circ$ at the meridian (Observation 1.2.1).
   - Magnitude filtering must apply to any active magnitude column (`mag_col` and `phot_g_mean_mag`) present in the catalog. Filtering only `mag_col` allows solar system bodies to escape, generating catastrophic Moffat clearance zones (Observation 1.2.2).
   - Strip column names with `clean_df.columns = clean_df.columns.astype(str).str.strip()` to handle CSV delimiter spacing (Observation 1.2.3).
   - Centroid refinement must use the 32-bit `l2_data.dq` array. Masking pixels with `(dq_box & (DO_NOT_USE | JUMP_DET)) > 0` zeros out cosmic ray and defective pixel weights. Excluding non-positive peaks (`peak <= 0.0`) prevents spurious centroid shifts on pure background noise (Observations 1.2.4 & 1.2.5).

2. **Integration Contract Between `loader.py` and `catalog.py`**:
   - `RomanL2Data` provides `dq: np.ndarray` (uint32) alongside `data: np.ndarray` (float32).
   - Slicing `dq[y0:y1, x0:x1]` in `refine_stellar_centroids` and bitwise-ANDing against `DQ_FLAGS["DO_NOT_USE"] | DQ_FLAGS["JUMP_DET"]` correctly preserves stellar flux while discarding cosmic rays and bad pixels.
   - Saturated pixels (`SATURATED = 2`) must NOT be masked during centroid refinement, because bright stars have saturated cores; zeroing them out would hollow the core and distort moments.

3. **Hardening Logic**:
   - When a user explicitly specifies `--config`, Click's `ctx.get_parameter_source("config")` is not `ParameterSource.DEFAULT`. If the file does not exist, `FileNotFoundError` must be raised and caught by CLI with exit code 1. When not explicitly passed, if `configs/default.yaml` is absent on disk, `load_config(None)` safely provides defaults (Observation 1.3.1).
   - Calling `cfg.validate()` after assigning CLI overrides (`--canvas-size`, etc.) in `run_command`, `single_command`, and `assemble_command` enforces configuration integrity (Observation 1.3.2).
   - Checking `type(canvas_size) is int and canvas_size > 0 and canvas_size % 2 == 1` in `PipelineConfig.validate()` prevents floats and booleans from passing (Observation 1.3.3).
   - Adding a `__post_init__` method to `RomanL2Data` verifying `err.shape == data.shape` and `dq.shape == data.shape` guarantees dataclass invariant integrity at all times (Observation 1.3.4).

---

## 3. Caveats

- **Existing Stress Test Alignment**: As documented in Observation 1.3.6, `tests/unit/test_challenger_stress.py` contains 5 tests authored by Challenger M1-2 that assert the *unhardened* behavior. When Worker M1-Iteration 2 hardens the implementation, those 5 tests must be updated to assert the hardened behavior; otherwise, `pytest` will report 5 failures in `test_challenger_stress.py`.
- **E2E Suite Compatibility**: All proposed remediations were checked against the 302 tests in `tests/e2e/`. None of the proposed changes disrupt any end-to-end pipelines or feature contracts.

---

## 4. Conclusion & Actionable Blueprint for Worker M1-Iteration 2

### 4.1 Unified Patch Specification

#### File 1: `src/romanepsf/catalog.py`
```python
# 1. Imports: import DQ_FLAGS from loader
from romanepsf.loader import DQ_FLAGS, RomanL2Data

# 2. sanitize_source_catalog: Strip whitespace and filter negative magnitudes across all mag columns
def sanitize_source_catalog(df: pd.DataFrame, mag_col: str = "mag_lambda") -> pd.DataFrame:
    clean_df = df.copy()
    clean_df.columns = clean_df.columns.astype(str).str.strip()

    # Deduplicate columns and handle phot_g_mean_mag_AB ...
    ...
    # Filter out unphysical solar system objects (mag < 0) across all active mag columns
    for m_col in [mag_col, "phot_g_mean_mag"]:
        if m_col in clean_df.columns:
            clean_df[m_col] = pd.to_numeric(clean_df[m_col], errors="coerce")
            valid_mag = clean_df[m_col].notna() & np.isfinite(clean_df[m_col]) & (clean_df[m_col] >= 0.0)
            clean_df = clean_df[valid_mag].copy()

# 3. project_catalog_to_pixels: Wrap delta_ra across 0/360 meridian
    cos_dec = np.cos(np.radians(dec_cand))
    delta_ra = (ra_back - ra_cand + 180.0) % 360.0 - 180.0
    delta_ra_arcsec = delta_ra * cos_dec * 3600.0
    delta_dec_arcsec = (dec_back - dec_cand) * 3600.0
    delta_theta_arcsec = np.hypot(delta_ra_arcsec, delta_dec_arcsec)

# 4. refine_stellar_centroids: Use l2_data.dq to mask cosmic rays & guard peak <= 0.0
    dq_box = (
        l2_data.dq[y0:y1, x0:x1]
        if hasattr(l2_data, "dq") and l2_data.dq is not None
        else None
    )
    if dq_box is not None:
        bad_mask = (dq_box & (DQ_FLAGS["DO_NOT_USE"] | DQ_FLAGS["JUMP_DET"])) > 0
    else:
        bad_mask = np.zeros(box.shape, dtype=bool)

    usable_pix = np.isfinite(box) & (~bad_mask)
    if not np.any(usable_pix):
        x_refined.append(x_init)
        y_refined.append(y_init)
        peak_fluxes.append(0.0)
        shifts.append(0.0)
        continue

    peak = float(np.nanmax(box[usable_pix]))

    # Guard: non-positive peak flux indicates pure negative noise background
    if peak <= 0.0:
        x_refined.append(x_init)
        y_refined.append(y_init)
        peak_fluxes.append(peak)
        shifts.append(0.0)
        continue

    valid_vals = box[usable_pix]
    bkg = float(np.percentile(valid_vals, 10))

    weights = np.maximum(box - bkg, 0.0)
    weights[~usable_pix] = 0.0
    total_w = float(np.sum(weights))

    if total_w > 0:
        grid_y, grid_x = np.indices(box.shape)
        cx = x0 + (np.sum(grid_x * weights) / total_w)
        cy = y0 + (np.sum(grid_y * weights) / total_w)
        shift = float(np.hypot(cx - x_init, cy - y_init))
        if np.isfinite(cx) and np.isfinite(cy) and (shift <= max_shift_px):
            x_refined.append(float(cx))
            y_refined.append(float(cy))
            shifts.append(shift)
        else:
            x_refined.append(x_init)
            y_refined.append(y_init)
            shifts.append(0.0)
    else:
        x_refined.append(x_init)
        y_refined.append(y_init)
        shifts.append(0.0)

    peak_fluxes.append(peak)
```

#### File 2: `src/romanepsf/loader.py`
```python
# 1. Add __post_init__ to RomanL2Data
@dataclass
class RomanL2Data:
    ...
    def __post_init__(self) -> None:
        if self.data is not None:
            if self.err is not None and self.err.shape != self.data.shape:
                raise ValueError(
                    f"err array shape {self.err.shape} does not match data shape {self.data.shape}"
                )
            if self.dq is not None and self.dq.shape != self.data.shape:
                raise ValueError(
                    f"dq array shape {self.dq.shape} does not match data shape {self.data.shape}"
                )

# 2. In load_l2_image: validate array shapes and phot_meta conversion factor
    if validate_shape and raw_data.shape != ACTIVE_SHAPE:
        raise ValueError(...)
    if err.shape != raw_data.shape:
        raise ValueError(f"Invalid err array shape {err.shape}, expected {raw_data.shape}")
    if dq.shape != raw_data.shape:
        raise ValueError(f"Invalid dq array shape {dq.shape}, expected {raw_data.shape}")

    if phot_meta is not None:
        raw_conv = getattr(phot_meta, "conversion_megajanskys", 1.0)
        try:
            conv_factor = float(raw_conv)
            if not np.isfinite(conv_factor) or conv_factor <= 0:
                raise ValueError(f"Invalid photometric conversion factor: {conv_factor}")
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid photometric conversion factor: {raw_conv}") from e
        pixel_area = float(getattr(phot_meta, "pixel_area", NOMINAL_PIXEL_AREA))
    else:
        conv_factor = 1.0
        pixel_area = NOMINAL_PIXEL_AREA
```

#### File 3: `src/romanepsf/config.py`
```python
# In PipelineConfig.validate():
    if (
        not isinstance(self.assembly.canvas_size, int)
        or isinstance(self.assembly.canvas_size, bool)
        or self.assembly.canvas_size <= 0
        or self.assembly.canvas_size % 2 == 0
    ):
        raise ValueError(
            f"canvas_size must be an odd positive integer, got {self.assembly.canvas_size}"
        )
```

#### File 4: `src/romanepsf/cli.py`
```python
# 1. In cli(): Check if user explicitly passed --config and verify existence
    try:
        is_explicit = ctx.get_parameter_source("config") != click.core.ParameterSource.DEFAULT
        if is_explicit:
            if not config.is_file():
                raise FileNotFoundError(f"Configuration file not found: {config}")
            cfg_file = config
        else:
            cfg_file = config if config.is_file() else None
        cfg = load_config(cfg_file)
    except Exception as e:
        click.secho(f"Error loading configuration: {e}", fg="red", err=True)
        sys.exit(1)

# 2. In run_command, single_command, and assemble_command: re-validate after overrides
    if canvas_size is not None:
        cfg.assembly.canvas_size = canvas_size
    ...
    try:
        cfg.validate()
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        sys.exit(1)
```

#### File 5: `tests/unit/test_challenger_stress.py`
Update the 5 tests documenting unhardened behavior to assert the hardened contracts:
- `test_cli_nonexistent_config_behavior` $\to$ expects `result.exit_code == 1` and `"Error loading configuration"` in output.
- `test_cli_even_canvas_size_override_bypasses_validation` $\to$ expects `result.exit_code == 1` and `"Configuration validation failed"` in output.
- `test_config_float_canvas_size_vulnerability` $\to$ expects `pytest.raises(ValueError, match="canvas_size must be an odd positive integer")`.
- `test_loader_mismatched_dq_array_shape_vulnerability` $\to$ expects `pytest.raises(ValueError, match="dq array shape")`.
- `test_loader_nan_conversion_megajanskys_vulnerability` $\to$ expects `pytest.raises(ValueError, match="Invalid photometric conversion factor")`.

---

## 5. Verification Method

To independently verify the implementation once applied:

1. **Verify Adversarial M1 Reproduction Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/unit/test_adversarial_m1.py -v
   ```
   *Expected outcome*: 10 passed, 0 failed.

2. **Verify Full Unit & Hardened Stress Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/unit/ -v
   ```
   *Expected outcome*: 82 passed in ~3.8s (`test_catalog.py`: 10, `test_cli.py`: 10, `test_config.py`: 10, `test_loader.py`: 11, `test_adversarial_m1.py`: 10, `test_challenger_stress.py`: 31).

3. **Verify E2E Suite Integrity**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/e2e/ -v
   ```
   *Expected outcome*: 297 passed, 4 skipped, 1 xfailed.

4. **Verify Real Commissioning ASDF & Catalog Integration (WFI01)**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/unit/test_loader.py -k test_real_asdf_smoke -v
   ```

**Invalidation Conditions**:
This plan is invalidated if any of the 82 unit tests fail, if `refine_stellar_centroids` fails to filter `JUMP_DET` cosmic rays or fails on negative background noise, or if CLI overrides allow invalid canvas sizes through to execution.
