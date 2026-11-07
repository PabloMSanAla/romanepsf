# DISPATCH: explorer_m4_it4_2

## Task
Formulate and verify the blueprint patch for Page 4 radial profiles when tier flux columns are missing from HDU 2 in `plot_page_radial_profiles` in `src/romanepsf/report.py`.

## Background & Bug Vector
In `src/romanepsf/report.py` (lines 590–607):
When `df_p` lacks `FLUX_FAINT`, `f_faint = df_p.get("FLUX_FAINT", pd.Series(np.nan)).values` returns an array of size 1. Boolean condition `(r_px <= 25.0)` has size $N_{\rm rad}$. Slicing `f_faint[mask_f]` crashes with:
`IndexError: boolean index did not match indexed array along axis 0; size of axis is 1 but size of corresponding boolean axis is len(r_px)`

## Mitigation Blueprint
Match the fallback array length to `len(r_px)`:
```python
n_r = len(r_px)
f_faint = df_p["FLUX_FAINT"].values if "FLUX_FAINT" in df_p else np.full(n_r, np.nan)
f_med = df_p["FLUX_MED_SCALED"].values if "FLUX_MED_SCALED" in df_p else np.full(n_r, np.nan)
f_bright = df_p["FLUX_BRIGHT_SCALED"].values if "FLUX_BRIGHT_SCALED" in df_p else np.full(n_r, np.nan)
```

## Inputs
- Production File: `src/romanepsf/report.py`
- Failure Report: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m4_it3_1/handoff.md`
- Stress Test Suite: `tests/adversarial_novel_edgecase_stress.py`
- Authoritative User Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`

## Instructions
1. Read `ORIGINAL_REQUEST.md` and `challenger_m4_it3_1/handoff.md`.
2. Inspect `src/romanepsf/report.py` lines 580–620.
3. Formulate and test the patch blueprint against `tests/adversarial_novel_edgecase_stress.py -k "tier_flux"`.
4. Produce a patch file and write a 5-component report in `handoff.md`.

## 2026-11-07T05:25:26Z
You are explorer_m4_it4_2. Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it4_2/

Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing anything else.
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it4_2/DISPATCH.md for your assigned task.

Investigate the Page 4 missing tier flux columns bug in `plot_page_radial_profiles` in `src/romanepsf/report.py`.
Design and test the array length matching patch against `tests/adversarial_novel_edgecase_stress.py -k "tier_flux"`.
Write a 5-component handoff report in `handoff.md` and notify the parent orchestrator via send_message.
Use Python environment: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python
