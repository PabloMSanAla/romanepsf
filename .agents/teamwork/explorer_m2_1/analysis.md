# Technical Analysis: Postage Stamp Extraction, Adaptive Sizing, Subpixel Realignment, and Background Subtraction

**Author**: Explorer 1 (`explorer_m2_1`)  
**Target Module**: `src/romanepsf/stamps.py` & `tests/unit/test_stamps.py`  
**Milestone**: Milestone 2 (Features 9, 10, 11)  
**Date**: 2026-11-06  

---

## 1. Executive Summary

Milestone 2 addresses the empirical postage stamp extraction and multi-tier synthesis of the 2D Extended Point Spread Function (ePSF) for the Roman Space Telescope Wide Field Instrument (WFI). This analysis establishes the detailed design blueprint for `src/romanepsf/stamps.py` and its accompanying unit test suite `tests/unit/test_stamps.py`.

The module serves as the primary bridge between calibrated Level 2 detector science data (`RomanL2Data`) and the downstream multi-tier PSF assembly pipeline (`src/romanepsf/assembly.py` and `src/romanepsf/profile.py`). It must robustly handle:
1. **Adaptive Stamp Sizing by Tier (Feature 9)**: Odd dimensions ($81\times 81$ faint, $201\times 201$ medium, and dynamically scaled up to $1001\times 1001$ bright) to capture diffraction spikes and extended wings without waste or boundary truncation.
2. **Subpixel Realignment (Feature 10)**: 3rd-order bicubic spline shifting with order-0 mask synchronization to place each star's continuous centroid at the exact pixel center $((S-1)/2, (S-1)/2)$.
3. **Background Estimation & Subtraction**: Annular 3-sigma clipped median and percentile estimation to remove the ~1.8 MJy/sr diffuse foreground prior to wing profiling and cross-tier flux matching.
4. **Faint Core DQ Bit 1 Protection (Feature 11)**: Preventing ramp-fit saturation flags (DQ bit 1, value 2) from hollowing out valid core pixels in faint stars ($m \ge 13.0$).
5. **Catalog Column Robustness**: Resolving the escalated bug in `src/stamps.py:168` where non-Gaia sources in Roman commissioning catalogs lack `phot_g_mean_mag`.

---

## 2. Problem Decomposition & Algorithmic Blueprint

### 2.1 Feature 9: Adaptive Stamp Sizing

#### Physical Rationale
The Roman WFI optical design features a 2.4-meter primary mirror with a 6-legged secondary spider. In Level 2 exposures (pixel scale $0.11''/\text{pixel}$), stars exhibit dramatic dynamic range ($m \sim 7.37$ to $m > 16.0$):
- **Bright Stars** ($m < 11.0$): Extended diffraction spikes extend out to $r > 500$ pixels. A fixed small cutout truncates the spikes and wings, leading to severe edge discontinuities and normalization bias.
- **Medium Stars** ($11.0 \le m < 13.0$): Spanning radii $8 < r < 45$ pixels, these stars serve as the photometric bridge between the unsaturated core and extended wings.
- **Faint Stars** ($m \ge 13.0$): Used exclusively for the unsaturated core ($r < 10$ pixels). Excessive cutout sizes waste memory and introduce contaminant contamination from crowded fields.

#### Mathematical Formulation
For bright stars, the stamp dimension is analytically computed from the Moffat profile extension to limiting surface brightness $\mu_{\text{lim}} = 30.0\,\text{mag}/\text{arcsec}^2$:
$$\mu(r) = \mu_0 + 2.5 \beta \log_{10}\left(1 + \left(\frac{r}{\alpha}\right)^2\right)$$
where $\alpha = 0.08''$, $\beta = 1.52$, and $\mu_0 = m + 2.5 \log_{10}\left(\frac{\pi \alpha^2}{\beta - 1}\right)$.
Solving for the extension radius:
$$r_{\text{ext}} = \alpha \sqrt{10^{\frac{\mu_{\text{lim}} - \mu_0}{2.5 \beta}} - 1}\quad [\text{arcseconds}]$$
To ensure full coverage of diffraction spikes and low-surface-brightness wings, a factor of $2.2\times$ the Moffat radius is converted to detector pixels:
$$S_{\text{raw}} = \text{round}\left(\frac{r_{\text{ext}} \times 2.2}{\text{pixel\_scale}}\right)$$
$$S = \min\left(\max(S_{\text{raw}}, 301), S_{\text{bright\_max}}\right)$$

#### Invariant: Strict Odd Dimension
To ensure that the center pixel has exact integer indices $(cx, cy) = ((S-1)/2, (S-1)/2)$ without half-pixel ambiguity:
$$\text{if } S \equiv 0 \pmod 2 \implies S \leftarrow S + 1$$

| Tier | Magnitude Range ($m_{\text{F146}}$) | Default Size ($S \times S$) | Radial Reach ($r_{\text{max}}$) | Primary Purpose |
|---|---|---|---|---|
| **Faint** | $m \ge 13.0$ | $81 \times 81$ | 40 px ($4.4''$) | Unsaturated core ($r < 10$ px) |
| **Medium** | $11.0 \le m < 13.0$ | $201 \times 201$ | 100 px ($11.0''$) | Overlap normalization ($8 < r < 45$ px) |
| **Bright** | $m < 11.0$ | $301 \times 301$ to $1001 \times 1001$ | up to 500 px ($55.0''$) | Extended wings & 6-fold spikes |

---

### 2.2 Cutout Extraction & Boundary Margin Handling

#### Mathematical Formulation
Given continuous centroid $(\hat{x}, \hat{y})$ and odd size $S$:
$$ix = \text{int}(\text{round}(\hat{x})), \quad iy = \text{int}(\text{round}(\hat{y})), \quad \text{half} = (S - 1) // 2$$
$$x_0 = ix - \text{half}, \quad x_1 = ix + \text{half} + 1$$
$$y_0 = iy - \text{half}, \quad y_1 = iy + \text{half} + 1$$

The intersection with the $4088 \times 4088$ detector boundary is:
$$\text{src\_}x_0 = \max(0, x_0), \quad \text{src\_}x_1 = \min(W, x_1)$$
$$\text{src\_}y_0 = \max(0, y_0), \quad \text{src\_}y_1 = \min(H, y_1)$$
$$\text{dst\_}x_0 = \text{src\_}x_0 - x_0, \quad \text{dst\_}x_1 = \text{dst\_}x_0 + (\text{src\_}x_1 - \text{src\_}x_0)$$
$$\text{dst\_}y_0 = \text{src\_}y_0 - y_0, \quad \text{dst\_}y_1 = \text{dst\_}y_0 + (\text{src\_}y_1 - \text{src\_}y_0)$$

#### Boundary Invariants
1. Out-of-bounds pixels in science flux are padded with `np.nan`.
2. Out-of-bounds pixels in Data Quality (DQ) are padded with `DQ_FLAGS["DO_NOT_USE"]` ($1$).
3. Cutout dimensions are invariant: shape is guaranteed to be $(S, S)$.

---

### 2.3 Feature 10: Subpixel Bicubic Realignment

#### Centroid Shift Mechanics
The continuous centroid $(\hat{x}, \hat{y})$ refined in Milestone 1 generally has non-zero fractional components relative to the integer center $(ix, iy)$:
$$\Delta x = \hat{x} - ix \in [-0.5, 0.5], \quad \Delta y = \hat{y} - iy \in [-0.5, 0.5]$$
To position the physical center of the stellar flux exactly at the central pixel index $(cx_0, cy_0) = (\text{half}, \text{half})$, the image coordinate grid must be shifted by:
$$\text{shift}_x = -\Delta x, \quad \text{shift}_y = -\Delta y$$

#### Interpolation Method & NaN Protection
1. **NaN Pre-filling**: Higher-order spline kernels (bicubic order 3) propagate NaNs across their full support footprint ($\pm 2$ pixels). Prior to shifting, all non-finite pixels are temporarily replaced with the local background estimate `bkg` (or $0.0$).
2. **Flux Image Shifting**: Evaluated using `scipy.ndimage.shift` with `order=3`, `mode="constant"`, and `cval=bkg`.
3. **Boolean Mask Shifting**: Shifted synchronously using nearest-neighbor interpolation (`order=0`), `mode="constant"`, and `cval=1.0`.
4. **Boundary Re-masking**: Any pixel shifted in from outside the boundary or non-finite in the aligned flux is strictly marked `True` in the mask:
   $$\text{aligned\_mask} \leftarrow \text{aligned\_mask} \mid (\neg\text{np.isfinite}(\text{aligned\_data}))$$
5. **Flux Conservation**: Bicubic spline shifting conserves integrated stellar flux to $< 1\%$ across all subpixel offsets.

---

### 2.4 Background Estimation and Subtraction

#### Astronomical Context
Roman Level 2 images calibrated in surface brightness (MJy/sr) include a diffuse astrophysical sky background (zodiacal light, Galactic cirrus, cosmic infrared background) of $\sim 1.5 - 2.0\,\text{MJy/sr}$ in F146.
Failure to subtract this background per stamp causes two critical errors:
1. **Outer Wing Leveling**: The radial profile asymptotically levels off to $B_{\text{sky}}$ instead of decaying towards zero.
2. **Scale Factor Distortion**: In overlap regions, cross-tier flux ratios $k = \text{median}(f_{\text{in}} / f_{\text{out}})$ become non-linear functions of radius because $(f_{\text{in}} + B) / (f_{\text{out}} + B) \neq f_{\text{in}} / f_{\text{out}}$.

#### Dual Estimator Architecture
1. **Annular Sigma-Clipped Median** (`method="annulus"`):
   - Defined between radii $r_{\text{in}} = 0.80 \cdot r_{\text{max}}$ and $r_{\text{out}} = 0.98 \cdot r_{\text{max}}$ centered on the star.
   - Restricts to valid, unmasked pixels (`~mask & np.isfinite(stamp)`).
   - Iteratively rejects outliers ($3\sigma$ clipping with robust MAD standard deviation $1.4826 \times \text{MAD}$).
2. **Percentile Estimator** (`method="percentile"`):
   - Fallback when fewer than 15 valid pixels exist in the annulus (e.g. cutouts near detector boundaries or heavily masked crowded fields).
   - Computes the 10th percentile of valid pixels in the outer half ($r \ge 0.5 \cdot r_{\text{max}}$).
3. **Subtraction & Record**:
   - $\text{stamp}_{\text{sub}} = \text{stamp} - \text{bkg\_val}$.
   - Store `bkg_value` and `bkg_rms` on `StellarStamp`.

---

### 2.5 Feature 11: Faint Core DQ Bit 1 Protection

#### The Defect in Naive DQ Masking
In Roman commissioning Level 2 data, the ramp fitting step in STScI's calwebb/roman_pipeline frequently sets Data Quality Bit 1 (`SATURATED`, value 2) on the central pixel of faint stars ($m \ge 13.0$). This occurs due to high variance or cosmic ray jump detection false-positives across the ramp fit, even when the measured surface brightness is well below the true physical saturation limit (~50,000 DN).
If bit 1 is naively masked for faint stars, the central peak is zeroed out, creating a "hollowed-out core" artifact in the stacked faint PSF.

#### Protection Algorithm
For all stars with `tier == "faint"`:
If `faint_core_protect_finite` is enabled (default `True` in `configs/default.yaml`):
1. In the inner core zone ($r \le 4.0$ pixels):
2. If the measured flux is finite and positive ($\text{flux} > 0$):
3. Bit 1 (`SATURATED`) is unflagged.
4. Genuinely corrupt flags (Bit 0 `DO_NOT_USE`, Bit 2 `JUMP_DET`, Bit 3 `DROPOUT`) remain strictly masked.
5. In bright stars, Bit 1 saturation IS preserved and masked to protect the extended wings from non-linear detector response.

---

### 2.6 Escalated Bug Fix: Catalog Column Dependency (`src/stamps.py:168`)

#### Observation
As documented in `TEST_READY.md` line 121, `src/stamps.py:168` contained:
```python
mag = float(row["phot_g_mean_mag"])
```
In simulated commissioning Level 2 catalogs (`r0108301001001001001_0001_wfi_source_catalog.csv`), Gaia $G$ magnitudes are absent for 2MASS and WISE infrared stars, resulting in `NaN`. This crashed stamp extraction with `ValueError: cannot convert float NaN to integer`.

#### Solution
Implement robust multi-tier column resolution in `_get_row_magnitude(row, preferred_col="mag_lambda")`:
```python
def _get_row_magnitude(row: pd.Series, preferred_col: str = "mag_lambda") -> float:
    if preferred_col in row and pd.notna(row[preferred_col]):
        try:
            return float(row[preferred_col])
        except (ValueError, TypeError):
            pass
    for col in ["mag_lambda", "phot_g_mean_mag", "phot_g_mean_mag_AB", "mag"]:
        if col in row and pd.notna(row[col]):
            try:
                return float(row[col])
            except (ValueError, TypeError):
                continue
    return 15.0  # Safe default faint magnitude
```

---

## 3. Data Structure Contract

### `StellarStamp` (alias `StampData`)
```python
@dataclass
class StellarStamp:
    source_id: Any
    tier: str
    mag: float
    data: np.ndarray            # Sub-pixel aligned flux image (float32)
    mask: np.ndarray            # Boolean mask (True = bad / contaminated / saturated)
    center_original: Tuple[float, float]
    size: int
    norm_factor: float = 1.0    # Photometric scale factor relative to reference tier
    bkg_value: float = 0.0      # Local sky background subtracted from stamp
    bkg_rms: float = 0.0        # Background RMS uncertainty
```

### `process_star_stamps` Signature & Polymorphism
```python
def process_star_stamps(
    l2_data: RomanL2Data,
    catalog_df: pd.DataFrame,
    spikes_cfg: Optional[Any] = None,
    stamps_cfg: Optional[Any] = None,
    max_bright_size: int = 1001,
    max_stars_per_tier: Optional[Dict[str, int]] = None,
    subtract_background: bool = True,
    bkg_method: str = "annulus",
    mag_col: str = "mag_lambda",
    faint_core_protect_finite: bool = True,
) -> Dict[str, List[StellarStamp]]:
```
This signature seamlessly handles:
- E2E test invocations: `process_star_stamps(l2, df)`
- CLI invocations: `process_star_stamps(l2, df, cfg.spikes, cfg.stamps)`
- Legacy positional invocations: `process_star_stamps(l2, df, 1001, {"bright": 10})`

---

## 4. Unit Test Suite Architecture (`tests/unit/test_stamps.py`)

A comprehensive 27-test suite organized across 6 test classes has been designed and verified:

1. **`TestAdaptiveStampSize` (7 tests)**:
   - Faint default size 81x81
   - Medium default size 201x201
   - Bright scaling: $m=7.37 \to 1001$, $m=9.0 \to \ge 501$, $m=10.8 \to \ge 301$
   - Bright size ceiling clamping (`max_size=501`)
   - Odd dimension invariant across all tiers and magnitudes
   - Custom configurable sizes (`faint_size=61`, `medium_size=151`)
   - Case-insensitive tier handling
2. **`TestExtractCutout` (5 tests)**:
   - Output shape $(S, S)$ and center rounding
   - Centered pixel content mapping
   - Edge boundary padding (`fill_value=np.nan`)
   - Corner boundary padding ($x=0, y=0$)
   - Custom DQ mask fill value (`fill_value=1`)
3. **`TestBackgroundEstimation` (5 tests)**:
   - Annular background recovery within $0.05\,\text{MJy/sr}$
   - Masked contamination immunity in outer annulus
   - Percentile background estimation
   - Zero-median background subtraction verification
   - All-NaN graceful fallback ($0.0, 0.0$)
4. **`TestSubpixelRealignment` (5 tests)**:
   - Gaussian peak centering to exact $((S-1)/2, (S-1)/2)$
   - Flux conservation $< 1\%$ across subpixel shifts
   - Zero-shift identity property within $10^{-5}$
   - Mask synchronous shifting
   - NaN pre-guard preventing spline ringing
5. **`TestFaintCoreDQProtection` (1 test)**:
   - Faint star with finite positive flux and DQ=2 core is preserved without zeroing
6. **`TestProcessStarStampsIntegration` (4 tests)**:
   - Column fallback when `phot_g_mean_mag` is NaN and `mag_lambda` is present
   - `StellarStamp` attribute completeness
   - `max_stars_per_tier` limit compliance
   - Empty catalog graceful handling

---

## 5. Artifact Reference
- Blueprint Implementation: `.agents/teamwork/explorer_m2_1/proposed_stamps.py`
- Test Suite Implementation: `.agents/teamwork/explorer_m2_1/proposed_test_stamps.py`
- Verification Status: **27 passed in 1.77s**
