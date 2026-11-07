# Handoff Report — Explorer M1-1: Packaging, Config & Loader Specifications

**Agent**: Explorer M1-1 (Packaging, Config & Loader Explorer)  
**Working Directory**: `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/`  
**Date**: 2026-11-06  
**Status**: COMPLETE (Hard Handoff)  
**Recipient**: Sub-Orchestrator M1 (`e80d314a-b5a0-43fb-be2e-ceabc982347e`) / Implementer M1-1  

---

## 1. Observation

### 1.1 Existing Workspace & Directory Structure
- **Current Workspace**: `/Users/pmsanch1/code/romanepsf/`
- Directory search (`find_by_name`) revealed:
  - Prototype files reside directly under `src/`: `src/loader.py`, `src/catalog.py`, `src/stamps.py`, `src/masking.py`, `src/profile.py`, `src/assembly.py`.
  - There is currently **no** `pyproject.toml` in the repository root.
  - There is **no** `src/romanepsf/` package folder.
  - There is **no** `configs/default.yaml`.
  - There is **no** `src/romanepsf/config.py`.
  - `src/catalog.py:17` and `src/stamps.py:15` currently import from `src.loader` via `from src.loader import RomanL2Data, get_dq_mask`.

### 1.2 Python Environment & Packaging Infrastructure
Inspection of `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python` (Python 3.12.12):
- Installed build tools:
  - `setuptools`: 84.0.0
  - `wheel`: 0.46.3
  - `pip`: 26.0.1
  - `build`: 1.4.0
  - Note: `hatchling` and `flit_core` are NOT installed.
- Core astronomical & numerical libraries:
  - `roman_datamodels`: 1.1.0
  - `asdf`: 5.4.0
  - `gwcs`: 1.0.3
  - `torch`: 2.14.1 (with verified Apple MPS acceleration: `torch.backends.mps.is_available() == True`)
  - `astropy`: 7.2.2
  - `photutils`: 2.3.0
  - `pandas`: 3.0.1
  - `pyyaml`: 6.0.3
  - `click`: 8.3.1
  - `matplotlib`: 3.10.8
  - `pytest`: 9.0.2

### 1.3 Level 2 Commissioning ASDF Characterization
Direct programmatic inspection of `/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf`:
- Object model: `<class 'roman_datamodels.datamodels._datamodels.ImageModel'>`
- Data array properties:
  - `dm.data`: Shape `(4088, 4088)`, dtype `float32`, units count rate `DN/s` (`meta.cal_step.flux == 'INCOMPLETE'`). Active science array without boundary reference pixels.
  - `dm.dq`: Shape `(4088, 4088)`, dtype `uint32`.
  - `dm.err`: Shape `(4088, 4088)`, dtype `float16`.
  - Reference boundary arrays stored separately: `border_ref_pix_left` `(15, 4096, 4)`, etc.
- Pointing & Astrometric WCS metadata:
  - `dm.meta.pointing.pa_aperture = -110.02244977773665` deg.
  - `dm.meta.wcsinfo.v3yangle = -59.99253` deg.
  - `dm.meta.wcsinfo.vparity = -1`.
  - `dm.meta.wcsinfo.roll_ref = -110.02244977773665` deg.
  - `dm.meta.wcs`: `gwcs.wcs._wcs.WCS` object connecting frames `['detector', 'v2v3', 'v2v3vacorr', 'v2v3corr', 'world']`. Roundtrip forward/backward coordinate transformation on center pixel `(2044.0, 2044.0)` yielded `(2044.0000000366917, 2044.000000027843)` (error $< 10^{-7}$ pixels).
- Photometric calibration metadata:
  - `dm.meta.photometry.conversion_megajanskys = 0.23896534740924835` MJy/sr per DN/s.
  - `dm.meta.photometry.pixel_area = 2.8009783078000727e-13` sr.
  - Calculated pixel scale: $\sqrt{2.800978 \times 10^{-13}} \times 206264.806 = 0.109164''/\text{pixel} \approx 0.11''/\text{pixel}$.
  - Calculated 1 DN/s flux: $F_{1\text{DN/s}} = 0.238965 \times 10^6 \times 2.800978 \times 10^{-13} = 6.693368 \times 10^{-8}$ Jy.
  - Calculated AB zero point: $\text{ZP}_{\text{AB}} = -2.5 \log_{10}(6.693368 \times 10^{-8} / 3631.0) = 26.83595$ mag.
- Saturated Ramp Pixel Artifacts:
  - Saturated pixels where ramp fit failed manifest as `NaN` values with `DQ = 3` (`DO_NOT_USE | SATURATED`).
  - Saturated pixels that did not become `NaN` exhibit corrupted unphysical negative/huge values (e.g. $-30,283$ DN/s). Total flagged bad pixels on WFI01: 8,995 (`get_dq_mask`), plus 1 unflagged NaN = 8,996 total effective bad pixels (`get_effective_mask`).

### 1.4 Interface Contracts & Contract Gaps in Prototype
- In `PROJECT.md` line 74-75:
  `load_l2_image(asdf_path: Path, calibrate: bool = True) -> RomanL2Data`
  Contract requires:
  `Returns RomanL2Data with attributes: data: np.ndarray (4088, 4088), dq: np.ndarray (4088, 4088), err: np.ndarray (4088, 4088), wcs: gwcs.WCS, pa_aperture: float, pixel_scale: float = 0.11, conversion_factor: float.`
- In the prototype `src/loader.py`:
  - `pa_aperture` was omitted from `RomanL2Data` dataclass fields (only stored inside `meta` dict).
  - Shape validation for `(4088, 4088)` was missing.
  - `dm.err` was converted to `float32`, but if uncalibrated was left without scaling checks.
  - `is_calibrated` was not exposed as an explicit attribute, causing potential confusion when downstream modules check calibration status.

---

## 2. Logic Chain

1. **Build System Selection**:
   - `setuptools` 84.0.0 is pre-installed in the designated environment, while `hatchling` and `flit` are absent (Observation 1.2).
   - Therefore, `pyproject.toml` must use standard PEP 517 / PEP 621 table:
     ```toml
     [build-system]
     requires = ["setuptools>=61.0", "wheel"]
     build-backend = "setuptools.build_meta"
     ```
   - Configuring `[tool.setuptools.packages.find] where = ["src"]` enables standard editable installation (`pip install -e .`), making `import romanepsf` universally resolvable.

2. **Package Layout & Namespace Consolidation**:
   - The project requirements demand a modular Python package under `src/romanepsf/` with CLI executable `romanepsf` (Observation 1.1, PROJECT.md).
   - Transitioning from flat `src/*.py` to `src/romanepsf/*.py` prevents namespace collisions and permits clean relative imports (`from .loader import ...`, `from .config import ...`).

3. **Configuration Architecture (`configs/default.yaml` & `config.py`)**:
   - `ORIGINAL_REQUEST.md` (R1) mandates that all operational parameters (stamp sizes, thresholds, tier boundaries, canvas size, etc.) must be configurable via YAML.
   - Using typed dataclasses with nested sections (`PipelineConfig`, `AssemblySection`, `TiersSection`, etc.) provides compile-time autocompletion, type safety, and runtime constraint checking.
   - Supporting dot-notation overrides (e.g. `overrides={"assembly.canvas_size": 2049}`) enables seamless CLI parameter overrides without manually assembling nested dictionaries.
   - Enforcing logical constraints in `validate()` (e.g. `bright_limit < faint_limit`, $r_{\min} < r_{\max}$, $r_a < r_b$, positive canvas size) prevents subtle mathematical bugs downstream.

4. **Level 2 Data Loader Design (`loader.py`)**:
   - Science array shape is strictly `(4088, 4088)` float32 (Observation 1.3). Any shape deviations must immediately raise `ValueError` to prevent misaligned cutouts.
   - Interface compliance requires promoting `pa_aperture: float`, `conversion_factor: float`, and `pixel_scale: float` to first-class attributes on `RomanL2Data` (Observation 1.4).
   - Photometric calibration must multiply both `data` and `err` by `conversion_megajanskys` when `calibrate=True`, while preserving the raw count rates in `raw_data` for background estimation and linearity checks.
   - DQ bitmasking must cover the full 14 flags defined in `roman_datamodels.dqflags.pixel`. Because ramp fits can fail to NaN before setting DQ bits or leave negative distortions, `get_effective_mask` combines `(dq & bitmask) > 0` with `~np.isfinite(data)`.

5. **Automated Verification**:
   - Running the test suite (`proposed_test_loader.py` and `proposed_test_config.py`) verifies all 15 unit tests against real Level 2 ASDF data and mock failure cases, ensuring 100% test pass rate.

---

## 3. Caveats

1. **ASDF File Size & Memory Lifecycle**:
   - Each Level 2 ASDF file is ~204 MB on disk and expands to ~135 MB of active arrays in memory (`data`, `err`, `dq`, `raw_data`).
   - Using `with rdm.open(str(path)) as dm:` ensures the file descriptor is immediately closed upon exit. Downstream pipeline scripts must explicitly delete `l2_data` and trigger `gc.collect()` after extracting stamps to keep peak memory below 4 GB during 18-detector execution.
2. **Aperture Position Angle Fallback**:
   - For simulated commissioning data, `meta.pointing.pa_aperture` is $-110.02^\circ$. If future synthetic or real ASDF files omit `meta.pointing.pa_aperture`, the loader safely falls back to `meta.wcsinfo.roll_ref`.
3. **Array Precision**:
   - The raw `dm.err` array in ASDF is `float16`. The loader explicitly casts it to `float32` upon reading to avoid numerical overflow / underflow during inverse-variance weighting and cross-tier scaling.

---

## 4. Conclusion

1. **Specification Deliverables Complete**:
   All code specifications, configuration schemas, dataclass definitions, and unit tests have been created and verified in `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/`:
   - `proposed_pyproject.toml`
   - `proposed_default.yaml`
   - `proposed_config.py`
   - `proposed_loader.py`
   - `proposed___init__.py`
   - `proposed_test_loader.py`
   - `proposed_test_config.py`
2. **Key Architectural Solutions**:
   - **`pyproject.toml`**: Configured with `setuptools.build_meta`, `src`-layout, Click entry point `romanepsf = romanepsf.cli:cli`, and pytest configuration.
   - **`config.py` & `default.yaml`**: Full 11-section dataclass architecture with dot-notation overrides, constraint validation, and Apple MPS / CUDA / CPU automatic device detection.
   - **`loader.py`**: Full Level 2 ASDF loader returning `RomanL2Data` with all required contract attributes (`pa_aperture`, `conversion_factor`, `pixel_scale`, `data`, `raw_data`, `err`, `dq`, `wcs`), active shape `(4088, 4088)` validation, and comprehensive DQ bitmasking (`get_dq_mask`, `get_effective_mask`).
3. **Readiness for Implementation**:
   - Implementer M1-1 can directly copy these verified reference files to target paths (`pyproject.toml`, `configs/default.yaml`, `src/romanepsf/config.py`, `src/romanepsf/loader.py`, `src/romanepsf/__init__.py`, `tests/unit/test_config.py`, `tests/unit/test_loader.py`).

---

## 5. Verification Method

### 5.1 Verification Commands
Run the full test suite using `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python`:

```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest \
  /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_test_loader.py \
  /Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_test_config.py \
  -v
```

**Observed Result**:
```
============================== 15 passed in 1.45s ==============================
```

### 5.2 Standalone Python Verification Script
```bash
/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -c "
import sys
sys.path.insert(0, '/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1')
import proposed_loader as loader
import proposed_config as config

# 1. Test loader on real commissioning ASDF
asdf_path = '/Users/pmsanch1/storage/ROMAN/simulated_comissioning/PID1083/detectors/r0108301001001001001_0001_wfi01_f146_cal.asdf'
l2 = loader.load_l2_image(asdf_path, calibrate=True)
assert l2.shape == (4088, 4088)
assert l2.detector == 'WFI01'
assert l2.pa_aperture < -100.0
assert l2.is_calibrated is True
print('Loader verification PASSED!')

# 2. Test config loader
yaml_path = '/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_default.yaml'
cfg = config.load_config(yaml_path, overrides={'assembly.canvas_size': 2049})
assert cfg.assembly.canvas_size == 2049
assert cfg.spikes.detector_alignment_offset_deg == -9.70
print('Config verification PASSED!')
"
```

### 5.3 Invalidation Conditions
This specification will be invalidated if:
1. Level 2 pipeline changes output shape from `(4088, 4088)` to include border reference pixels `(4096, 4096)`.
2. Photometric conversion factor key in ASDF metadata is moved from `meta.photometry.conversion_megajanskys`.
3. GWCS frame nomenclature changes from `['detector', 'v2v3', 'v2v3vacorr', 'v2v3corr', 'world']`.

---

## 6. Implementation Plan for Implementer M1-1

### Step 1: Initialize Package Layout & `pyproject.toml`
1. Copy `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_pyproject.toml` to `/Users/pmsanch1/code/romanepsf/pyproject.toml`.
2. Create directories:
   - `mkdir -p /Users/pmsanch1/code/romanepsf/src/romanepsf`
   - `mkdir -p /Users/pmsanch1/code/romanepsf/configs`
   - `mkdir -p /Users/pmsanch1/code/romanepsf/tests/unit`
3. Copy `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed___init__.py` to `/Users/pmsanch1/code/romanepsf/src/romanepsf/__init__.py`.
4. Install package in editable mode:
   `/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/pip install -e /Users/pmsanch1/code/romanepsf/`

### Step 2: Implement Configuration System
1. Copy `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_default.yaml` to `/Users/pmsanch1/code/romanepsf/configs/default.yaml`.
2. Copy `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_config.py` to `/Users/pmsanch1/code/romanepsf/src/romanepsf/config.py`.
3. Copy `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_test_config.py` to `/Users/pmsanch1/code/romanepsf/tests/unit/test_config.py` (adjust import to `from romanepsf.config import ...`).

### Step 3: Implement Level 2 Data Loader
1. Copy `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_loader.py` to `/Users/pmsanch1/code/romanepsf/src/romanepsf/loader.py`.
2. Copy `/Users/pmsanch1/code/romanepsf/.agents/teamwork/explorer_m1_1/proposed_test_loader.py` to `/Users/pmsanch1/code/romanepsf/tests/unit/test_loader.py` (adjust import to `from romanepsf.loader import ...`).
3. For backward compatibility during migration, update root `src/loader.py` to re-export from `romanepsf.loader`:
   ```python
   from romanepsf.loader import *
   ```

### Step 4: Run Unit Tests
Execute:
`/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python -m pytest tests/unit/ -v`
Ensure all tests pass cleanly.
