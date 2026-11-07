## 2026-11-06T10:16:41Z
You are Explorer 3 for Milestone 2 (explorer_m2_3).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_3

MANDATORY: First read the authoritative user request:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md

Next, read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md (Milestone 2, Features 15, 16, 17, 18, 19)
- /Users/pmsanch1/code/romanepsf/src/profile.py, /Users/pmsanch1/code/romanepsf/src/assembly.py, and /Users/pmsanch1/code/ROSALIA

Your mission:
Investigate and blueprint the implementation of `src/romanepsf/profile.py` and `src/romanepsf/assembly.py`:
1. Strict Scientific Constraint:
   - 1D radial profiles via `profile.py` are strictly reserved for finding saturation boundaries and cross-tier scaling factors.
   - Prohibit radial averaging or circularizing the 2D PSF canvas. The synthesized model must directly capture 2D structure and 2D diffraction spikes.
2. Dual-radius overlap scaling (eliminating IndexError):
   - In `assembly.py:152`, `determine_overlap_scale_factor` has an index mismatch because `prof_inner` and `prof_outer` have different radial lengths (e.g. 40 vs 100).
   - Implement `determine_overlap_scale_factor_dual(prof_inner, prof_outer, r_inner, r_outer, r_min, r_max) -> float` taking independent radius vectors.
3. 2D Cosine-Taper Partition-of-Unity Stitching:
   - Implement smooth $C^1$ raised-cosine blending across annular intervals:
     $w(r) = 0.5 \times (1 + \cos(\pi \times (r - r_{\text{start}}) / (r_{\text{end}} - r_{\text{start}})))$
     for $r \in [r_{\text{start}}, r_{\text{end}}]$.
   - Faint-to-Medium overlap (e.g. $[10, 18]$ px) and Medium-to-Bright overlap (e.g. $[30, 48]$ px).
4. Robust Tier Tensor Stacking:
   - Sigma-clipped median stacking per tier.
5. Global unit flux normalization:
   - Unit volume normalization $\sum \text{ePSF} = 1.0$ and non-negative clipping.
6. Unit test design for `tests/unit/test_profile.py` and `tests/unit/test_assembly.py`.

Deliver a comprehensive handoff report (Observation, Logic Chain, Caveats, Conclusion, Verification Method) in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_3/handoff.md` and notify the parent orchestrator via send_message.

## 2026-11-06T10:26:04Z
**Context**: Milestone 2 Exploration (Features 15-19: profile.py, assembly.py)
**Content**: Checking in on status. Explorers 1 and 2 have delivered their handoffs for stamps and masking. How is your blueprint for the dual-radius fix, 2D cosine-taper assembly, and profile calibration progressing?
**Action**: Please report your current progress and status.
