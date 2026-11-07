# Progress — Spec Miner Survey 3 (Pipeline Specification Miner)

Last visited: 2026-11-06T09:12:00Z

## Status
- [x] Initialized DISPATCH.md and BRIEFING.md
- [x] Review ORIGINAL_REQUEST.md and existing codebase (`romanepsf`, `ROSALIA`, `src/profile.py`, etc.)
- [x] Review survey reports from explorer agents (explorer_survey_1, explorer_survey_2)
- [x] Investigate 1: Pupil Geometry & Diffraction Spikes (base angles, V3PA / PA_APER, detector coordinate transforms, high-aspect-ratio filtering, spike protection vs neighbor masking)
  - Empirically verified spike angles on WFI01: [13.5, 48.0, 72.0, 108.0, 132.5, 166.0] deg (mod 180).
  - Derived coordinate transform from base angles [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] to detector frame: Delta_theta = -9.7 to -10.0 deg.
  - Formalized directional linear structuring elements and radial ridge filtering on Moffat residuals.
- [x] Investigate 2: Multi-tier Modeling & Non-circular 2D Preservation
  - Formalized star tiers (Bright < 11.0, Medium 11.0-13.0, Faint >= 13.0 in F146 mag_lambda).
  - Defined strict prohibition against circularization and radial averaging.
  - Specified 1D radial profiling for saturation boundaries and overlap scale factors ($k_{\text{FM}}$, $k_{\text{MB}}$).
  - Formulated seamless 2D cosine-taper partition-of-unity stitching algorithm.
- [x] Investigate 3: Single to 18-Detector Architecture (memory efficiency, 4088x4088 arrays, multiprocessing)
  - Formulated lazy detector loading, garbage collection, and tensor memory management.
  - Designed two-level parallelization hierarchy (inter-detector multiprocessing + intra-detector PyTorch vectorization).
- [x] Investigate 4: Validation & Residual Analysis
  - Defined 2D subtraction residual maps and radial metrics ($\mu_{\text{frac}}$, $\text{RMS}_{\text{frac}}$, $\chi^2$) partitioned across 4 functional zones (core, transition, wings, spikes).
- [x] Investigate 5: YAML Configuration & CLI Specifications
  - Formulated complete YAML configuration schema and Click CLI subcommands.
- [x] Investigate 6: Publication-ready PDF Report & Technical Docs Specifications
  - Designed 8-page publication-ready PDF structure via `matplotlib.backends.backend_pdf.PdfPages`.
- [x] Compile comprehensive handoff report at `handoff.md`
- [x] Send handoff notification to orchestrator
