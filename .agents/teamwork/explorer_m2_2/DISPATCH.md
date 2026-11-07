## 2026-11-06T10:16:32Z
You are Explorer 2 for Milestone 2 (explorer_m2_2).
Your working directory is: /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_2

MANDATORY: First read the authoritative user request:
/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md

Next, read:
- /Users/pmsanch1/code/romanepsf/.agents/teamwork/PROJECT.md (Milestone 2, Features 12, 13, 14)
- /Users/pmsanch1/code/romanepsf/src/masking.py and /Users/pmsanch1/code/ROSALIA

Your mission:
Investigate and blueprint the implementation of `src/romanepsf/masking.py`:
1. Theoretical 6-fold pupil geometry spike angles:
   - Base angles: [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] degrees
   - Rotation adjustment for aperture PA (`pa_aperture`) and detector rotation ($\Delta\theta_{\text{det}} \approx -9.70^\circ$)
   - Angular wedge / cone protection masks around theoretical spike rays
2. High-aspect-ratio directional morphological filtering:
   - Moffat profile fitting on stamp
   - Moffat subtraction to isolate residuals
   - Directional morphological opening/closing or line kernels detecting linear diffraction spikes
3. Dual-prior spike protection mask fusion:
   - Fuse theoretical geometric cones and empirical morphological ridge detections
   - Construct contaminant mask that masks neighbor stars and artifacts while strictly PROTECTING diffraction spikes from being masked out
4. Interface contract:
   `mask_contaminants_with_spikes_protected(stamp: np.ndarray, dq_mask: np.ndarray, pa_aperture: float, cfg: SpikesConfig) -> Tuple[np.ndarray, np.ndarray, np.ndarray]`
5. Unit test design for `tests/unit/test_masking.py`.

Deliver a comprehensive handoff report (Observation, Logic Chain, Caveats, Conclusion, Verification Method) in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m2_2/handoff.md` and notify the parent orchestrator via send_message.
