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
SAFE_CALLS = {"print", "len", "sum", "min", "max", "sorted", "range", "enumerate", "abs", "round",
              "str", "int", "float", "bool", "list", "dict", "set", "tuple", "zip", "map", "filter", "any", "all",
              "reversed", "isinstance", "repr", "divmod", "chr", "ord", "format"}
# The standard-library subset an analysis turn may use: pure data work, no
# files, processes, network, or introspection. Modules are preloaded by the
# preamble and handed out through a restricted __import__.
SAFE_MODULES = ("math", "statistics", "json", "csv", "re", "datetime", "collections", "itertools",
                "string", "textwrap", "fractions", "decimal", "io")
SAFE_NODES = (ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.Name, ast.Constant, ast.List, ast.Tuple, ast.Dict,
              ast.Set, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.If, ast.IfExp, ast.For, ast.While,
              ast.Break, ast.Continue, ast.Pass, ast.Load, ast.Store, ast.Del,
              ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Not,
              ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
              ast.Subscript, ast.Slice, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.comprehension,
              ast.Call, ast.keyword, ast.Attribute, ast.Import, ast.ImportFrom, ast.alias, ast.FunctionDef, ast.arguments,
              ast.arg, ast.Return, ast.Lambda, ast.JoinedStr, ast.FormattedValue, ast.Try, ast.ExceptHandler, ast.Raise,
              ast.Starred, ast.Tuple)


DENIED_NAMES = {"open", "eval", "exec", "compile", "getattr", "setattr", "delattr", "globals", "locals", "vars",
                "input", "breakpoint", "exit", "quit", "help", "dir", "type", "object", "memoryview", "super",
                "classmethod", "staticmethod", "property", "id", "hash", "iter", "next", "callable", "bytes", "bytearray"}


def validate_tree(tree):
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    defined |= {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda)
                for target in node.targets if isinstance(target, ast.Name)}
    # A name imported from an allowlisted module (from collections import Counter,
    # import statistics as st) is as callable as the module itself.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in SAFE_MODULES:
            defined |= {alias.asname or alias.name for alias in node.names if alias.name != "*"}
        elif isinstance(node, ast.Import):
            defined |= {alias.asname for alias in node.names if alias.asname and alias.name.split(".")[0] in SAFE_MODULES}
    for node in ast.walk(tree):
        if not isinstance(node, SAFE_NODES):
            raise ValueError(f"unsupported code construct: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id in DENIED_NAMES:
            raise ValueError(f"'{node.id}' is not available in the sandbox")
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                if target.id not in SAFE_CALLS and target.id not in defined:
                    raise ValueError("only allowlisted builtins, allowlisted modules, and functions defined in the code may be called")
            elif not isinstance(target, ast.Attribute):
                raise ValueError("only named functions and methods may be called")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in {"system", "popen", "spawn", "fork"}):
            raise ValueError("private and process attributes are not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("dunder names are not allowed")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for module in modules:
                if module.split(".")[0] not in SAFE_MODULES:
                    raise ValueError(f"module not in the sandbox allowlist: {module}")
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                raise ValueError("star imports are not allowed")
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            raise ValueError("private function names are not allowed")


PREAMBLE = (
    "import builtins as _b\n"
    "import " + ", ".join(SAFE_MODULES) + "\n"
    "_modules = {name: globals()[name] for name in " + repr(list(SAFE_MODULES)) + "}\n"
    "def _safe_import(name, *args, **kwargs):\n"
    "    root = name.split('.')[0]\n"
    "    if root not in _modules:\n"
    "        raise ImportError('module not in the sandbox allowlist: ' + name)\n"
    "    return _modules[root]\n"
    "_allowed = {name: getattr(_b, name) for name in " + repr(sorted(SAFE_CALLS)) + "}\n"
    "_allowed['__import__'] = _safe_import\n"
    "for _name in ('ValueError', 'TypeError', 'KeyError', 'IndexError', 'ZeroDivisionError', 'Exception', 'StopIteration', 'True', 'False', 'None'):\n"
    "    _allowed[_name] = getattr(_b, _name)\n"
    "del _b\n")


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


def run(code, data="", prelude=""):
    """Run one task; ``prelude`` is approved resident-tool code (validated again here)
    defined in the same restricted namespace before the task."""
    if not code.strip() or len(code) > MAX_CODE:
        return {"status": "rejected", "reason": "code is empty or exceeds bounded length", "contract": CONTRACT}
    data = str(data or "")[:MAX_DATA]
    # Approved tools and the task are validated together, so the task may call
    # the tools and nothing else beyond the allowlist.
    combined = (prelude.rstrip() + "\n" + code) if prelude else code
    try:
        tree = ast.parse(combined, mode="exec")
        validate_tree(tree)
        compile(tree, "task.py", "exec")
    except (SyntaxError, ValueError) as error:
        return {"status": "rejected", "reason": str(error)[:160], "contract": CONTRACT}
    code = combined
    with tempfile.TemporaryDirectory(prefix="backrooms-code-") as work:
        script = Path(work) / "task.py"
        # The task runs in a fresh namespace whose builtins are the allowlist, so
        # the restriction binds the code itself, not only the preamble.
        script.write_text(PREAMBLE + "exec(compile(" + repr(code) + ", 'task.py', 'exec'), {'__builtins__': _allowed, 'data': " + repr(data) + "})\n")
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
    parser.add_argument("--prelude-file", default="", help="file of approved resident-tool code to define first")
    args = parser.parse_args()
    prelude = Path(args.prelude_file).read_text() if args.prelude_file and Path(args.prelude_file).exists() else ""
    print(json.dumps(run(args.code, args.data, prelude)))
