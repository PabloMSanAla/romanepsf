## 2026-11-07T01:19:23Z
You are worker_m4_1 (role: Milestone 4 Implementation Worker).
Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_1/
You must write your progress to /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_1/progress.md and your final report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_1/handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

MANDATORY INSTRUCTION:
Read the authoritative user request at /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before writing code.

Python Environment:
Use /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python for all execution and testing.
Local ROSALIA codebase is at /Users/pmsanch1/code/ROSALIA.

Mission:
Implement Milestone 4: Model Validation, Technical Documentation & Publication-Ready PDF Report.

Authoritative Input & Blueprints to read:
1. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/blueprint_validation.py
2. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/test_validation_blueprint.py
3. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_1/handoff.md
4. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_2/blueprint_report.py
5. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_2/test_report_blueprint.py
6. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_2/handoff.md
7. /Users/pmsanch1/code/romanepsf/docs/technical_documentation.md
8. /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_3/handoff.md

Tasks:
1. Implement `src/romanepsf/validation.py` and `src/validation.py` (backward-compatibility wrapper re-exporting public symbols):
   - Dataclasses: `StarResidualResult`, `RadialMetrics`, `ValidationResults` with `.to_dict()`, `.save_residual_fits()`, `.save_summary()`.
   - Core functions: `compute_spike_ray_mask`, `fit_star_to_model`, `compute_radial_residual_metrics`, `evaluate_epsf_validation`.
   - Support 2D subtraction residual mapping: $R = I_{\text{obs}} - I_{\text{mod}}$, normalized residual $Z = R / \sigma$, fractional residual $F = R / (I_{\text{mod}} + \epsilon_{\text{reg}})$.
   - Partitioned radial residual metrics across 4 zones:
     1. Core zone ($r < 10$ px, target $|\mu_{\text{frac}}| \le 0.05$)
     2. Transition zone ($10 \le r < 40$ px)
     3. Extended wings ($40 \le r < 200$ px, target $\chi_\nu^2 \in [0.5, 2.5]$)
     4. 12 Spike rays ($\pm 2^\circ$ angular sectors) vs off-spike background.
2. Implement `src/romanepsf/report.py` and `src/report.py` (backward-compatibility wrapper):
   - `ReportDataBundle` and modular page plotters `plot_page_title_executive`, `plot_page_star_selection`, `plot_page_spike_protection`, `plot_page_radial_profiles`, `plot_page_composite_epsf`, `plot_page_subtraction_residuals`, `plot_page_residual_metrics`, `plot_page_performance_benchmarks`.
   - `generate_publication_pdf_report(input_source, output_pdf_path, *, composite_fits_path, validation_results, cfg, dpi=300, ...) -> Path`.
   - Exactly 8 pages, publication-quality styling, `%PDF-` header, no pdflatex dependency.
3. Update `src/romanepsf/cli.py`:
   - Wire up `validate` subcommand and `report` subcommand.
4. Author Unit Tests:
   - `tests/unit/test_validation.py` (incorporating tests from `explorer_m4_1`)
   - `tests/unit/test_report.py` (incorporating tests from `explorer_m4_2`)
5. Verify Build & Tests:
   - Run `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
   - Run `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v`
6. Live Execution Verification:
   - Run validation:
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli validate --model output/run_all/roman_epsf_composite.fits --output-dir output/validation`
   - Run report generation:
     `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m romanepsf.cli report --results-dir output/run_all --output-pdf output/report.pdf`
   - Verify `output/report.pdf` exists, has size > 1 MB, and has exactly 8 pages.
7. Deliver comprehensive `handoff.md` and message the orchestrator when finished.
