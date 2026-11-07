import ast
from pathlib import Path

src_dir = Path("/Users/pmsanch1/code/romanepsf/src")
py_files = sorted(src_dir.rglob("*.py"))

print(f"Analyzing function definitions across {len(py_files)} files...")

facades = []

for py_path in py_files:
    if "egg-info" in str(py_path):
        continue
    content = py_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(py_path))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Filter docstrings
            body = [stmt for stmt in node.body if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str))]
            
            # Check for empty body / pass only
            if len(body) == 0 or (len(body) == 1 and isinstance(body[0], ast.Pass)):
                # If it's an abstract method or protocol or overload, it's fine, else flag
                facades.append((str(py_path), node.lineno, node.name, "Empty body or only Pass"))
            
            # Check for single return of constant
            elif len(body) == 1 and isinstance(body[0], ast.Return):
                ret_val = body[0].value
                if isinstance(ret_val, ast.Constant):
                    facades.append((str(py_path), node.lineno, node.name, f"Single return constant: {ret_val.value}"))
                elif isinstance(ret_val, (ast.List, ast.Dict, ast.Tuple)) and len(getattr(ret_val, 'elts', getattr(ret_val, 'keys', []))) == 0:
                    facades.append((str(py_path), node.lineno, node.name, f"Single return empty collection"))

print(f"Potential facade / trivial functions found: {len(facades)}")
for f, l, name, reason in facades:
    print(f"  {f}:{l} {name}() -> {reason}")
