# Milestone 5 Phase 2 Handoff Report: Adversarial Coverage Hardening (Core Pipeline)

**Agent**: `challenger_m5_tier5_1` (Teamwork Challenger, Roles: critic, specialist)  
**Date**: 2026-11-07T06:07:00Z  
**Target Suite**: `tests/test_tier5_adversarial_core.py`  
**Target Codebase**: `src/romanepsf/loader.py`, `catalog.py`, `stamps.py`, `masking.py`, `assembly.py`, `profile.py`, `config.py`

---

## 1. Observation

### Test Execution Commands & Verbatim Outputs
1. Execution of newly authored Tier 5 core pipeline adversarial test suite:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_tier5_adversarial_core.py -v
   ```
   **Result**:
   ```
   ============================= test session starts ==============================
   platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python
   cachedir: .pytest_cache
   rootdir: /Users/pmsanch1/code/romanepsf
   configfile: pyproject.toml
   plugins: anyio-4.12.1, zarr-3.1.5
   collected 39 items

   tests/test_tier5_adversarial_core.py::TestLoaderAdversarial::test_adv_loader_mismatched_dimensions_raises_value_error PASSED [  2%]
   tests/test_tier5_adversarial_core.py::TestLoaderAdversarial::test_adv_loader_dq_mask_extreme_flags_and_bitmasks PASSED [  5%]
   tests/test_tier5_adversarial_core.py::TestLoaderAdversarial::test_adv_loader_effective_mask_nan_inf_subnormal PASSED [  7%]
   tests/test_tier5_adversarial_core.py::TestLoaderAdversarial::test_adv_loader_extract_detector_name_adversarial_patterns PASSED [ 10%]
   tests/test_tier5_adversarial_core.py::TestLoaderAdversarial::test_adv_loader_nonexistent_file_raises_filenotfound PASSED [ 12%]
   tests/test_tier5_adversarial_core.py::TestLoaderAdversarial::test_adv_loader_mock_asdf_invalid_conversion_and_shape_validation PASSED [ 15%]
   tests/test_tier5_adversarial_core.py::TestLoaderAdversarial::test_adv_loader_dataclass_methods_and_properties PASSED [ 17%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_sanitize_extreme_solar_system_negative_mag PASSED [ 20%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_sanitize_missing_coordinates_raises_value_error PASSED [ 23%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_sanitize_duplicate_columns_and_sources PASSED [ 25%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_project_pixels_empty_and_corrupted PASSED [ 28%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_refine_stellar_centroids_edge_and_divergence PASSED [ 30%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_filter_isolated_stars_extreme_crowding_and_ties PASSED [ 33%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_assign_stellar_tiers_boundary_precision PASSED [ 35%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_moffat_extension_extremes PASSED [ 38%]
   tests/test_tier5_adversarial_core.py::TestCatalogAdversarial::test_adv_catalog_get_detector_sky_bounds_and_empty_filters PASSED [ 41%]
   tests/test_tier5_adversarial_core.py::TestStampsAdversarial::test_adv_stamps_adaptive_stamp_size_odd_parity_guarantee PASSED [ 43%]
   tests/test_tier5_adversarial_core.py::TestStampsAdversarial::test_adv_stamps_extract_cutout_extreme_off_detector PASSED [ 46%]
   tests/test_tier5_adversarial_core.py::TestStampsAdversarial::test_adv_stamps_estimate_background_pathological PASSED [ 48%]
   tests/test_tier5_adversarial_core.py::TestStampsAdversarial::test_adv_stamps_recenter_align_spline_stability PASSED [ 51%]
   tests/test_tier5_adversarial_core.py::TestStampsAdversarial::test_adv_stamps_faint_core_protection_behavior PASSED [ 53%]
   tests/test_tier5_adversarial_core.py::TestStampsAdversarial::test_adv_stamps_process_star_stamps_polymorphic_signatures PASSED [ 56%]
   tests/test_tier5_adversarial_core.py::TestMaskingAdversarial::test_adv_masking_theoretical_angles_periodicity_and_invariance PASSED [ 58%]
   tests/test_tier5_adversarial_core.py::TestMaskingAdversarial::test_adv_masking_geometric_spike_mask_core_exclusion PASSED [ 61%]
   tests/test_tier5_adversarial_core.py::TestMaskingAdversarial::test_adv_masking_morphological_spikes_discrimination PASSED [ 64%]
   tests/test_tier5_adversarial_core.py::TestMaskingAdversarial::test_adv_masking_fit_moffat_model_pathological PASSED [ 66%]
   tests/test_tier5_adversarial_core.py::TestMaskingAdversarial::test_adv_masking_dual_prior_protection_invariant PASSED [ 69%]
   tests/test_tier5_adversarial_core.py::TestProfileAdversarial::test_adv_profile_ellipse_meshgrid_torch_aspect_ratio_bounds PASSED [ 71%]
   tests/test_tier5_adversarial_core.py::TestProfileAdversarial::test_adv_profile_clip_single_bin_pathological PASSED [ 74%]
   tests/test_tier5_adversarial_core.py::TestProfileAdversarial::test_adv_profile_elliptical_profile_validation PASSED [ 76%]
   tests/test_tier5_adversarial_core.py::TestProfileAdversarial::test_adv_profile_moffat_extension_beta_bound PASSED [ 79%]
   tests/test_tier5_adversarial_core.py::TestAssemblyAdversarial::test_adv_assembly_stack_empty_list_raises_value_error PASSED [ 82%]
   tests/test_tier5_adversarial_core.py::TestAssemblyAdversarial::test_adv_assembly_stack_varying_sizes_and_outlier_rejection PASSED [ 84%]
   tests/test_tier5_adversarial_core.py::TestAssemblyAdversarial::test_adv_assembly_stack_hollow_core_recovery PASSED [ 87%]
   tests/test_tier5_adversarial_core.py::TestAssemblyAdversarial::test_adv_assembly_overlap_scale_factor_dual_pathological PASSED [ 89%]
   tests/test_tier5_adversarial_core.py::TestAssemblyAdversarial::test_adv_assembly_blend_partition_of_unity PASSED [ 92%]
   tests/test_tier5_adversarial_core.py::TestAssemblyAdversarial::test_adv_assembly_composite_psf_empty_and_graceful_tier_degradation PASSED [ 94%]
   tests/test_tier5_adversarial_core.py::TestAssemblyAdversarial::test_adv_assembly_serialize_fits_headers_and_empty_summaries PASSED [ 97%]
   tests/test_tier5_adversarial_core.py::TestAssemblyAdversarial::test_adv_assembly_embed_or_crop_canvas_and_wrapper PASSED [100%]

   ============================== 39 passed in 2.49s ==============================
   ```

2. Full regression suite execution across all unit tests:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v
   ```
   **Result**: `612 passed, 6 warnings in 48.54s` (0 failures, 0 regressions).

### Specific Code Observations
- **`src/romanepsf/catalog.py:21-49` vs `src/romanepsf/profile.py:274-315`**:
  `profile.py` line 299 explicitly validates:
  ```python
  if beta <= 1.0:
      raise ValueError("Moffat beta parameter must be > 1.0 for finite integrated flux.")
  ```
  In contrast, `catalog.py:42` computes `term = (np.pi * (alpha**2)) / (beta - 1.0)` without guarding `beta <= 1.0`. For `beta = 1.0`, this raises `ZeroDivisionError`, and for `beta < 1.0`, it yields negative arguments inside `np.log10(term)`.
- **`src/romanepsf/masking.py:389-445` (Diffraction Spike Protection Invariant)**:
  When a candidate source pixel falls within any of the 12 theoretical spike corridors (e.g. angle $\theta = 225.0^\circ$, which is within $0.59^\circ$ of the theoretical ray at $225.59^\circ$), `protected_stellar_area` correctly evaluates to `True`, and lines 444-445 strictly zero out contaminant masking on that pixel (`contaminants &= (~protected_stellar_area)`). Off-axis contaminants (e.g. along $\theta = 90.0^\circ$ at $r = 30$ px) are accurately detected and masked (`final_mask == True`).
- **`src/romanepsf/assembly.py:447-456` (Graceful Tier Degradation)**:
  `assemble_composite_extended_psf` safely constructs a unit-normalized composite 2D extended PSF across all tier population permutations (3-tier full synthesis, 2-tier faint+medium, 2-tier medium+bright, 2-tier faint+bright direct, 1-tier faint only, 1-tier medium only, and 1-tier bright only). It strictly raises `ValueError` if and only if all tiers are empty.
- **`src/romanepsf/assembly.py:309-347` (Partition of Unity)**:
  `blend_2d_annular_profiles` enforces $w(r) + (1 - w(r)) \equiv 1.0$ everywhere across the transition annulus, verified with identical inputs ($1.0 + 1.0 \rightarrow 1.0$ with zero discontinuity).

---

## 2. Logic Chain

1. **Loader Verification**:
   - `RomanL2Data` shape checking in `__post_init__` enforces that `err` and `dq` must match `data.shape`. When passed 3D or 1D arrays, it raises `ValueError`.
   - `get_effective_mask` combines `get_dq_mask(dq)` and `~np.isfinite(data)`. We tested positive Inf, negative Inf, NaN, and subnormal floats. In every case, non-finite values are trapped as invalid (`True`).
   - `load_l2_image` enforces `validate_shape` and validates `conversion_megajanskys > 0`. When mocked with negative or zero conversion factors, it cleanly raises `ValueError`.

2. **Catalog Sanitization and Projection**:
   - Simulated commissioning catalogs contain unphysical negative magnitude solar system bodies (Sun at -26.9, Moon at -4.7, Earth, Jupiter). `sanitize_source_catalog` filters rows with `mag < 0`, coordinates out of range ($RA \notin [0, 360]$, $Dec \notin [-90, 90]$), or non-finite values.
   - Astrometric projection handles forward roundtrip verification against GWCS. Stars with roundtrip discrepancy $\Delta \theta \ge 0.5''$ are rejected.
   - Centroid refinement handles image borders (pixel `(0, 0)`), all-NaN boxes, and divergent shifts ($> 3.0$ px) by falling back safely to catalog coordinates without divergence or `IndexError`.
   - In dense clusters, pairwise isolation with Moffat extension radii deterministically preserves the brightest star and breaks ties using `source_id`.

3. **Stamps Processing & Faint Core Protection**:
   - `get_adaptive_stamp_size` guarantees odd-integer dimensions across all tiers ($S \% 2 == 1$), ensuring exact integer central indexing `(S-1)//2`.
   - `extract_cutout` handles coordinates situated completely off the detector (`cx=-500, cy=-500`) by allocating an array of size `(size, size)` filled entirely with `fill_value` without memory fault or unhandled exception.
   - `recenter_and_align_stamp` performs subpixel bicubic shifting while masking newly exposed boundary pixels (`cval=1.0 > 0.5`) in `aligned_mask`.
   - `faint_core_protect_finite`: When enabled, faint stars with DQ bit 1 (`SATURATED`) in their core retain their positive core pixels (`sat_bool = False`). When disabled, core pixels are masked out.

4. **Masking & Diffraction Spike Dual-Prior**:
   - `get_theoretical_spike_angles` correctly produces 12 strictly sorted angles in $[0, 360)^\circ$ that are invariant under $360^\circ$ periodicity and aperture rotation offsets.
   - `detect_morphological_spikes` uses directional angular variance and radial continuity ($\ge 15$ px) to classify linear diffraction spikes while rejecting circular companion stars.
   - The dual-prior fusion guarantee was empirically verified: no pixel within the core protection radius or within the 12 spike corridors is ever marked as a contaminant.

5. **Profile Extraction & Acceleration**:
   - `create_ellipse_meshgrid_torch` clamps ellipticity `eps` safely to $[0.0, 0.9999]$, preventing division-by-zero singularities under extreme aspect ratios.
   - Parallel single-bin sigma clipping (`_clip_single_bin`) rejects extreme outliers ($10^{9}$) and handles zero-variance or empty bins safely.
   - `elliptical_profile` enforces 2D array input, $\ge 2$ bin edges, and handles big-endian `>f4` layouts.

6. **Assembly & Extended PSF Synthesis**:
   - Tensor stacking with PyTorch handles varying stamp dimensions by padding to maximum odd size, and clips outliers via nanmedian MAD statistics when $N \ge 3$.
   - Hollow core fallback recovers central pixels from the surrounding 3x3 median if masked across all stamps in a tier.
   - Overlap scale matching (`determine_overlap_scale_factor_dual`) returns fallback 1.0 on disjoint or inverted radius intervals.
   - Composite ePSF assembly degrades gracefully when bright or medium tiers are missing, producing unit-flux normalized canvases ($sum = 1.0$) in all valid cases.
   - FITS serialization outputs 4 valid HDUs (`PRIMARY`, `COVERAGE`, `RADIAL_PROFILES`, `DETECTOR_SUMMARY`) with all required mission metadata keys.

---

## 3. Caveats

1. **Hardware-Specific Acceleration**:
   - PyTorch tensor operations were stress-tested on host CPU and Apple Silicon MPS backend. Multi-GPU CUDA distributed execution paths were validated logically via `resolve_device`, but physical multi-GPU hardware was not present in this runtime environment.
2. **Catalog Moffat Beta Consistency**:
   - In `src/romanepsf/catalog.py:get_psf_extension_moffat`, there is no explicit check for `beta <= 1.0` (which would cause a division by zero or log of a negative number). In standard pipeline operations, `beta` is defaulted to `1.52`, so this does not trigger in nominal workflows; however, a parameter guard matching `profile.py` would improve defensive robustness.
3. **Tier Dictionary Key Normalization**:
   - In `src/romanepsf/assembly.py:assemble_composite_extended_psf`, tier lookups use literal lowercase strings (`tier_stamps.get("bright")`). Any caller providing uppercase keys (`"BRIGHT"`) would result in empty tier detection.

---

## 4. Conclusion

The core pipeline modules (`loader.py`, `catalog.py`, `stamps.py`, `masking.py`, `assembly.py`, `profile.py`, and `config.py`) demonstrate high empirical robustness against extreme, adversarial, and boundary conditions:
- **Zero-star and partial tier synthesis**: Gracefully handled without crashes.
- **Boundary & off-detector coordinates**: Cleanly padded and isolated.
- **Contaminant vs Spike discrimination**: Strict invariant preservation of 2D diffraction spikes and stellar cores.
- **Outlier & non-finite handling**: NaNs, Infs, and unphysical values are thoroughly filtered and regularized.
- **Test Suite Status**: 39/39 adversarial tests passing in `tests/test_tier5_adversarial_core.py`, with 0 regressions across the entire 612-test unit test suite.

---

## 5. Verification Method

To independently verify all findings and execute the Tier 5 adversarial stress test suite:

```bash
# 1. Run the dedicated Tier 5 Core Adversarial Stress Suite
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/test_tier5_adversarial_core.py -v

# 2. Run full regression across existing unit tests
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v

# 3. Inspect the newly authored test file
# Path: /Users/pmsanch1/code/romanepsf/tests/test_tier5_adversarial_core.py
```

**Invalidation Conditions**:
- Any test failure in `tests/test_tier5_adversarial_core.py`.
- Any regression in `tests/unit/`.
- Failure to preserve 2D diffraction spikes or stellar cores in `mask_contaminants_with_spikes_protected`.
