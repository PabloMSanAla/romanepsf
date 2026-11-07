# BRIEFING — 2026-11-06T09:21:00Z

## Mission
Produce a detailed implementation plan and code specifications for `src/romanepsf/catalog.py` covering column renames, roundtrip WCS verification, centroid refinement, Moffat isolation filtering, and multi-tier star assignment.

## 🔒 My Identity
- Archetype: Explorer
- Roles: Catalog & WCS Explorer
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: M1 (Catalog & Preprocessing)

## 🔒 Key Constraints
- Read-only investigation — do NOT modify source code directly
- Output detailed implementation plan and code specifications in handoff.md
- Adhere to Teamwork file workspace convention (.agents/teamwork/explorer_m1_2/)

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: 2026-11-06T09:21:00Z

## Investigation State
- **Explored paths**:
  - Commissioning catalog `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv` (198,802 rows, 46 columns).
  - All 18 Level 2 ASDF files in `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/` (ImageModel, 4088x4088).
  - Existing `src/catalog.py`, `src/loader.py`, `src/profile.py`, `src/stamps.py`.
  - Cached files `cache/gaia_dr3_wfi01_g20.csv` and `g22.csv`.
- **Key findings**:
  - Confirmed duplicate column bug caused when renaming `phot_g_mean_mag_AB` while `phot_g_mean_mag` exists, creating a 2D DataFrame that breaks NumPy broadcasting.
  - Confirmed naive WCS `backward_transform` yields 3 spurious stars on WFI01 with 3136" error; roundtrip verification ($\Delta\theta < 0.5''$) isolates exactly 7 stars (187 across focal plane with 50px margin, 194 with 0px margin).
  - Confirmed 18-detector star counts: 17 Bright ($<11.0$), 50 Medium ($11.0-13.0$), 127 Faint ($\ge 13.0$) based on `mag_lambda` (F146).
  - Confirmed centroid first moments require handling NaNs in saturated cores and bounding shifts to avoid divergence.
  - Confirmed Moffat isolation clearance (depth 28 mag/arcsec^2, safety factor 1.3) properly filters blended stars when prioritized by ascending magnitude.
- **Unexplored areas**: None for M1 catalog scope.

## Key Decisions Made
- Vectorized WCS projection implemented with NumPy/GWCS, processing 198k sources in ~1-2 seconds per detector.
- Sorting by magnitude (brightest first) established as canonical order for isolation filtering to guarantee primary star retention.
- Fallback mechanisms specified for centroid divergence, missing magnitude columns, and empty detector footprints.

## Artifact Index
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2/DISPATCH.md — Received orchestrator instructions
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2/progress.md — Progress heartbeat
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_2/handoff.md — Final investigation and specification report
