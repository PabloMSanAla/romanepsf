## 2026-11-07T00:58:56Z
You are explorer_m4_3 (role: Technical Documentation & Deliverables Explorer).
Your working directory is /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_3/
You must write your progress to /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_3/progress.md and your final report to /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m4_3/handoff.md.

MANDATORY INSTRUCTION:
Read the authoritative user request at /Users/pmsanch1/code/romanepsf/.agents/teamwork/ORIGINAL_REQUEST.md before starting your investigation.

Python Environment:
Use /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python for all execution and testing.
Local ROSALIA codebase is at /Users/pmsanch1/code/ROSALIA.

Mission:
Investigate and design the technical markdown documentation in `docs/technical_documentation.md` to satisfy Requirement R5:
"Provide complete technical documentation in markdown covering preprocessing, star selection criteria, postage stamp extraction, normalization, modeling methodology, residual evaluation, and performance benchmarks."

Key Investigation & Design Tasks:
1. Examine E2E Test Expectations for Documentation:
   - Read lines 1320-1360 of `tests/e2e/test_tier1_features.py` where Feature 24 is tested:
     * `test_f24_01_technical_documentation_exists`
     * `test_f24_02_documentation_sections_present`
     * `test_f24_03_methodology_detailed`
     * `test_f24_04_performance_benchmarks_included`
     Identify all required section headings, keywords, tables, and benchmarks that the E2E test suite asserts.
2. Outline and Structure for `docs/technical_documentation.md`:
   - Section 1: System Overview & Architecture (modular structure, CLI, dependencies, environment, ROSALIA integration).
   - Section 2: Commissioning Dataset Preprocessing & Level 2 ASDF Ingestion (`roman_datamodels`, photometric calibration, WCS coordinate frames, DQ arrays).
   - Section 3: Star Selection, Astrometry & Centroid Refinement (GWCS backward/forward transforms, coordinate bounding, 2D centroid refinement, isolation safety radius).
   - Section 4: 3-Tier Magnitude Classification (Bright $m < 11.0$, Medium $11.0 \le m < 13.0$, Faint $m \ge 13.0$, census across 18 SCAs, handling missing bright stars).
   - Section 5: Postage Stamp Extraction & Dual-Prior Spike Protection (Theoretical 6-fold pupil geometry angles [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] adjusted for PA and offset -9.70 deg, morphological line filtering on Moffat residuals, local background subtraction).
   - Section 6: Assembly, Normalization & Annular Blending (PyTorch accelerated stacking, 1D radial profiles strictly for calibration, $k_{\text{FM}}$ and $k_{\text{MB}}$ scaling, partition-of-unity cosine annular blending, unit flux normalization).
   - Section 7: Scalability, Memory Lifecycle & 18-Detector Orchestration (Sequential execution, explicit `del l2_data; gc.collect()`, peak RSS strictly < 4 GB proof, multi-extension 4-HDU FITS architecture).
   - Section 8: Model Validation, Subtraction Residuals & Performance Benchmarks (2D residual mapping, $\mu_{\text{frac}}(r)$, $\text{RMS}_{\text{frac}}(r)$, $\chi_\nu^2$ across Core, Transition, Wings, Spikes, execution benchmarks).
3. Draft Production Content:
   - Write a complete draft of `docs/technical_documentation.md` in your working directory (`draft_technical_documentation.md`).
   - Run a test verification using `pytest tests/e2e/test_tier1_features.py -k "Feature24"` against your draft (temporarily copying or pointing) to ensure all Feature 24 assertions pass.

Deliver your findings, draft documentation, and verification method in `handoff.md`.
