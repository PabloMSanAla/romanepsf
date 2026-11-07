## 2026-11-07T00:03:33Z
You are Challenger 2 for Milestone 2 Iteration 2 of the Roman Extended PSF (ePSF) pipeline project.
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m2_it2_2
Project root: /Users/pmsanch1/code/romanepsf
Python executable: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python

MANDATORY FIRST STEP:
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m2_it2_1/handoff.md

Your task:
Adversarially stress-test `src/romanepsf/assembly.py` and `src/assembly.py`:
1. Design an adversarial test harness covering:
   - All multi-tier permutations:
     * 3-tier: Faint + Medium + Bright
     * 2-tier: Faint + Medium (e.g. WFI02)
     * 2-tier: Medium + Bright
     * 2-tier: Faint + Bright (skipping Medium)
     * 1-tier: Faint only, Medium only, Bright only
     * 0-tier: All empty (must raise ValueError with informative message)
   - Edge cases in tensor stacking:
     * High NaN fraction (up to 99% masked/NaNs)
     * Single stamp per tier, large count (100+ stamps)
     * Integer dtypes, float16/float64 dtypes
   - Edge cases in dual-radius scale matching:
     * Coordinate mismatches, sub-pixel rounding offsets, non-overlapping radii
   - Edge cases in canvas embedding and blending:
     * Even target dimensions (e.g. 500, 1024), odd target dimensions (501, 1025)
     * Output size smaller than stamp size, output size much larger than stamp size
   - Physical invariants:
     * Integrated sum of ePSF canvas must equal 1.0 (within float precision)
     * Non-negativity: no negative flux values
     * Strict radial monotonicity in cross-tier overlap regions when noise is zero
2. Execute your adversarial test suite against the codebase.
3. Formulate an objective verdict: `APPROVE` or `REQUEST_CHANGES`.
4. Deliver a structured handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m2_it2_2/handoff.md`.
Notify the orchestrator with send_message upon completion.
