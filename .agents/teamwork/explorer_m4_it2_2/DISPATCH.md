## 2026-11-07T01:43:13Z

You are explorer_m4_it2_2, a technical exploration agent.
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_2/

MANDATORY FIRST STEP: Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing any work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m4_2/handoff.md (CRITICAL: Read Finding 2 on lines 95-125)
- /Users/pmsanch1/code/romanepsf/src/romanepsf/report.py (specifically plot_page_residual_metrics, lines 812-935)
- /Users/pmsanch1/code/romanepsf/src/romanepsf/validation.py
- /Users/pmsanch1/code/romanepsf/output/validation/validation_summary.json

Your Mission:
Design an authentic, non-facade remediation blueprint for Page 7 (Radial Residual Metrics & Consistency) in `src/romanepsf/report.py` and resolve the $\chi_\nu^2$ / fractional residual contradiction in `validation.py`.
1. Address Page 7 Fabricated Profiles:
   - `plot_page_residual_metrics` currently fabricates radial profiles $\mu_{frac}(r)$ and $\text{RMS}_{frac}(r)$ using `np.random.seed(101)` and synthetic exponential equations.
   - Design a method to extract and plot real empirical radial residual curves $\mu_{frac}(r)$ and $\text{RMS}_{frac}(r)$ computed across annular bins from the real residual maps (`output/validation/residual_*.fits` or `validation_results`).
   - Also plot the genuine azimuthal profile around the 12 diffraction spikes from real residual data.
2. Address Page 7 Contradictory Table:
   - In `plot_page_residual_metrics`, the table hardcodes `"PASSED"` next to `Reduced χ² = 141711.41` alongside `Ceiling Spec: < 1.20`.
   - Investigate why `core_chi2` reports $141,711$ in `validation_summary.json` (Hint: check if saturated core pixels DQ=2 on bright stars are dominating the unweighted $\chi_\nu^2$ or if `err_map` in cores needs proper masking, and check how `core_stats` is aggregated across tiers).
   - Ensure the summary table derives its `Verification` status dynamically from `zone_summary[z]['status']`.
   - Update column headers and specifications so the criteria are unambiguous (e.g. $|\mu_{frac}| \le 0.05$ on unsaturated stars, transition continuity, wings $\chi_\nu^2$, spike peak residual $\le 10\%$).
3. Eliminate all `np.random` calls from `plot_page_residual_metrics`.
4. Write a self-contained blueprint script (e.g. `blueprint_page7_metrics.py`) in your working directory and test it against real validation outputs using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`.
5. Write a complete handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it2_2/handoff.md`.
6. Send a message to the orchestrator with your findings and blueprint location.
