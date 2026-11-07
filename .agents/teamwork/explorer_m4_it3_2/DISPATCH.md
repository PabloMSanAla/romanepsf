# Explorer M4_It3_2 Working Directory
## 2026-11-07T04:53:26Z
[Message] sender=e80d314a-b5a0-43fb-be2e-ceabc982347e priority=MESSAGE_PRIORITY_HIGH content=You are explorer_m4_it3_2, a technical exploration agent.
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_2/

MANDATORY FIRST STEP: Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing any work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m4_it2_1/handoff.md (CRITICAL: Read Obs 1.2.3 and Obs 1.2.4)
- /Users/pmsanch1/code/romanepsf/src/romanepsf/report.py (specifically extract_empirical_azimuthal_profile lines 1330-1375 and plot_page_residual_metrics lines 1545-1600)
- /Users/pmsanch1/code/romanepsf/tests/adversarial_remediated_report_stress.py

Your Mission:
Design a precise, defensive blueprint patch for Page 7 in `src/romanepsf/report.py`:
1. Root cause 1 (Azimuthal Scan FITS crash): In `extract_empirical_azimuthal_profile`, lines 1336-1374 execute `with fits.open(bright_fits)` without exception handling. Corrupted bright residual FITS files raise `OSError: No SIMPLE card found` before the existing `epsf_canvas` fallback at line 1375 can execute.
   Solution: Wrap lines 1336-1374 in a `try...except (OSError, KeyError, Exception) as exc:` block so that corruption falls through cleanly to line 1375.
2. Root cause 2 (Null Metric Formatting crash): In `plot_page_residual_metrics`, formatting dictionary values with `f"{val:+.4f}"` (e.g. `core_dict.get('mu_frac', 0.0)`) raises `TypeError` when the JSON summary contains `null` because `get('mu_frac', 0.0)` returns `None` (not `0.0`).
   Solution: Implement defensive null-coalescing for metric floats:
   ```python
   def _safe_float(d, key, default):
       val = d.get(key)
       return default if val is None else float(val)
   ```
3. Test your blueprint patch against:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/adversarial_remediated_report_stress.py -k "vector3" -v`
4. Write your blueprint and verification findings in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_2/handoff.md`.
5. Send a message to the orchestrator with your findings.
