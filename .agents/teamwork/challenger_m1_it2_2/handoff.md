# Handoff Report — Challenger M1-it2-2: Adversarial Stress-Testing of CLI, Config, and Loader

**Agent**: Challenger M1 Iteration 2-2 (`challenger_m1_it2_2`)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m1_it2_2`  
**Date**: 2026-11-06  
**Verdict**: **APPROVE**  
**Recipient**: Parent Orchestrator (`e80d314a-b5a0-43fb-be2e-ceabc982347e`)  

---

## 1. Observation

### 1.1 Empirical Test Suite Execution
A comprehensive, adversarial stress test harness consisting of 89 targeted tests was authored at:
`/Users/pmsanch1/code/romanepsf/tests/unit/test_challenger_stress_m1_it2.py`.

The full test suite was executed using the designated environment `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:

1. **Iteration 2 Dedicated Adversarial Stress Suite**:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_challenger_stress_m1_it2.py -v`
   - Output: `89 passed in 2.65s` (100% pass rate).

2. **Full Unit Test Suite**:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
   - Output: `171 passed in 4.38s` (100% pass rate).
   - Component Breakdown:
     * `tests/unit/test_adversarial_m1.py`: 10 passed
     * `tests/unit/test_catalog.py`: 10 passed
     * `tests/unit/test_cli.py`: 12 passed
     * `tests/unit/test_config.py`: 11 passed
     * `tests/unit/test_loader.py`: 11 passed
     * `tests/unit/test_challenger_stress.py`: 28 passed
     * `tests/unit/test_challenger_stress_m1_it2.py`: 89 passed

3. **End-to-End Regression Test Suite**:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/`
   - Output: `297 passed, 4 skipped, 1 xfailed in 16.96s` (zero regressions across all features).

---

### 1.2 Direct Observations Across Challenged Dimensions

#### Dimension A: CLI Option Parsing, Missing Config Handling, and Overrides Validation
1. **Explicit Missing or Directory Config**:
   - In `src/romanepsf/cli.py` (lines 50–57, 90–102), `--config` is defined as `type=click.Path(dir_okay=False, path_type=Path)`.
   - Supplying a directory path (`--config /tmp`) is trapped by Click with exit code 2: `Directory '...' is not a file.`
   - Supplying an explicit non-existent file (`--config nonexistent.yaml`) is trapped by `is_explicit and not config.is_file()`, raising `FileNotFoundError` and exiting with code 1 (`Error loading configuration: Configuration file not found: ...`).
   - Supplying a syntactically malformed YAML file or a file with a scalar/list root is caught by `try...except Exception as e` in `cli()` and cleanly exits with code 1 without unhandled stack traces.

2. **CLI Overrides Validation Across Subcommands**:
   - In `src/romanepsf/cli.py`, `cfg.validate()` is explicitly invoked after parameter overrides in:
     * `run_command` (lines 165–177)
     * `single_command` (lines 225–235)
     * `assemble_command` (lines 430–437)
   - Passing an even canvas size (e.g. `--canvas-size 1024`, `--canvas-size 2048`), zero (`--canvas-size 0`), or negative (`--canvas-size -1025`) triggers `cfg.validate()`, emitting `Configuration validation failed: canvas_size must be an odd positive integer, got ...` and terminating with exit code 1.
   - Passing non-integer strings to `--canvas-size` is caught by Click's option parser (`type=int`), cleanly terminating with exit code 2.

3. **Global CLI Option Precedence**:
   - In `src/romanepsf/cli.py` (lines 107–110), when both `--log-level ERROR` and `-v` (`--verbose`) are specified, `verbose` takes precedence, ensuring `cfg.pipeline.log_level = "DEBUG"`.
   - Comma-delimited detector lists (`--detectors " wfi01 , wfi02 , , wfi03 "`) in `run_command` (line 164) are cleanly stripped of whitespace and empty entries to `['wfi01', 'wfi02', 'wfi03']`.

#### Dimension B: PipelineConfig Schema Validation
1. **`canvas_size` Schema Invariants**:
   - In `src/romanepsf/config.py` (lines 280–292):
     ```python
     if isinstance(self.assembly.canvas_size, str) or not isinstance(self.assembly.canvas_size, (int, float)):
         raise TypeError(f"canvas_size must be an integer, got {type(self.assembly.canvas_size).__name__}")
     if (
         not isinstance(self.assembly.canvas_size, int)
         or isinstance(self.assembly.canvas_size, bool)
         or self.assembly.canvas_size <= 0
         or self.assembly.canvas_size % 2 == 0
     ):
         raise ValueError(f"canvas_size must be an odd positive integer, got {self.assembly.canvas_size}")
     ```
   - Tested and verified:
     * String `"1025"`, `"odd"`, `""`, `None`, `[1025]`, `{"s": 1025}`, `1025+0j` raise `TypeError`.
     * Even positive `1024`, `2048`, `2` raise `ValueError`.
     * Zero `0` raises `ValueError`.
     * Negative integers `-1`, `-2`, `-1025` raise `ValueError`.
     * Booleans `True`, `False` raise `ValueError`.
     * Floats `1025.0`, `1025.5` raise `ValueError`.

2. **Logical Parameter Constraints**:
   - Inverted or equal tier limits (`bright_limit >= faint_limit`, e.g. 13.0 and 11.0, or 11.0 and 11.0) raise `ValueError: bright_limit must be strictly less than faint_limit`.
   - Inverted overlap boundaries (`r_min >= r_max` or `blend_start >= blend_end`) for both `overlap_fm` and `overlap_mb` raise `ValueError`.
   - Non-positive or zero `catalog.roundtrip_tolerance_arcsec` (0.0, -0.1) raises `ValueError`.
   - Unsupported compute device strings (`"tpu"`, `"vulkan"`, `"opencl"`, `""`) raise `ValueError`. Case-insensitive strings (`"CPU"`, `"auto"`, `"MPS"`, `"CUDA"`) are accepted.

3. **YAML Serialization & Deserialization**:
   - `cfg.to_dict()` recursively stringifies all `Path` objects into string primitives.
   - `cfg.save(path)` writes valid YAML, and re-reading via `load_config(path)` reconstructs the identical dataclass hierarchy with 100% attribute fidelity.

#### Dimension C: RomanL2Data Dataclass Invariants and load_l2_image Validation
1. **`RomanL2Data` Invariant Enforcement**:
   - In `src/romanepsf/loader.py` (lines 63–73), `RomanL2Data.__post_init__` verifies:
     ```python
     if self.data is not None:
         if self.err is not None and self.err.shape != self.data.shape:
             raise ValueError(f"err array shape {self.err.shape} does not match data shape {self.data.shape}")
         if self.dq is not None and self.dq.shape != self.data.shape:
             raise ValueError(f"dq array shape {self.dq.shape} does not match data shape {self.data.shape}")
     ```
   - Attempting to construct `RomanL2Data` with shape mismatches (e.g. data 4088x4088 with err 4088x2048, or dq 2048x4088, or 1D err array) raises `ValueError`.
   - `get_effective_mask()` correctly combines DQ bitflags (DO_NOT_USE, SATURATED) with `np.nan`, `np.inf`, and `-np.inf`.

2. **`load_l2_image` Photometric Conversion & Dimension Verification**:
   - In `src/romanepsf/loader.py` (lines 222–249):
     * Mismatched `err.shape != raw_data.shape` raises `ValueError: Invalid err array shape ...`
     * Mismatched `dq.shape != raw_data.shape` raises `ValueError: Invalid dq array shape ...`
     * When `validate_shape=True`, any science array shape other than `(4088, 4088)` raises `ValueError`.
     * When `validate_shape=False`, non-standard shapes (e.g. 512x512) are permitted, but `err.shape` and `dq.shape` must still match `raw_data.shape`.
     * Photometric conversion factor (`conversion_megajanskys`) validation checks `np.isfinite(conv_factor) and conv_factor > 0`. Values `0.0`, `-1.0`, `NaN`, `+Inf`, `-Inf`, `"not_a_number"`, and `None` raise `ValueError: Invalid photometric conversion factor`.
     * Missing photometry metadata cleanly defaults to `conversion_factor = 1.0` and nominal pixel area `NOMINAL_PIXEL_AREA (2.8e-13)`.
     * Non-positive pixel area triggers nominal ZP AB (`26.836`) and pixel scale (`0.11`).

3. **Real Commissioning Data Validation**:
   - Loading `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf` verified:
     * Science array: float32 (4088, 4088)
     * Error array: float32 (4088, 4088)
     * DQ bitmask: uint32 (4088, 4088)
     * `conversion_factor`: positive and finite (`0.0487...`)
     * `pa_aperture`: `-0.0033...` degrees
     * `pixel_scale`: nominal `~0.11` arcsec/pixel
     * `is_calibrated`: `True`

---

## 2. Logic Chain

1. **CLI Robustness and Predictability**:
   - Observations A.1 through A.3 prove that CLI option parsing distinguishes cleanly between syntactic Click option errors (code 2), missing/corrupted configs and invalid runtime configurations (code 1), and valid executions (code 0).
   - Because `cfg.validate()` is re-invoked following parameter overrides in all execution subcommands (`run`, `single`, `assemble`), invalid parameters (such as even canvas sizes) cannot silently penetrate the pipeline core.

2. **Schema and Dataclass Invariant Soundness**:
   - Observations B.1 through B.3 and C.1 through C.3 confirm that all boundary conditions and type mismatches (including edge cases such as Python booleans as integers, floating point numbers with zero decimals, negative values, and dimensional broadcasting mismatches) are strictly intercepted before execution.
   - The dataclass `__post_init__` safeguards against programmatic misconstruction, while `load_l2_image` safeguards against corrupted ASDF files or anomalous header metadata.

3. **Zero Regressions**:
   - The addition of 89 adversarial stress tests (bringing the unit suite to 171 tests) and the execution of the full 302-test E2E suite confirmed 100% test pass rates and zero regressions.

---

## 3. Caveats

- **MockGWCS vs Spherical GWCS**: Unit tests for coordinate projections use `MockGWCS` planar models with meridian modulo arithmetic. Production execution utilizes real spherical models from `gwcs`.
- **Downstream Milestones**: Assembly and validation subcommands invoke pipeline modules currently scheduled for Milestones 2, 3, and 4. CLI testing for these subcommands was performed using isolated option parsing and validation harnesses.

---

## 4. Conclusion & Verdict

**Explicit Gate Verdict: APPROVE**

Milestone 1 Iteration 2 satisfies all architectural tenets, interface contracts, and robustness requirements:
1. CLI option parsing, missing config handling, and overrides validation are fully hardened.
2. `PipelineConfig` schema validation strictly enforces type, parity, range, and interval constraints.
3. `RomanL2Data` dataclass invariants and `load_l2_image` shape and photometric calibration validation are strictly enforced.
4. The codebase achieves 100% pass across 171 unit tests and 297 E2E tests with zero regressions.

Milestone 1 is verified and ready for sign-off.

---

## 5. Verification Method

To independently reproduce and verify this assessment:

1. **Execute Dedicated Adversarial Stress Harness**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/unit/test_challenger_stress_m1_it2.py -v
   ```
   *Expected outcome*: `89 passed in ~2.6s`.

2. **Execute Full Unit Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/unit/ -v
   ```
   *Expected outcome*: `171 passed in ~4.4s`.

3. **Execute Full E2E Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/tests/e2e/
   ```
   *Expected outcome*: `297 passed, 4 skipped, 1 xfailed in ~17s`.

4. **Invalidation Conditions**:
   - Any test failure in `tests/unit/test_challenger_stress_m1_it2.py` or `tests/unit/`.
   - Any regression in `tests/e2e/`.
   - Failure to reject even/negative canvas sizes or non-positive photometric conversion factors.
