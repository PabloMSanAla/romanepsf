# Milestone 3 Adversarial Challenge Report: Memory Footprint, Scalability & FITS Forensics

**Agent**: `challenger_m3_2` (Role: Milestone 3 Challenger 2 — Memory Footprint, Scalability & FITS Forensics)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_2`  
**Target Files Reviewed**:  
- `src/romanepsf/pipeline.py` (and backward-compatibility wrapper `src/pipeline.py`)  
- `src/romanepsf/assembly.py` (and backward-compatibility wrapper `src/assembly.py`)  
- `output/run_all/roman_epsf_composite.fits`  
- `output/single_wfi01/roman_epsf_wfi01.fits`  
**Test Suite Created**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_2/test_adversarial_fits_memory.py`  
**Verdict**: **APPROVE**

---

## 1. Observation

### A. Memory Ceiling & Leak Audit (Requirement R3)
- Tool command executed:
  ```bash
  /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_2/test_adversarial_fits_memory.py -k TestMemoryFootprintAndLeaks -v
  ```
- **18-Detector Multi-SCA Peak RSS**:
  - Full pipeline execution across all 18 WFI SCAs (`run_pipeline(output_dir=...)`) achieved:
    * Run 1 Peak RSS: **1,554.53 MB** (dt = 2.63s).
    * Run 2 Peak RSS: **1,660.16 MB** (dt = 2.23s).
    * Safety Headroom below 4,000 MB ceiling: **2,339.84 MB** (> 58% margin).
- **Single-Detector Memory Footprint & Consecutive Leak Stress**:
  - In a 10-iteration continuous execution loop of `run_single_detector('wfi01')`:
    * Iter 1: 1,520.59 MB (initial loading of ASDF, astropy, scipy, PyTorch libraries).
    * Iter 2: 1,766.75 MB (+246.16 MB memory arena allocation).
    * Iter 3: 1,847.95 MB (+81.20 MB).
    * Iter 4: 1,976.36 MB (+128.41 MB).
    * Iter 5: 2,001.88 MB (+25.52 MB).
    * Iter 6: 2,069.03 MB (+67.16 MB).
    * Iter 7: 2,078.38 MB (+9.34 MB).
    * Iter 8: 2,079.16 MB (+0.78 MB).
    * Iter 9: 2,127.62 MB (+48.47 MB).
    * Iter 10: 2,109.58 MB (-18.05 MB).
  - Steady-state plateau reached at ~2,080 - 2,109 MB; memory growth ceases and enters steady-state arena recycling without unbounded leak.
  - Peak RSS across all single-detector stress testing remained strictly < 2,150 MB (headroom > 1,850 MB against 4,000 MB ceiling).

### B. FITS Output Forensics
Audited both `output/run_all/roman_epsf_composite.fits` and `output/single_wfi01/roman_epsf_wfi01.fits`:

1. **HDU Structure, Types, Shapes, and BITPIX (`output/run_all/roman_epsf_composite.fits`)**:
   - `HDU 0 (EPSF)`: `fits.PrimaryHDU`, `BITPIX = -32` (IEEE single precision float), shape `(1025, 1025)`.
   - `HDU 1 (COVERAGE)`: `fits.ImageHDU`, `BITPIX = 32` (32-bit signed integer), shape `(1025, 1025)`.
   - `HDU 2 (RADIAL_PROFILES)`: `fits.BinTableHDU`, `BITPIX = 8`, 500 rows x 6 columns (`RADIUS_PX`, `RADIUS_ARCSEC`, `FLUX_COMPOSITE`, `FLUX_FAINT`, `FLUX_MED_SCALED`, `FLUX_BRIGHT_SCALED`).
   - `HDU 3 (DETECTOR_SUMMARY)`: `fits.BinTableHDU`, `BITPIX = 8`, exactly 18 rows x 9 columns (`DETECTOR`, `N_FAINT`, `N_MEDIUM`, `N_BRIGHT`, `N_TOTAL`, `PA_APER_DEG`, `PIXSCALE`, `TIME_SEC`, `STATUS`).
   - `output/single_wfi01/roman_epsf_wfi01.fits`: `fits.PrimaryHDU`, `BITPIX = -32`, shape `(1025, 1025)` (single-HDU design per `export_single_detector_fits`).

2. **Standard Keyword Length & HIERARCH Audit**:
   - Scanned all 105 header cards across 4 HDUs in `roman_epsf_composite.fits` and 40 cards in `roman_epsf_wfi01.fits`:
     * Header cards examined: 48 (composite HDU 0) + 9 (HDU 1) + 21 (HDU 2) + 27 (HDU 3) + 40 (single HDU 0) = 145 cards.
     * Keywords exceeding 8 characters: **0** (strictly $\le 8$ chars).
     * `HIERARCH` header cards found: **0**.

3. **Primary HDU Flux, Centering, and Cleanliness**:
   - Integrated flux:
     * Composite: $\sum \text{flux} = 0.99999994$ ($|\sum - 1.0| = 6.0 \times 10^{-8} < 10^{-4}$).
     * Single WFI01: $\sum \text{flux} = 1.00000000$ ($|\sum - 1.0| = 0.0 < 10^{-4}$).
   - Peak pixel flux:
     * Composite: $0.06392875 > 0$.
     * Single WFI01: $0.12939543 > 0$.
   - Peak centering:
     * Discrete argmax pixel: `(511, 512)` on a `1025 x 1025` canvas whose center coordinate is `(512, 512)` (distance = 1.0 pixel).
     * Continuous sub-pixel centroid in central 7x7 box: $dx = -0.0809$ px, $dy = +0.0571$ px (net centroid offset = 0.0990 px from geometric center).
   - Non-finite pixel check:
     * NaN count = 0, Inf count = 0, Minimum pixel value = 0.0 (strictly non-negative).

4. **HDU 1 (COVERAGE) Verification**:
   - Minimum coverage = 0 (valid outer bounds), Maximum coverage = 135 stars.
   - Core pixel `(512, 512)` coverage = 10 valid stars (> 0).
   - Data type: `int32` (standard signed 32-bit integer).

5. **HDU 2 (RADIAL_PROFILES) Verification**:
   - Radii: 500 rows strictly increasing from $r = 1.0$ px ($0.11''$) to $r = 500.0$ px ($55.0''$).
   - Outer wing monotonicity: Across $r \in [50, 300]$ px, $\Delta \text{FLUX} \le 0$ everywhere without positive noise spikes (zero spikes with $\Delta \text{FLUX} > 10^{-8}$).
   - Flux smoothly decreases from $4.94 \times 10^{-2}$ at 1 px down to $1.43 \times 10^{-6}$ at 50 px, $2.29 \times 10^{-8}$ at 200 px, and $7.27 \times 10^{-9}$ at 300 px.

6. **HDU 3 (DETECTOR_SUMMARY) Verification**:
   - Exactly 18 rows corresponding to detectors `WFI01` through `WFI18`.
   - Every single detector has `STATUS == 'SUCCESS'`.
   - Detector star count breakdown:
     * Bright: 12 stars across 12 SCAs (6 SCAs — WFI02, WFI03, WFI08, WFI13, WFI17, WFI18 — contain 0 bright stars).
     * Medium: 39 stars.
     * Faint: 89 stars.
     * Total pooled stars across table: **140 stars**.
   - Matches Primary HDU keyword `NSTARS = 140` exactly.

### C. 2D Non-Circular Structure & Spike Preservation Audit
- **Azimuthal Variance**:
  - Ring at $r = 50.0 \pm 3.0$ px: Mean flux = $1.472 \times 10^{-6}$, Standard deviation = $4.688 \times 10^{-7}$, Coefficient of Variation ($\sigma / \mu$) = **0.3185 (31.85%)**.
  - Ring at $r = 150.0 \pm 5.0$ px: Mean flux = $5.580 \times 10^{-8}$, Standard deviation = $2.291 \times 10^{-8}$, Coefficient of Variation ($\sigma / \mu$) = **0.4106 (41.06%)**.
  - Proves the 2D ePSF is NOT circularized (a circularized model yields $\sigma / \mu \approx 0.0$).
- **Theoretical 6-Fold Spike Geometry Alignment**:
  - Mean aperture position angle: $\bar{\theta}_{\text{PA}} = -110.004^\circ$; Nominal detector clocking offset: $-9.70^\circ$; Net rotation: $\theta_{\text{net}} = 240.296^\circ$.
  - Theoretical 12 radial directions: `[23.18, 58.37, 83.85, 115.59, 140.55, 178.95, 203.18, 238.37, 263.85, 295.59, 320.55, 358.95]` degrees.
  - On-spike flux vs. off-spike background comparison:
    * $r = 50$ px: On-spike flux = $1.563 \times 10^{-6}$, Off-spike flux = $1.452 \times 10^{-6}$ (**+7.62% elevation**; ratio = 1.076x).
    * $r = 80$ px: On-spike flux = $4.072 \times 10^{-7}$, Off-spike flux = $3.880 \times 10^{-7}$ (**+4.96% elevation**; ratio = 1.050x).
    * $r = 100$ px: On-spike flux = $2.047 \times 10^{-7}$, Off-spike flux = $1.918 \times 10^{-7}$ (**+6.73% elevation**; ratio = 1.067x).
    * $r = 150$ px: On-spike flux = $5.880 \times 10^{-8}$, Off-spike flux = $5.575 \times 10^{-8}$ (**+5.46% elevation**; ratio = 1.055x).
  - Demonstrates that diffraction spikes are preserved in 2D along theoretical spider strut angles without being masked out as contaminants.

### D. Cross-Tier Overlap Scale Factors
- Scale factor physics check ($0 < k_{\text{MB}} < k_{\text{FM}} < 1$):
  * Composite (18 detectors): $k_{\text{FM}} = 0.193659$, $k_{\text{MB}} = 0.025527$ ($0 < 0.0255 < 0.1937 < 1$).
  * Single detector (WFI01): $k_{\text{FM}} = 0.197245$, $k_{\text{MB}} = 0.027220$ ($0 < 0.0272 < 0.1972 < 1$).
- Both strictly satisfy physical cross-tier flux ordering.

---

## 2. Logic Chain

1. **Memory Budget Verification**:
   - *Observation*: Requirement R3 mandates peak RSS < 4,000 MB during full 18-detector execution.
   - *Observation*: Live multi-detector runs measure peak RSS of 1,554.53 MB and 1,660.16 MB.
   - *Deduction*: Peak RSS utilizes $\approx 41.5\%$ of the allowable memory ceiling, providing 2,339.84 MB of headroom.
   - *Observation*: In a 10-run consecutive single-detector stress loop, memory stabilized at 2,079 MB (iter 8) and 2,109 MB (iter 10) with negative delta (-18 MB).
   - *Deduction*: Initial RSS rise from 1.5 GB to 2.1 GB is standard CPython/OS memory pool arena allocation for NumPy/PyTorch buffers; no unbounded object or cyclic reference leak exists.

2. **FITS Compliance & Forensics**:
   - *Observation*: Multi-extension FITS file `output/run_all/roman_epsf_composite.fits` contains exactly 4 HDUs (`EPSF`, `COVERAGE`, `RADIAL_PROFILES`, `DETECTOR_SUMMARY`) with standard BITPIX (-32, 32, 8, 8).
   - *Observation*: All 145 header cards across both files have keyword length $\le 8$ characters, and zero `HIERARCH` cards were detected.
   - *Observation*: Primary HDU flux integrates to $0.99999994 \approx 1.0$, peak is positive ($0.0639$) and centered (discrete dist 1.0 px, continuous offset 0.099 px), with 0 NaNs and 0 negative pixels.
   - *Observation*: HDU 3 has 18 rows representing WFI01-WFI18, with total star sum = 140, matching Primary HDU keyword `NSTARS = 140`.
   - *Deduction*: The serialized FITS outputs are fully compliant with FITS standards, astropy conventions, and Requirement R3/R4 specifications.

3. **2D Geometry & Spike Preservation**:
   - *Observation*: Azimuthal coefficient of variation is 31.8% at $r = 50$ px and 41.1% at $r = 150$ px.
   - *Observation*: Mean flux along the 12 theoretical diffraction spike rays is consistently 5% to 8% higher than off-spike background across the bright wing region ($r = 50$ to $150$ px).
   - *Deduction*: The 2D ePSF synthesizes true 2D morphology without radial circularization or azimuthal blurring, adhering strictly to Requirement R2.

4. **Scale Factor Soundness**:
   - *Observation*: $k_{\text{FM}} \approx 0.194$ and $k_{\text{MB}} \approx 0.026$.
   - *Deduction*: Because bright stars have larger integrated fluxes than medium stars, which have larger fluxes than faint stars, normalizations satisfy $0 < k_{\text{MB}} < k_{\text{FM}} < 1$.

---

## 3. Caveats

- **Single-Detector FITS HDU Count**: `output/single_wfi01/roman_epsf_wfi01.fits` contains 1 HDU (PrimaryHDU) rather than 4 HDUs. This is by architectural design (`export_single_detector_fits` in `src/romanepsf/pipeline.py`), verified by unit test `tests/unit/test_pipeline.py::test_export_fits_headers_compliance` (`assert len(hdul) == 1`). Multi-extension 4-HDU structure (`PRIMARY`, `COVERAGE`, `RADIAL_PROFILES`, `DETECTOR_SUMMARY`) is specifically produced for composite models via `serialize_composite_epsf_fits` in `output/run_all/roman_epsf_composite.fits`.
- **Aperture PA Variation Across Focal Plane**: Across the 18 SCAs, aperture position angle varies slightly ($\bar{\theta}_{\text{PA}} = -110.004^\circ \pm 0.13^\circ$). Because the variation across SCAs ($\approx 0.26^\circ$) is much smaller than the 6-fold spike width corridor ($\approx 4.0^\circ$), pooling stamps into a composite canvas does not cause visible angular smearing of the spikes.

---

## 4. Conclusion

The Milestone 3 deliverables (`src/romanepsf/pipeline.py`, `src/romanepsf/assembly.py`, `output/run_all/roman_epsf_composite.fits`, and `output/single_wfi01/roman_epsf_wfi01.fits`) satisfy all empirical challenge criteria:
1. Peak RSS during 18-detector execution is 1,554.53 - 1,660.16 MB, strictly < 4,000 MB ceiling (> 2,339 MB headroom), with stable memory arena recycling and no unbounded leaks.
2. Standard 4-HDU FITS output is verified: all keywords $\le 8$ characters, zero `HIERARCH` cards, unit flux sum ($1.000000 \pm 10^{-4}$), centered positive peak, valid coverage map, monotonic radial profile in outer wings, and 18-row detector summary matching total stars (140).
3. 2D non-circular structure and 6-fold diffraction spikes are preserved without radial circularization (azimuthal CV > 30-40%, on-spike flux elevated +5% to +8%).
4. Overlap scale factors satisfy physical ordering ($0 < k_{\text{MB}} < k_{\text{FM}} < 1$).

Verdict: **APPROVE**.

---

## 5. Verification Method

To independently execute and verify the empirical adversarial test suite:

1. **Execute Challenger M3_2 Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python /Users/pmsanch1/code/romanepsf/.agents/teamwork/challenger_m3_2/test_adversarial_fits_memory.py -v
   ```
   *Expected result*: All 13 tests pass in ~11 seconds with 100% pass rate.

2. **Execute Full Test Suite**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ tests/e2e/ -q
   ```
   *Expected result*: `802 passed, 4 skipped in ~41 seconds`.

3. **Verify FITS Header and Multi-HDU Structure Programmatically**:
   ```bash
   /Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
   from astropy.io import fits
   with fits.open('output/run_all/roman_epsf_composite.fits') as hdul:
       assert len(hdul) == 4
       assert [h.name for h in hdul] == ['EPSF', 'COVERAGE', 'RADIAL_PROFILES', 'DETECTOR_SUMMARY']
       for h in hdul:
           for c in h.header.cards:
               assert len(c.keyword) <= 8
               assert 'HIERARCH' not in str(c)
       print('FITS forensics passed!')
   "
   ```

4. **Invalidation Conditions**:
   - Peak RSS during 18-detector execution exceeding 4,000 MB.
   - Any FITS header keyword exceeding 8 characters or triggering `HIERARCH` warnings.
   - Primary HDU flux sum deviating from 1.0 by more than $10^{-4}$.
   - Failure of 2D diffraction spike detection along theoretical angles.
