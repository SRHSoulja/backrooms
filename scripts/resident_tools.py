#!/usr/bin/env python3
"""Tools the residents propose for themselves, approved by a human, run in the sandbox.

A proposal is a small pure function ``tool(text) -> str`` with its own test
cases. The gate validates the code with the sandbox's rules and runs the tests
inside the sandbox; a proposal that passes is archived as ready for review and
published. Nothing a resident proposed ever runs in the world until a human
runs ``scripts/approve_tool.py``, which copies the function into ``tools/``
(tracked, public). Approved tools are then preloaded into every analysis turn
as ``tool_<name>(text)``.
"""

import argparse
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.code_sandbox import run as sandbox_run, validate_tree
    from scripts.storage import atomic_write_json
except ImportError:
    from code_sandbox import run as sandbox_run, validate_tree
    from storage import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
PROPOSALS = ROOT / "state/tool-proposals.json"
MAX_TOOL_CODE = 1600
MIN_TESTS = 2
NAME = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
SENSITIVE = re.compile(r"(?i)(api[_ -]?key|password|secret|token|mnemonic|credential|private key)")


def slug(name):
    text = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")
    return text[:31]


def validate_tool(code):
    """Return "" when the code is a valid tool proposal, else the reason."""
    code = str(code or "")
    if not code.strip() or len(code) > MAX_TOOL_CODE:
        return "tool code is empty or exceeds the bounded length"
    if SENSITIVE.search(code):
        return "tool code mentions credentials"
    try:
        tree = ast.parse(code, mode="exec")
        validate_tree(tree)
    except (SyntaxError, ValueError) as error:
        return "sandbox rules: " + str(error)[:140]
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if not any(node.name == "tool" and len(node.args.args) == 1 for node in functions):
        return "the code must define exactly `def tool(text):` taking one argument"
    tests = [node for node in tree.body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == "TESTS" for target in node.targets)]
    if not tests or not isinstance(tests[-1].value, (ast.List, ast.Tuple)) or len(tests[-1].value.elts) < MIN_TESTS:
        return f"the code must define TESTS = [[input, expected], ...] with at least {MIN_TESTS} cases"
    return ""


def run_tests(code):
    """Run the proposal's own tests in the sandbox; returns (passed, total, output)."""
    harness = (code + "\n_ok = 0\nfor _case in TESTS:\n    _got = str(tool(_case[0]))\n"
               "    _ok += 1 if _got == str(_case[1]) else 0\n    print('PASS' if _got == str(_case[1]) else 'FAIL ' + repr(_got)[:80])\n"
               "print('RESULT', _ok, len(TESTS))\n")
    result = sandbox_run(harness, "")
    output = str(result.get("output") or result.get("reason") or "")
    match = re.search(r"RESULT (\d+) (\d+)", output)
    if result.get("status") != "completed" or not match:
        return 0, 0, output[:600]
    return int(match.group(1)), int(match.group(2)), output[:600]


def load_proposals(path=PROPOSALS):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {"privacy": "resident tool proposals; nothing runs in the world until a human approves it", "proposals": []}


def propose_tool(resident, cycle, name, description, code, path=PROPOSALS):
    """Gate one proposal and archive it with its status; returns the record."""
    record = {"id": "tool-" + hashlib.sha256(f"{slug(name)}:{code}".encode()).hexdigest()[:12],
              "name": slug(name), "description": re.sub(r"\s+", " ", str(description or "")).strip()[:200],
              "resident": resident, "cycle": cycle, "code": str(code or "")[:MAX_TOOL_CODE],
              "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "rejected", "reason": "", "tests_passed": 0, "tests_total": 0}
    if not NAME.match(record["name"]):
        record["reason"] = "name must be 3 to 31 lower-case letters, digits, or underscores"
    else:
        record["reason"] = validate_tool(record["code"])
    if not record["reason"]:
        passed, total, output = run_tests(record["code"])
        record["tests_passed"], record["tests_total"], record["test_output"] = passed, total, output
        if total and passed == total:
            record["status"], record["reason"] = "ready-for-review", "all tests passed in the sandbox; awaiting human approval"
        else:
            record["reason"] = f"tests failed: {passed} of {total} passed"
    ledger = load_proposals(path)
    proposals = ledger.setdefault("proposals", [])
    if any(item.get("id") == record["id"] for item in proposals):
        return next(item for item in proposals if item.get("id") == record["id"])
    if record["status"] == "ready-for-review" and any(item.get("name") == record["name"] and item.get("status") in {"ready-for-review", "approved"} for item in proposals):
        record["status"], record["reason"] = "rejected", "a proposal with this name is already pending or approved"
    proposals.append(record)
    ledger["proposals"] = proposals[-200:]
    atomic_write_json(Path(path), ledger)
    return record


def approved_tools(tools_dir=TOOLS_DIR):
    """Approved tools from tools/*.py: name, description (first docstring line), code."""
    tools = []
    for path in sorted(Path(tools_dir).glob("*.py")):
        code = path.read_text()
        try:
            tree = ast.parse(code)
            validate_tree(tree)
        except (SyntaxError, ValueError):
            continue
        doc = ast.get_docstring(tree) or ""
        tools.append({"name": path.stem, "description": doc.strip().splitlines()[0][:200] if doc.strip() else "", "code": code})
    return tools


def prelude(tools_dir=TOOLS_DIR):
    """Sandbox prelude defining tool_<name>(text) for every approved tool."""
    parts = []
    for tool in approved_tools(tools_dir):
        body = re.sub(r"^def tool\(", f"def tool_{tool['name']}(", tool["code"], count=1, flags=re.M)
        body = re.sub(r"^TESTS\s*=.*?(?=^\S|\Z)", "", body, flags=re.M | re.S)
        parts.append(body.rstrip() + "\n")
    return "\n".join(parts)


def approve(proposal_id, path=PROPOSALS, tools_dir=TOOLS_DIR, approver="steward"):
    """Copy a ready proposal into tools/ and mark it approved; returns the file path."""
    ledger = load_proposals(path)
    record = next((item for item in ledger.get("proposals", []) if item.get("id") == proposal_id), None)
    if record is None:
        raise SystemExit(f"no proposal {proposal_id}")
    if record.get("status") != "ready-for-review":
        raise SystemExit(f"proposal {proposal_id} is {record.get('status')}, not ready-for-review")
    reason = validate_tool(record.get("code", ""))
    if reason:
        raise SystemExit("proposal no longer validates: " + reason)
    passed, total, _output = run_tests(record["code"])
    if not total or passed != total:
        raise SystemExit(f"tests no longer pass: {passed} of {total}")
    Path(tools_dir).mkdir(parents=True, exist_ok=True)
    target = Path(tools_dir) / f"{record['name']}.py"
    header = (f'"""{record.get("description") or record["name"]}\n\nProposed by resident {record.get("resident")} at cycle {record.get("cycle")}; '
              f'approved by {approver} on {datetime.now(timezone.utc).date().isoformat()} ({record["id"]}).\n"""\n')
    target.write_text(header + record["code"].rstrip() + "\n")
    record["status"] = "approved"
    record["approved_at"] = datetime.now(timezone.utc).isoformat()
    record["approved_by"] = approver
    record["path"] = str(target.relative_to(ROOT)) if str(target).startswith(str(ROOT)) else str(target)
    atomic_write_json(Path(path), ledger)
    return target


def main():
    parser = argparse.ArgumentParser(description="Approve a resident's tool proposal into tools/ (human step).")
    parser.add_argument("proposal_id")
    parser.add_argument("--approver", default="steward")
    args = parser.parse_args()
    target = approve(args.proposal_id, approver=args.approver)
    print(json.dumps({"approved": args.proposal_id, "path": str(target)}))
    print("Now commit tools/ so the next cycle preloads it: git add tools && git commit -m 'approve resident tool' && git push")


if __name__ == "__main__":
    main()
