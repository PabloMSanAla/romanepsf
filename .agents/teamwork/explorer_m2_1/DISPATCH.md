## 2026-11-06T10:16:26Z
You are Explorer 1 for Milestone 2 (explorer_m2_1).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_1

MANDATORY: First read the authoritative user request:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md

Next, read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md (Milestone 2, Features 9, 10, 11)
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/TEST_READY.md
- /Users/pmsanch1/code/romanepsf/src/stamps.py and /Users/pmsanch1/code/ROSALIA

Your mission:
Investigate and blueprint the implementation of `src/romanepsf/stamps.py`:
1. Adaptive stamp sizing by tier:
   - Faint ($m \ge 13.0$): $81 \times 81$ pixels (or configurable)
   - Medium ($11.0 \le m < 13.0$): $201 \times 201$ pixels
   - Bright ($m < 11.0$): up to $1001 \times 1001$ pixels (clamped to available canvas)
2. Subpixel realignment to integer grid center:
   - Interpolation using PyTorch or scipy bicubic spline / grid_sample
   - Handling border margins and boundary cutouts
3. Background estimation and subtraction:
   - Robust annular or percentile background subtraction per stamp
4. Integration with `RomanL2Data` and `assign_stellar_tiers` DataFrame from Milestone 1.
5. Unit test design for `tests/unit/test_stamps.py`.

Deliver a comprehensive handoff report (Observation, Logic Chain, Caveats, Conclusion, Verification Method) in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_1/handoff.md` and notify the parent orchestrator via send_message.
