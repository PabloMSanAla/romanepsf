# DISPATCH: explorer_m4_it4_3

## Task
Formulate and verify the blueprint patch for Page 2 census column handling in `plot_page_star_selection`, Page 7 `results_dir` None handling in `plot_page_residual_metrics`, and synthesize/verify the unified patch across all 23 tests in `tests/adversarial_novel_edgecase_stress.py`.

## Background & Bug Vectors
1. **Page 2 Census Columns**:
   In `src/romanepsf/report.py` (lines 404–411), direct indexing `row["N_FAINT"]` crashes with `KeyError: 'N_FAINT'` when `detector_summary` contains a partial table.
   Fix:
   ```python
   det_id = str(row.get("DETECTOR", f"WFI{_ + 1:02d}"))
   nf = int(row.get("N_FAINT", 0))
   nm = int(row.get("N_MEDIUM", 0))
   nb = int(row.get("N_BRIGHT", 0))
   nt = int(row.get("N_TOTAL", nf + nm + nb))
   pa = float(row.get("PA_APER_DEG", -110.0))
   px = float(row.get("PIXSCALE", 0.11))
   ```
2. **Page 7 results_dir None handling**:
   In line 1438:
   ```python
   results_dir = Path(getattr(data, "results_dir", None) or "output")
   ```
3. **Unified Verification**:
   Combine the patches from all 3 explorers and verify that all 23 tests in `tests/adversarial_novel_edgecase_stress.py` pass 100%.

## Inputs
- Production File: `src/romanepsf/report.py`
- Failure Report: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m4_it3_1/handoff.md`
- Stress Test Suite: `tests/adversarial_novel_edgecase_stress.py`
- Authoritative User Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`

## Instructions
1. Read `ORIGINAL_REQUEST.md` and `challenger_m4_it3_1/handoff.md`.
2. Inspect `src/romanepsf/report.py` lines 400–420 and 1430–1445.
3. Formulate and test the patch blueprint against `tests/adversarial_novel_edgecase_stress.py`.
4. Produce a unified patch file and write a 5-component report in `handoff.md`.

## 2026-11-07T05:25:30Z
You are explorer_m4_it4_3. Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it4_3/

Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing anything else.
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it4_3/DISPATCH.md for your assigned task.

Investigate the Page 2 census columns bug in `plot_page_star_selection` and Page 7 `results_dir` None handling in `plot_page_residual_metrics` in `src/romanepsf/report.py`.
Synthesize and verify the unified patch against all 23 tests in `tests/adversarial_novel_edgecase_stress.py`.
Write a 5-component handoff report in `handoff.md` and notify the parent orchestrator via send_message.
Use Python environment: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python
