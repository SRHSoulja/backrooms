"""Public capability policy catalog used by bounded resident workflows."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/tool-catalog.json"

POLICIES = {
    "public-web-read": {"grant": "auto", "prerequisites": ["interview-accepted"], "scope": "public HTTPS read-only"},
    "public-data-read": {"grant": "auto", "prerequisites": ["interview-accepted"], "scope": "public JSON/CSV read-only"},
    "public-source-read": {"grant": "auto", "prerequisites": ["interview-accepted"], "scope": "sanitized repository source only"},
    "local-code-execution": {"grant": "review", "prerequisites": ["three-verified-findings"], "scope": "data-only temporary sandbox"},
    "code-change-proposal": {"grant": "review", "prerequisites": ["isolated-review"], "scope": "non-applying local proposal"},
    "external-write": {"grant": "never", "prerequisites": [], "scope": "not provisioned"},
    "financial-transaction": {"grant": "never", "prerequisites": [], "scope": "not provisioned"},
}


def policy_for(capability):
    return dict(POLICIES.get(str(capability), {
        "grant": "review", "prerequisites": ["explicit-scope"], "scope": "bounded and reviewed"
    }))


def public_catalog():
    """Return the catalog with explicit grant policy and no local state."""
    try:
        catalog = json.loads(CATALOG.read_text())
    except (OSError, json.JSONDecodeError):
        catalog = {"tools": []}
    for tool in catalog.get("tools", []):
        policy = policy_for(tool.get("capability"))
        tool["grant"] = policy["grant"]
        tool["prerequisites"] = policy["prerequisites"]
        tool["scope"] = policy["scope"]
    return catalog
