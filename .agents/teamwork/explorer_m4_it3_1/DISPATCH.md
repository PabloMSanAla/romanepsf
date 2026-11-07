## 2026-11-07T04:53:15Z
You are explorer_m4_it3_1, a technical exploration agent.
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_1/

MANDATORY FIRST STEP: Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing any work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m4_it2_1/handoff.md (CRITICAL: Read Obs 1.2.1 and Obs 1.2.2)
- /Users/pmsanch1/code/romanepsf/src/romanepsf/report.py (specifically load_tier_residual_data, lines 860-930)
- /Users/pmsanch1/code/romanepsf/tests/adversarial_remediated_report_stress.py

Your Mission:
Design a precise, defensive blueprint patch for Page 6 FITS ingestion in `load_tier_residual_data`:
1. Root cause: In `src/romanepsf/report.py`, lines 874-901 execute `with fits.open(best_f) as hdul:` and access HDUs `['OBSERVED', 'MODEL', 'RESIDUAL', 'NORM_RES', 'FRAC_RES']` without exception handling. Corrupted FITS files raise `OSError: No SIMPLE card found`, and incomplete FITS files raise `KeyError: Extension 'OBSERVED' not found`, crashing before Strategy 3 (deterministic mock fallback) can execute.
2. Solution: Wrap lines 874-901 in a `try...except (OSError, KeyError, Exception) as exc:` block. If reading `best_f` fails or if any required HDU is missing or corrupt, log a warning and let execution fall through cleanly to Strategy 3 (deterministic mock fallback).
3. Test your blueprint patch against:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/adversarial_remediated_report_stress.py -k "vector2" -v`
4. Write your blueprint and verification findings in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_it3_1/handoff.md`.
5. Send a message to the orchestrator with your findings.
