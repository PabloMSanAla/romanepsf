# BRIEFING — 2026-11-06T10:57:00Z

## Mission
Perform adversarial and quality review for Milestone 2 (Features 9-19): spike protection, residual filtering, dual-prior protection mask fusion, 2D overlap scaling & cosine-taper partition-of-unity assembly, unit flux normalization, non-hollow core, test suite verification, and integrity checks.

## 🔒 My Identity
- Archetype: reviewer_and_adversarial_critic
- Roles: reviewer, critic
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_2
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: Milestone 2
- Instance: 2 of 2

## 🔒 Key Constraints
- Review-only — do NOT modify implementation code
- Actively check for integrity violations (hardcoded values, facade logic, shortcuts, fabricated verifications)
- Verify 6-fold spike angle base angles [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] adjusted for PA and offset (-9.70 deg)
- Verify directional morphological line filtering on Moffat residuals
- Verify dual-prior protection mask fusion ensures spikes are preserved without being masked
- Verify dual-radius overlap scaling (no IndexError) and 2D cosine-taper partition-of-unity blending without circular averaging
- Verify unit flux normalization (sum = 1.0) and non-hollow core
- Run pytest tests/unit/ -v and pytest tests/e2e/ -v using /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python
- Produce formal handoff report and send verdict to parent orchestrator

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: not yet

## Review Scope
- **Files reviewed**:
  - `src/romanepsf/masking.py`, `src/masking.py`
  - `src/romanepsf/stamps.py`, `src/stamps.py`
  - `src/romanepsf/profile.py`, `src/profile.py`
  - `src/romanepsf/assembly.py`, `src/assembly.py`
  - `tests/unit/test_assembly.py`, `tests/unit/test_masking.py`, `tests/unit/test_profile.py`, `tests/unit/test_stamps.py`
  - `tests/e2e/test_tier1_features.py`, `tests/e2e/test_tier2_boundaries.py`, `tests/e2e/test_tier3_combinations.py`, `tests/e2e/test_tier4_scenarios.py`
  - `worker_m2_1/handoff.md`

## Review Checklist
- **Items reviewed**:
  - 6-fold spike angles & PA adjustment: VERIFIED
  - Directional morphological filtering on Moffat residuals: VERIFIED
  - Dual-prior spike protection fusion: VERIFIED
  - Dual-radius overlap scaling (no IndexError): VERIFIED
  - 2D cosine-taper partition-of-unity blending: VERIFIED
  - Unit flux normalization & non-hollow core: VERIFIED
  - Real Level 2 WFI01 commissioning assembly: FAILED (k_mb collapsed to 1.0, 25x flux surge step discontinuity)
  - Multi-detector tier robustness: FAILED (ValueError on detectors like WFI02 with missing bright tier)
- **Verdict**: REQUEST_CHANGES
- **Integrity Violations**: None found (genuine implementations, no hardcoded cheating).

## Attack Surface
- **Hypotheses tested**:
  1. Does `assemble_composite_extended_psf` correctly calculate `k_mb` on real commissioning Level 2 WFI01 data? -> FAILED: `k_mb` evaluated to `1.0` (unscaled) due to unmasked `0.0` pixels from sparse coverage driving annular median to zero.
  2. Does the composite ePSF on WFI01 maintain physical monotonicity? -> FAILED: Artificial 25x flux surge from $r=30$ to $r=48$ px.
  3. Does `assemble_composite_extended_psf` survive detectors with empty tiers (e.g. WFI02 with 0 bright stars)? -> FAILED: Crashes with `ValueError: Cannot stack an empty stamp list`.
  4. Does contaminant masking in `masking.py` preserve stellar wings? -> FAILED: Up to 70% of halo pixels in medium stars are falsely masked as contaminants.

## Key Decisions Made
- Issued gate verdict `REQUEST_CHANGES` with clear fixes and reproduction steps.

## Artifact Index
- `.agents/teamwork/reviewer_m2_2/DISPATCH.md` — recorded dispatch message
- `.agents/teamwork/reviewer_m2_2/BRIEFING.md` — persistent working memory
- `.agents/teamwork/reviewer_m2_2/progress.md` — liveness heartbeat
- `.agents/teamwork/reviewer_m2_2/handoff.md` — formal review handoff report
