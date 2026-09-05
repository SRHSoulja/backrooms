#!/usr/bin/env python3
"""Federation: worlds corroborating each other's findings, read-only and re-verified.

Another Backrooms instance publishes the same public feeds this one does. Each
cycle this world reads its peers' ``findings.json``, takes the accepted findings
it does not already hold, and re-fetches every one from its original source
through the read-only broker: the quoted passage must be found on the page by
this world's own fetch before the finding enters the ledger, with this world's
own content hash. An imported finding is a finding like any other, filed by
``peer:<name>``, and is judged against this world's findings under the same
independence rules; a supporting pair with one side from a peer is
cross-world corroboration, and a room founded on it says so. Nothing is ever
written to a peer, and a peer's text is data, never instruction.
"""

import hashlib
import json
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.corroboration import definition_source, profile_subject, republisher, not_a_document, domain_of
    from scripts.storage import atomic_write_json
except ImportError:
    from corroboration import definition_source, profile_subject, republisher, not_a_document, domain_of
    from storage import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PEERS = ROOT / "federation/peers.json"
STATE_FILE = ROOT / "state/federation.json"
FINDINGS = ROOT / "state/findings.jsonl"
PUBLIC = ROOT / "docs/federation.json"
PROTOCOL = "backrooms-federation/1"
MAX_IMPORTS_PER_CYCLE = 5
MAX_PEER_RECORDS = 200
MIN_QUOTE_CHARS = 20
NAME = re.compile(r"^[a-z0-9][a-z0-9\-]{1,40}$")


def load_peers(path=PEERS):
    """Peers with a plain https site URL and a short name; anything else is ignored."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    peers = []
    for item in data.get("peers", []) if isinstance(data, dict) else []:
        name, url = str(item.get("name", "")).strip().lower(), str(item.get("url", "")).strip()
        parsed = urllib.parse.urlparse(url)
        if NAME.match(name) and parsed.scheme == "https" and parsed.netloc and "@" not in parsed.netloc:
            peers.append({"name": name, "url": url.rstrip("/")})
    return peers


def feed_url(peer):
    return peer["url"] + "/findings.json"


def _norm(text):
    """Lower-case words only; citation markers like [12] are dropped so an encyclopedia lead matches its page."""
    text = re.sub(r"\[\d+\]", " ", str(text or ""))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def peer_findings(payload):
    """Accepted findings from a peer's public findings feed, in the shape this world files."""
    records = payload.get("records", []) if isinstance(payload, dict) else []
    out = []
    for item in records[-MAX_PEER_RECORDS:]:
        if not isinstance(item, dict):
            continue
        if item.get("status") in ("rejected", "retracted", "duplicate") or item.get("lifecycle_stage") in ("rejected", "retracted", "duplicate"):
            continue
        out.append({key: item.get(key) for key in ("id", "claim", "quote", "url", "content_hash", "topic", "cycle", "agent", "status")})
    return out


def load_ledger(path=FINDINGS):
    rows = []
    try:
        for line in Path(path).read_text().splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def eligible(finding, own_rows):
    """(ok, reason): the same source rules this world applies to itself, plus no duplicates of what it holds."""
    claim, quote, url = str(finding.get("claim") or "").strip(), str(finding.get("quote") or "").strip(), str(finding.get("url") or "").strip()
    if not claim or len(quote) < MIN_QUOTE_CHARS:
        return False, "no claim or a quote too short to re-verify"
    if not url.startswith("https://"):
        return False, "source is not an https URL"
    probe = {"url": url, "claim": claim, "quote": quote}
    if definition_source(probe):
        return False, "dictionary source"
    if profile_subject(probe):
        return False, "an individual's account or profile"
    if republisher(probe):
        return False, "republished copy"
    if not_a_document(probe):
        return False, "homepage or search page"
    own_quotes = {_norm(row.get("quote")) for row in own_rows if row.get("quote")}
    own_keys = {(str(row.get("url", "")).rstrip("/"), _norm(row.get("claim"))) for row in own_rows}
    if (url.rstrip("/"), _norm(claim)) in own_keys:
        return False, "already on this world's ledger"
    if _norm(quote) in own_quotes:
        return False, "this world already quotes that passage"
    return True, ""


def verify_quote(url, quote, fetch_text):
    """Re-fetch the source through the broker and look for the quoted passage.
    Returns (ok, content_hash, reason); the hash is of this world's own excerpt."""
    try:
        result = fetch_text(url, quote[:200])
    except Exception as error:  # noqa: BLE001 - a failed fetch is a reason, never a crash
        return False, "", f"fetch failed: {type(error).__name__}"
    if not isinstance(result, dict) or result.get("status") != "completed":
        return False, "", "fetch " + str((result or {}).get("status") or "failed")
    excerpt = str(result.get("excerpt") or "")
    normalized_excerpt, normalized_quote = _norm(excerpt), _norm(quote)
    head = " ".join(normalized_quote.split()[:12])
    if normalized_quote in normalized_excerpt or (head and head in normalized_excerpt):
        return True, hashlib.sha256(excerpt.encode()).hexdigest(), ""
    return False, "", "quoted passage not found at the source"


def import_record(peer, finding, cycle, content_hash):
    lineage = f"peer:{peer['name']}:{finding.get('url')}:{_norm(finding.get('claim'))}"
    return {"id": "finding-fed-" + hashlib.sha256(lineage.encode()).hexdigest()[:20],
            "agent": f"peer:{peer['name']}", "cycle": int(cycle), "origin": "federated",
            "peer": {"name": peer["name"], "url": peer["url"], "finding_id": finding.get("id"),
                     "content_hash": finding.get("content_hash"), "cycle": finding.get("cycle"), "agent": finding.get("agent")},
            "topic": str(finding.get("topic") or "federated finding")[:160],
            "claim": str(finding.get("claim"))[:300], "quote": str(finding.get("quote"))[:300],
            "url": str(finding.get("url"))[:500], "content_hash": content_hash, "confidence": 0.5,
            "claim_origin": "peer", "quote_match": "verified-by-refetch", "relates_to": ["relay"],
            "status": "unreviewed", "recorded_at": datetime.now(timezone.utc).isoformat()}


def load_state(path=STATE_FILE):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "peers": {}}


def federate(cycle, peers, fetch_json, fetch_text, ledger_path=FINDINGS, state_path=STATE_FILE, limit=MAX_IMPORTS_PER_CYCLE):
    """Read every peer, verify what is new, file up to ``limit`` imports; returns the cycle's summary."""
    state = load_state(state_path)
    own = load_ledger(ledger_path)
    imported, skipped, events = [], {}, []
    stamp = datetime.now(timezone.utc).isoformat()
    for peer in peers:
        entry = state.setdefault("peers", {}).setdefault(peer["name"], {"url": peer["url"], "imported": 0, "verified_failed": 0, "seen": []})
        entry["url"] = peer["url"]
        entry["last_fetch_at"] = stamp
        try:
            payload = fetch_json(feed_url(peer))
            candidates = peer_findings(payload)
            entry["last_status"] = "ok"
            entry["last_records"] = len(candidates)
        except Exception as error:  # noqa: BLE001
            entry["last_status"] = f"unreachable: {type(error).__name__}"
            entry["last_records"] = 0
            continue
        seen = set(entry.get("seen", []))
        for finding in candidates:
            if len(imported) >= limit:
                break
            key = str(finding.get("id") or finding.get("url"))
            if key in seen:
                continue
            ok, reason = eligible(finding, own)
            if not ok:
                skipped[reason] = skipped.get(reason, 0) + 1
                seen.add(key)
                continue
            verified, content_hash, why = verify_quote(finding["url"], finding["quote"], fetch_text)
            seen.add(key)
            if not verified:
                entry["verified_failed"] = int(entry.get("verified_failed", 0)) + 1
                skipped[why] = skipped.get(why, 0) + 1
                continue
            row = import_record(peer, finding, cycle, content_hash)
            if any(existing.get("id") == row["id"] for existing in own):
                continue
            with Path(ledger_path).open("a") as handle:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            own.append(row)
            imported.append(row)
            entry["imported"] = int(entry.get("imported", 0)) + 1
            events.append({"kind": "federation-import", "actor": f"peer:{peer['name']}", "finding_id": row["id"], "peer": peer["name"],
                           "domain": domain_of(row), "text": (f"A finding from peer world '{peer['name']}' was re-fetched from its source, "
                                                                f"its quote confirmed, and filed for judgment ({domain_of(row)}).")[:240]})
        entry["seen"] = sorted(seen)[-2000:]
    state["last_cycle"] = int(cycle)
    state["last_run_at"] = stamp
    atomic_write_json(Path(state_path), state)
    return {"imported": imported, "skipped": skipped, "events": events, "peers": len(peers)}


def check(site_url, fetch_json, fetch_text, own_rows=(), verify_limit=3):
    """Read a world's feed and report what this world would import, verifying a few; writes nothing."""
    peer = {"name": "check", "url": site_url.rstrip("/")}
    candidates = peer_findings(fetch_json(feed_url(peer)))
    report = {"site": peer["url"], "records": len(candidates), "eligible": 0, "verified": 0, "skipped": {}, "samples": []}
    for finding in candidates:
        ok, reason = eligible(finding, list(own_rows))
        if not ok:
            report["skipped"][reason] = report["skipped"].get(reason, 0) + 1
            continue
        report["eligible"] += 1
        if len(report["samples"]) < verify_limit:
            verified, _hash, why = verify_quote(finding["url"], finding["quote"], fetch_text)
            report["verified"] += int(verified)
            report["samples"].append({"claim": str(finding.get("claim"))[:120], "domain": domain_of(finding), "verified": verified, "reason": why})
    return report


def public_view(state, peers, ledger_rows, corroborations, site_url=""):
    imported = [row for row in ledger_rows if row.get("origin") == "federated"]
    cross = [record for record in corroborations if record.get("cross_world")]
    return {"schema_version": 1, "protocol": PROTOCOL, "generated_at": datetime.now(timezone.utc).isoformat(),
            "privacy": ("Peer worlds this world reads from and what it imported. Every import was re-fetched from its original source "
                        "by this world and its quote confirmed before it counted; peers are never written to."),
            "feeds": {"findings": site_url + "/findings.json", "corroborations": site_url + "/frontier.json", "world": site_url + "/world.json",
                      "federation": site_url + "/federation.json"} if site_url else {},
            "peers": [{"name": peer["name"], "url": peer["url"], **{key: value for key, value in (state.get("peers", {}).get(peer["name"]) or {}).items() if key != "seen"}}
                      for peer in peers],
            "imported": len(imported),
            "imports": [{"id": row.get("id"), "peer": (row.get("peer") or {}).get("name"), "claim": str(row.get("claim", ""))[:200],
                         "domain": domain_of(row), "cycle": row.get("cycle"), "status": row.get("status")} for row in imported[-50:]],
            "cross_world_pairs": len(cross),
            "cross_world": [{"id": record.get("id"), "relation": record.get("relation"), "shared_claim": record.get("shared_claim"),
                             "domains": record.get("domains"), "cycle": record.get("cycle")} for record in cross[-50:]]}


def main():
    import argparse
    try:
        from scripts.tool_broker import fetch, public_text, RESEARCH_MAX_BYTES
    except ImportError:
        from tool_broker import fetch, public_text, RESEARCH_MAX_BYTES
    parser = argparse.ArgumentParser(description="Read-only check of another world's feed: what this world would import and whether its quotes verify.")
    parser.add_argument("--check", required=True, help="the other world's public site, e.g. https://owner.github.io/backrooms")
    parser.add_argument("--against-own-ledger", action="store_true", help="treat this world's ledger as already held (skips duplicates)")
    parser.add_argument("--verify", type=int, default=3)
    args = parser.parse_args()
    own = load_ledger() if args.against_own_ledger else []
    report = check(args.check, lambda url: json.loads(fetch(url, RESEARCH_MAX_BYTES)), public_text, own, args.verify)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
