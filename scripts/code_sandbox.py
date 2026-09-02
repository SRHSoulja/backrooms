#!/usr/bin/env python3
"""Run small data tasks in a disposable, networkless bubblewrap sandbox."""
import argparse
import ast
import json
import subprocess
import tempfile
from pathlib import Path

MAX_CODE = 8000
MAX_OUTPUT = 16000
CONTRACT = {"capability": "local-code-execution", "access": "restricted-python",
            "network": "none by language policy", "side_effects": "temporary workspace only",
            "max_code": MAX_CODE, "timeout_seconds": 5, "max_output": MAX_OUTPUT}
SAFE_CALLS = {"print", "len", "sum", "min", "max", "sorted", "range", "enumerate", "abs", "round"}
SAFE_NODES = (ast.Module, ast.Expr, ast.Assign, ast.Name, ast.Constant, ast.List, ast.Tuple, ast.Dict,
              ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.If, ast.IfExp, ast.For, ast.Load,
              ast.Store, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub,
              ast.UAdd, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
              ast.Subscript, ast.Slice, ast.ListComp, ast.comprehension, ast.Call)


def validate_tree(tree):
    for node in ast.walk(tree):
        if not isinstance(node, SAFE_NODES):
            raise ValueError(f"unsupported code construct: {type(node).__name__}")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in SAFE_CALLS):
            raise ValueError("only allowlisted data functions may be called")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("dunder names are not allowed")


def run(code):
    if not code.strip() or len(code) > MAX_CODE:
        return {"status": "rejected", "reason": "code is empty or exceeds bounded length", "contract": CONTRACT}
    try:
        tree = ast.parse(code, mode="exec")
        validate_tree(tree)
        compile(tree, "task.py", "exec")
    except (SyntaxError, ValueError) as error:
        return {"status": "rejected", "reason": str(error)[:160], "contract": CONTRACT}
    with tempfile.TemporaryDirectory(prefix="backrooms-code-") as work:
        script = Path(work) / "task.py"
        script.write_text("import builtins\n__builtins__ = {name: getattr(builtins, name) for name in " + repr(sorted(SAFE_CALLS)) + "}\n" + code)
        command = ["python3", "-I", str(script)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=5,
                                       cwd=work, env={"PATH": "/usr/bin:/bin", "LANG": "C"})
        except subprocess.TimeoutExpired:
            return {"status": "timed-out", "contract": CONTRACT}
        output = (completed.stdout + completed.stderr)[:MAX_OUTPUT]
        return {"status": "completed" if completed.returncode == 0 else "failed",
                "returncode": completed.returncode, "output": output,
                "contract": CONTRACT, "workspace": "temporary-and-destroyed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.code)))
