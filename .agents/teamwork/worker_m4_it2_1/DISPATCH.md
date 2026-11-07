## 2026-11-07T01:56:43Z

You are worker_m4_it2_1, an implementation worker.
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_it2_1/

MANDATORY FIRST STEP: Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing any work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m4_2/handoff.md (review findings that triggered changes)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_1/handoff.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_1/proposed_page6_remediation.patch
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_1/blueprint_page6_residuals.py
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_2/handoff.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_2/blueprint_page7_metrics.py
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_3/handoff.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_3/report_remediation_p8_p4_p2.patch
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_3/blueprint_page8_benchmarks.py

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Write Ownership:
You own exclusively:
- `src/romanepsf/report.py` and `src/report.py`
- `src/romanepsf/validation.py` and `src/validation.py`
- Any related unit tests in `tests/unit/test_report.py` and `tests/unit/test_validation.py`

Your Implementation Tasks:
1. Remediate `src/romanepsf/report.py`:
   - Page 6 (`plot_page_subtraction_residuals`): Apply the authentic 5-panel residual maps blueprint from `explorer_m4_it2_1`. Dynamically load real observed stars, real forward models, and real residual/norm_res/frac_res arrays from `output/validation/residual_*.fits` or `validation_results.star_results`. Display real header parameters (`MAG`, `FLXSCALE`, `DX`, `DY`, `CHI2_NU`). Eliminate all `np.random` calls and hardcoded `tiers_info`. Include clean fallback for minimal test runs.
   - Page 7 (`plot_page_residual_metrics`): Apply the empirical radial residual profiles blueprint from `explorer_m4_it2_2`. Extract and plot real empirical radial curves $\mu_{frac}(r)$ and $\text{RMS}_{frac}(r)$ from validation residuals. Plot authentic 12-spike azimuthal scan from real bright star data at $r=50$ px. Resolve table contradiction: derive status dynamically from `zone_summary[z]['status']`, set unambiguous governing spec headers, and add explanatory note for core saturation. Eliminate all `np.random` calls.
   - Page 8 (`plot_page_performance_benchmarks`): Apply the empirical benchmark blueprint from `explorer_m4_it2_3`. Read authentic execution times and memory from HDU 3 (`DETECTOR_SUMMARY`) of composite FITS, and dynamic summary table. Eliminate all `np.random` calls.
   - Page 4 (`plot_page_radial_profiles`): Fix text placement by anchoring at `y=0.86, va="top"`, eliminating header collision.
   - Page 2 & `ReportDataBundle`: Harmonize star census loading across all 18 detectors so 140 stars (89 Faint, 39 Medium, 12 Bright) display consistently.
2. Remediate `src/romanepsf/validation.py`:
   - Apply localized fixes from `explorer_m4_it2_2`: model-aware Poisson error variance to prevent negative ringing noise collapse, exclude negative spline ringing pixels from $\chi_\nu^2$, and use `copy.deepcopy` for `repr_metrics` so star 0 is not aliased.
3. Verify zero occurrences of `np.random` in `src/romanepsf/report.py` for report rendering.
4. Execute verification commands using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:
   - Run unit tests: `python -m pytest tests/unit/ -v`
   - Run e2e tests: `python -m pytest tests/e2e/ -v`
   - Run live CLI validation: `python -m romanepsf.cli validate --model output/run_all/roman_epsf_composite.fits --output-dir output/validation`
   - Run live CLI report: `python -m romanepsf.cli report --results-dir output/run_all --output-pdf output/report.pdf`
   - Verify `output/report.pdf`: 8 pages, size > 1 MB, header `%PDF-`.
5. Write a comprehensive handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_it2_1/handoff.md`.
6. Send a message to the orchestrator upon completion.
