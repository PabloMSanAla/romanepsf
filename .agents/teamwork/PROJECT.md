# Project: Roman Extended PSF (ePSF) Measurement Pipeline

## Architecture
The Roman ePSF Measurement Pipeline is a modular, high-performance Python package and CLI built under `src/` to synthesize empirical extended 2D point spread functions across the 18 Sensor Chip Assemblies (SCAs) of the Roman Space Telescope Wide Field Instrument (WFI), using simulated commissioning Level 2 data (`PID1083`) and precomputed source catalogs.

### Key Architectural Tenets:
1. **Multi-Tier Stacking**:
   - **Bright Stars** ($m_{\text{F146}} < 11.0$): Outer halo wings and extended 6-fold diffraction spikes out to $r > 500$ px.
   - **Medium Stars** ($11.0 \le m_{\text{F146}} < 13.0$): Transition overlap region ($8 < r < 45$ px) for cross-tier scale factor calibration.
   - **Faint Stars** ($m_{\text{F146}} \ge 13.0$): Unsaturated central core ($r < 10$ px).
2. **2D Structure & Spike Preservation**:
   - The final model is strictly a non-circular 2D canvas ($1025 \times 1025$ to $2049 \times 2049$).
   - 1D radial profiles (`src/profile.py`) are strictly reserved for determining saturation plateau radii ($r_{\text{sat}}$) and calculating scalar cross-tier overlap scale factors ($k_{\text{FM}}, k_{\text{MB}}$). Azimuthal averaging or circularizing the 2D PSF is strictly prohibited.
   - 6-fold secondary mirror support struts generate 12 diffraction spike rays matching base angles $[23.55, 55.29, 80.25, 118.65, 142.88, 178.07]^\circ$ rotated into the detector frame by $\Delta\theta_{\text{det}} \approx -9.70^\circ$.
   - Dual-prior spike protection fuses geometric angle cones with high-aspect-ratio morphological filtering on 2D Moffat residuals to shield spikes and cores from contaminant masking.
3. **Seamless 2D Partition-of-Unity Stitching**:
   - Raised-cosine annular taper blending ($C^1$ smooth) across $[10, 18]$ px (Faint-to-Medium) and $[30, 48]$ px (Medium-to-Bright) eliminates high-frequency step discontinuities and Fourier ringing.
4. **Scalable Multi-Detector Lifecycle**:
   - Lazy ASDF loading, prompt garbage collection, and tensor vectorization via PyTorch (`rosalia-dev` environment with Apple MPS acceleration) keep peak memory below 4 GB RAM across all 18 detectors (`wfi01`..`wfi18`).
5. **Validation & Reporting**:
   - Empirical star subtraction and radial metrics ($\mu_{\text{frac}}, \text{RMS}_{\text{frac}}, \chi_\nu^2$) across core, transition, wings, and spike zones.
   - Publication-ready 8-page PDF technical report generated natively via `matplotlib.backends.backend_pdf.PdfPages` without external dependencies.

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Level 2 ASDF Loader & Calibration | Read L2 ASDF ImageModel, extract science data (4088x4088), DQ bitmask, conversion to MJy/sr | M1 | Survey (Explorer 1 & 2) |
| 2 | WCS Forward Roundtrip Verification | Validate backward_transform against forward wcs with tolerance < 0.5 arcsec to eliminate false positives | M1 | Survey (Explorer 1) |
| 3 | Source Catalog Ingestion & Sanitization | Ingest precomputed catalog, sanitize duplicate columns (phot_g_mean_mag), filter stars | M1 | Survey (Explorer 1 & 2) |
| 4 | Centroid Refinement | Background-subtracted first moment subpixel centroiding | M1 | Survey (Explorer 1 & Spec Miner) |
| 5 | Moffat Isolation Clearance Filtering | Reject blended neighbor stars using analytic Moffat extent down to 28 mag/arcsec^2 | M1 | Survey (Explorer 2 & Spec Miner) |
| 6 | Multi-Tier Partitioning | Partition catalog into Bright (<11.0), Medium (11.0-13.0), and Faint (>=13.0) using mag_lambda (F146) | M1 | Survey (Explorer 1 & Spec Miner) |
| 7 | YAML Configuration Architecture | Hierarchical YAML config schema (configs/default.yaml) and dataclass loader | M1 | Survey (Explorer 2 & Spec Miner) |
| 8 | Click CLI Framework | Modular CLI with subcommands (run, single, catalog, stamps, assemble, validate, report) | M1 | Survey (Explorer 2 & Spec Miner) |
| 9 | Adaptive Postage Stamp Sizing | Dynamic odd stamp dimensions (81x81, 201x201, up to 1001x1001) based on tier and magnitude | M2 | Survey (Explorer 1 & Spec Miner) |
| 10 | Subpixel Bicubic Realignment | Order-3 spline shifting to center continuous centroid at ((S-1)/2, (S-1)/2) | M2 | Survey (Explorer 2 & Spec Miner) |
| 11 | Faint Core DQ Bit 1 Protection | Prevent zeroing out valid core pixels in faint stars where ramp fit set DQ=2 but flux is finite | M2 | Survey (Explorer 2) |
| 12 | 6-Fold Pupil Angle Transform | Transform base angles [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] to detector frame (offset -9.70 deg) | M2 | Survey (Explorer 1 & Spec Miner) |
| 13 | High-Aspect-Ratio Ridge Filter | Directional morphological line filter on Moffat residuals detecting linear diffraction spikes | M2 | Survey (Explorer 2 & Spec Miner) |
| 14 | Dual-Prior Spike Protection Masking | Fuse geometric cones and morphological ridge mask to protect spikes while masking neighbor stars | M2 | Survey (Explorer 2 & Spec Miner) |
| 15 | Robust Tier Tensor Stacking | Sigma-clipped median stacking of aligned stamps per tier using PyTorch acceleration | M2 | Survey (Explorer 2 & Spec Miner) |
| 16 | 1D Radial Profile Operator strictly for Calibration | Compute 1D profiles via src/profile.py strictly for saturation boundary & overlap scaling | M2 | Survey (Explorer 2 & Spec Miner) |
| 17 | Dual-Radius Cross-Tier Normalization | Compute scalar scaling factors k_FM and k_MB using independent inner and outer radius vectors | M2 | Survey (Explorer 2 & Spec Miner) |
| 18 | 2D Cosine-Taper Partition-of-Unity Stitching | C1 smooth raised-cosine blending across annular intervals [10, 18] and [30, 48] px | M2 | Survey (Spec Miner) |
| 19 | Global Energy Conservation Normalization | Non-negative clipping and volume normalization to unit flux (sum = 1.0) | M2 | Survey (Spec Miner) |
| 20 | Single-Detector Validation on WFI01 | Execute end-to-end pipeline on WFI01 (7 verified stars, all 3 tiers) | M3 | Survey (Explorer 1 & 2) |
| 21 | Scalable 18-Detector Orchestration | Process all 18 SCAs with lazy ASDF lifecycle, peak RAM < 4 GB, generating 1025^2/2049^2 canvas | M3 | Survey (Explorer 1, 2, Spec Miner) |
| 22 | 2D Subtraction Residual Mapping | Forward-model test stars with scaled ePSF and generate 2D subtraction residual maps | M4 | Survey (Spec Miner) |
| 23 | Partitioned Radial Residual Metrics | Measure mu_frac, RMS_frac, chi^2 across Core, Transition, Wings, and Spike zones | M4 | Survey (Spec Miner) |
| 24 | Comprehensive Markdown Documentation | Complete technical documentation covering dataset, star selection, masking, assembly, benchmarks | M4 | Survey (Spec Miner) |
| 25 | Publication-Ready 8-Page PDF Report | Generate publication-ready 8-page PDF report with intermediate step figures using PdfPages | M4 | Survey (Explorer 2 & Spec Miner) |
| 26 | E2E Test Suite Validation (Tiers 1-4) | Independent opaque-box test suite verifying 100% pass across all features | M5 | Survey (E2E Track) |
| 27 | Adversarial Coverage Hardening (Tier 5) | White-box stress testing, corner cases, and boundary protection | M5 | Survey (E2E Track) |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|--------------|--------|
| M1 | Core Package, CLI & Catalog Ingestion | Features 1-8: `configs/default.yaml`, `cli.py`, `config.py`, `loader.py`, `catalog.py`, WCS roundtrip validation, bug fixes | none | DONE (Passed Gate It2: 187 unit tests, 10 adversarial tests, 297 E2E tests, zero integrity violations) |
| M2 | Postage Stamps, Spike Protection & 2D Assembly | Features 9-19: `stamps.py`, `masking.py`, `profile.py`, `assembly.py`, dual-prior spike protection, 2D cosine stitching | M1 | DONE (Passed Gate It2: 486 unit tests, 298 E2E tests, zero integrity violations, WFI01/WFI02 verified) |
| M3 | Single-Detector Validation & 18-Detector Pipeline | Features 20-21: `pipeline.py`, single-detector execution on `wfi01`, full 18-detector execution, composite canvas FITS | M2 | DONE (Passed Gate: 830 unit/adv tests, 4 skipped, 2 Reviewers APPROVE, 2 Challengers APPROVE, Auditor CLEAN; live WFI01 2.3s, live 18 SCAs 12.9s, peak RSS 1.55-1.93 GB < 4 GB) |
| M4 | Model Validation, Technical Documentation & PDF Report | Features 22-25: `validation.py`, `report.py`, `docs/technical_documentation.md`, publication-ready 8-page PDF report | M3 | DONE (Passed Gate It4: 2 Reviewers APPROVE, 2 Challengers APPROVE, Auditor CLEAN; 2.42 MB 8-page PDF, 612 unit tests, 55 adversarial tests pass, zero RNG) |
| M5 | Final Milestone: E2E Test Pass (Tiers 1-4) & Adversarial Hardening (Tier 5) | Features 26-27: 100% pass of E2E test suite, adversarial coverage hardening, final verification | M4, TEST_READY.md | DONE (Passed Gate: 302/302 E2E pass, 69 Tier 5 adversarial pass, 612 unit pass, 1038 repo tests pass; 2 Reviewers APPROVE, Challenger APPROVE, Auditor CLEAN) |

---

## Interface Contracts

### Loader ↔ Catalog (`loader.py` ↔ `catalog.py`)
- `load_l2_image(asdf_path: Path, calibrate: bool = True) -> RomanL2Data`
  - Returns `RomanL2Data` with attributes: `data: np.ndarray (4088, 4088)`, `dq: np.ndarray (4088, 4088)`, `err: np.ndarray (4088, 4088)`, `wcs: gwcs.WCS`, `pa_aperture: float`, `pixel_scale: float = 0.11`, `conversion_factor: float`.
- `project_catalog_to_pixels(l2_data: RomanL2Data, catalog_df: pd.DataFrame, margin_px: int = 50, tolerance_arcsec: float = 0.5) -> pd.DataFrame`
  - Returns DataFrame containing `[source_id, ra, dec, mag_lambda, x, y, detector]` with verified roundtrip coordinates.
- `assign_stellar_tiers(df: pd.DataFrame, bright_limit: float = 11.0, faint_limit: float = 13.0) -> pd.DataFrame`
  - Adds column `tier` with values `'bright'`, `'medium'`, `'faint'`.

### Stamps ↔ Masking (`stamps.py` ↔ `masking.py`)
- `mask_contaminants_with_spikes_protected(stamp: np.ndarray, dq_mask: np.ndarray, pa_aperture: float, cfg: SpikesConfig) -> Tuple[np.ndarray, np.ndarray, np.ndarray]`
  - Inputs: stamp cutout, bad pixel DQ mask, aperture position angle, spike configuration dataclass.
  - Returns: `(final_mask: bool[H, W], protected_area: bool[H, W], residual: float[H, W])`.
  - Guarantees: `final_mask & protected_area == False` for all spike and core pixels.
- `process_star_stamps(l2_data: RomanL2Data, catalog_df: pd.DataFrame, spikes_cfg: SpikesConfig) -> Dict[str, List[StampData]]`
  - Returns dictionary with keys `'bright'`, `'medium'`, `'faint'`, containing aligned, masked, background-subtracted stamps.

### Assembly ↔ Profile (`assembly.py` ↔ `profile.py`)
- `measure_radial_profile_1d(image: np.ndarray, device: str = 'cpu') -> Tuple[np.ndarray, np.ndarray, np.ndarray]`
  - Strictly reserved for calibration: returns `(radii: np.ndarray, median_profile: np.ndarray, std_profile: np.ndarray)`.
- `determine_overlap_scale_factor_dual(prof_inner, prof_outer, r_inner, r_outer, r_min: float, r_max: float) -> float`
  - Evaluates independent radii coordinates to eliminate IndexError. Returns scalar float ratio $k = \text{median}(f_{\text{in}} / f_{\text{out}})$.
- `blend_2d_annular_profiles(inner_image: np.ndarray, outer_image: np.ndarray, r_start: float, r_end: float) -> np.ndarray`
  - Cosine-taper partition-of-unity 2D blending without radial circularization.
- `assemble_composite_extended_psf(stamps_by_tier: Dict[str, List[StampData]], cfg: AssemblyConfig) -> np.ndarray`
  - Returns unit-normalized 2D composite ePSF canvas ($1025 \times 1025$ or $2049 \times 2049$).

### Pipeline ↔ Validation & Report (`pipeline.py` ↔ `validation.py`, `report.py`)
- `run_pipeline(config_path: Path) -> PipelineOutputs`
  - Outputs: `composite_epsf: np.ndarray`, `fits_path: Path`, `diagnostics: Dict[str, Any]`.
- `evaluate_epsf_validation(epsf_model: np.ndarray, test_stamps: List[StampData], cfg: ValidationConfig) -> ValidationResults`
  - Returns residual maps, $\mu_{\text{frac}}(r)$, $\text{RMS}_{\text{frac}}(r)$, $\chi_\nu^2$, pass/fail flags per zone.
- `generate_publication_pdf_report(outputs: PipelineOutputs, validation: ValidationResults, report_path: Path)`
  - Generates 8-page publication-ready PDF document.

---

## Code Layout
```
/Users/pmsanch1/code/romanepsf/
├── pyproject.toml
├── configs/
│   └── default.yaml
├── src/
│   └── romanepsf/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── loader.py
│       ├── catalog.py
│       ├── stamps.py
│       ├── masking.py
│       ├── profile.py
│       ├── assembly.py
│       ├── pipeline.py
│       ├── validation.py
│       └── report.py
├── docs/
│   └── technical_documentation.md
├── tests/
│   ├── unit/
│   │   ├── test_loader.py
│   │   ├── test_catalog.py
│   │   ├── test_masking.py
│   │   ├── test_assembly.py
│   │   └── test_profile.py
│   └── e2e/
│       ├── test_tier1_features.py
│       ├── test_tier2_boundaries.py
│       ├── test_tier3_combinations.py
│       └── test_tier4_scenarios.py
└── output/
```
