## 2026-11-07T01:32:12Z
You are challenger_m4_1, a code-executing adversarial verifier.
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m4_1/

MANDATORY FIRST STEP: Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before doing any work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m4_1/handoff.md
- /Users/pmsanch1/code/romanepsf/src/romanepsf/validation.py
- /Users/pmsanch1/code/romanepsf/tests/unit/test_validation.py

Your Mission:
Adversarially challenge and stress-test `src/romanepsf/validation.py` and the validation pipeline.
1. Design and execute adversarial stress tests targeting edge cases, pathological inputs, and numerical stability:
   - Saturated core stars: ensure saturated DQ pixels are strictly masked and do not distort scale factor fitting or bias core residual metrics.
   - Extreme Poisson/Gaussian noise, very faint stars near background limit, negative or zero flux estimates.
   - NaNs, Infs, or negative values in input data, error, or DQ arrays.
   - Off-center stars near stamp boundaries, coordinate shifts outside boundaries.
   - Pathological aperture position angles ($0^\circ, 90^\circ, 180^\circ, 359.9^\circ$).
   - Division-by-zero guards in $\chi_\nu^2$, $\mu_{frac}$, and fractional residual $F$.
   - Multi-extension FITS serialization roundtrip: write to FITS and verify all HDUs and header metadata match exactly.
2. Write your test suite in your working directory (e.g., `tests/adversarial_validation_stress.py`).
3. Execute the stress tests using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`.
4. Document all tested attack vectors, test outcomes, and code resilience in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m4_1/handoff.md`.
5. Deliver an explicit Verdict: APPROVE or REQUEST_CHANGES.
6. Send a message to the orchestrator with your verdict and findings summary.
