# Review and Adversarial Audit Report: Milestone 5 Tier 5 Hardening

**Reviewer**: reviewer_m5_1  
**Archetype/Roles**: Reviewer, Critic  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m5_1`  
**Date**: 2026-11-07T06:26:00Z  
**Verdict**: **APPROVE**  

---

## 1. Observation

### 1.1 Direct Inspection of Source Code Changes

1. **`src/romanepsf/cli.py` (`assemble_command` lines 553–565)**:
   - Verbatim implementation:
     ```python
     extended_psf, diagnostics = assemble_composite_extended_psf(
         stamps_by_tier,
         output_size=cfg.assembly.output_size,
         cfg=cfg.assembly,
         device=ctx.obj["device"],
     )

     hdu = fits.PrimaryHDU(extended_psf.astype(np.float32))
     hdu.header["EXTNAME"] = "EPSF"
     hdu.header["FILTER"] = cfg.data.filter_name
     hdu.header["CANVAS_S"] = cfg.assembly.canvas_size
     hdu.header["NORM"] = "UNIT_FLUX"
     hdu.writeto(out_fits, overwrite=True)
     ```
   - Observed behavior: Correctly passes `output_size` by keyword argument rather than positional argument 2, unpacks `(extended_psf, diagnostics)`, and converts the NumPy ndarray `extended_psf` to single-precision float (`np.float32`) before writing to FITS.

2. **`src/romanepsf/cli.py` (`run_command` lines 207–213 and `single_command` lines 310–316)**:
   - Verbatim implementation:
     ```python
     if canvas_size is not None:
         if canvas_size > 0 and canvas_size % 2 == 0:
             logger.warning(
                 f"Even canvas size {canvas_size} provided; promoting to odd {canvas_size + 1}"
             )
             canvas_size = canvas_size + 1
         cfg.assembly.canvas_size = canvas_size
     ```
   - Observed behavior: Positive even numbers (`canvas_size > 0 and canvas_size % 2 == 0`) like `1024` or `2048` are promoted to `1025` and `2049` prior to calling `cfg.validate()`. Non-positive numbers (e.g., `0`, `-100`) bypass promotion and are cleanly intercepted and rejected by `cfg.validate()`.

3. **`src/romanepsf/config.py` (`AssemblySection` lines 213–220)**:
   - Verbatim implementation:
     ```python
     @property
     def output_size(self) -> int:
         """Alias for canvas_size for assembly compatibility."""
         return self.canvas_size

     @output_size.setter
     def output_size(self, val: int) -> None:
         self.canvas_size = val
     ```
   - Observed behavior: Transparently maps `output_size` to `canvas_size`. Verified that `dataclasses.asdict(AssemblySection())` only outputs dataclass fields (`canvas_size`, `stack_sigma_clip`, `overlap_fm`, `overlap_mb`, `normalize_flux`) without polluting schema serialization.

4. **`src/romanepsf/report.py` (`plot_page_composite_epsf` lines 718–780 and `plot_page_spike_protection` lines 564–568)**:
   - Verbatim implementation:
     ```python
     # plot_page_composite_epsf
     vmax = max(float(np.max(epsf)), 1e-11)
     vmin = min(1e-8, max(vmax * 1e-4, 1e-12))
     if vmin >= vmax:
         vmin = vmax * 0.1
     im = ax_canvas.imshow(
         epsf, origin="lower", extent=extent_px,
         cmap="viridis", norm=LogNorm(vmin=vmin, vmax=vmax)
     )
     ...
     lvl_min = max(vmax * 5e-5, vmin * 1.01)
     lvl_max = vmax * 0.8
     if lvl_min < lvl_max:
         levels = np.logspace(np.log10(lvl_min), np.log10(lvl_max), 8)
         ax_cont.contour(...)
     ...
     core_vmin = max(float(vmax * 1e-3), 1e-12)
     if core_vmin >= vmax:
         core_vmin = vmax * 0.1
     ...
     spike_vmax = max(float(vmax * 1e-2), vmin * 2.0)
     ```
   - Observed behavior: `vmin < vmax` and `0 < vmin` are guaranteed across all flux scales, including low-flux, flat, all-zero, all-negative, and extreme spike inputs.

### 1.2 Independent Test Suite Execution Results

1. **Compilation Check**:
   - Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m py_compile src/romanepsf/cli.py src/romanepsf/report.py src/romanepsf/config.py`
   - Exit code: `0` (clean compilation).

2. **Tier 5 Adversarial Suites**:
   - Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_tier5_adversarial_core.py tests/test_tier5_adversarial_integration.py -v`
   - Exit code: `0`
   - Result: **69 passed, 1 warning in 16.17s** (39 core + 30 integration).

3. **Full Unit Test Suite**:
   - Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
   - Exit code: `0`
   - Result: **612 passed, 6 warnings in 51.98s**.

4. **Full End-to-End (E2E) Test Suite**:
   - Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v`
   - Exit code: `0`
   - Result: **302 passed in 16.85s** across 5 tiers.

5. **Publication PDF Report Generation**:
   - Command: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli report --results-dir output/run_all --output-pdf output/report.pdf`
   - Exit code: `0`
   - Result: Generated 8-page PDF, file size 2,859,877 bytes (~2.86 MB), valid PDF header `%PDF-1.4`.

6. **Adversarial Edge Case Stress Tests**:
   - Zero-flux model canvas report generation: `PASSED` (PDF generated without error).
   - Uniform negative flux ($-1.0$) canvas report generation: `PASSED` (PDF generated without error).
   - Extreme single-pixel spike ($10^6$) canvas report generation: `PASSED` (PDF generated without error).
   - CLI `single --canvas-size 1024`: `PASSED` (promoted to 1025 with warning, executed cleanly).
   - CLI `run --canvas-size -100`: `PASSED` (cleanly rejected with exit code 1).
   - CLI `assemble --help` and `single --help`: `PASSED` (exit code 0).

---

## 2. Logic Chain

1. **Inference from 1.1.1 & 1.2.2**:
   - In `assemble_command`, passing `output_size=cfg.assembly.output_size` avoids positional argument misalignment with `assemble_composite_extended_psf(tier_stamps, output_size=None, cfg=None, device="cpu")`.
   - Unpacking `extended_psf, diagnostics` guarantees that `.astype(np.float32)` is called directly on a NumPy ndarray rather than on a tuple, resolving the regression observed by Tier 5 Challenger 2.
   - Verified via `test_cli_assemble_command_defect_empirical` which passes cleanly.

2. **Inference from 1.1.2, 1.1.3 & 1.2.6**:
   - The original requirement R3 specifies canvas dimensions between 1024x1024 and 2048x2048. When users pass `--canvas-size 1024` or `2048`, `run_command` and `single_command` now intercept even numbers, log an informative warning, and promote them to odd numbers (`1025`, `2049`) before `cfg.validate()` runs.
   - Non-positive values (`0`, `-100`) are not promoted and are rejected by `cfg.validate()`.
   - The `@property` and setter `output_size` on `AssemblySection` provide polymorphic access without impacting YAML or dataclass serialization.

3. **Inference from 1.1.4 & 1.2.6**:
   - Matplotlib's `LogNorm(vmin, vmax)` requires $0 < v_{\min} \le v_{\max}$.
   - The bounds implemented in `report.py` guarantee that `vmin = min(1e-8, max(vmax * 1e-4, 1e-12))` is clamped such that if `vmin >= vmax`, `vmin = vmax * 0.1`.
   - For any non-negative or negative canvas, `vmax` is clamped to at least $10^{-11}$, and `vmin` is strictly positive and less than `vmax`.
   - The contour levels are guarded by `if lvl_min < lvl_max:`, preventing `np.logspace` from raising errors when the dynamic range is collapsed.
   - Direct empirical execution on flat, zero, negative, and extreme delta canvases confirms zero crashes.

4. **Integrity Assessment**:
   - No hardcoded test fixtures, dummy implementations, or shortcuts were found.
   - Changes are genuine, robust control flow and numerical conditioning logic.
   - All 983 test cases across Tier 5 adversarial, E2E, and unit suites execute and pass independently.

---

## 3. Findings & Adversarial Observations

### [Minor] CLI Parity: `assemble` Subcommand Does Not Promote Even Canvas Sizes

- **What**: `romanepsf run` and `romanepsf single` promote positive even canvas sizes to odd (`1024` -> `1025`), but `romanepsf assemble` does not apply this promotion before calling `cfg.validate()`.
- **Where**: `src/romanepsf/cli.py`, lines 530–535.
- **Why**: Invoking `romanepsf assemble --canvas-size 1024` fails with `Configuration validation failed: canvas_size must be an odd positive integer, got 1024` (exit code 1).
- **Risk Level**: Low / Usability only. The CLI help text for `assemble` explicitly documents `--canvas-size (e.g. 1025 or 2049)`, and `assemble` is an advanced diagnostic subcommand primarily operating on pre-extracted stamp directories.
- **Recommendation**: In a future maintenance pass, consider adding the same 3-line positive even promotion to `assemble_command` for 100% uniformity across all CLI subcommands.

---

## 4. Integrity Violation Audit

| Integrity Check | Status | Verification Evidence |
|---|---|---|
| Hardcoded test outputs | PASS | Code inspection shows purely dynamic math and parameter handling. |
| Dummy or facade implementations | PASS | Full execution of PyTorch stacking, FITS export, and 8-page PDF generation verified. |
| Shortcuts bypassing core pipeline | PASS | All 18 SCAs, PSF stitching, and validation metrics fully executed. |
| Fabricated verification artifacts | PASS | Independently ran all 983 test cases and recompiled the 2.86 MB PDF report. |
| Self-certifying without verification | PASS | Multi-suite execution independently confirmed in active virtualenv. |

**Verdict on Integrity**: **PASS (Zero Violations)**.

---

## 5. Caveats

- **External Hardware Acceleration**: Tests were executed using the CPU device backend (`device="cpu"`). PyTorch MPS/CUDA paths were verified via unit mocks and type checks, but hardware execution was on CPU.
- **No other caveats**: All core requirements (R1–R5) and Tier 5 hardening criteria have been verified.

---

## 6. Conclusion

The code changes in `src/romanepsf/cli.py`, `src/romanepsf/report.py`, and `src/romanepsf/config.py` effectively and correctly resolve all Tier 5 defects:
1. `assemble_command` properly unpacks `(extended_psf, diagnostics)` and passes `output_size` by keyword, writing valid FITS files.
2. `run_command` and `single_command` promote positive even `canvas_size` values to odd integers while rejecting invalid non-positive inputs.
3. `report.py` strictly safeguards $v_{\min} < v_{\max}$ across all `LogNorm` instances, surviving even pathological flat or zero-flux canvases.
4. Total independent test validation: **983 tests passed (69 Tier 5 + 302 E2E + 612 Unit), 0 failures, 0 regressions**.

**Final Verdict**: **APPROVE**.

---

## 7. Verification Method

To independently reproduce the complete verification:

```bash
# 1. Run Tier 5 Adversarial Suites (69 tests)
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_tier5_adversarial_core.py tests/test_tier5_adversarial_integration.py -v

# 2. Run Full Unit Test Suite (612 tests)
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v

# 3. Run Full E2E Test Suite (302 tests)
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v

# 4. Recompile Publication PDF Report
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli report --results-dir output/run_all --output-pdf output/report.pdf
```
