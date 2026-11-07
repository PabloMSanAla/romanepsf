## 2026-11-07T00:03:25Z
You are Challenger 1 for Milestone 2 Iteration 2 of the Roman Extended PSF (ePSF) pipeline project.
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m2_it2_1
Project root: /Users/pmsanch1/code/romanepsf
Python executable: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python

MANDATORY FIRST STEP:
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m2_it2_1/handoff.md

Your task:
Adversarially stress-test `src/romanepsf/masking.py` and `src/masking.py`:
1. Design an adversarial test harness covering:
   - Extreme dynamic range cutouts: background sky from -10 to +1000 MJy/sr, saturated stars with 10^5 dynamic range.
   - Non-standard cutouts: asymmetric, non-square, tiny cutouts (e.g. 11x11), huge cutouts (1001x1001).
   - Radial threshold scaling: verify $\sigma(r) = \sigma_0(1 + A \exp(-r/r_0))$ behavior under boundary conditions ($r \to 0$, $r \to \infty$, negative values, zero variance).
   - Dual-prior spike protection: ensure diffraction spikes along theoretical angles $[23.55, 55.29, 80.25, 118.65, 142.88, 178.07]^\circ - 9.70^\circ$ are never masked as contaminants even in high-contrast noise.
   - Contaminant detection: ensure actual off-axis point sources ($>5\sigma$ above local background) at various radii ($r=10, 25, 50, 100$ px) are accurately masked without spreading into the central core or spikes.
2. Execute your adversarial test suite against the codebase.
3. Formulate an objective verdict: `APPROVE` (all adversarial tests pass or reveal robust handling) or `REQUEST_CHANGES` (found critical failure).
4. Deliver a structured handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m2_it2_1/handoff.md`.
Notify the orchestrator with send_message upon completion.
