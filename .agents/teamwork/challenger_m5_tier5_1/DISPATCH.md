# DISPATCH: challenger_m5_tier5_1

## Role
Milestone 5 Phase 2 Adversarial Coverage Hardening Challenger 1 (Core Pipeline: Loader, Catalog, Stamps, Masking, Assembly)

## Working Directory
`/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m5_tier5_1`

## Inputs
- Authoritative User Request: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`
- Source Code:
  - `src/romanepsf/loader.py`
  - `src/romanepsf/catalog.py`
  - `src/romanepsf/stamps.py`
  - `src/romanepsf/masking.py`
  - `src/romanepsf/assembly.py`
  - `src/romanepsf/profile.py`
  - `src/romanepsf/config.py`
- Existing test suites in `tests/`

## Instructions
1. Perform white-box source code analysis of the core pipeline modules (`loader.py`, `catalog.py`, `stamps.py`, `masking.py`, `assembly.py`, `profile.py`).
2. Identify untested branches, corner cases, boundary conditions, or potential edge-case failure modes (e.g., zero stars in a tier, invalid WCS headers, extreme aspect ratios, NaN pixel masks, non-square stamps, extreme mag thresholds).
3. Author a dedicated Tier 5 adversarial stress test suite in `tests/test_tier5_adversarial_core.py`.
4. Run your test suite using:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_tier5_adversarial_core.py -v`
5. Report any identified gaps, defects, or confirm robustness.
6. Write your report to `handoff.md` and send your findings back to the orchestrator via `send_message`.
