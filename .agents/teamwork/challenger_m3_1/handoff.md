# Milestone 3 Challenger 1 Report: CLI, Configuration & Signature Adversarial Stress Testing

**Agent**: `challenger_m3_1` (Role: Milestone 3 Challenger 1 — Empirical Adversarial Stress Testing)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_1`  
**Test Suite**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_1/test_adversarial_pipeline.py`  
**Date**: 2026-11-07  
**Verdict**: **APPROVE**  

---

## 1. Observation

A standalone adversarial stress test suite containing 28 test cases was authored and executed using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_1/test_adversarial_pipeline.py -v`.

All 28 stress tests passed in 25.58 seconds with zero failures. Furthermore, executing the entire combined test suite via:
`/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ tests/e2e/ .agents/teamwork/challenger_m3_1/test_adversarial_pipeline.py -q`
yielded:
`830 passed, 4 skipped in 64.26s` (100% pass rate).

Direct empirical observations across the five targeted stress test areas:

### Area 1: Missing-Tier Detectors (`wfi02`, `wfi03`, `wfi08`, `wfi13`, `wfi17`, `wfi18`)
1. All 6 detectors that lack bright stars ($m_{\text{F146}} < 11.0$) were individually executed via `run_single_detector`:
   - `wfi02`: 6 total stars (0 B, 2 M, 4 F), $k_{\text{FM}} = 0.1069$, $k_{\text{MB}} = \text{None}$, FITS header `K_MB = -1.0`, `N_BRIGHT = 0`.
   - `wfi03`: 5 total stars (0 B, 1 M, 4 F), $k_{\text{FM}} = 0.1456$, $k_{\text{MB}} = \text{None}$, FITS header `K_MB = -1.0`, `N_BRIGHT = 0`.
   - `wfi08`: 6 total stars (0 B, 1 M, 5 F), $k_{\text{FM}} = 0.0703$, $k_{\text{MB}} = \text{None}$, FITS header `K_MB = -1.0`, `N_BRIGHT = 0`.
   - `wfi13`: 10 total stars (0 B, 3 M, 7 F), $k_{\text{FM}} = 0.2243$, $k_{\text{MB}} = \text{None}$, FITS header `K_MB = -1.0`, `N_BRIGHT = 0`.
   - `wfi17`: 8 total stars (0 B, 1 M, 7 F), $k_{\text{FM}} = 1.0000$, $k_{\text{MB}} = \text{None}$, FITS header `K_MB = -1.0`, `N_BRIGHT = 0`.
   - `wfi18`: 11 total stars (0 B, 3 M, 8 F), $k_{\text{FM}} = 0.3094$, $k_{\text{MB}} = \text{None}$, FITS header `K_MB = -1.0`, `N_BRIGHT = 0`.
2. In all 6 detectors:
   - No crash occurred; 2-tier synthesis (Faint + Medium) completed cleanly.
   - Output canvas has shape `(1025, 1025)`, type `float32`, is strictly finite, and integrates to $\sum \text{flux} = 1.0000 \pm 10^{-4}$.
   - Exported FITS Primary HDU header contains `K_MB = -1.0`, `N_BRIGHT = 0`, `DETECTOR = WFIxx`, and `SUM_FLUX > 0.999`.

### Area 2: Signature Polymorphism Stress
1. Positional Config-First:
   - `run_single_detector(cfg, detector="wfi01")` returns `SingleDetectorResult` with `success=True` and `detector_id="wfi01"`.
2. Positional 5-Argument:
   - `run_single_detector("wfi01", asdf_path, catalog_path, cfg, output_dir)` executes and returns verified result.
3. Keyword-Only Invocations:
   - Calling with subsets of overrides (e.g. `detector_id="wfi01", canvas_size=1025`, or `detector="wfi01", device="cpu"`) works seamlessly.
4. Path Types:
   - Passing `str` path representations operates identically to `pathlib.Path` objects across all input/output path parameters.
5. Invalid Arguments:
   - Non-existent ASDF path raises `FileNotFoundError("Detector ASDF file not found: ...")` at `pipeline.py:463`.
   - Invalid detector name `"wfi99"` raises `FileNotFoundError("Detector ASDF file not found: ...")` at `pipeline.py:463`.
   - Unsupported config type (e.g. `config=99999`) raises `AttributeError` rather than silently corrupting settings.
6. `export_single_detector_fits`:
   - Supports passing `SingleDetectorResult`, `(epsf_model=canvas, fits_path=...)`, and positional `(canvas, fits_path)`.
   - Invalid model type (e.g. passing a string) raises `ValueError("Must provide either SingleDetectorResult or 2D numpy array...")` at `pipeline.py:339`.
   - Missing output path raises `ValueError("Must specify output path or fits_path.")` at `pipeline.py:331`.
7. `discover_detectors`:
   - Correctly handles `requested=["WFI01", "wfi10"]` with case-insensitivity.
   - Correctly expands `requested=["all"]`.
   - Returns empty dictionary for directories with no ASDF files.

### Area 3: Canvas Dimensions & Coordinate Centering
1. Even Dimension Promotion:
   - Supplying even canvas size (e.g. `canvas_size=1024` or `canvas_size=2048`) is logged with a warning and promoted to odd integer (`1025` or `2049`).
   - Exported FITS header records `CANVAS_S = 1025`, `CRPIX1 = 513.0`, `CRPIX2 = 513.0` (`(S + 1.0) / 2.0`).
2. Coordinate Centering on Synthetic Stars:
   - For analytical 2D Gaussian stellar stamps, `assemble_composite_extended_psf` centers the peak flux pixel EXACTLY at `((S-1)//2, (S-1)//2)` for sizes 501, 1025, and 2049 (e.g. peak is at `(512, 512)` for size 1025).
3. Coordinate Centering on Real Level 2 Commissioning Data:
   - For real WFI01 data, the discrete maximum pixel is at `(511, 512)` (distance = 1.0 pixel from geometric center `(512, 512)`).
   - Investigation revealed that in Roman Level 2 commissioning data, faint stars in WFI01 have DQ bit 1 (`DO_NOT_USE` / `DROPOUT`) at their central pixel in the detector DQ array. The faint core protection logic masks this pixel, so the discrete argmax lies at an adjacent pixel, while the continuous subpixel alignment is centered at `(512.0, 512.0)`.

### Area 4: CLI Subcommand Invocations (`romanepsf single` and `romanepsf run`)
1. Click `CliRunner` was used to evaluate all CLI error paths:
   - Invalid global `--device quantum_tpu`: exits with code 2 and message `'quantum_tpu' is not one of 'auto', 'mps', 'cuda', 'cpu'`.
   - Invalid subcommand `--device quantum_gpu`: exits with code 2.
   - Non-existent ASDF path `--asdf /bogus.asdf`: exits with code 2 and message `File '...' does not exist`.
   - Non-existent catalog path `--catalog /bogus.csv`: exits with code 2 and message `File '...' does not exist`.
   - Unknown options (e.g. `--unrecognized-flag`): exits with code 2.
   - Invalid integer options (e.g. `--canvas-size not_an_int`): exits with code 2.
   - Non-existent detector SCA (`single --detector wfi99`): cleanly catches exception, logs `[ERROR] [romanepsf] Single detector execution failed: Detector ASDF file not found: ...`, and exits with code 1.

### Area 5: Zero-Star Detector Graceful Error Handling
1. Catalog with stars outside detector celestial footprint:
   - Raises descriptive `RuntimeError("No catalog stars found within celestial footprint of detector WFI01.")` at `pipeline.py:512`.
2. Completely empty catalog CSV:
   - Ingests header cleanly, detects 0 candidates, and raises `RuntimeError("No catalog stars found within celestial footprint of detector WFI01.")`.
3. `run_pipeline` with zero pooled stars:
   - Raises `RuntimeError("No valid stars extracted across any of the 1 detectors.")` at `pipeline.py:752`.

---

## 2. Logic Chain

1. **Missing-Tier Resilience**:
   - *Premise*: 6 of Roman's 18 SCAs lack bright stars.
   - *Observation*: `pipeline.py` passes extracted stamps to `assemble_composite_extended_psf`, which implements a 4-branch synthesis matrix (`assembly.py:504-572`). When `has_f and has_m` is True and `has_b` is False, it synthesizes a 2-tier blend, leaves `k_mb = None`, and `export_single_detector_fits` encodes `K_MB = -1.0` in the FITS header.
   - *Deduction*: The pipeline handles missing-tier detectors without crashing or throwing empty-tier exceptions.

2. **Polymorphic Calling Interface**:
   - *Premise*: The pipeline runner must accommodate positional, keyword, and config-driven CLI invocations.
   - *Observation*: `run_single_detector` checks `isinstance(detector_id_or_config, PipelineConfig)` and unrolls both positional and keyword arguments, while coercing all paths to `pathlib.Path`.
   - *Deduction*: Callers cannot cause runtime failures through trivial argument ordering or path type mismatches.

3. **Odd Canvas Centering and FITS WCS Consistency**:
   - *Premise*: An extended PSF canvas must have an unambiguous central pixel for convolution kernels, and FITS WCS headers must reference the center.
   - *Observation*: When given an even canvas size $S$, `pipeline.py:448` promotes it to $S+1$. In `export_single_detector_fits`, `CRPIX1` and `CRPIX2` are set to $(S+1)/2.0$, which is the exact center in 1-indexed FITS convention. Analytical Gaussians placed at the center produce peak pixel at $((S-1)//2, (S-1)//2)$.
   - *Deduction*: Mathematical coordinate centering is exact and standards-compliant.

4. **CLI Robustness and Clean Exit Codes**:
   - *Premise*: CLI utilities must validate inputs and fail with non-zero exit codes (exit 2 for CLI usage errors, exit 1 for runtime failures).
   - *Observation*: Click options use `exists=True`, `type=click.Choice`, and `type=int`. When invoked with invalid inputs, Click produces exit code 2. When the pipeline encounters a missing detector file, it catches the error and exits with code 1.
   - *Deduction*: CLI error handling conforms strictly to POSIX CLI conventions.

5. **Zero-Star Footprints**:
   - *Premise*: An empty catalog or remote catalog must not trigger raw index errors, `NaN` division, or crashes.
   - *Observation*: `pipeline.py:511` checks `if sub_df.empty:` and explicitly raises a descriptive `RuntimeError`.
   - *Deduction*: Error paths are cleanly guarded.

---

## 3. Caveats

- **Commissioning L2 DQ Masking at Faint Core**:
  In Roman simulated commissioning Level 2 data, the central pixel of faint stars in detector `wfi01` carries DQ bit 1 (`DO_NOT_USE` / `DROPOUT`). Consequently, the discrete maximum on real WFI01 data falls on an adjacent unmasked pixel at distance $1.0$ px from $(512, 512)$, while the subpixel continuous centroid is maintained at $(512.0, 512.0)$. This is an intrinsic property of the simulated data's DQ flags, not a bug in the centering algorithm (which was proven exact on clean synthetic stars).
- **Sequential Execution**:
  Multiprocessing (`num_workers > 1`) was verified via mock tests; live stress testing of all 18 detectors was executed sequentially, which takes ~14 seconds and consumes peak RSS of ~760 MB (well below the 4 GB limit).

---

## 4. Conclusion

**Verdict: APPROVE**

The Milestone 3 implementation (`src/romanepsf/pipeline.py`, `src/pipeline.py`, and `src/romanepsf/cli.py`) has undergone adversarial stress testing across all five designated challenge areas.
- All 6 missing-tier detectors run smoothly, setting $k_{\text{MB}}=\text{None}$ and exporting FITS with `K_MB = -1.0`.
- All signature polymorphism permutations, path types, and invalid arguments behave as specified.
- Canvas dimension promotion and coordinate centering are mathematically sound and compliant with FITS standards.
- CLI invocations handle all invalid flags and parameters with appropriate exit codes (2 for usage errors, 1 for runtime errors).
- Zero-star footprints raise clean, descriptive `RuntimeError` exceptions.
- All 28 adversarial stress tests pass, and all 830 repository tests pass with 100% success rate.

---

## 5. Verification Method

To independently verify all findings and execute the adversarial stress test suite:

1. **Run Standalone Adversarial Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_1/test_adversarial_pipeline.py -v
   ```
   *Expected outcome*: 28 passed in ~25s.

2. **Run Full Combined Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ tests/e2e/ .agents/teamwork/challenger_m3_1/test_adversarial_pipeline.py -q
   ```
   *Expected outcome*: 830 passed, 4 skipped in ~64s.

3. **Verify All 6 Missing-Tier Detectors on Real Commissioning Data**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   import tempfile
   from romanepsf.pipeline import run_single_detector
   from astropy.io import fits
   with tempfile.TemporaryDirectory() as tmpdir:
       for det in ['wfi02', 'wfi03', 'wfi08', 'wfi13', 'wfi17', 'wfi18']:
           res = run_single_detector(det, output_dir=tmpdir)
           assert res.success is True
           assert res.star_counts['bright'] == 0
           assert res.scale_factors['k_mb'] is None
           with fits.open(res.fits_path) as hdul:
               assert hdul[0].header['K_MB'] == -1.0
               assert hdul[0].header['N_BRIGHT'] == 0
           print(f'Verified {det.upper()}: k_mb=None, FITS K_MB=-1.0')
   "
   ```

4. **Invalidation Conditions**:
   - Any crash or unhandled `ValueError` when running `run_single_detector` on `wfi02`, `wfi03`, `wfi08`, `wfi13`, `wfi17`, or `wfi18`.
   - Any FITS header for missing-bright-tier detectors where `K_MB` is not equal to `-1.0` or `N_BRIGHT` is not equal to 0.
   - Any failure in the 28 tests of `test_adversarial_pipeline.py`.
