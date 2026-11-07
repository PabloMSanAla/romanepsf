## 2026-11-06T11:00:09Z
You are Explorer 1 for Milestone 2 Iteration 2 (explorer_m2_it2_1).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_1

MANDATORY: First read the authoritative user request:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md

Next, read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/m2/GATE_STATUS.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_2/handoff.md (specifically Finding 1: Critical Defect at assembly.py:417-419)

Your mission:
Analyze Defect 1:
In `src/romanepsf/assembly.py:417-419`:
`r_f, prof_f, _ = measure_radial_profile_1d(psf_faint, device=device)`
`r_m, prof_m, _ = measure_radial_profile_1d(psf_medium, device=device)`
`r_b, prof_b, _ = measure_radial_profile_1d(psf_bright, device=device)`
Omitting `mask=(cov == 0)` causes unobserved pixels (filled with 0.0) to dominate the median in sparse tiers (e.g. WFI01 with 2 medium stars), driving `prof_m` to 0.0 in $[22, 45]$ px. This forces `k_mb` to silently fall back to `1.0`, creating a catastrophic 25x (+2377%) unphysical flux surge at $r=30..48$ px.
Passing `mask=(cov == 0)` fixes this and recovers `k_mb = 0.0179` with smooth monotonic decay.

Formulate the exact code fix in `assembly.py` and `src/assembly.py`, and design regression test assertions ensuring `k_mb < 0.1` and monotonic decay on WFI01.
Deliver a comprehensive handoff report in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_1/handoff.md` and notify the parent orchestrator via send_message.
