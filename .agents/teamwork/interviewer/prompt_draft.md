Build a scalable extended PSF (ePSF) measurement pipeline for the Roman Space Telescope using simulated commissioning Level 2 data, execute it across all 18 WFI detectors, and produce technical documentation and a comprehensive PDF report illustrating the entire process.

Working directory: /Users/pmsanch1/code/romanepsf
Integrity mode: development

## Requirements

### R1. Extended PSF Measurement Pipeline Architecture & CLI
Build a modular Python package and CLI under `src/` to measure the extended 2D PSF of the Roman Space Telescope using simulated Level 2 data (`/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/*asdf`) and the precomputed source catalog (`/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv`), utilizing the designated Python environment (`/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`) and local ROSALIA codebase (`/Users/pmsanch1/code/ROSALIA`). All operational parameters (e.g., stamp sizes, thresholds, tier boundaries, canvas size) must be configurable via YAML.

### R2. Multi-Tier ePSF Modeling and 2D Diffraction Spike Preservation
Implement three star tiers:
- Bright stars: used for the extended PSF wings and extended diffraction spikes.
- Medium stars: used to unify the core and extended PSF across the transition overlap region.
- Faint stars: used for the unsaturated central core.
The model must directly capture the full 2D structure including 2D spikes; radial averaging or circularizing the 2D PSF is prohibited. 1D radial profiles (via `src/profile.py`) are strictly reserved for identifying saturation boundaries and calculating cross-tier flux scaling factors. Model diffraction spikes using both theoretical 6-fold pupil geometry angle priors (base angles [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] adjusted for aperture position angle) and morphological high-aspect-ratio filtering on Moffat residuals, ensuring diffraction spikes are preserved without being masked out as contaminants.

### R3. Single-Detector Testing and Full 18-Detector Execution
Validate the pipeline architecture first on single detector `wfi01`, ensuring memory efficiency and parallelization. Then execute across all 18 detectors (`wfi01` through `wfi18`) to synthesize a composite extended PSF canvas sized between 1024x1024 and 2048x2048 pixels based on memory and performance optimization.

### R4. Model Validation and Residual Analysis
Validate the synthesized ePSF model by subtracting it from observed star images. Generate 2D residual maps and compute radial residual metrics to assess model accuracy and identify any systematic deviations across core, transition, and spike regions.

### R5. Documentation and Comprehensive PDF Report
Provide complete technical documentation in markdown covering preprocessing, star selection criteria, postage stamp extraction, normalization, modeling methodology, residual evaluation, and performance benchmarks. Compile a publication-ready PDF report containing figures illustrating intermediate steps (star selection, spike protection masks, overlap profiles, composite 2D ePSF, subtraction residuals, and resource/performance usage).

## Acceptance Criteria

### Execution & Modeling
- [ ] Pipeline CLI executes successfully on single detector `wfi01`, generating an intermediate ePSF model and validating the modular architecture.
- [ ] Pipeline executes across all 18 detectors (`wfi01` to `wfi18`) without out-of-memory errors and outputs a composite 2D ePSF canvas (1024x1024 to 2048x2048 pixels).
- [ ] Synthesized extended PSF captures 2D non-circular structure and 6-fold diffraction spikes matching the theoretical angles.
- [ ] 1D radial profiles are used only for finding saturation boundaries and cross-tier scaling, not for circular averaging of the 2D PSF canvas.

### Validation & Deliverables
- [ ] Programmatic validation script computes 2D subtraction residual maps and radial residual metrics against observed stars.
- [ ] Technical documentation is created in markdown detailing dataset preprocessing, star selection, stamp normalization, ePSF assembly, and performance optimization.
- [ ] A complete, readable PDF report is generated containing figures for intermediate steps, star selection, spike masks, radial overlap profiles, composite 2D ePSF, subtraction residuals, and performance metrics.
