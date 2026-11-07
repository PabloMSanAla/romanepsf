# Handoff Report: Milestone 5 Phase 2 Adversarial Integration Coverage

**Author**: challenger_m5_tier5_2  
**Role**: Teamwork Challenger (Adversarial Critic & Domain Specialist)  
**Target Modules**:
- `src/romanepsf/pipeline.py`
- `src/romanepsf/validation.py`
- `src/romanepsf/report.py`
- `src/romanepsf/cli.py`

---

## 1. Observation

### Test Execution Summary
- **Test suite**: `tests/test_tier5_adversarial_integration.py`
- **Execution command**:
  ```bash
  /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_tier5_adversarial_integration.py -v
  ```
- **Outcome**: **30 passed, 1 warning in 11.54s** across 7 test classes.

### Concrete Defect Findings Observed

#### Finding 1: CLI `assemble` Subcommand Parameter Mismatch & Return Type Handling
- **Location**: `src/romanepsf/cli.py:542-544`
  ```python
  epsf_model = assemble_composite_extended_psf(stamps_by_tier, cfg.assembly, device=ctx.obj["device"])

  hdu = fits.PrimaryHDU(epsf_model.astype("float32"))
  ```
- **Observed Behavior**:
  Running `romanepsf assemble --stamps-dir <dir> --output-fits <path>` fails with exit code 1:
  ```
  [ERROR] [romanepsf] Assembly command failed: unsupported operand type(s) for %: 'AssemblySection' and 'int'
  ```
- **Root Cause**:
  1. `assemble_composite_extended_psf` (`src/romanepsf/assembly.py:375`) defines positional signature `(tier_stamps, output_size=None, cfg=None, device="cpu")`. In `cli.py`, `cfg.assembly` is passed as the second positional argument (`output_size`). Inside `assembly.py`, `target_sz % 2 == 0` attempts modulo on `AssemblySection`, raising `TypeError`.
  2. `assemble_composite_extended_psf` returns a tuple `(extended_psf, diagnostics)`. Line 544 in `cli.py` attempts `epsf_model.astype("float32")`, which fails on a tuple object.
- **Empirical Test**: `TestAdversarialCliPermutations::test_cli_assemble_command_defect_empirical` confirms exit code 1 and error output.

#### Finding 2: CLI Pre-Validation Rejection of Even Canvas Sizes
- **Location**: `src/romanepsf/cli.py:223, 315` vs `src/romanepsf/pipeline.py:445-449, 690-694`
- **Observed Behavior**:
  Both `run_pipeline` and `run_single_detector` include explicit logic to promote even canvas sizes to odd integers:
  ```python
  if cfg.assembly.canvas_size % 2 == 0:
      logger.warning(f"Even canvas size {cfg.assembly.canvas_size} provided; promoting to odd {cfg.assembly.canvas_size + 1}")
      cfg.assembly.canvas_size += 1
  ```
  However, in `cli.py`, `run_command` and `single_command` invoke `cfg.validate()` before calling the pipeline runners. `cfg.validate()` in `src/romanepsf/config.py:288` strictly rejects even integers:
  ```
  [ERROR] [romanepsf] Configuration validation failed: canvas_size must be an odd positive integer, got 1024
  ```
- **Impact**: Any user executing `romanepsf single --canvas-size 1024` or `romanepsf run --canvas-size 2048` gets an immediate CLI failure (exit code 1) rather than the intended odd promotion.
- **Empirical Test**: `TestAdversarialCliPermutations::test_cli_canvas_size_validation_discrepancy`.

#### Finding 3: Report Generator Page 5 Crash on Low-Flux / Flat Canvas
- **Location**: `src/romanepsf/report.py:714-715, 763`
  ```python
  vmax = float(np.max(epsf))
  vmin = max(float(vmax * 1e-6), 1e-8)
  ...
  ax_spike_inset.imshow(spike_cut, origin="lower", cmap="viridis", norm=LogNorm(vmin=vmin, vmax=vmax*1e-2))
  ```
- **Observed Behavior**:
  When a model canvas with peak flux $v_{\max} < 10^{-6}$ (such as an un-normalized, flat, or uniform canvas where $v_{\max} = 1/(1025^2) \approx 9.5 \times 10^{-7}$) is passed, `vmin` is clamped to $10^{-8}$. At line 763, the upper bound is $v_{\max} \times 10^{-2} \approx 9.5 \times 10^{-9} < 10^{-8} = v_{\min}$.
  This violates Matplotlib's invariant $v_{\min} \le v_{\max}$, throwing:
  ```
  ValueError: vmin must be less or equal to vmax
  ```
- **Empirical Test**: `TestMultiExtensionFitsEdgeCases::test_report_lognorm_flat_canvas_edge_case`.

### Verified System Robustness
1. **Multi-Detector Partial Failure Resilience**:
   In `src/romanepsf/pipeline.py:726-750`, sequential SCA extraction catches individual detector failures, records them in `failed_detectors` and `detector_summaries`, pools stamps from healthy detectors, and successfully produces composite FITS models without crashing. (Verified by `test_pipeline_partial_detector_failure_resilience`).
2. **Deterministic Memory Disposal**:
   `process_single_detector_stamps` guarantees execution of `del l2_data` and `gc.collect()` within its `finally` block, ensuring no memory leakage across sequential SCAs even during unexpected exceptions. (Verified by `test_process_single_detector_stamps_lifecycle_cleanup`).
3. **Multi-Extension FITS Fallbacks**:
   `ReportDataBundle` seamlessly handles minimal 1-HDU FITS files by defaulting coverage to `np.ones_like` and populating empty DataFrames for radial profiles and detector summaries. (Verified by `test_fits_ingestion_single_hdu_minimal`).
4. **Corrupted Validation JSON Recovery**:
   `ReportDataBundle` searches a 4-path candidate fallback hierarchy and ignores JSON syntax errors via `try/except`. Plotting functions use `_safe_float` to sanitize nulls, non-numeric strings, and astronomical numbers ($>10^{12}$). (Verified by `TestCorruptedValidationSummaryJsonAndReport`).
5. **FITS Header Specification Conformance**:
   `export_single_detector_fits` writes standard $\le 8$ character FITS cards (`EXTNAME`, `TELESCOP`, `INSTRUME`, `DETECTOR`, `FILTER`, `PIXSCALE`, `PIXAREA`, `ZP_AB`, `PA_APER`, `CANVAS_S`, `CRPIX1`, `CRPIX2`, `CRVAL1`, `CRVAL2`, `CDELT1`, `CDELT2`, `CTYPE1`, `CTYPE2`, `CUNIT1`, `CUNIT2`, `NORM`, `SUM_FLUX`, `PEAKFLUX`, `TOTALFLX`, `N_BRIGHT`, `N_MEDIUM`, `N_FAINT`, `N_TOTAL`, `K_FM`, `K_MB`, `DATE_UTC`, `DATE`, `PROV_VER`, `ORIGIN`). (Verified by `test_fits_export_header_card_conformance`).
6. **Publication Report Compilation**:
   `generate_publication_pdf_report` reliably compiles an 8-page PDF document containing exact US Letter `[0 0 612 792]` MediaBoxes and valid `startxref` trailers, with optional individual PNG page exports. (Verified by `TestPublicationReportEndToEndIntegrity`).

---

## 2. Logic Chain

1. **Premise**: Adversarial integration testing requires subjecting high-level runner interfaces and data boundaries to non-ideal inputs (corrupted inputs, invalid CLI flags, memory lifecycle events, extreme dynamic range arrays).
2. **Step 1 (CLI Examination)**:
   - CLI flags `--canvas-size` and `--detectors` were tested against Click parser boundaries.
   - Tracing `cli.py:assemble_command` revealed positional argument ordering mismatch with `assemble_composite_extended_psf` and tuple return handling.
   - Executing `test_cli_assemble_command_defect_empirical` reproduced the crash with `TypeError`.
3. **Step 2 (FITS and Matplotlib Normalization)**:
   - FITS files with minimal HDUs, missing cards, and uniform arrays were tested.
   - For an un-normalized canvas, `vmin` clamping logic in `report.py:715` causes $v_{\min} > v_{\max}$ on inset plots, causing Matplotlib `LogNorm` to raise `ValueError`.
   - Normalization with realistic peak fluxes ($v_{\max} > 10^{-4}$) generates complete 8-page PDFs cleanly.
4. **Step 3 (Sequential Pipeline Execution)**:
   - In multi-detector execution across SCAs, isolating one detector failure (`OSError`) proved that `run_pipeline` does not abort, but isolates the failure and aggregates all available stamps.
   - Memory cleanup in `process_single_detector_stamps` was verified to trigger `gc.collect()` in `finally`.
5. **Step 4 (Validation Ingestion)**:
   - Corrupted validation JSON files, empty metric objects, and missing test stamps were passed into `evaluate_epsf_validation` and `plot_page_residual_metrics`. All handled gracefully with `status="NO_DATA"` and fallback constants.

---

## 3. Caveats

1. **Review-Only Constraint**: In strict adherence to our challenger persona, no changes were made to source files under `src/romanepsf/`. All defects were documented as findings and proven via tests in `tests/test_tier5_adversarial_integration.py`.
2. **Live Commissioning ASDF Footprint**: Live tests run against real simulated commissioning data if present at `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors`, but the test suite is designed with self-contained synthetic fixtures to remain fully portable and deterministic across environments.

---

## 4. Conclusion

The Roman ePSF integration, validation, report, and CLI architecture exhibits high operational resilience across multi-detector execution, memory lifecycle management, and publication PDF compilation.

Three specific implementation defects were identified and empirically reproduced:
1. **Critical Defect**: `cli.py:542` `assemble_command` argument mismatch (`cfg.assembly` passed to `output_size`) and tuple unpack omission.
2. **Moderate Defect**: `cli.py:223,315` premature `cfg.validate()` prevents even canvas size promotion logic in `run_pipeline` / `run_single_detector`.
3. **Low/Corner Defect**: `report.py:715,763` `LogNorm` $v_{\min} > v_{\max}$ failure when rendering synthetic/flat canvas with peak flux $< 10^{-6}$.

All 30 tests in `tests/test_tier5_adversarial_integration.py` pass cleanly.

---

## 5. Verification Method

To independently execute and verify the Tier 5 adversarial stress test suite:

```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_tier5_adversarial_integration.py -v
```

Expected result:
```
======================== 30 passed, 1 warning in 11.54s ========================
```

Files to inspect:
- `tests/test_tier5_adversarial_integration.py`
- `.agents/teamwork/challenger_m5_tier5_2/BRIEFING.md`
- `.agents/teamwork/challenger_m5_tier5_2/handoff.md`
