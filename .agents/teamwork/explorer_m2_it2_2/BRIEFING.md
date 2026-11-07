# BRIEFING — 2026-11-06T11:16:30Z

## Mission
Analyze Defect 2 in masking.py:414-424 (over-masking of legitimate stellar wings due to flat MAD threshold on sky background) and design the exact fix strategy.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_2
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: m2_it2

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Analyze Defect 2: residual masking over-masking diffuse stellar wings
- Design exact fix strategy (radial threshold scaling, morphological aspect ratio/compactness filtering, etc.)
- Deliver comprehensive handoff report in handoff.md and notify parent via send_message

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: 2026-11-06T11:16:30Z

## Investigation State
- **Explored paths**: `src/romanepsf/masking.py`, `src/romanepsf/stamps.py`, `src/romanepsf/assembly.py`, `tests/unit/test_masking.py`, real commissioning data WFI01 (`PID1083`)
- **Key findings**:
  1. Flat $3\sigma$ threshold (~0.1 MJy/sr) calculated from distant sky background in `clean_area` wipes out 85.3% to 96.0% of medium star wings in $[15, 45]$ px.
  2. Compounding bug in `fit_moffat_model`: outer 25% of truncated core fit ($r \in [26, 30]$ px) treated as sky background, creating a +1.9 MJy/sr pedestal across entire stamp and depressing `res_med` to $-1.9$ MJy/sr.
  3. Binary connected component filtering alone cannot break the bridge between an off-axis companion and the halo at flat $3\sigma$ because the intervening halo is $> 3\sigma$.
  4. Radial threshold scaling $\sigma(r) = \sigma_0(1 + A \exp(-r/r_0))$ with $A=200, r_0=15$ drops false wing masking from 96% down to 1.5% - 3.0%, reduces medium tier zero-coverage from 64.4% to 0.1%, and ensures 100% reliable detection of real companion stars.
- **Unexplored areas**: None. Both root causes mapped, verified empirically, and regression-tested.

## Key Decisions Made
- Formulate radial threshold scaling $\sigma(r) = \sigma_0 (1 + A \exp(-r/r_0))$ tailored by tier.
- Correct `fit_moffat_model` background estimation to measure from outer cutout perimeter ($r > 0.75 r_{\max}$) rather than truncated core.
- Provide complete diff patch `fix_stellar_halo_masking.patch` and unit regression tests in `handoff.md`.

## Artifact Index
- DISPATCH.md — incoming dispatch messages
- progress.md — liveness heartbeat and step-by-step progress
- handoff.md — final comprehensive 5-component report
- fix_stellar_halo_masking.patch — machine-applicable diff patch for masking.py
