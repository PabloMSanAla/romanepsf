# Dispatch: Explorer Survey 1 (Data & Catalog)

## Objective
Thoroughly inspect the Roman simulated commissioning Level 2 data and source catalog to determine file structures, metadata, detector coverage, catalog columns, star counts, and brightness distributions.

## Reference Files
- User Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- Data Directory: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/`
- Catalog File: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv`
- Python Environment: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`

## Output Requirements
Produce a comprehensive handoff report at `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/handoff.md`.


## 2026-11-06T08:54:17Z
You are Explorer 1 (Data & Catalog Explorer).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/
Your parent orchestrator is: e80d314a-b5a0-43fb-be2e-ceabc982347e

MANDATORY FIRST STEP: Read /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md.

YOUR MISSION:
Thoroughly inspect the Roman simulated commissioning Level 2 data and source catalog to map out all data structures, metadata, detector files, catalog columns, star counts, and brightness distributions.

Investigate:
1. Directory contents of /Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/
   - Check all 18 detector files (`*asdf`), file sizes, naming patterns, file integrity.
2. ASDF structure and metadata:
   - Use Python environment `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python` to inspect the ASDF files.
   - What is the ASDF tree structure? (roman_datamodels, asdf, etc.)
   - Where are data arrays, error/variance arrays, DQ (data quality) arrays stored?
   - What are the image shapes (e.g. 4088x4088 or 4096x4096)?
   - Where are WCS, pointing, and aperture position angle (V3PA, PA_APER, or PA_V3) stored?
   - What are the saturation flags / saturation levels in the Level 2 data?
3. Source Catalog:
   - File: /Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv
   - Inspect columns, header, units.
   - How are coordinates specified (RA, Dec, pixel x, y)? Are detector IDs included or mapped via WCS?
   - Magnitude and flux distributions: What filters are present (e.g., F184, F158, etc.)?
   - Total star counts, counts per detector, dynamic range (brightest vs faintest stars).
   - What are suitable magnitude/flux thresholds for partitioning into Bright, Medium, and Faint star tiers?
   - Are there saturation issues for bright stars? What radii are saturated?

Deliverables:
- Keep /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/progress.md updated.
- Write your final structured handoff report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/handoff.md with concrete findings, numbers, schemas, and recommendations.
- When done, call send_message to notify parent e80d314a-b5a0-43fb-be2e-ceabc982347e that your handoff is ready.
