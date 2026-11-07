import ast
from pathlib import Path
import sys

src_dir = Path("/Users/pmsanch1/code/romanepsf/src")
py_files = sorted(src_dir.rglob("*.py"))

print(f"Scanning {len(py_files)} Python files in {src_dir}...")

rng_findings = []

for py_path in py_files:
    try:
        content = py_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_path))
    except Exception as e:
        print(f"Error parsing {py_path}: {e}")
        continue

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "random" in alias.name:
                    rng_findings.append((str(py_path), node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if "random" in mod:
                rng_findings.append((str(py_path), node.lineno, f"from {mod} import ..."))
            for alias in node.names:
                if "random" in alias.name or "rand" in alias.name:
                    rng_findings.append((str(py_path), node.lineno, f"from {mod} import {alias.name}"))

        # Check function / method calls
        elif isinstance(node, ast.Call):
            # Check func name
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
                val = node.func.value
                val_chain = []
                while isinstance(val, ast.Attribute):
                    val_chain.append(val.attr)
                    val = val.value
                if isinstance(val, ast.Name):
                    val_chain.append(val.id)
                val_chain.reverse()
                full_attr = ".".join(val_chain + [func_name])
                if any(k in full_attr for k in ["random", "rand", "choice", "shuffle", "default_rng", "seed"]):
                    rng_findings.append((str(py_path), node.lineno, f"Call to {full_attr}"))
            if func_name in ["default_rng", "randint", "rand", "randn", "random", "uniform"]:
                rng_findings.append((str(py_path), node.lineno, f"Direct call to {func_name}"))

print(f"Total potential RNG findings: {len(rng_findings)}")
for file, line, msg in rng_findings:
    print(f"  {file}:{line} -> {msg}")
