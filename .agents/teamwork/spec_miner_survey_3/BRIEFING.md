# BRIEFING — 2026-11-06T09:15:00Z

## Mission
Mine and formalize detailed mathematical, algorithmic, and engineering specifications for the Roman extended PSF (ePSF) measurement pipeline based on ORIGINAL_REQUEST.md, Roman optical geometry, 6-fold pupil geometry angle priors, multi-tier modeling, high-aspect-ratio filtering, residual metrics, and PDF reporting requirements.

## 🔒 My Identity
- Archetype: Specification Miner (Teamwork Specialist)
- Roles: Specification Miner, Pipeline Architect, Optical Geometry Analyst
- Working directory: /Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3
- Original parent: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Milestone: Survey & Pipeline Specification

## 🔒 Key Constraints
- Discover and document features and specifications by probing authoritative specification sources.
- Do NOT implement anything — read-only specification mining.
- Strict rule: NO radial averaging or circularizing the 2D PSF.
- Strict rule: 1D radial profiles are strictly reserved for finding saturation boundaries and calculating cross-tier flux scaling factors.
- Base angles: [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] degrees.
- Output handoff report to `/Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md`.
- Communicate completion via `send_message` to parent `e80d314a-b5a0-43fb-be2e-ceabc982347e`.

## Current Parent
- Conversation ID: e80d314a-b5a0-43fb-be2e-ceabc982347e
- Updated: not yet

## Task Summary
- **What to build**: Comprehensive mathematical, algorithmic, and engineering specification for the Roman extended PSF measurement pipeline.
- **Success criteria**: Detailed formalizations of pupil geometry / spike coordinate transformations, high-aspect-ratio filtering / spike protection algorithms, multi-tier 2D stitching without circularizing, 18-detector memory & multiprocessing architecture, residual metrics & validation, YAML config & CLI design, technical documentation & publication-ready PDF report specifications.
- **Interface contracts**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md`

## Key Decisions Made
- Analyzed and verified optical spike geometry: base angles [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] deg correspond to strut pairs in the pupil; in detector coordinates, spikes are rotated by Delta_theta = -9.7 to -10.0 deg (aligned with aperture PA -110.08 deg).
- Formulated dual-prior spike protection algorithm combining directional line structuring elements / radial ridge filters on Moffat residuals with geometric sector cones to preserve spikes while masking neighbor stars.
- Established multi-tier model based on Roman commissioning data: Bright (mag_lambda < 11.0, 17 stars), Medium (11.0 <= mag_lambda < 13.0, 50 stars), Faint (mag_lambda >= 13.0, 127 stars).
- Strictly formalized 2D non-circular preservation: 1D radial profiles are strictly used for saturation boundary detection and overlap scaling factors ($k_{FM}$, $k_{MB}$); 2D stitching uses smooth cosine taper partition-of-unity blending.
- Memory architecture: lazy detector loading, prompt garbage collection, and tensor memory cleanup ensures < 4 GB peak RAM across 18 detectors with canvas sizes 1024x1024 or 2048x2048.
- Validation metrics: defined 2D subtraction maps and radial metrics ($\mu_{\text{frac}}$, $\text{RMS}_{\text{frac}}$, $\chi^2$) in core, transition, wings, and spike zones.
- Config & CLI: drafted full YAML configuration schema and Click CLI subcommands.
- PDF Report: specified 8-page publication-ready technical document using `matplotlib.backends.backend_pdf.PdfPages`.

## Artifact Index
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/DISPATCH.md` — Dispatch record
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/BRIEFING.md` — Persistent briefing
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/progress.md` — Liveness & task progress
- `/Users/pmsanch1/code/romanepsf/.agents/teamwork/spec_miner_survey_3/handoff.md` — Comprehensive specification handoff report
