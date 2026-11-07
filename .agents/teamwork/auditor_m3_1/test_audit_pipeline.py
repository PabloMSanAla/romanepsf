"""
Forensic Integrity Audit Script for Milestone 3.
Auditor: auditor_m3_1

Checks:
1. Hardcoded Values & Facade Detection (AST & regex analysis).
2. 2D Non-Circular Structure & Spike Preservation Audit.
3. Astropy FITS Standard Compliance (8-character headers, NO HIERARCH cards).
4. Dynamic Execution Trace (WFI01 execution to a temporary output dir).
"""

import ast
import os
import re
import sys
import tempfile
from pathlib import Path
import numpy as np
from astropy.io import fits

PYTHON_BIN = "/Users/pmsanch1/miniforge3/envs/rosalia-dev/bin/python"
WORKSPACE = Path("/Users/pmsanch1/code/romanepsf")
SINGLE_FITS = WORKSPACE / "output/single_wfi01/roman_epsf_wfi01.fits"
COMPOSITE_FITS = WORKSPACE / "output/run_all/roman_epsf_composite.fits"

TARGET_PY_FILES = [
    WORKSPACE / "src/romanepsf/pipeline.py",
    WORKSPACE / "src/pipeline.py",
    WORKSPACE / "src/romanepsf/assembly.py",
    WORKSPACE / "src/assembly.py",
    WORKSPACE / "src/romanepsf/cli.py",
]


def check_ast_and_hardcoding():
    print("=== CHECK 1: AST and Hardcoding Analysis ===")
    violations = []
    
    # 1. AST check for large canned float arrays or constant matrices
    for p in TARGET_PY_FILES:
        if not p.is_file():
            violations.append(f"Missing target file: {p}")
            continue
        code = p.read_text()
        tree = ast.parse(code, filename=str(p))
        
        # Look for suspicious assign nodes with large literals or hardcoded scale factors
        for node in ast.walk(tree):
            # Check for hardcoded k_fm or k_mb constants
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name = target.id
                        if name in ("k_fm", "k_mb", "K_FM", "K_MB"):
                            # If assigned a constant number in global scope
                            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                                violations.append(f"{p.name}: Hardcoded constant assignment {name} = {node.value.value}")
                        # Check for hardcoded arrays/lists with > 20 literal numbers
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            elts = node.value.elts
                            if len(elts) > 30 and all(isinstance(e, ast.Constant) for e in elts[:10]):
                                # Ensure it's not base spike angles
                                if name not in ("ROMAN_BASE_SPIKE_ANGLES_DEG",):
                                    violations.append(f"{p.name}: Suspicious hardcoded array assigned to {name} (len={len(elts)})")
    
    # 2. Regex check for hardcoded results or mock returns
    mock_patterns = [
        re.compile(r"def\s+run_single_detector\b.*?return\s+SingleDetectorResult\(.*?epsf_model\s*=\s*np\.zeros", re.DOTALL),
        re.compile(r"def\s+assemble_composite_extended_psf\b.*?return\s+np\.zeros", re.DOTALL),
        re.compile(r"mock|dummy|fake|canned", re.IGNORECASE),
    ]
    for p in TARGET_PY_FILES:
        code = p.read_text()
        # Look for mock/dummy/fake in code (excluding comments)
        lines = code.splitlines()
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"\b(mock|dummy|canned_psf|fake_psf)\b", stripped, re.IGNORECASE):
                violations.append(f"{p.name}:{idx}: Found suspicious token '{stripped}'")

    print(f"AST & Hardcoding Violations Found: {len(violations)}")
    for v in violations:
        print(f"  - {v}")
    return len(violations) == 0, violations


def check_2d_spike_and_circularization():
    print("\n=== CHECK 2: 2D Non-Circular Structure & Spike Preservation ===")
    violations = []

    # 1. Inspect assembly.py to ensure 2D PSF is not circularized
    assembly_code = (WORKSPACE / "src/romanepsf/assembly.py").read_text()
    
    # Check if there is any code converting 1D profile back into a 2D image
    # (e.g. radial grid r used as index into profile or 2D image created from prof)
    suspicious_circularizers = [
        r"prof\[.*r.*\]",
        r"np\.interp\s*\(\s*r\b",
        r"profile_to_2d",
        r"radial_profile_to_image",
        r"azimuthal_average",
    ]
    for pat in suspicious_circularizers:
        match = re.search(pat, assembly_code)
        if match:
            violations.append(f"assembly.py contains suspicious circularizing pattern: {match.group(0)}")

    # 2. Inspect FITS output: output/run_all/roman_epsf_composite.fits
    if not COMPOSITE_FITS.is_file():
        violations.append(f"Composite FITS file does not exist: {COMPOSITE_FITS}")
        return False, violations

    with fits.open(COMPOSITE_FITS) as hdul:
        data = hdul[0].data
        print(f"Composite FITS Primary HDU shape: {data.shape}, dtype: {data.dtype}, sum: {np.sum(data):.6e}")

        # Check that canvas is square and odd or within 1024-2049
        ny, nx = data.shape
        if ny != nx:
            violations.append(f"Composite canvas is not square: {data.shape}")
        if not (1024 <= ny <= 2049):
            violations.append(f"Composite canvas size {ny} is outside required 1024-2048 range")

        # Test 2D Non-Circularity and Spike Preservation:
        # Roman spikes are 6-fold spikes at angles: [23.55, 55.29, 80.25, 118.65, 142.88, 178.07] + PA_APER + offset
        # A circularized image has azimuthal variance close to 0 at any radius r.
        # An image with 6-fold diffraction spikes will have high azimuthal variance and prominent peaks at spike angles!
        cy, cx = (ny - 1) / 2.0, (nx - 1) / 2.0
        y, x = np.ogrid[:ny, :nx]
        r = np.hypot(x - cx, y - cy)
        theta_deg = np.degrees(np.arctan2(y - cy, x - cx)) % 360.0

        # Sample at radii r = 30, 60, 100, 150, 200, 300, 400
        test_radii = [30, 60, 100, 150, 200, 300]
        for tr in test_radii:
            annulus_mask = (r >= tr - 2.0) & (r <= tr + 2.0)
            annulus_vals = data[annulus_mask]
            annulus_thetas = theta_deg[annulus_mask]
            
            if len(annulus_vals) == 0:
                continue
            
            v_mean = np.mean(annulus_vals)
            v_std = np.std(annulus_vals)
            v_max = np.max(annulus_vals)
            v_min = np.min(annulus_vals)
            # Relative variation / peak-to-trough ratio
            peak_to_mean = v_max / (v_mean + 1e-12)
            cv = v_std / (v_mean + 1e-12)
            print(f"Radius {tr:3d} px: mean={v_mean:.3e}, std={v_std:.3e}, max={v_max:.3e}, peak/mean={peak_to_mean:.2f}, CV={cv:.3f}")

            # If CV is extremely small (< 0.05) or peak/mean < 1.1, the image would be artificially circularized!
            if cv < 0.05 or peak_to_mean < 1.2:
                violations.append(f"Radius {tr} px appears azimuthally circularized! CV={cv:.4f}, peak/mean={peak_to_mean:.4f}")

        # Check spike angle correlation:
        # In header:
        net_rot = hdul[0].header.get("NET_ROT", None)
        pa_aper = hdul[0].header.get("PA_APER", None)
        print(f"Header NET_ROT: {net_rot}, PA_APER: {pa_aper}")

        # Measure azimuthal peaks in composite ePSF:
        ann = (r >= 60.0) & (r <= 150.0)
        th_bins = np.linspace(0, 360, 361)
        th_c = 0.5 * (th_bins[:-1] + th_bins[1:])
        az_comp = np.zeros(len(th_c))
        for i in range(len(th_c)):
            m = ann & (theta_deg >= th_bins[i]) & (theta_deg < th_bins[i + 1])
            if np.sum(m) > 0:
                az_comp[i] = np.median(data[m])
        from scipy.signal import find_peaks
        comp_peaks, _ = find_peaks(az_comp, distance=10, prominence=0.3 * np.std(az_comp))
        comp_peak_thetas = th_c[comp_peaks]
        print(f"Detected {len(comp_peak_thetas)} spike rays in composite ePSF: {[round(t, 1) for t in comp_peak_thetas]}")
        
        # Verify that composite ePSF has at least 8 distinct spike rays
        if len(comp_peak_thetas) < 8:
            violations.append(f"Insufficient diffraction spike rays detected in composite ePSF ({len(comp_peak_thetas)} < 8)")

    print(f"2D Spike & Circularization Violations Found: {len(violations)}")
    for v in violations:
        print(f"  - {v}")
    return len(violations) == 0, violations


def check_fits_standard_compliance():
    print("\n=== CHECK 3: Astropy FITS Standard Compliance (8-char headers, NO HIERARCH) ===")
    violations = []
    
    files_to_check = [SINGLE_FITS, COMPOSITE_FITS]
    for fits_file in files_to_check:
        if not fits_file.is_file():
            violations.append(f"FITS file missing: {fits_file}")
            continue

        with fits.open(fits_file) as hdul:
            print(f"Inspecting {fits_file.name} ({len(hdul)} HDUs):")
            for hdu_idx, hdu in enumerate(hdul):
                hdr = hdu.header
                # Check for HIERARCH keywords
                for card in hdr.cards:
                    kw = card.keyword
                    if kw.startswith("HIERARCH"):
                        violations.append(f"{fits_file.name} HDU {hdu_idx}: Found HIERARCH card: {kw}")
                    elif len(kw) > 8:
                        violations.append(f"{fits_file.name} HDU {hdu_idx}: Keyword longer than 8 chars: '{kw}' (len={len(kw)})")
                
                # Check key standard cards in Primary HDU
                if hdu_idx == 0:
                    for req_key in ["EXTNAME", "TELESCOP", "INSTRUME", "DETECTOR", "FILTER", "PIXSCALE", "CANVAS_S"]:
                        if req_key not in hdr:
                            violations.append(f"{fits_file.name} HDU 0: Missing required header card: {req_key}")
                        else:
                            val = hdr[req_key]
                            print(f"  HDU 0 [{req_key}] = {val}")

            # Check HDU names for composite fits
            if fits_file == COMPOSITE_FITS:
                hdu_names = [h.name for h in hdul]
                print(f"  HDU Names: {hdu_names}")
                for expected in ["PRIMARY", "COVERAGE", "RADIAL_PROFILES", "DETECTOR_SUMMARY"]:
                    # Note: HDU 0 might be PRIMARY or have EXTNAME
                    if expected not in hdu_names and (expected != "PRIMARY" or hdul[0].name != "EPSF"):
                        violations.append(f"{fits_file.name}: Missing expected HDU '{expected}'")

    print(f"FITS Standard Compliance Violations Found: {len(violations)}")
    for v in violations:
        print(f"  - {v}")
    return len(violations) == 0, violations


def check_dynamic_execution():
    print("\n=== CHECK 4: Dynamic Execution Trace ===")
    violations = []
    
    # We will invoke run_single_detector dynamically on WFI01 to a temporary output directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        print(f"Executing run_single_detector to temporary directory: {tmp_path}")
        
        from romanepsf.pipeline import run_single_detector
        from romanepsf.config import load_config
        
        cfg = load_config()
        # Small canvas size for fast dynamic trace test
        cfg.assembly.canvas_size = 501
        
        t0 = os.times()
        res = run_single_detector(
            cfg,
            detector="wfi01",
            output_dir=tmp_path,
            canvas_size=501,
        )
        
        print(f"Execution finished with result: {res.summary()}")
        print(f"Output files in tmpdir: {[f.name for f in tmp_path.iterdir()]}")
        
        # Verify result properties
        if not res.success:
            violations.append("run_single_detector reported success=False")
        
        if res.epsf_model is None:
            violations.append("run_single_detector returned None for epsf_model")
        elif res.epsf_model.shape != (501, 501):
            violations.append(f"Unexpected epsf_model shape: {res.epsf_model.shape}, expected (501, 501)")
        elif not np.isclose(np.sum(res.epsf_model), 1.0, atol=1e-4):
            violations.append(f"Model flux sum is not normalized to 1.0: sum={np.sum(res.epsf_model)}")
            
        # Verify star counts
        print(f"Dynamic star counts: {res.star_counts}")
        if res.star_counts.get("total", 0) <= 0:
            violations.append("Dynamic execution extracted 0 stars")
            
        # Verify scale factor
        print(f"Dynamic scale factors: {res.scale_factors}")
        if res.scale_factors.get("k_fm") is None or res.scale_factors.get("k_fm") <= 0:
            violations.append(f"Invalid dynamic k_fm: {res.scale_factors.get('k_fm')}")
            
        # Verify FITS file created
        out_fits = tmp_path / "roman_epsf_wfi01.fits"
        if not out_fits.is_file():
            violations.append(f"Expected output FITS file not created: {out_fits}")
        else:
            with fits.open(out_fits) as hdul:
                for card in hdul[0].header.cards:
                    if card.keyword.startswith("HIERARCH") or len(card.keyword) > 8:
                        violations.append(f"Dynamic FITS header keyword invalid: {card.keyword}")

    print(f"Dynamic Execution Trace Violations Found: {len(violations)}")
    for v in violations:
        print(f"  - {v}")
    return len(violations) == 0, violations


if __name__ == "__main__":
    v1_ok, v1 = check_ast_and_hardcoding()
    v2_ok, v2 = check_2d_spike_and_circularization()
    v3_ok, v3 = check_fits_standard_compliance()
    v4_ok, v4 = check_dynamic_execution()

    all_ok = v1_ok and v2_ok and v3_ok and v4_ok
    print("\n===============================")
    if all_ok:
        print("FINAL VERDICT: CLEAN")
        sys.exit(0)
    else:
        print("FINAL VERDICT: INTEGRITY VIOLATION")
        sys.exit(1)
