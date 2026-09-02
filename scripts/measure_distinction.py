#!/usr/bin/env python3
"""Measure surface distinction between two resident outputs.

This is a behavioral metric, not a consciousness metric. It rewards useful
role-specific language while making no claim about inner experience.
"""

import argparse
import json
import re


def words(text):
    return set(re.findall(r"[a-z]{4,}", text.lower()))


parser = argparse.ArgumentParser()
parser.add_argument("path", help="JSON file containing echo and morrow fields")
args = parser.parse_args()
data = json.load(open(args.path))
echo, morrow = data["echo"], data["morrow"]
shared = words(echo) & words(morrow)
union = words(echo) | words(morrow)
overlap = len(shared) / len(union) if union else 1.0
echo_markers = sum(marker in echo.lower() for marker in ("propose", "test", "criterion"))
morrow_markers = sum(marker in morrow.lower() for marker in ("counterexample", "confound", "assumption", "missing control"))
result = {"metric": "surface-distinction-v1", "jaccard_overlap": round(overlap, 3),
          "echo_role_markers": echo_markers, "morrow_role_markers": morrow_markers,
          "interpretation": "useful separation" if echo_markers and morrow_markers and overlap < 0.75 else "needs review"}
print(json.dumps(result, indent=2))
