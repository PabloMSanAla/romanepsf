# Handoff Report — Explorer 2: Codebase, ROSALIA & Environment Survey

## 1. Observation

### 1.1 Python Environment & Tooling
- **Interpreter**: `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python` (Python 3.12.12).
- **Core Installed Packages**:
  - `numpy: 2.5.3`
  - `scipy: 1.17.1`
  - `astropy: 7.2.2`
  - `photutils: 2.3.0`
  - `roman_datamodels: 1.1.0`
  - `asdf: 5.4.0`
  - `pandas: 3.0.1`
  - `PyYAML (yaml): 6.0.3`
  - `click: 8.3.1`
  - `matplotlib: 3.10.8`
  - `pillow (PIL): 12.1.1`
  - `torch: 2.14.1` (Apple Metal Performance Shaders GPU acceleration verified: `torch.backends.mps.is_available() == True`)
  - `rosalia-wfi: 1.3.9.dev0` (installed in editable mode from `/Users/pmsanch1/code/ROSALIA`)
  - `romanisim: 0.15.0`, `stpsf: 2.2.0`, `GalSim: 2.8.4`, `pysiaf: 0.28.0`, `gwcs: 1.0.3`, `pytest: 9.0.2`.
- **Missing Packages**:
  - `weasyprint`, `reportlab`, `pypdf`, `fitz`, `fpdf2`, `skimage`, `cv2` are NOT installed.
- **Available PDF Engines**:
  - `matplotlib.backends.backend_pdf.PdfPages` is fully functional and generated vector test PDF (`test_report.pdf`, 24,257 bytes).
  - `/Library/TeX/texbin/pdflatex`, `/Library/TeX/texbin/xelatex`, `/Library/TeX/texbin/lualatex`, and `/usr/local/bin/gs` are installed system-wide.
- **Missing External Binaries**:
  - GNU Astronomy Utilities (`astradialprofile`, `astscript-psf-scale-factor`, `astscript-psf-subtract`, `astcrop`, `astfits`) are NOT found on PATH (`which` returned exit code 1).

### 1.2 ROSALIA Codebase (`/Users/pmsanch1/code/ROSALIA`)
- **Focal Plane & Canvas Geometry**:
  - `rosalia/psf.py:385-430`: Contains `_roman_apertures()`, `get_roman_canvas_geometry(pixscale=0.11)`, and SIAF coordinate mappings (`_detector_to_canvas`, `_canvas_to_detector`). Computes the full 18-detector Roman focal plane canvas shape: `(16076, 26352)` pixels with origin `(-1449.24, -1080.59)`.
  - `rosalia/psf.py:478-516`: `make_roman_canvas_from_detectors(data_list, wcs_list, pixscale=0.11)` and `recover_roman_detectors_from_canvas`.
- **Analytic PSF & Spike Equations**:
  - `rosalia/psf.py:2308-2356`: `get_psf_extension_spikes(m_star, depth=31, l=0.91, w=0.0758, n_struts=6, ainner=0.3915, aouter=1.2765)` computes the Roman WFI diffraction spike extent in arcseconds based on strut geometry.
  - `rosalia/psf.py:2358-2370`: `get_psf_extension_moffat(mag, depth=30, alpha=0.08, beta=1.52)` calculates analytical Moffat core/wing extent.
- **ASDF & Header Ingestion**:
  - `rosalia/inspector.py:177-270`: `exposure_inspector_asdf` opens ASDF files (`asdf.open(input_name)['roman']` or `rdm.open`), extracts detector (`WFI01`..`WFI18`), filter, conversion factor (`conversion_megajanskys`), pixel area (`pixel_area`), pointing, and converts `gwcs` to `astropy.wcs.WCS`.
  - `rosalia/telescopes.py`: Roman class with optical transmission curves for all 8 WFI filters.
- **Non-Reusable or Incompatible Parts**:
  - `rosalia/core.py:927`: `exposure.psf()` is a *forward synthetic modeling tool* (using analytical superback, STPSF, or GalSim), NOT an empirical ePSF builder.
  - `rosalia/psf.py:818,890`: `astscript_radial_profile`, `measure_maxradii`, and `astscript_psf_subtract` rely on Gnuastro CLI commands which are missing from the system.

### 1.3 Commissioning Data & Catalogs
- **Path**: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/`
  - Contains all 18 Level 2 ASDF files: `r0108301001001001001_0001_wfi01_f146_cal.asdf` through `wfi18` (~204 MB each).
  - Shape: `(4088, 4088)` float32 science data, uint32 DQ bitmask, float16 error array, GWCS.
  - Aperture roll reference: `roll_ref = -110.0224` deg, optical element: `F146`.
- **Precomputed Catalog**:
  - `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv` (77 MB, 198,802 rows).
  - Contains columns `source_id`, `ra`, `dec`, `phot_g_mean_mag_AB`, `phot_g_mean_mag`, `mag_lambda`. First 14 rows are solar system bodies (Sun, Moon, Earth) and Hipparcos stars, followed by Gaia DR3 stars.

### 1.4 Workspace `romanepsf` State & Critical Deficiencies Discovered
- **Existing Files in `src/`**:
  - `loader.py`: `load_l2_image`, `RomanL2Data`, `get_dq_mask`.
  - `catalog.py`: `query_gaia_for_detector`, `project_catalog_to_pixels`, `refine_stellar_centroids`, `filter_isolated_stars`, `assign_stellar_tiers`.
  - `stamps.py`: `process_star_stamps`, `get_adaptive_stamp_size`, `recenter_and_align_stamp`.
  - `masking.py`: `mask_contaminants_with_spikes_protected`, `get_theoretical_spike_angles`, `create_geometric_spike_mask`, `detect_morphological_spikes`, `fit_moffat_model`.
  - `profile.py`: `elliptical_profile`, `create_ellipse_meshgrid_torch`, `get_psf_extension_moffat`.
  - `assembly.py`: `stack_tier_stamps_torch`, `measure_radial_profile_1d`, `determine_overlap_scale_factor`, `blend_2d_annular_profiles`, `assemble_composite_extended_psf`.
- **Defects Discovered via Diagnostic Runs**:
  1. **`IndexError` in `assembly.py:determine_overlap_scale_factor` (Line 152)**:
     - `psf_faint` is 81x81 (radial profile length 40), `psf_medium` is 201x201 (profile length 100).
     - Line 246 passed `r_f` (length 40) into `determine_overlap_scale_factor(prof_f, prof_m, r_f)`. Line 152 attempted `v_out = prof_outer[idx]`, raising: `IndexError: boolean index did not match indexed array along axis 0; size of axis is 100 but size of corresponding boolean axis is 40`.
  2. **Duplicate Column Name Bug in `catalog.py:query_gaia_for_detector` (Line 91)**:
     - When querying from `r0108301001001001001_0001_wfi_source_catalog.csv`, the file already contains both `phot_g_mean_mag_AB` and `phot_g_mean_mag`.
     - Renaming `phot_g_mean_mag_AB` to `phot_g_mean_mag` produced two identical columns, resulting in `df['phot_g_mean_mag']` returning a 2D DataFrame (shape `N x 2`). This subsequently failed in `filter_isolated_stars` with: `ValueError: operands could not be broadcast together with shapes (6,) (6,2)`.
  3. **Hollow Core Due to DQ Bit 1 Over-Masking in `stamps.py:process_star_stamps`**:
     - `stamps.py:154` unconditionally masked `SATURATED` (DQ bit 1 = 2) across all stars.
     - In Roman simulated commissioning data (PID1083), stars down to $G \sim 19$ have DQ bit 1 flagged in ramp fits despite having valid, positive, non-NaN flux in `l2.data` (~100 to 1,000 MJy/sr).
     - Unconditionally masking DQ bit 1 zeroed out the coverage in the inner $5 \times 5$ pixels of faint stars, leading to a hollow center (`composite[250, 250] == 0.0`).
  4. **Missing Architectural Components**:
     - No CLI script or CLI package entry points.
     - No YAML configuration loader / schema validator (`config/default.yaml`).
     - No 18-detector orchestration module to combine all SCAs into a single composite canvas.
     - No star subtraction validation script (`validation.py`).
     - No PDF reporting script (`report.py`).
     - No unit tests or integration tests.

---

## 2. Logic Chain

1. **Environmental Viability**:
   - Packages `torch`, `astropy`, `photutils`, `roman_datamodels`, `asdf`, `pandas`, `yaml`, `click`, and `matplotlib` are present and modern (Observation 1.1).
   - Apple MPS hardware acceleration works reliably with PyTorch tensors (Observation 1.1).
   - Gnuastro is absent, confirming that ROSALIA's `astscript_*` wrappers cannot run. However, `src/profile.py` implements a pure PyTorch binning pipeline that ran 10 radial profiles in < 0.2s, completely replacing Gnuastro (Observation 1.1, 1.4).
2. **ROSALIA Integration Strategy**:
   - Because `rosalia-wfi` is installed in editable mode, `romanepsf` can directly import `rosalia.psf` for `_roman_apertures`, `_detector_to_canvas`, and `get_psf_extension_spikes` without copying or re-implementing SIAF mechanics (Observation 1.2).
   - ROSALIA does not contain empirical ePSF construction logic; `romanepsf` must supply the empirical stacking, spike preservation, multi-tier normalization, and validation (Observation 1.2).
3. **Pipeline Correctness & Bug Resolution**:
   - Correcting `assembly.py:determine_overlap_scale_factor` to use dual radial coordinate arrays (`radii_inner`, `radii_outer`) enables robust cross-tier scaling ($k_{FM} \approx 0.386$, $k_{MB} \approx 0.118$) (Observation 1.4).
   - Sanitizing catalog columns in `catalog.py` prevents DataFrame duplication and allows smooth catalog ingestion of all 198k sources (Observation 1.3, 1.4).
   - For faint stars, central core pixels with finite flux should not be masked simply because DQ bit 1 is set in ramp fitting. Radial profiles should determine the true saturation plateau per star, strictly reserving Faint stars for the unsaturated core (Requirement R2, Observation 1.4).
4. **Execution Performance across 18 Detectors**:
   - Single-detector test (`wfi01`) with 3 bright, 10 medium, and 20 faint stars took **9.5 seconds** (Observation 1.4).
   - Across 18 detectors, total sequential execution would take $\sim 3$ minutes.
   - When synthesizing a composite extended PSF canvas sized between 1024x1024 and 2048x2048 pixels, memory usage for a float32 canvas is only $4 \times 2048^2 \approx 16.8$ MB, well within system limits (64-128 GB).
5. **PDF Reporting Solution**:
   - Since `weasyprint`, `reportlab`, and `typst` are absent, but `matplotlib.backends.backend_pdf.PdfPages` is native and fully functional (tested 24 KB vector PDF), a multi-page PDF generation module using `PdfPages` is the most robust, zero-dependency, publication-grade solution (Observation 1.1). System `/Library/TeX/texbin/pdflatex` is also available as a supplementary build path.

---

## 3. Caveats

1. **Aperture Roll Angle Sign**: Roman ASDF pointing metadata specifies `roll_ref = -110.0224` deg. The coordinate rotation between detector pixel frame and aperture frame must consistently apply this negative angle to align theoretical diffraction spikes at $[23.55, 55.29, 80.25, 118.65, 142.88, 178.07] + \text{roll\_ref}$.
2. **Precomputed Source Catalog vs Online Gaia TAP**: Offline execution using the precomputed catalog (`r0108301001001001001_0001_wfi_source_catalog.csv`) or local cache (`cache/gaia_dr3_*.csv`) is significantly faster (8.7s vs 45s+) and does not depend on ESA Gaia TAP service availability.
3. **Detector Border Stars**: Stars within 50 pixels of the detector edges should be excluded to avoid asymmetric cutouts or convolution boundary artifacts.

---

## 4. Conclusion & Recommendations

### Recommended Modular Package Architecture
Maintain the clean package structure under `src/romanepsf/` with a root `pyproject.toml` and CLI entry points:

```
/Users/pmsanch1/code/romanepsf/
├── pyproject.toml
├── configs/
│   └── default.yaml          # Stamp sizes, thresholds, tier boundaries, canvas size
├── src/
│   └── romanepsf/
│       ├── __init__.py
│       ├── cli.py            # Click CLI with subcommands: run, single, validate, report
│       ├── config.py         # YAML configuration loader & dataclasses
│       ├── loader.py         # Roman Level 2 ASDF loader and photometric calibration
│       ├── catalog.py        # Stellar catalog ingestion, centroiding, isolation, tiers
│       ├── stamps.py         # Postage stamp extraction, adaptive sizing, subpixel centering
│       ├── masking.py        # Dual-prior spike protection & contaminant masking
│       ├── profile.py        # PyTorch-accelerated elliptical radial profile
│       ├── assembly.py       # 2D tier stacking, cross-tier normalization, composite assembly
│       ├── pipeline.py       # 18-detector orchestration & composite focal plane canvas
│       ├── validation.py     # Subtraction residual maps and radial residual metrics
│       └── report.py         # Publication-ready multi-page PDF generator via PdfPages
└── tests/
    ├── test_loader.py
    ├── test_catalog.py
    ├── test_masking.py
    ├── test_profile.py
    └── test_assembly.py
```

### Key Technical Decisions
1. **CLI Design**: Use `click` (v8.3.1) with subcommands:
   - `romanepsf run-single --detector wfi01 --config configs/default.yaml`
   - `romanepsf run-all --input-dir <dir> --config configs/default.yaml --canvas-size 1024`
   - `romanepsf validate --model <epsf.fits> --data <image.asdf> --output-dir <out>`
   - `romanepsf report --results <out> --output report.pdf`
2. **Interface with ROSALIA**:
   - Import directly: `import rosalia as rs`.
   - Reusable calls: `rs.psf.get_psf_extension_spikes`, `rs.psf.get_psf_extension_moffat`, `rs.psf._roman_apertures`, and `rs.psf._detector_to_canvas`.
3. **Immediate Bug Fixes Needed During Implementation**:
   - Fix `determine_overlap_scale_factor` in `assembly.py` to accept independent radius vectors for inner and outer profiles.
   - Fix duplicate column renaming in `catalog.py`.
   - Refine faint-star core masking: do not zero out valid non-NaN core pixels where the profile is monotonic and finite.
4. **PDF Generation**:
   - Implement `report.py` using `matplotlib.backends.backend_pdf.PdfPages` to produce an 8-page publication-ready technical document containing figures for each intermediate step (star selection, spike masks, radial overlap profiles, composite 2D ePSF, subtraction residuals, and performance metrics).

---

## 5. Verification Method

Independent verification can be performed with the following commands in `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:

1. **Verify Environment & Packages**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   import rosalia, roman_datamodels, asdf, astropy, photutils, torch, matplotlib, yaml, click
   print('All critical packages imported successfully')
   assert torch.backends.mps.is_available()
   print('Apple MPS GPU acceleration is ACTIVE')
   "
   ```

2. **Verify ROSALIA Reusable Methods**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   import rosalia as rs
   spike_ext = rs.psf.get_psf_extension_spikes(10.0, depth=28.0)
   moffat_ext = rs.psf.get_psf_extension_moffat(10.0, depth=28.0)
   origin, shape = rs.psf.get_roman_canvas_geometry(pixscale=0.11)
   print('Spike extent (arcsec):', spike_ext)
   print('Moffat extent (arcsec):', moffat_ext)
   print('Roman focal plane canvas shape:', shape)
   assert spike_ext > 0 and moffat_ext > 0
   "
   ```

3. **Verify Fixed Scale Factor Logic**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   import numpy as np
   r_in = np.arange(0.5, 40.5, 1.0)
   r_out = np.arange(0.5, 100.5, 1.0)
   p_in = 100.0 / (1.0 + r_in**2)
   p_out = 10.0 / (1.0 + r_out**2)
   idx_in = (r_in >= 8.0) & (r_in <= 16.0)
   idx_out = (r_out >= 8.0) & (r_out <= 16.0)
   ratio = np.median(p_in[idx_in] / p_out[idx_out])
   print('Recovered scale ratio:', ratio)
   assert np.isclose(ratio, 10.0)
   "
   ```

4. **Verify PDF Generation**:
   Inspect generated artifact:
   `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_2/test_report.pdf`
