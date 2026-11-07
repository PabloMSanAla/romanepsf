## 2026-11-07T01:43:21Z
You are explorer_m4_it2_3, a technical exploration agent.
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_3/

MANDATORY FIRST STEP: Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing any work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m4_2/handoff.md (CRITICAL: Read Findings 3, 4, 5 on lines 126-153)
- /Users/pmsanch1/code/romanepsf/src/romanepsf/report.py (specifically plot_page_radial_profiles line 613-632, plot_page_performance_benchmarks line 952-993, and ReportDataBundle line 144-158)
- /Users/pmsanch1/code/romanepsf/output/run_all/roman_epsf_composite.fits

Your Mission:
Design an authentic remediation blueprint for Page 8 (Empirical Benchmarks), Page 4 (Typography Overlap Fix), and Page 2 (Star Census Harmonization) in `src/romanepsf/report.py`.
1. Address Page 8 Fabricated Benchmarks:
   - `plot_page_performance_benchmarks` currently generates per-detector RSS memory usage using `np.random.uniform(0.05, 0.24, 18)`.
   - In `output/run_all/roman_epsf_composite.fits`, HDU 3 (`DETECTOR_SUMMARY`) contains the table of all 18 detectors processed during the run (`DETECTOR`, `N_BRIGHT`, `N_MED`, `N_FAINT`, `EXEC_SEC`, `PEAK_RSS_MB`).
   - Modify `plot_page_performance_benchmarks` to read real per-detector execution times and peak memory footprints from HDU 3 (`DETECTOR_SUMMARY`), or fallback to deterministic measured benchmark constants from the 18-detector execution profile.
   - Eliminate all `np.random` calls from `plot_page_performance_benchmarks`.
2. Address Page 4 Typography Overlap:
   - In `plot_page_radial_profiles`, the body text in the "CROSS-TIER OVERLAP & INVARIANTS" card collides with and obscures the box title because vertical alignment is omitted (defaults to baseline/bottom).
   - Set `y=0.86, va="top"` so the body text cleanly and legibly flows below the title header.
3. Address Page 2 Star Census Harmonization:
   - In `ReportDataBundle` (lines 144-158), loading `output/*stars_tiered.csv` only finds 13 detector CSVs (100 stars) because single-detector runs were saved there, whereas the full 18-detector run in `output/run_all/` or HDU 3 contains all 140 stars (89 Faint, 39 Medium, 12 Bright).
   - Ensure `ReportDataBundle` preferentially loads the full-focal-plane catalog (e.g. from `output/run_all/` or cross-matching all 18 detector files) so Page 2 displays the true 140-star census consistent with Page 1.
4. Write a self-contained blueprint script (e.g. `blueprint_page8_benchmarks.py`) in your working directory and test it against `output/run_all/roman_epsf_composite.fits` using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`.
5. Write a complete handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_3/handoff.md`.
6. Send a message to the orchestrator with your findings and blueprint location.
