# BRIEFING — 2026-11-06T10:25:00Z

## Mission
Investigate and blueprint the implementation of `src/romanepsf/masking.py` for Milestone 2 (Features 12, 13, 14: spike geometry, directional morphological filtering, dual-prior protection mask fusion, contaminant masking).

## 🔒 My Identity
- Archetype: Explorer
- Roles: Read-only investigation, synthesis
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_2
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: Milestone 2

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Deliver comprehensive handoff report in `.agents/teamwork/explorer_m2_2/handoff.md`
- Report back via `send_message` to parent `e80d314a-b5a0-43fb-be2e-ceabc982347e`
- Only write metadata/reports in `.agents/teamwork/explorer_m2_2/`

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: 2026-11-06T10:25:00Z

## Investigation State
- **Explored paths**:
  - `ORIGINAL_REQUEST.md`, `PROJECT.md`
  - `src/romanepsf/config.py` (SpikesConfig, SpikesSection)
  - `configs/default.yaml`
  - `src/masking.py` (existing implementation under `src/`)
  - `src/stamps.py`, `src/profile.py`, `src/assembly.py`
  - `tests/e2e/test_tier1_features.py` (F11, F12, F13, F14)
  - `tests/e2e/test_tier2_boundaries.py` (B10, B11, B12)
  - `tests/e2e/test_tier3_combinations.py` (Pairs 6, 7, 8)
  - `tests/e2e/test_tier4_scenarios.py` (S3.4)
  - `ROSALIA/rosalia/superback.py`, `psf.py`
- **Key findings**:
  1. Base spike angles are `[23.55, 55.29, 80.25, 118.65, 142.88, 178.07]`. 6 struts yield 12 radial rays via $\theta + 180^\circ$.
  2. Detector frame offset is $\Delta\theta_{\text{det}} \approx -9.70^\circ$. Total rotation is $pa_{\text{aperture}} + \Delta\theta_{\text{det}}$.
  3. `src/romanepsf/masking.py` does not exist yet; currently `src/masking.py` exists directly under `src/` but with legacy parameter signature that crashes when called with `SpikesConfig`.
  4. Interface contract requires unifying `mask_contaminants_with_spikes_protected(stamp, dq_mask, pa_aperture, cfg: SpikesConfig)` while retaining backward compatibility with legacy kwargs (`pa_offset_deg`, `core_protection_radius_px`, `detection_sigma`).
  5. Directional morphological filtering requires background noise estimation, radial span $\ge 15$ px, linearity verification, core suppression ($r < 5$ px), and zero-variance robustness.
  6. Dual-prior fuses geometric cone mask, morphological ridge detections, and stellar core protection, strictly enforcing `final_mask & protected == False` for valid stellar pixels while masking companion stars.
- **Unexplored areas**: None for M2 masking scope.

## Key Decisions Made
- Architecture blueprint: Implement canonical module at `src/romanepsf/masking.py` and shim at `src/masking.py`.
- Interface design: Dual-signature parameter resolution supporting both `(stamp, dq_mask, pa_aperture, cfg)` and `(stamp, dq_mask, pa_offset_deg, ...)`.
- Test suite: Complete unit test design for `tests/unit/test_masking.py` covering 28 test cases across 6 test classes.

## Artifact Index
- DISPATCH.md — Dispatch log
- BRIEFING.md — Situational awareness
- progress.md — Liveness heartbeat
- handoff.md — Comprehensive handoff report
