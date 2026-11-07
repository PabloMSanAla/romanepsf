## 2026-11-06T11:14:27Z
You are the Milestone 2 Iteration 2 Implementation Worker (worker_m2_it2_1).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m2_it2_1

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

First, read the authoritative user request:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md

Next, read the unified blueprint and defect reports:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_3/handoff.md (contains exact patches and code snippets for assembly.py and masking.py)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_1/handoff.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/reviewer_m2_2/handoff.md

Your exclusive write ownership:
- `src/romanepsf/assembly.py` and top-level `src/assembly.py` wrapper
- `src/romanepsf/masking.py` and top-level `src/masking.py` wrapper
- `tests/unit/test_assembly.py`
- `tests/unit/test_challenger_assembly_stress.py`
- `tests/unit/test_masking.py`

Tasks:
1. Apply the unified patch to `src/romanepsf/assembly.py` (and re-export wrapper `src/assembly.py`):
   - In `assemble_composite_extended_psf`:
     * Pass `mask=(cov_faint == 0)`, `mask=(cov_medium == 0)`, `mask=(cov_bright == 0)` to `measure_radial_profile_1d`.
     * Implement graceful multi-tier fallback (3-tier, 2-tier [faint+medium, medium+bright, faint+bright], 1-tier, and raise ValueError only when ALL tiers are empty).
     * Add `_embed_or_crop_canvas` helper for symmetrical canvas embedding.
     * Symmetrical annular blending for arbitrary canvas shapes.
     * Cast stamp data to `float32` and guard unmasked NaNs in `stack_tier_stamps_torch`.
     * Fallback to linear interpolation in `determine_overlap_scale_factor_dual` if coordinate count mismatches.
2. Apply the unified patch to `src/romanepsf/masking.py` (and re-export wrapper `src/masking.py`):
   - In `fit_moffat_model`: estimate background on outer edge (`r > 0.75 * max(cx, cy)`), avoiding pedestal inflation from stellar halo.
   - In `mask_contaminants_with_spikes_protected`: implement annularly localized median + scatter thresholding (`rad_med[r_int] + sig_eff * rad_std[r_int]`), preventing legitimate stellar halos from being wiped out.
3. Update tests:
   - In `tests/unit/test_challenger_assembly_stress.py`: update `test_missing_or_empty_tier_raises_value_error` to assert ValueError when ALL tiers are empty.
   - In `tests/unit/test_assembly.py`: add multi-tier fallback tests (`test_assembly_missing_bright_tier_fallback`, `test_assembly_missing_faint_tier_fallback`, `test_assembly_single_tier_fallback`) and WFI01 monotonicity assertion.
4. Execute full verification using /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python:
   - `pytest tests/unit/ -v` (must pass 100%)
   - `pytest tests/e2e/ -v` (must pass 100%)
   - Execute verification script for WFI01 (verifying `k_mb < 0.1` and monotonic radial decay)
   - Execute verification script for WFI02 (verifying 2-tier assembly executes cleanly without ValueError)
5. Write your handoff report to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m2_it2_1/handoff.md` and notify the parent orchestrator via send_message.

## 2026-11-06T11:16:47Z
**Context**: Milestone 2 Iteration 2 implementation
**Content**: explorer_m2_it2_2 has published its final patch and handoff report:
- Patch: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_2/fix_stellar_halo_masking.patch`
- Report: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_it2_2/handoff.md`
Key parameters verified on WFI01 data:
- Tiered radial scaling: A=200, r0=15 for medium; A=200, r0=20 for bright; A=50, r0=15 for faint.
- Outer perimeter background estimation in fit_moffat_model: r > 0.75 * r_max across full stamp.
**Action**: Please incorporate these exact parameters and patch into your implementation alongside explorer_m2_it2_3's assembly blueprint.
