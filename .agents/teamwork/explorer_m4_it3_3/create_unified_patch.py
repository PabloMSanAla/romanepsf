import difflib
from pathlib import Path

current_path = Path("src/romanepsf/report.py")
current_text = current_path.read_text().splitlines(keepends=True)

# Build pre-remediation original text
orig_lines = []
for line in current_text:
    if line == "import logging\n" or line == 'logger = logging.getLogger("romanepsf.report")\n':
        continue
    orig_lines.append(line)

# 1. Revert Page 6 (load_tier_residual_data)
p6_old = []
i = 0
while i < len(orig_lines):
    if "            try:\n" in orig_lines[i] and i + 1 < len(orig_lines) and "with fits.open(best_f) as hdul:\n" in orig_lines[i+1]:
        i += 1  # skip 'try:'
        while i < len(orig_lines) and "            except (OSError, KeyError, Exception) as exc:\n" not in orig_lines[i]:
            line = orig_lines[i]
            if line.startswith("                    "):
                p6_old.append("                " + line[20:])
            elif line.startswith("                "):
                p6_old.append("            " + line[16:])
            else:
                p6_old.append(line)
            i += 1
        # skip except block
        while i < len(orig_lines) and "    # Strategy 3: Deterministic mock fallback" not in orig_lines[i]:
            i += 1
        continue
    p6_old.append(orig_lines[i])
    i += 1

orig_lines = p6_old

# 2. Revert Page 7 (extract_empirical_azimuthal_profile & plot_page_residual_metrics)
p7_old = []
i = 0
while i < len(orig_lines):
    if "    loaded_from_fits = False\n" in orig_lines[i]:
        i += 1
        # '    if bright_fits is not None and bright_fits.is_file():\n'
        p7_old.append(orig_lines[i])
        i += 1
        if "        try:\n" in orig_lines[i]:
            i += 1
        while i < len(orig_lines) and "        except (OSError, KeyError, Exception)" not in orig_lines[i]:
            if "loaded_from_fits = True\n" in orig_lines[i]:
                i += 1
                continue
            line = orig_lines[i]
            if line.startswith("                "):
                p7_old.append("            " + line[16:])
            else:
                p7_old.append(line)
            i += 1
        # skip except block
        while i < len(orig_lines) and "    if not loaded_from_fits and epsf_canvas is not None:\n" not in orig_lines[i]:
            i += 1
        p7_old.append("    elif epsf_canvas is not None:\n")
        i += 1
        continue
    if '"has_observed": bool(loaded_from_fits),\n' in orig_lines[i]:
        p7_old.append('        "has_observed": bool(bright_fits is not None),\n')
        i += 1
        continue
    if "    def _safe_float(d: Any, key: str, default: float) -> float:\n" in orig_lines[i]:
        while i < len(orig_lines) and "    core_mu = " not in orig_lines[i]:
            i += 1
        while i < len(orig_lines) and "    off_mu = " not in orig_lines[i]:
            i += 1
        orig_p7b_chunk = [
            '    core_dict = zs.get("core", {})\n',
            '    trans_dict = zs.get("transition", {})\n',
            '    wings_dict = zs.get("wings", {})\n',
            '    spikes_dict = zs.get("spikes", {})\n',
            '\n',
            '    core_mu = f"{core_dict.get(\'mu_frac\', 0.0):+.4f}" if core_dict else "-0.0652"\n',
            '    core_rms = f"{core_dict.get(\'rms_frac\', 0.0):.4f}" if core_dict else "0.4199"\n',
            '    raw_core_chi2 = core_dict.get("chi2_nu", 1.0) if core_dict else 141711.41\n',
            '    core_chi2_str = f"{raw_core_chi2:.1f} [1]" if raw_core_chi2 > 999 else f"{raw_core_chi2:.2f}"\n',
            '    core_status = core_dict.get("status", "PASS")\n',
            '\n',
            '    trans_mu = f"{trans_dict.get(\'mu_frac\', 0.0):+.4f}" if trans_dict else "-0.0764"\n',
            '    trans_rms = f"{trans_dict.get(\'rms_frac\', 0.0):.4f}" if trans_dict else "0.1294"\n',
            '    trans_chi2 = f"{trans_dict.get(\'chi2_nu\', 1.0):.2f}" if trans_dict else "116.81"\n',
            '    trans_status = trans_dict.get("status", "PASS")\n',
            '\n',
            '    wings_mu = f"{wings_dict.get(\'mu_frac\', 0.0):+.4f}" if wings_dict else "-0.0190"\n',
            '    wings_rms = f"{wings_dict.get(\'rms_frac\', 0.0):.4f}" if wings_dict else "0.2207"\n',
            '    wings_chi2 = f"{wings_dict.get(\'chi2_nu\', 1.0):.2f}" if wings_dict else "281.35"\n',
            '    wings_status = wings_dict.get("status", "PASS")\n',
            '\n',
            '    spikes_mu = f"{spikes_dict.get(\'mu_frac\', 0.0):+.4f}" if spikes_dict else "-0.0210"\n',
            '    spikes_rms = f"{spikes_dict.get(\'rms_frac\', 0.0):.4f}" if spikes_dict else "0.0824"\n',
            '    peak_res_val = spikes_dict.get("peak_res_frac", 0.10) if spikes_dict else 0.521\n',
            '    spikes_metric = f"Peak: {peak_res_val*100:.1f}%"\n',
            '    spikes_status = spikes_dict.get("status", "PASS")\n',
            '\n',
        ]
        p7_old.extend(orig_p7b_chunk)
        continue
    p7_old.append(orig_lines[i])
    i += 1

orig_lines = p7_old

# 3. Revert Page 8 (DEFAULT_TIMES slice)
p8_old = []
i = 0
while i < len(orig_lines):
    if "    DEFAULT_TIMES = [" in orig_lines[i]:
        while i < len(orig_lines) and "    # 2. Authentic Execution Times from HDU 3" not in orig_lines[i]:
            i += 1
        p8_old.append(orig_lines[i])
        i += 1
        orig_p8_times = [
            '    if not data.detector_summary.empty:\n',
            '        if "TIME_SEC" in data.detector_summary:\n',
            '            times = np.array(data.detector_summary["TIME_SEC"].values, dtype=float)\n',
            '        elif "EXEC_SEC" in data.detector_summary:\n',
            '            times = np.array(data.detector_summary["EXEC_SEC"].values, dtype=float)\n',
            '        else:\n',
            '            times = np.array([1.24, 0.37, 0.33, 0.60, 0.59, 0.57, 0.65, 0.34, 0.58, 0.64, 0.51, 0.54, 0.35, 0.57, 0.59, 0.72, 0.30, 0.40], dtype=float)\n',
            '    else:\n',
            '        times = np.array([1.24, 0.37, 0.33, 0.60, 0.59, 0.57, 0.65, 0.34, 0.58, 0.64, 0.51, 0.54, 0.35, 0.57, 0.59, 0.72, 0.30, 0.40], dtype=float)\n',
        ]
        p8_old.extend(orig_p8_times)
        while i < len(orig_lines) and "    # 3. Authentic Peak RSS Memory" not in orig_lines[i]:
            i += 1
        continue
    p8_old.append(orig_lines[i])
    i += 1

orig_lines = p8_old

# Compute unified diff
diff = list(difflib.unified_diff(
    orig_lines,
    current_text,
    fromfile="a/src/romanepsf/report.py",
    tofile="b/src/romanepsf/report.py",
))

patch_text = "".join(diff)
out_patch = Path(".agents/teamwork/explorer_m4_it3_3/unified_adversarial_remediation.patch")
out_patch.write_text(patch_text)
print(f"Complete unified patch written to {out_patch} ({len(diff)} lines)")
