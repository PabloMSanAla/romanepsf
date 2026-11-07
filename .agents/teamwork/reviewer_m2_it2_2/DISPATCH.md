## 2026-11-07T00:03:18Z
You are Reviewer 2 for Milestone 2 Iteration 2 of the Roman Extended PSF (ePSF) pipeline project.
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_it2_2
Project root: /Users/pmsanch1/code/romanepsf
Python executable: /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python

MANDATORY FIRST STEP:
Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting work.
Also read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_2/handoff.md (the review that raised Defects 1, 2, 3)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m2_it2_1/handoff.md

Your task:
Perform empirical verification of the 3 defect resolutions on actual Roman simulated commissioning Level 2 data:
1. Defect 1 (WFI01 $k_{\text{MB}}$ collapse & flux surge):
   Run WFI01 data (`r0108301001001001001_0001_wfi01_f146_cal.asdf`) through catalog projection, tier assignment, stamp extraction, and assembly.
   Verify that $0.010 < k_{\text{MB}} < 0.100$ and that the composite ePSF exhibits strictly monotonic decay across [30, 48] px (no 25x flux surge).
2. Defect 2 (False halo contaminant over-masking):
   Inspect medium star stamps extracted from WFI01.
   Verify that false contaminant masking across the overlap region [22, 45] px is < 5% (previously ~70%), and that off-axis companions remain detected.
3. Defect 3 (Missing bright tier on WFI02):
   Run WFI02 data (`r0108301001001001001_0001_wfi02_f146_cal.asdf`) through assembly.
   Verify that 2-tier assembly executes cleanly without `ValueError: Cannot stack an empty stamp list`, producing a valid normalized (501, 501) ePSF canvas with $k_{\text{MB}} = \text{None}$.
4. Run full test suite:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v`
5. Formulate an objective verdict: `APPROVE` or `REQUEST_CHANGES`.
6. Deliver a structured handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_it2_2/handoff.md`.
Notify the orchestrator with send_message upon completion.
