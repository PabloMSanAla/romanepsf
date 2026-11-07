# E2E Test Infra: Roman Extended PSF (ePSF) Measurement Pipeline

## Test Philosophy
- **Opaque-Box & Requirement-Driven**: Tests are derived strictly from `ORIGINAL_REQUEST.md` and user-facing requirements (CLI commands, YAML configs, input ASDF datasets, output FITS models, residual maps, and PDF reports). They do not depend on internal module implementations.
- **Methodology**: 4-Tier Systematic Testing:
  - Tier 1: Feature Coverage (Category-Partition representative inputs, happy-path isolation).
  - Tier 2: Boundary & Corner Cases (Boundary Value Analysis at limits, edge cases, NaN/corrupted values).
  - Tier 3: Cross-Feature Combinations (Pairwise Combinatorial Testing for state/dataflow interactions).
  - Tier 4: Real-World Commissioning Scenarios (Single detector WFI01, multi-detector WFI01-18, dynamic range extremes, publication PDF verification).

---

## Feature Inventory & Test Mapping

| # | Feature | Requirement Source | Tier 1 (Count) | Tier 2 (Count) | Tier 3 (Pairwise) |
|---|---------|-------------------|:--------------:|:--------------:|:-----------------:|
| F1 | Level 2 ASDF Loader & Calibration | R1 | 5 | 5 | ✓ |
| F2 | WCS Forward Roundtrip Verification | R1 | 5 | 5 | ✓ |
| F3 | Source Catalog Ingestion & Sanitization | R1 | 5 | 5 | ✓ |
| F4 | Centroid Refinement | R1, R2 | 5 | 5 | ✓ |
| F5 | Moffat Isolation Clearance Filtering | R2 | 5 | 5 | ✓ |
| F6 | Multi-Tier Partitioning (Bright, Med, Faint) | R2 | 5 | 5 | ✓ |
| F7 | YAML Configuration Architecture | R1 | 5 | 5 | ✓ |
| F8 | Click CLI Framework & Subcommands | R1 | 5 | 5 | ✓ |
| F9 | Adaptive Postage Stamp Sizing | R1, R2 | 5 | 5 | ✓ |
| F10 | Subpixel Bicubic Realignment | R2 | 5 | 5 | ✓ |
| F11 | Faint Core DQ Bit 1 Protection | R2 | 5 | 5 | ✓ |
| F12 | 6-Fold Pupil Angle Transform (-9.7 deg) | R2 | 5 | 5 | ✓ |
| F13 | High-Aspect-Ratio Ridge Filter | R2 | 5 | 5 | ✓ |
| F14 | Dual-Prior Spike Protection Masking | R2 | 5 | 5 | ✓ |
| F15 | Robust Tier Tensor Stacking | R2 | 5 | 5 | ✓ |
| F16 | 1D Radial Profile Operator (src/profile.py) | R2 | 5 | 5 | ✓ |
| F17 | Dual-Radius Cross-Tier Normalization | R2 | 5 | 5 | ✓ |
| F18 | 2D Cosine-Taper Partition-of-Unity Stitching | R2 | 5 | 5 | ✓ |
| F19 | Global Energy Conservation Normalization | R2 | 5 | 5 | ✓ |
| F20 | Single-Detector Validation on WFI01 | R3 | 5 | 5 | ✓ |
| F21 | Scalable 18-Detector Orchestration | R3 | 5 | 5 | ✓ |
| F22 | 2D Subtraction Residual Mapping | R4 | 5 | 5 | ✓ |
| F23 | Partitioned Radial Residual Metrics | R4 | 5 | 5 | ✓ |
| F24 | Comprehensive Markdown Documentation | R5 | 5 | 5 | ✓ |
| F25 | Publication-Ready 8-Page PDF Report | R5 | 5 | 5 | ✓ |

---

## Real-World Application Scenarios (Tier 4)

| # | Scenario | Features Exercised | Complexity | Success Criteria |
|---|----------|--------------------|------------|------------------|
| S1 | Single Detector WFI01 End-to-End | F1, F3, F6, F8, F12, F14, F18, F20, F22 | Medium | CLI `single` runs to completion, outputs FITS ePSF and validates with residual RMS < 10% |
| S2 | Full 18-Detector Composite Synthesis | F1, F3, F7, F8, F14, F18, F21, F22, F25 | High | CLI `run` executes across all 18 SCAs, produces 1025x1025 or 2049x2049 FITS without OOM (RAM < 4 GB) |
| S3 | Extreme Brightness & Dynamic Range Robustness | F1, F6, F9, F11, F12, F13, F14, F17 | High | Preserves 6-fold spikes on m=7.37 star (WFI05) without saturation corruption or core hollow artifacts |
| S4 | 2D Residual Forward-Model Validation | F18, F20, F22, F23 | Medium | Subtracting ePSF from observed stars yields fractional residual |mu_frac| < 5% in core and transition zones |
| S5 | Publication PDF Report Completeness | F24, F25 | Medium | Generates multi-page PDF (8 pages) containing all required figures, tables, and metrics, readable with valid PDF header |

---

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: $\ge 5$ test cases per feature (Total $\ge 125$ assertions/tests).
- **Tier 2 (Boundary & Corner Cases)**: $\ge 5$ test cases per feature (Total $\ge 125$ assertions/tests).
- **Tier 3 (Cross-Feature Combinations)**: $\ge 25$ test cases covering key feature pairs.
- **Tier 4 (Real-World Scenarios)**: $\ge 5$ comprehensive end-to-end tests.
- **Total Test Suite Target**: $\ge 280$ test cases/assertions.

---

## Test Architecture & Invocation
- Environment: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`
- Runner: `pytest` (v9.0.2)
- Directory: `tests/e2e/`
- Full Suite Command:
  ```bash
  /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/e2e/ -v
  ```
- Pass Semantics: 100% of tests must pass with exit code 0.
