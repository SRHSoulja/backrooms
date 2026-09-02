#!/usr/bin/env python3
"""Read public market pages and publish aggregate demand signals only."""

import html, ipaddress, json, re, socket, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "upwork-ai-services": "https://www.upwork.com/services/ai-machine-learning",
    "upwork-ai-jobs": "https://www.upwork.com/freelance-jobs/artificial-intelligence/",
    "freelancer-ai-jobs": "https://www.freelancer.com/jobs/artificial-intelligence/",
}
TERMS = ("agent", "automation", "evaluation", "security", "prompt", "rag", "mcp", "a2a", "workflow", "voice", "data", "integration")


def public_host(host):
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        return all(not ipaddress.ip_address(address).is_private and not ipaddress.ip_address(address).is_loopback
                   and not ipaddress.ip_address(address).is_link_local for address in addresses)
    except (OSError, ValueError):
        return False


def scan(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {urllib.parse.urlparse(item).hostname for item in SOURCES.values()} or not public_host(parsed.hostname):
        raise ValueError("source is not on the fixed public allowlist")
    request = urllib.request.Request(url, headers={"User-Agent": "Backrooms-Market-Watch/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(100_000).decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", html.unescape(body)).lower()
    text = re.sub(r"\s+", " ", text)
    return {"source": url, "characters": len(text), "term_hits": {term: len(re.findall(r"\b" + re.escape(term) + r"\b", text)) for term in TERMS}}


results = []
for source, url in SOURCES.items():
    try:
        result = scan(url); result["id"] = source; result["status"] = "online"
    except Exception as error:
        result = {"id": source, "source": url, "status": "unavailable", "error": type(error).__name__}
    results.append(result)
snapshot = {"checked_at": datetime.now(timezone.utc).isoformat(), "sources": results,
            "privacy": "Aggregate public-page term counts only; no client data or raw page content is stored.",
            "staffing": "Market Watch is a standing research desk for local hirelings; demand signals inform proposals, not automatic outreach."}
(ROOT / "docs/market-watch.json").write_text(json.dumps(snapshot, indent=2) + "\n")
print(json.dumps(snapshot, indent=2))
