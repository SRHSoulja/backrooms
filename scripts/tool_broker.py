#!/usr/bin/env python3
"""Safe, read-only internet broker for local hireling research."""

import argparse, html, ipaddress, json, re, socket, urllib.parse, urllib.request
from pathlib import Path

MAX_BYTES = 32_000
BLOCKED = re.compile(r"api[_ -]?key|password|secret|private\s+(?:key|memory|data)|credential|(?:auth|access|bearer)[_ -]?token|wallet\s+(?:seed|key)|seed phrase|mnemonic", re.I)
TOOL_CONTRACTS = {
    "wikipedia-search": {"capability": "public-web-read", "access": "read-only", "network": "public HTTPS", "side_effects": False, "max_bytes": MAX_BYTES},
    "public-https": {"capability": "public-web-read", "access": "read-only", "network": "public HTTPS", "side_effects": False, "max_bytes": MAX_BYTES},
    "public-search": {"capability": "public-web-read", "access": "read-only", "network": "public HTTPS search", "side_effects": False, "max_bytes": MAX_BYTES},
    "local-code-sandbox": {"capability": "local-code-execution", "access": "isolated-execution", "network": "none", "side_effects": "temporary workspace only", "max_code": 8000, "timeout_seconds": 5, "max_output": 16000},
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("redirects are not allowed")


def public_host(host):
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        return all(not ipaddress.ip_address(address).is_private and not ipaddress.ip_address(address).is_loopback
                   and not ipaddress.ip_address(address).is_link_local for address in addresses)
    except (OSError, ValueError):
        return False


def fetch(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname or not public_host(parsed.hostname):
        raise ValueError("only public HTTPS URLs without credentials are allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "BackroomsResearch/1.0"}, method="GET")
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=15) as response:
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("response exceeds broker limit")
        return data.decode("utf-8", errors="replace")


def wikipedia(query):
    if not query or len(query) > 160 or BLOCKED.search(query):
        raise ValueError("query failed bounded validation")
    params = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query,
                                     "srlimit": 3, "format": "json", "utf8": 1})
    data = json.loads(fetch("https://en.wikipedia.org/w/api.php?" + params))
    results = [{"title": item.get("title", ""), "pageid": item.get("pageid")}
               for item in data.get("query", {}).get("search", [])]
    return {"tool": "wikipedia-search", "query": query, "results": results,
            "source": "https://en.wikipedia.org/", "status": "completed",
            "contract": TOOL_CONTRACTS["wikipedia-search"]}


def public_search(query):
    if not query or len(query) > 160 or BLOCKED.search(query):
        raise ValueError("query failed bounded validation")
    params = urllib.parse.urlencode({"q": query, "kl": "us-en"})
    page = fetch("https://html.duckduckgo.com/html/?" + params)
    results = []
    for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
        url = html.unescape(match.group(1))
        title = re.sub(r"<[^>]+>", "", html.unescape(match.group(2))).strip()
        if url.startswith("//"):
            url = "https:" + url
        results.append({"title": title[:160], "url": url[:500]})
        if len(results) >= 5:
            break
    return {"tool": "public-search", "query": query, "results": results,
            "source": "https://html.duckduckgo.com/", "status": "completed",
            "contract": TOOL_CONTRACTS["public-search"]}


def run(tool, value):
    try:
        if tool == "wikipedia-search":
            return wikipedia(value)
        if tool == "public-search":
            return public_search(value)
        return {"tool": tool, "status": "completed", "characters": len(fetch(value)), "contract": TOOL_CONTRACTS[tool]}
    except Exception as error:
        return {"tool": tool, "status": "rejected", "reason": str(error)[:120], "contract": TOOL_CONTRACTS[tool]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=tuple(TOOL_CONTRACTS))
    parser.add_argument("value")
    args = parser.parse_args()
    print(json.dumps(run(args.tool, args.value)))
