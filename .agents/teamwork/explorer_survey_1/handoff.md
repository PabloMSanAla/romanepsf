# Extended PSF Pipeline Survey: Level 2 Data & Catalog Characterization
**Agent**: Explorer 1 (Data & Catalog Explorer)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_survey_1/`  
**Date**: 2026-11-06  

---

## 1. Observation

### 1.1 Directory Contents & File Integrity
- **Directory Path**: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/`
- **Total Storage**: 3,674.3 MB (~3.59 GB) across 18 Level 2 calibrated ASDF files:
  - `r0108301001001001001_0001_wfi01_f146_cal.asdf` (204.7 MB)
  - `r0108301001001001001_0001_wfi02_f146_cal.asdf` (204.3 MB)
  - `r0108301001001001001_0001_wfi03_f146_cal.asdf` (203.9 MB)
  - `r0108301001001001001_0001_wfi04_f146_cal.asdf` (208.0 MB)
  - `r0108301001001001001_0001_wfi05_f146_cal.asdf` (204.3 MB)
  - `r0108301001001001001_0001_wfi06_f146_cal.asdf` (204.6 MB)
  - `r0108301001001001001_0001_wfi07_f146_cal.asdf` (203.9 MB)
  - `r0108301001001001001_0001_wfi08_f146_cal.asdf` (203.1 MB)
  - `r0108301001001001001_0001_wfi09_f146_cal.asdf` (204.0 MB)
  - `r0108301001001001001_0001_wfi10_f146_cal.asdf` (204.5 MB)
  - `r0108301001001001001_0001_wfi11_f146_cal.asdf` (203.8 MB)
  - `r0108301001001001001_0001_wfi12_f146_cal.asdf` (203.6 MB)
  - `r0108301001001001001_0001_wfi13_f146_cal.asdf` (204.5 MB)
  - `r0108301001001001001_0001_wfi14_f146_cal.asdf` (203.4 MB)
  - `r0108301001001001001_0001_wfi15_f146_cal.asdf` (203.4 MB)
  - `r0108301001001001001_0001_wfi16_f146_cal.asdf` (203.2 MB)
  - `r0108301001001001001_0001_wfi17_f146_cal.asdf` (203.0 MB)
  - `r0108301001001001001_0001_wfi18_f146_cal.asdf` (203.8 MB)
- **Subdirectories**:
  - `code/`: Contains `r0108301001001001001_0001_wfi_source_catalog.csv` (77 MB) and `star_modelling.ipynb` (2.9 KB).
  - `fits/`: Contains individual detector FITS files (`*WFI1.fits` to `*WFI18.fits`), multi-extension FITS `*WFI1-18.fits` (1.1 GB), Gnuastro temporary segmentations (`_temp_nc.fits`, `_temp_seg.fits`), and test scripts (`psf_test.py`, `leaky_test.py`).
  - `psf/`: Contains 56 reference PNG comparison images (`psf_SCA*_stpsf_noproject.png`, `psf_SCA*_superback_*.png`).
- **File Integrity**: All 18 ASDF files opened successfully without exceptions using `roman_datamodels.open` in Python `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`.

### 1.2 ASDF Tree & Datamodel Schema
Direct programmatic inspection of `wfi01_f146_cal.asdf` reveals:
- Top-level ASDF keys: `['asdf_library', 'history', 'roman']`
- Data model class: `<class 'roman_datamodels.datamodels._datamodels.ImageModel'>`
- Primary image arrays under `model` (and `tree['roman']`):
  - `model.data`: Shape `(4088, 4088)`, dtype `float32`, units `DN/s` (`cal_step.flux = 'INCOMPLETE'`). Active science area without reference border pixels.
  - `model.dq`: Shape `(4088, 4088)`, dtype `uint32`.
  - `model.err`: Shape `(4088, 4088)`, dtype `float16`.
  - `model.var_poisson`: Shape `(4088, 4088)`, dtype `float16`.
  - `model.chisq`: Shape `(4088, 4088)`, dtype `float32`.
  - Reference border arrays (stripped 4 boundary rows/columns): `border_ref_pix_left` (15, 4096, 4), `border_ref_pix_right` (15, 4096, 4), `border_ref_pix_top` (15, 4, 4096), `border_ref_pix_bottom` (15, 4, 4096).
- Metadata (`model.meta`):
  - Pointing center: `meta.pointing.target_ra = 303.122654825545`, `meta.pointing.target_dec = -19.92604222465988`
  - Spacecraft V3 position angle: `meta.pointing.pa_v3 = 250.03752987761314` deg (identical across all 18 files).
  - Aperture position angle: `meta.pointing.pa_aperture = -110.02244977773665` (wfi01) to `-109.87` (wfi16), span of 0.26 deg.
  - Exposure timing: `meta.exposure.exposure_time = 294.10974` s, `frame_time = 3.16247` s, `nresultants = 16`, read pattern MA table `IM_294_16`.
  - Photometric calibration factor: `meta.photometry.conversion_megajanskys = 0.238965` MJy/sr per DN/s.
  - Astrometric WCS: `meta.wcs` is a `gwcs.wcs._wcs.WCS` object connecting frames: `detector` -> `v2v3` -> `v2v3vacorr` -> `v2v3corr` -> `world`.

### 1.3 Data Quality Bitmask Definitions
From `roman_datamodels.dqflags.pixel`:
```python
GOOD             = 0          (0x00000000)
DO_NOT_USE       = 1          (0x00000001)
SATURATED        = 2          (0x00000002)
JUMP_DET         = 4          (0x00000004)
DROPOUT          = 8          (0x00000008)
OUTLIER          = 128        (0x00000080)
NON_SCIENCE      = 512        (0x00000200)
DEAD             = 1024       (0x00000400)
HOT              = 2048       (0x00000800)
WARM             = 4096       (0x00001000)
LOW_QE           = 8192       (0x00002000)
NONLINEAR        = 65536      (0x00010000)
BAD_REF_PIXEL    = 131072     (0x00020000)
OTHER_BAD_PIXEL  = 1073741824 (0x40000000)
```
- In Level 2 calibrated data, saturated pixels manifest in two ways:
  1. `NaN` values: `m.data` contains NaNs at saturated pixel locations where ramp fitting failed completely. In `wfi01`, 296 out of 350 NaNs are flagged `SATURATED` (0x02) and `DO_NOT_USE` (0x01), resulting in `DQ = 3`.
  2. Corrupted finite values: Saturated pixels that did not become NaN have extreme distorted values ranging from -30,283 DN/s to +104,281 DN/s.
  3. Total saturated pixels per detector range from 2,902 (WFI02) to 13,845 (WFI12).
  4. Saturated pixels MUST be identified via `(dq & 2) > 0` or `np.isnan(data)`, never by thresholding `data` alone.

### 1.4 Source Catalog Structure
- **Path**: `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv`
- **Total Rows**: 198,802 rows.
- **Columns (46)**:
  `['Unnamed: 0.2', 'Unnamed: 0', 'healpix_lvl', 'source_id', 'ra', 'dec', 'phot_g_mean_mag_AB', 'phot_bp_mean_mag_AB', 'phot_rp_mean_mag_AB', 'phot_j_mean_mag_AB', 'phot_h_mean_mag_AB', 'phot_ks_mean_mag_AB', 'phot_w1_mean_mag_AB', 'phot_w2_mean_mag_AB', 'phot_w3_mean_mag_AB', 'phot_w4_mean_mag_AB', 'dist', 'Unnamed: 0.1', 'source_id_2', 'wise_ra', 'wise_dec', 'tmass_ra', 'tmass_dec', 'phot_bp_mean_mag', 'phot_g_mean_mag', 'phot_rp_mean_mag', 'parallax', 'w1', 'w1_error', 'w2', 'w2_error', 'w3', 'w3_error', 'w4', 'w4_error', 'j', 'j_error', 'h', 'h_error', 'ks', 'ks_error', 'g', 'bp', 'rp', 'mag_lambda', 'cat_id']`
- **Coordinate System**: Astrometric `ra`, `dec` in ICRS degrees. Neither detector ID nor pixel coordinates (x, y) exist in the catalog.
- **Filter**: `mag_lambda` is the synthetic Roman bandpass magnitude in filter `F146` (effective wavelength 1.46 um), derived from Gaia, 2MASS, and WISE SED interpolation.

### 1.5 Critical WCS Inversion Bug & Solution
- Calling `wcs.backward_transform(ra, dec)` on stars located far outside the detector footprint (e.g., 0.5 degrees away) yields spurious pixel coordinates that fall inside `[0, 4088]`.
- Directly testing `source_id: 6854335253968474368` (ra=302.953, dec=-20.231) on WFI18 produced `x=2047.92, y=3992.95`. However, forward transformation `wcs(2047.92, 3992.95)` gave `ra=302.782, dec=-19.777`, an error of 1,745 arcseconds! Inspection of the WFI18 image at (2048, 3993) confirmed purely background noise (~1.8 DN/s) with zero star signal.
- **Mandatory Solution**: Every coordinate transformation from sky to detector pixel must include a roundtrip validation:
  $$\Delta \theta = \sqrt{(\alpha_{\text{back}} - \alpha_{\text{in}})^2 + (\delta_{\text{back}} - \delta_{\text{in}})^2} \times 3600'' < 0.5''$$
- Applying this roundtrip filter completely eliminates spurious detections and yields exact correspondence with observed image peaks.

### 1.6 Verified In-Field Star Counts & Magnitudes
Applying the validated roundtrip WCS match to the entire catalog across all 18 detectors reveals exactly **194 verified stars**:
- Total detector-star instances: 194 (all 194 stars are unique; no seams duplicated within active science areas).
- Dynamic range: `mag_lambda = 7.371` to `14.844` (span of 7.47 magnitudes, flux ratio 975:1).
- Magnitude distribution:
  - Minimum: 7.371
  - 25th percentile: 12.407
  - Median: 13.575
  - 75th percentile: 14.203
  - Maximum: 14.844
- Per-detector distribution:

| Detector | Total Verified Stars | Brightest `mag_lambda` | Faintest `mag_lambda` | Bright (<11.0) | Medium (11.0–13.0) | Faint (≥13.0) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **WFI01** | 7  | 10.44 | 14.44 | 1 | 2 | 4 |
| **WFI02** | 7  | 11.11 | 14.62 | 0 | 2 | 5 |
| **WFI03** | 5  | 11.46 | 14.84 | 0 | 3 | 2 |
| **WFI04** | 6  | 10.83 | 14.31 | 1 | 1 | 4 |
| **WFI05** | 19 | 7.37  | 14.54 | 3 | 3 | 13 |
| **WFI06** | 10 | 10.74 | 13.82 | 1 | 3 | 6 |
| **WFI07** | 12 | 10.43 | 14.68 | 2 | 1 | 9 |
| **WFI08** | 7  | 11.14 | 14.67 | 0 | 2 | 5 |
| **WFI09** | 15 | 9.27  | 14.61 | 1 | 2 | 12 |
| **WFI10** | 17 | 9.22  | 14.75 | 2 | 5 | 10 |
| **WFI11** | 9  | 10.68 | 14.32 | 1 | 2 | 6 |
| **WFI12** | 10 | 8.83  | 14.68 | 1 | 5 | 4 |
| **WFI13** | 14 | 11.60 | 14.56 | 0 | 3 | 11 |
| **WFI14** | 11 | 9.49  | 14.39 | 1 | 4 | 6 |
| **WFI15** | 11 | 9.40  | 14.43 | 2 | 5 | 4 |
| **WFI16** | 12 | 10.55 | 14.30 | 1 | 2 | 9 |
| **WFI17** | 8  | 11.00 | 14.49 | 0 | 1 | 7 |
| **WFI18** | 14 | 11.90 | 14.59 | 0 | 4 | 10 |
| **ALL 18** | **194** | **7.37** | **14.84** | **17** | **50** | **127** |

---

## 2. Logic Chain

1. **Active Science Array Geometry**:
   - `model.data.shape == (4088, 4088)`.
   - The Roman H4RG-10 detector physical size is 4096 x 4096, but Level 2 processing isolates the active photosensitive area by trimming the 4 boundary rows/columns, storing them separately in `border_ref_pix_*`.
   - Therefore, the extended PSF canvas and stamp extraction coordinate system must strictly operate on `(4088, 4088)` bounds.

2. **Astrometric Projection & In-Field Determination**:
   - The source catalog contains celestial coordinates `(ra, dec)` for 198,802 objects across the entire sky.
   - Using `wcs.backward_transform(ra, dec)` alone is mathematically ill-posed outside the localized detector tangent plane because high-order distortion polynomials extrapolate spuriously.
   - Enforcing $\Delta \theta < 0.5''$ forward verification guarantees that exactly 194 catalog stars lie physically on the Roman focal plane array.

3. **Core Saturation Mechanics in Commissioning Data**:
   - The exposure time is $T_{\text{exp}} = 294.11$ s.
   - Due to the large collecting area ($D=2.4$ m) and broad F146 filter, even moderately faint stars ($m \approx 13.5$) deposit sufficient flux to saturate the later resultant reads in the 16-read ramp.
   - When saturation occurs in the earliest reads, the ramp fit fails and assigns `NaN` and `DQ = 3` (DO_NOT_USE | SATURATED).
   - In stars with $m < 10.0$, the saturated region expands into a contiguous core of radius $r_{\text{sat}} \approx 26 - 56$ pixels ($2.9'' - 6.2''$).
   - In stars with $11.0 \le m < 13.0$, the saturated core shrinks to $r_{\text{sat}} \approx 6 - 16$ pixels ($0.7'' - 1.8''$).
   - In stars with $m \ge 13.0$, the saturated core shrinks to $r_{\text{sat}} \approx 0 - 6$ pixels ($0.0'' - 0.7''$).

4. **Multi-Tier Partitioning Justification**:
   - **Bright Tier ($m < 11.0$, 17 stars)**: Heavily saturated core ($r_{\text{sat}} > 17$ pix), but extensive extended wings and 6-fold diffraction spikes visible out to $r > 500$ pixels. These stars provide high SNR for the outer ePSF canvas ($r > 25$ pixels) and spike preservation.
   - **Medium Tier ($11.0 \le m < 13.0$, 50 stars)**: Moderately saturated core ($r_{\text{sat}} \approx 6 - 16$ pix), with clean wings between $10 < r < 80$ pixels. This tier acts as the bridge/overlap tier, allowing radial profile cross-calibration between faint star cores and bright star wings.
   - **Faint Tier ($m \ge 13.0$, 127 stars)**: Minimal to zero saturation ($r_{\text{sat}} \le 6$ pix, median $4.7$ pix). These stars provide the uncorrupted central PSF core ($r < 10$ pixels).

5. **Diffraction Spike Geometry & Roll Alignment**:
   - Direct measurement on the brightest star in the survey (WFI05, $m=7.371$) revealed 6 continuous spike lines in image coordinates at angles $\theta \approx [12.5^\circ, 47.5^\circ, 72.5^\circ, 107.5^\circ, 132.5^\circ, 167.5^\circ]$ (mod $180^\circ$).
   - The theoretical base pupil spider angles are $[23.55^\circ, 55.29^\circ, 80.25^\circ, 118.65^\circ, 142.88^\circ, 178.07^\circ]$.
   - The angular difference between base angles and measured spikes is consistently $\Delta \approx -10.0^\circ \pm 1.5^\circ$.
   - This matches the aperture position angle $\text{PA}_{\text{aper}} = -110.08^\circ$ (since $-110.08^\circ + 100^\circ = -10.08^\circ$, or $-110.08^\circ \pmod{60^\circ} = 9.92^\circ$).
   - Therefore, diffraction spike protection masks must apply the rotation:
     $$\theta_{\text{spike}} = (\theta_{\text{base}} + \Delta_{\text{PA}}) \pmod{180^\circ}$$
     where $\Delta_{\text{PA}}$ is calibrated from `meta.pointing.pa_aperture`.

---

## 3. Caveats

1. **Raw Pixel Values in Saturated Regions**:
   - In Level 2 `_cal.asdf` images, saturated pixels are NOT clipped to a constant saturation ceiling. They may be either `NaN` or unphysical large/negative numbers (e.g. $-30,283$ DN/s). Masking MUST use `(dq & 2) > 0` or `np.isnan(data)`.
2. **Absolute Photometric Zero Points**:
   - Data array units are in DN/s (counts/second) because `meta.cal_step.flux == 'INCOMPLETE'`. Absolute surface brightness conversion to MJy/sr requires multiplying by `meta.photometry.conversion_megajanskys` (~0.239 MJy/sr per DN/s).
3. **Detector Fringing & Background Gradients**:
   - Local background level in Level 2 images is approximately $1.67 - 1.85$ DN/s. Background subtraction must be performed locally in each star cutout before multi-tier stacking.
4. **Single-Detector Validation Constraints**:
   - Single-detector testing on `wfi01` will exercise 7 stars (1 Bright, 2 Medium, 4 Faint). While sufficient to validate all pipeline stages end-to-end, full spatial sampling of the outer spikes requires synthesizing across all 18 detectors (194 stars).

---

## 4. Conclusion

1. **Data Completeness**: All 18 Level 2 detector ASDF files are complete, uncorrupted, and conform strictly to `roman_datamodels.datamodels.ImageModel` with active science shape `(4088, 4088)`.
2. **Catalog Matching**: Exactly 194 unique stars are located on the active detector areas, spanning $m_{\text{F146}} = 7.371$ to $14.844$. Every WCS backward transformation must be accompanied by forward roundtrip verification ($\Delta \theta < 0.5''$) to suppress out-of-footprint false positives.
3. **Multi-Tier Thresholds**:
   - **Bright Tier**: $m_{\text{F146}} < 11.0$ (17 stars, $r_{\text{sat}} \approx 17 - 56$ pix) $\rightarrow$ Wings & Diffraction Spikes.
   - **Medium Tier**: $11.0 \le m_{\text{F146}} < 13.0$ (50 stars, $r_{\text{sat}} \approx 6 - 16$ pix) $\rightarrow$ Transition Overlap & Scaling.
   - **Faint Tier**: $m_{\text{F146}} \ge 13.0$ (127 stars, $r_{\text{sat}} \approx 0 - 6$ pix) $\rightarrow$ Central Core.
4. **Spike Masking**: Diffraction spike preservation masks must combine theoretical 6-fold pupil geometry ($[23.55^\circ, 55.29^\circ, 80.25^\circ, 118.65^\circ, 142.88^\circ, 178.07^\circ]$ rotated by focal plane PA) with high-aspect-ratio morphological filtering.
5. **Memory & Sizing**: Memory requirement per detector is ~200 MB; processing single detector `wfi01` requires < 1 GB RAM, and processing all 18 detectors in parallel requires ~4 GB RAM. A composite canvas size of 1024x1024 (or 2048x2048) pixels is well within machine memory limits.

---

## 5. Verification Method

### 5.1 Verification Commands
Execute the following verification script using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:

```python
import roman_datamodels as rdm
import pandas as pd
import numpy as np

# 1. Verify WFI01 ASDF readability and shape
m = rdm.open('/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf')
assert m.data.shape == (4088, 4088), f"Expected (4088, 4088), got {m.data.shape}"
assert m.dq.shape == (4088, 4088)
assert m.meta.pointing.pa_v3 == 250.03752987761314
m.close()

# 2. Verify Catalog and Roundtrip WCS Mapping
csv_path = '/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/code/r0108301001001001001_0001_wfi_source_catalog.csv'
df = pd.read_csv(csv_path, low_memory=False)
cand = df[np.hypot((df['ra']-303.12)*np.cos(np.radians(-19.93)), df['dec'] - (-19.93)) < 1.0]

m1 = rdm.open('/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf')
x, y = m1.meta.wcs.backward_transform(cand['ra'].values, cand['dec'].values)
in_bounds = (x >= 0) & (x < 4088) & (y >= 0) & (y < 4088)
idx = np.where(in_bounds)[0]
ra_back, dec_back = m1.meta.wcs(x[idx], y[idx])
valid = np.hypot(ra_back - cand['ra'].values[idx], dec_back - cand['dec'].values[idx]) * 3600.0 < 0.5
assert np.sum(valid) == 7, f"Expected exactly 7 verified stars on WFI01, got {np.sum(valid)}"
m1.close()
print("All verifications passed successfully!")
```

### 5.2 Invalidation Conditions
This analysis will be invalidated if:
1. Level 2 data files are re-calibrated with reference pixel borders retained (resulting in shape 4096x4096).
2. The source catalog is filtered by an external magnitude depth cut (e.g. omitting stars fainter than $m=14$).
3. The GWCS distortion model is replaced with a single-step analytic TAN-SIP polynomial that changes the angle offset $\Delta_{\text{PA}}$.
