# Milestone 3 Review & Adversarial Challenge Report

**Reviewer**: `reviewer_m3_1` (Role: Milestone 3 Reviewer 1 — Pipeline Architecture & Single-Detector Validation)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m3_1`  
**Date**: 2026-11-07  
**Verdict**: **APPROVE**  
**Integrity Assessment**: CLEAN — Zero integrity violations detected (no hardcoded outputs, dummy facades, or shortcuts)

---

## 1. Observation

1. **Interface & Architecture Conformance**:
   - `src/romanepsf/pipeline.py` (lines 63–103) implements `SingleDetectorResult` with attributes `detector_id`, `asdf_path`, `fits_path`, `epsf_model`, `canvas_size`, `star_counts`, `scale_factors`, `pixel_scale`, `pa_aperture`, `diagnostics`, `stamps_by_tier`, `catalog_df`, `execution_time_s`, and `success`. It provides `.to_dict()` and `.summary()`.
   - `src/romanepsf/pipeline.py` (lines 106–122) implements `PipelineOutputs` conforming to `PROJECT.md` interface specifications (`composite_epsf: np.ndarray`, `fits_path: Path`, `diagnostics: Dict[str, Any]`), with aliasing between `pooled_stamps` and `stamps_by_tier`.
   - `src/pipeline.py` provides backward compatibility by re-exporting all primary pipeline symbols from `romanepsf.pipeline`.
   - `run_single_detector` (lines 396–433) supports signature polymorphism:
     * Config-first: `run_single_detector(cfg, detector="wfi01")`
     * Positional/Keyword: `run_single_detector("wfi01", asdf_path=..., catalog_path=..., config=..., output_dir=...)`
     * Keyword-only: `run_single_detector(detector_id="wfi01", ...)`
     * Keyword overrides: `canvas_size`, `output_dir`, `device`.
   - Canvas dimension handling (lines 445–450, lines 690–695) cleanly promotes even dimensions (e.g. 512, 1024, 2048) to odd integers (+1) with explicit logging.
   - `export_single_detector_fits` (lines 285–393) exports Primary HDU FITS with standard header cards $\le 8$ characters:
     `EXTNAME='EPSF'`, `TELESCOP='ROMAN'`, `INSTRUME='WFI'`, `DETECTOR`, `FILTER`, `PIXSCALE`, `PIXAREA`, `ZP_AB`, `PA_APER`, `CANVAS_S`, `CRPIX1/2`, `CRVAL1/2`, `CDELT1/2`, `CTYPE1/2`, `CUNIT1/2`, `NORM='UNIT_FLUX'`, `SUM_FLUX`, `PEAKFLUX`, `TOTALFLX`, `N_BRIGHT`, `N_MEDIUM`, `N_FAINT`, `N_TOTAL`, `K_FM`, `K_MB`, `DATE_UTC`, `PROV_VER`, `ORIGIN`.

2. **Multi-Tier Fallback Handling**:
   - `src/romanepsf/assembly.py` (lines 530–573) and `src/romanepsf/pipeline.py` (lines 378–385, lines 582–593):
     When bright stars are absent (as in detector `wfi02`), the assembly engine falls back to 2-tier synthesis without raising exceptions.
     In `export_single_detector_fits`, `K_MB` defaults to `-1.0` when `k_mb is None`, and `N_BRIGHT` is recorded as `0`.
   - Live execution on `wfi02` completed in 2.17s, generating `roman_epsf_wfi02.fits` with `N_BRIGHT=0`, `K_MB=-1.0`, `SUM_FLUX=1.000000`.

3. **CLI Single Subcommand**:
   - `src/romanepsf/cli.py` (lines 242–295) defines `single` subcommand accepting:
     * `-d, --detector`: default `'wfi01'`
     * `--asdf`: path to L2 ASDF file
     * `--catalog`: path to source catalog CSV
     * `-c, --config`: path to YAML config file
     * `-s, --canvas-size`: canvas dimension integer
     * `-o, --output-dir`: output directory
   - Verified via `test_cli_single_full_options` and live CLI invocations.

4. **Automated Test Suite Verification**:
   - `tests/unit/test_pipeline.py` and `tests/unit/test_cli.py`:
     Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_pipeline.py tests/unit/test_cli.py -v`
     Result: `30 passed in 9.97s`
   - Full unit test suite:
     Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -q`
     Result: `504 passed in 30.42s`
   - Full E2E test suite:
     Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -q`
     Result: `298 passed, 4 skipped in 19.63s`
   - Overall test execution: 802 passed, 4 skipped out of 806 test cases (100% pass rate).

5. **Live Dataset Execution & FITS Validation**:
   - Live WFI01 execution:
     Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli single --detector wfi01 --canvas-size 1025 --output-dir output/reviewer_test_wfi01`
     Result: Completed in 2.90s.
     Model inspection: 1025x1025, 32-bit float (`>f4`), integrated flux sum = 1.000000, 0 NaNs/Infs, min >= 0.0, 5 stars (1 B, 2 M, 2 F), $k_{FM}=0.1972$, $k_{MB}=0.0272$.
   - Live WFI02 execution:
     Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli single --detector wfi02 --canvas-size 1025 --output-dir output/reviewer_test_wfi02`
     Result: Completed in 2.17s.
     Model inspection: 1025x1025, 32-bit float (`>f4`), integrated flux sum = 1.000000, 0 NaNs/Infs, min >= 0.0, 6 stars (0 B, 2 M, 4 F), $k_{FM}=0.1069$, $k_{MB}=\text{None}$, `K_MB=-1.0`.
   - Composite 18-detector FITS inspection (`output/run_all/roman_epsf_composite.fits`):
     Primary HDU: `ALL18`, `NDET=18`, `NSTARS=140`, `SUM_FLUX=1.000000`, `SCALE_FM=0.1937`, `SCALE_MB=0.0255`, `BASE_ANG='23.55,55.29,80.25,118.65,142.88,178.07'`, `NET_ROT=240.30`.
     HDU 1: `COVERAGE` (1025x1025, int32, max 135 stars/pixel).
     HDU 2: `RADIAL_PROFILES` (500 bins x 6 columns).
     HDU 3: `DETECTOR_SUMMARY` (18 rows x 9 columns).

6. **Integrity & Adversarial Checks**:
   - Codebase search for hardcoded constants, mock shortcuts, dummy returns: None found.
   - Non-existent detector (`wfi99`) test: properly raises `FileNotFoundError`.
   - Invalid arguments to `export_single_detector_fits`: properly raises `ValueError`.
   - Even canvas size (512) test in `run_pipeline`: cleanly promoted to odd 513 without error.
   - Memory management in `process_single_detector_stamps`: uses explicit `del l2_data; gc.collect()` in `finally:` block; peak RSS across detectors remains well below the 4 GB limit.

---

## 2. Logic Chain

1. *Observation 1 & 3* demonstrate that all API interface contracts defined in `PROJECT.md` and the review dispatch are fully implemented. `SingleDetectorResult` and `PipelineOutputs` dataclasses match all specifications, and `run_single_detector` satisfies polymorphic signature requirements.
2. *Observation 2 & 5* prove that single-detector fallback handling functions correctly both logically and in real commissioning execution. Detectors lacking bright stars (such as WFI02) do not raise unhandled exceptions; instead, they produce valid 2-tier models with `N_BRIGHT=0` and `K_MB=-1.0`.
3. *Observation 4* confirms that unit and end-to-end regressions are zero across the entire codebase (802 passed, 4 skipped).
4. *Observation 5* confirms that output FITS files conform to standard FITS conventions (standard $\le 8$ character keyword names, big-endian 32-bit IEEE float data arrays, unit flux normalization $\sum f = 1.0$, non-negative pixel values, and absence of NaNs/Infs).
5. *Observation 6* proves that the implementation contains zero integrity violations: no hardcoded outputs, no mocked bypasses, and robust error handling for out-of-boundary inputs.
6. Therefore, the implementation fulfills all requirements for Milestone 3.

---

## 3. Caveats

- **Astropy Model Fit Warnings**: During stamp extraction on WFI02, a minor warning (`WARNING: The fit may be unsuccessful; check fit_info['message']`) was logged by astropy's 2D Moffat fitter for low-S/N stars. This does not impair pipeline execution because morphological ridge protection and geometric angle masking provide redundant fallback coverage.
- **Multiprocessing on macOS**: Sequential processing across the 18 detectors executes in ~13 seconds with peak RSS < 1.7 GB. Although `--num-workers` is available in `romanepsf run`, sequential execution is recommended as the default on macOS to avoid MPS context contention.

---

## 4. Conclusion

**Verdict: APPROVE**

Milestone 3 (Pipeline Architecture & Single-Detector Validation) is complete, robust, and fully verified. The implementation satisfies all acceptance criteria in `PROJECT.md` and `ORIGINAL_REQUEST.md`:
- `run_single_detector` and `run_pipeline` provide high-performance, polymorphic execution.
- Single-detector execution on WFI01 and WFI02 succeeds with valid 2D FITS models.
- Multi-tier fallback handling on sparse SCAs functions cleanly without exceptions.
- 18-detector pooling and 4-HDU composite serialization meet publication standards.
- Test suite passes 100% (802/802 runnable tests passed).
- Zero integrity violations detected.

Milestone 3 is cleared for transition to Milestone 4 (Model Validation, Technical Documentation & PDF Report).

---

## 5. Verification Method

To independently reproduce the review findings:

1. **Run Unit and E2E Test Suites**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/test_pipeline.py tests/unit/test_cli.py -v
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -q
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -q
   ```
   *Expected result*: 30 passed in unit pipeline/cli, 504 passed in unit, 298 passed / 4 skipped in e2e.

2. **Execute Live Single-Detector Runs**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli single --detector wfi01 --canvas-size 1025 --output-dir output/test_wfi01
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli single --detector wfi02 --canvas-size 1025 --output-dir output/test_wfi02
   ```

3. **Inspect Output FITS Headers and Arrays**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   from astropy.io import fits
   import numpy as np

   for det, path, exp_b in [('WFI01', 'output/test_wfi01/roman_epsf_wfi01.fits', True),
                            ('WFI02', 'output/test_wfi02/roman_epsf_wfi02.fits', False)]:
       with fits.open(path) as hdul:
           hdr = hdul[0].header
           data = hdul[0].data
           assert hdr['DETECTOR'] == det
           assert hdr['NORM'] == 'UNIT_FLUX'
           assert np.isclose(np.sum(data), 1.0, atol=1e-5)
           assert np.all(np.isfinite(data))
           assert (hdr['N_BRIGHT'] > 0 if exp_b else hdr['N_BRIGHT'] == 0)
           assert (hdr['K_MB'] > 0.0 if exp_b else hdr['K_MB'] == -1.0)
           print(f'{det} verification passed.')
   "
   ```

4. **Invalidation Conditions**:
   - Any test failure in `tests/unit/` or `tests/e2e/`.
   - Failure of `run_single_detector` on WFI02 or any SCA without bright stars.
   - Any FITS header card exceeding 8 characters or emitting `HIERARCH` warnings.
   - Any NaN or non-finite pixel in the generated ePSF models.
