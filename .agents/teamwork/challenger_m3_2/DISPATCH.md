## 2026-11-07T00:46:10Z
You are challenger_m3_2 (role: Milestone 3 Challenger 2 — Memory Footprint, Scalability & FITS Forensics).
Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_2/
You must write your progress to /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_2/progress.md and your final challenge report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_2/handoff.md.

MANDATORY INSTRUCTION:
Read the authoritative user request at /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting your challenges.

Python Environment:
Use /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python for all execution and testing.
Local ROSALIA codebase is at /Users/pmsanch1/code/ROSALIA.

Mission:
Write and execute rigorous empirical stress tests against the 18-detector execution, memory limits, and FITS files:
- `src/romanepsf/pipeline.py`
- `src/romanepsf/assembly.py`

Adversarial Stress Test Areas:
1. Memory Ceiling & Leak Audit (Requirement R3):
   - Measure RSS throughout multi-detector runs. Perform consecutive runs to ensure there is no memory leakage across multiple invocations of `run_pipeline` or `run_single_detector`.
   - Confirm peak RSS is strictly < 4,000 MB at all times (record exact peak RSS in MB).
2. FITS Output Forensics:
   - Perform deep audit on `output/run_all/roman_epsf_composite.fits` and `output/single_wfi01/roman_epsf_wfi01.fits`:
     * Verify all 4 HDUs exist and have correct names, types, shapes, and bitpix.
     * Check every single header keyword in all HDUs: ensure NO keyword exceeds 8 characters and NO `HIERARCH` cards exist.
     * Verify Primary HDU: total sum of flux = 1.000000 ± 1e-4, peak pixel is positive and centered, no NaN or Inf values.
     * Verify HDU 1 (COVERAGE): min coverage >= 0, integer type, core region has positive coverage.
     * Verify HDU 2 (RADIAL_PROFILES): columns `RADIUS_PX`, `RADIUS_ARCSEC`, `FLUX_COMPOSITE`, `FLUX_FAINT`, `FLUX_MED_SCALED`, `FLUX_BRIGHT_SCALED`. Verify radial monotonicity in the outer wings.
     * Verify HDU 3 (DETECTOR_SUMMARY): exactly 18 rows, correct columns, total star sum matches Primary HDU `NSTARS`.
3. 2D Non-Circular Structure & Spike Preservation Audit:
   - Empirically verify that the composite ePSF is NOT circularized:
     * Check azimuthal variance as a function of angle at fixed radius (e.g. at $r = 50$ px and $r = 150$ px).
     * Verify that flux along the theoretical 6-fold spike angles (`ROMAN_BASE_SPIKE_ANGLES_DEG` adjusted for net orientation) is significantly higher than off-spike flux, proving diffraction spikes are preserved in 2D.
4. Scale Factor Validation:
   - Verify that cross-tier scale factors $k_{\text{FM}}$ and $k_{\text{MB}}$ are strictly positive and satisfy $0 < k_{\text{MB}} < k_{\text{FM}} < 1$.

Write a standalone adversarial test suite (e.g. `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_2/test_adversarial_fits_memory.py`), execute it, and record findings in `handoff.md`.

Deliver your verdict: **APPROVE** or **REQUEST_CHANGES** with concrete empirical metrics.
