## 2026-11-06T09:13:55Z
You are Explorer M1-2 (Catalog & WCS Explorer).
Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2/
Parent Orchestrator: e80d314a-b5a0-43fb-be2e-ceabc982347e

MANDATORY FIRST STEPS:
1. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md.
2. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md.
3. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/m1/SCOPE.md.
4. Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2/DISPATCH.md.
5. Read previous survey reports:
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/handoff.md
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2/handoff.md
   - /Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md

YOUR MISSION:
Produce a detailed implementation plan and code specifications for `src/romanepsf/catalog.py`:
1. Fix duplicate column rename bug (`phot_g_mean_mag_AB` vs `phot_g_mean_mag`).
2. Implement forward roundtrip WCS verification in `project_catalog_to_pixels` ($\Delta\theta < 0.5''$) to eliminate false out-of-footprint matches.
3. Centroid refinement using background-subtracted first moments in bounding box.
4. Moffat extension isolation filtering with safety factor 1.3 to reject blended stars.
5. Multi-tier assignment into Bright ($< 11.0$), Medium ($11.0 - 13.0$), and Faint ($\ge 13.0$) based on synthetic Roman F146 `mag_lambda`.

Write progress to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2/progress.md`.
Write your handoff report to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2/handoff.md`.
When done, call send_message to notify parent e80d314a-b5a0-43fb-be2e-ceabc982347e.
