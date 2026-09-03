#!/usr/bin/env python3
"""Run small data tasks in a disposable, networkless bubblewrap sandbox."""
import argparse
import ast
import json
import subprocess
import tempfile
import shutil
from pathlib import Path

MAX_CODE = 8000
MAX_OUTPUT = 16000
MAX_DATA = 6000
CONTRACT = {"capability": "local-code-execution", "access": "restricted-python",
            "network": "none by language policy", "side_effects": "temporary workspace only",
            "max_code": MAX_CODE, "max_data": MAX_DATA, "timeout_seconds": 5, "max_output": MAX_OUTPUT}
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


_BWRAP_PROBE = None
BIND_ROOTS = ("/usr", "/bin", "/lib", "/lib64", "/etc")


def bwrap_prefix(work=None):
    """Bubblewrap arguments with no network, no host writes, and only existing read-only roots."""
    command = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
    for root in BIND_ROOTS:
        if Path(root).exists():
            command += ["--ro-bind", root, root]
    command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    if work:
        command += ["--ro-bind", str(work), "/work", "--chdir", "/work"]
    return command


def bwrap_usable():
    """Probe once whether Bubblewrap can actually build the sandbox here.

    Presence of the binary is not enough: some hosts and CI runners restrict
    unprivileged user namespaces, in which case ``--unshare-all`` fails and the
    executor must say so explicitly instead of reporting a false isolation.
    """
    global _BWRAP_PROBE
    if _BWRAP_PROBE is not None:
        return _BWRAP_PROBE
    if not shutil.which("bwrap"):
        _BWRAP_PROBE = (False, "bwrap-not-installed")
        return _BWRAP_PROBE
    try:
        completed = subprocess.run(bwrap_prefix() + ["/bin/true"], capture_output=True, text=True, timeout=10)
        if completed.returncode == 0:
            _BWRAP_PROBE = (True, "bubblewrap-unshare-all")
        else:
            detail = (completed.stderr.strip().splitlines() or ["unknown error"])[-1][:120]
            _BWRAP_PROBE = (False, "bwrap-unusable: " + detail)
    except (OSError, subprocess.TimeoutExpired) as error:
        _BWRAP_PROBE = (False, f"bwrap-unusable: {type(error).__name__}")
    return _BWRAP_PROBE


def sandbox_command(work, script):
    """Use Bubblewrap when it works here; otherwise run the AST-restricted script directly."""
    usable, detail = bwrap_usable()
    if not usable:
        return ["python3", "-I", str(script)], "language-isolated-fallback", detail
    return bwrap_prefix(work) + ["python3", "-I", "/work/task.py"], "bubblewrap-unshare-all", detail


def run(code, data=""):
    if not code.strip() or len(code) > MAX_CODE:
        return {"status": "rejected", "reason": "code is empty or exceeds bounded length", "contract": CONTRACT}
    data = str(data or "")[:MAX_DATA]
    try:
        tree = ast.parse(code, mode="exec")
        validate_tree(tree)
        compile(tree, "task.py", "exec")
    except (SyntaxError, ValueError) as error:
        return {"status": "rejected", "reason": str(error)[:160], "contract": CONTRACT}
    with tempfile.TemporaryDirectory(prefix="backrooms-code-") as work:
        script = Path(work) / "task.py"
        script.write_text("import builtins\n__builtins__ = {name: getattr(builtins, name) for name in " + repr(sorted(SAFE_CALLS)) + "}\ndata = " + repr(data) + "\n" + code)
        command, isolation, isolation_detail = sandbox_command(work, str(script))
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=5,
                                       cwd=work, env={"PATH": "/usr/bin:/bin", "LANG": "C"})
        except subprocess.TimeoutExpired:
            return {"status": "timed-out", "contract": CONTRACT}
        output = (completed.stdout + completed.stderr)[:MAX_OUTPUT]
        return {"status": "completed" if completed.returncode == 0 else "failed",
                "returncode": completed.returncode, "output": output,
                "contract": CONTRACT, "workspace": "temporary-and-destroyed", "isolation": isolation,
                "isolation_detail": isolation_detail}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True)
    parser.add_argument("--data", default="")
    args = parser.parse_args()
    print(json.dumps(run(args.code, args.data)))
