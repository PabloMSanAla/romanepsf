## 2026-11-07T00:45:53Z

You are reviewer_m3_2 (role: Milestone 3 Reviewer 2 — 18-Detector Scalability, Memory & FITS Architecture).
Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m3_2/
You must write your progress to /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m3_2/progress.md and your final review report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m3_2/handoff.md.

MANDATORY INSTRUCTION:
Read the authoritative user request at /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting your review.

Python Environment:
Use /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python for all execution and testing.
Local ROSALIA codebase is at /Users/pmsanch1/code/ROSALIA.

Review Scope:
Review the 18-detector scalability, memory lifecycle, and FITS serialization delivered by worker_m3_1:
- Worker Handoff: /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m3_1/handoff.md
- Implementation files:
  * `src/romanepsf/assembly.py` (`serialize_composite_epsf_fits`)
  * `src/assembly.py`
  * `src/romanepsf/pipeline.py` (`run_pipeline`, `process_single_detector_stamps`, `discover_detectors`)
  * `src/romanepsf/cli.py` (`run` subcommand)

Review Checklist:
1. 18-Detector Scalability & Memory Management (Requirement R3):
   - Check `process_single_detector_stamps`: verify explicit memory lifecycle cleanup (`del l2_data; gc.collect()`) inside a `finally:` block.
   - Verify that all 18 detectors are processed sequentially or safely, and that peak RSS remains strictly < 4.0 GB.
2. Cross-SCA Pooling:
   - Verify that stamps from all 18 SCAs are pooled into global `bright`, `medium`, `faint` collections before composite canvas assembly.
   - Verify that all 3 tiers are populated (140 total stars across 18 SCAs: 12 B, 39 M, 89 F).
   - Check derived scale factors: $k_{\text{FM}} \approx 0.194$, $k_{\text{MB}} \approx 0.026$.
3. FITS Serialization Architecture:
   - Inspect `serialize_composite_epsf_fits` and the generated composite FITS file `output/run_all/roman_epsf_composite.fits`:
     * HDU 0: PRIMARY (float32 2D ePSF model, unit sum = 1.0)
     * HDU 1: COVERAGE (int32 ImageHDU, star count per pixel)
     * HDU 2: RADIAL_PROFILES (BinTableHDU, 1D profiles)
     * HDU 3: DETECTOR_SUMMARY (BinTableHDU, 18 rows of per-detector stats)
   - Verify header card compatibility: all keywords MUST be $\le 8$ characters, emitting zero `HIERARCH` warnings.
   - Verify optical metadata: `BASE_ANG`, `DET_OFF`, `PA_APER`, `NET_ROT`, `SCALE_FM`, `SCALE_MB`, `NDET`, `NSTARS`.
4. CLI Run Subcommand:
   - Verify `romanepsf run` accepts `--input-dir`, `--catalog`, `--config`, `--output-dir`, `--canvas-size`, `--device`, `--detectors`, `--num-workers`.
5. Test & Command Verification:
   - Run unit & e2e tests.
   - Run live `romanepsf run --canvas-size 1025 --output-dir output/run_all` and check memory and execution time.

Deliver your verdict: **APPROVE** or **REQUEST_CHANGES** with concrete evidence in `handoff.md`, and send a message with the verdict.
