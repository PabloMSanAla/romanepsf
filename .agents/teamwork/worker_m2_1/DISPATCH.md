## 2026-11-06T10:30:33Z
You are the Milestone 2 Implementation Worker (worker_m2_1).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m2_1

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

First, read the authoritative user request:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md

Next, read PROJECT.md and the 3 Milestone 2 Explorer handoffs:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md (Milestone 2, Features 9-19)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_1/handoff.md (also check proposed_stamps.py and proposed_test_stamps.py in that directory)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_2/handoff.md
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_3/handoff.md (also check proposed_assembly.py, proposed_profile.py, proposed_test_assembly.py, proposed_test_profile.py in that directory)

Your exclusive write ownership:
- `src/romanepsf/stamps.py` and `src/stamps.py` wrapper
- `src/romanepsf/masking.py` and `src/masking.py` wrapper
- `src/romanepsf/profile.py` and `src/profile.py` wrapper
- `src/romanepsf/assembly.py` and `src/assembly.py` wrapper
- `tests/unit/test_stamps.py`
- `tests/unit/test_masking.py`
- `tests/unit/test_profile.py`
- `tests/unit/test_assembly.py`
- `tests/e2e/test_tier4_scenarios.py` (adjust xfail on test_s1_03 to test now that assembly bug is resolved)

Tasks:
1. Implement `src/romanepsf/stamps.py` and top-level `src/stamps.py` per explorer_m2_1's blueprint.
2. Implement `src/romanepsf/masking.py` and top-level `src/masking.py` per explorer_m2_2's blueprint.
3. Implement `src/romanepsf/profile.py` and top-level `src/profile.py` per explorer_m2_3's blueprint. Remember the strict scientific constraint: 1D radial profiles are strictly reserved for finding saturation boundaries and cross-tier scaling, NOT for circularizing the 2D PSF canvas.
4. Implement `src/romanepsf/assembly.py` and top-level `src/assembly.py` per explorer_m2_3's blueprint:
   - Implement `determine_overlap_scale_factor_dual` with independent radius vectors.
   - Implement smooth 2D cosine-taper partition-of-unity blending across annular overlap intervals [10, 18] and [30, 48] px.
   - Implement robust PyTorch tensor stacking with outlier rejection and hollow-core fallback.
   - Fix canvas embedding/cropping to eliminate IndexError and ValueError.
   - Implement global unit flux normalization (sum = 1.0) and non-negative clipping.
5. Create comprehensive unit tests:
   - `tests/unit/test_stamps.py`
   - `tests/unit/test_masking.py`
   - `tests/unit/test_profile.py`
   - `tests/unit/test_assembly.py`
6. Run full verification with /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python:
   - `pytest tests/unit/ -v`
   - `pytest tests/e2e/ -v`
   - Confirm all unit tests pass, and confirm E2E tests pass (including test_s1_03).
7. Write your handoff report to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/worker_m2_1/handoff.md` and notify the parent orchestrator via send_message.


## 2026-11-06T10:40:59Z
**Context**: Milestone 2 Implementation
**Content**: Checking in on status. We noticed src/romanepsf/masking.py and tests/unit/test_masking.py have been implemented. How are stamps.py, profile.py, assembly.py, and test runs progressing?
**Action**: Please update progress.md and report current progress.
