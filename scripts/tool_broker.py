#!/usr/bin/env python3
"""Safe, read-only internet broker for local hireling research."""

import argparse, csv, html, ipaddress, io, json, re, socket, urllib.parse, urllib.request
from pathlib import Path

MAX_BYTES = 32_000
RESEARCH_MAX_BYTES = 5_000_000
CSV_MAX_ROWS = 100_000
BLOCKED = re.compile(r"api[_ -]?key|password|secret|private\s+(?:key|memory|data)|credential|(?:auth|access|bearer)[_ -]?token|wallet\s+(?:seed|key)|seed phrase|mnemonic", re.I)
SCRIPT_STYLE = re.compile(r"<(?:script|style|noscript)[^>]*>.*?</(?:script|style|noscript)>", re.I | re.S)
SENSITIVE_ASSIGNMENT = re.compile(r"(?i)\b(?:api[_ -]?key|password|secret|credential|token|mnemonic)\s*[:=]\s*[^\s,;]+")
TOOL_CONTRACTS = {
    "wikipedia-search": {"capability": "public-web-read", "access": "read-only", "network": "public HTTPS", "side_effects": False, "max_bytes": MAX_BYTES},
    "wikipedia-summary": {"capability": "public-text-read", "access": "read-only", "network": "public HTTPS", "side_effects": False, "max_bytes": MAX_BYTES, "raw_data": False, "untrusted_content": True},
    "public-https": {"capability": "public-web-read", "access": "read-only", "network": "public HTTPS", "side_effects": False, "max_bytes": MAX_BYTES},
    "public-search": {"capability": "public-web-read", "access": "read-only", "network": "public HTTPS search", "side_effects": False, "max_bytes": MAX_BYTES},
    "public-json": {"capability": "public-data-read", "access": "read-only", "network": "public HTTPS", "side_effects": False, "max_bytes": RESEARCH_MAX_BYTES, "raw_data": False},
    "public-csv": {"capability": "public-data-read", "access": "read-only", "network": "public HTTPS", "side_effects": False, "max_bytes": RESEARCH_MAX_BYTES, "max_rows": CSV_MAX_ROWS, "raw_data": False},
    "public-text": {"capability": "public-text-read", "access": "read-only", "network": "public HTTPS", "side_effects": False, "max_bytes": RESEARCH_MAX_BYTES, "raw_data": False, "untrusted_content": True},
    "local-code-sandbox": {"capability": "local-code-execution", "access": "isolated-execution", "network": "none", "side_effects": "temporary workspace only", "max_code": 8000, "timeout_seconds": 5, "max_output": 16000},
    "local-code-read": {"capability": "public-source-read", "access": "read-only", "network": "none", "side_effects": False, "max_file_bytes": 120000, "max_inventory_bytes": 400000, "write_access": False, "secrets": "redacted"},
    "code-proposal-gate": {"capability": "code-change-proposal", "access": "validate-and-archive-only", "network": "none", "side_effects": "local proposal metadata only", "max_patch_bytes": 80000, "max_changed_lines": 240, "applies_changes": False, "secret_scan": True},
    "code-review-runner": {"capability": "isolated-code-review", "access": "temporary-test-copy", "network": "none", "side_effects": "temporary workspace only", "timeout_seconds": 20, "applies_changes": False},
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


def fetch(url, max_bytes=MAX_BYTES):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname or not public_host(parsed.hostname):
        raise ValueError("only public HTTPS URLs without credentials are allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "BackroomsResearch/1.0", "Accept-Encoding": "identity"}, method="GET")
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=15) as response:
        if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
            raise ValueError("compressed responses are not accepted by the broker")
        declared_length = response.headers.get("Content-Length")
        if declared_length and int(declared_length) > max_bytes:
            raise ValueError("response exceeds broker limit")
        chunks = []
        total = 0
        while True:
            chunk = response.read(min(64 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("response exceeds broker limit")
        data = b"".join(chunks)
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


def wikipedia_summary(query):
    """Resolve a query to one Wikipedia article and return its plain-text summary as evidence.

    The REST summary endpoint yields clean, quotable prose with a canonical
    page URL, which makes it the preferred first source for a research turn.
    """
    if not query or len(query) > 160 or BLOCKED.search(query):
        raise ValueError("query failed bounded validation")
    params = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query,
                                     "srlimit": 1, "format": "json", "utf8": 1})
    data = json.loads(fetch("https://en.wikipedia.org/w/api.php?" + params))
    hits = data.get("query", {}).get("search", [])
    if not hits:
        return {"tool": "wikipedia-summary", "query": query, "status": "no-match",
                "source": "https://en.wikipedia.org/", "contract": TOOL_CONTRACTS["wikipedia-summary"]}
    title = str(hits[0].get("title", "")).strip()
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    summary = json.loads(fetch("https://en.wikipedia.org/api/rest_v1/page/summary/" + encoded))
    extract = re.sub(r"\s+", " ", html.unescape(str(summary.get("extract", "")))).strip()
    extract = SENSITIVE_ASSIGNMENT.sub("[withheld]", extract)
    extract = BLOCKED.sub("[withheld]", extract)
    page_url = str(((summary.get("content_urls") or {}).get("desktop") or {}).get("page") or
                   "https://en.wikipedia.org/wiki/" + encoded)
    if not extract or not page_url.startswith("https://"):
        return {"tool": "wikipedia-summary", "query": query, "status": "no-match", "title": title,
                "source": "https://en.wikipedia.org/", "contract": TOOL_CONTRACTS["wikipedia-summary"]}
    return {"tool": "wikipedia-summary", "query": query, "title": title, "url": page_url,
            "excerpt": extract[:2400], "status": "completed", "contract": TOOL_CONTRACTS["wikipedia-summary"]}


def public_search(query):
    query = re.sub(r"\s+", " ", str(query)).strip(" ,.;:!?")
    if not query or len(query) > 160 or BLOCKED.search(query):
        raise ValueError("query failed bounded validation")
    params = urllib.parse.urlencode({"q": query, "kl": "us-en"})
    results = []
    provider = "https://html.duckduckgo.com/"
    try:
        page = fetch("https://html.duckduckgo.com/html/?" + params)
        pattern = r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        matches = re.finditer(pattern, page, re.I | re.S)
    except Exception:
        matches = []
    for match in matches:
        url = html.unescape(match.group(1))
        title = re.sub(r"<[^>]+>", "", html.unescape(match.group(2))).strip()
        if url.startswith("//"):
            url = "https:" + url
        if not url.lower().startswith("https://") or re.search(r"(?:login|log-in|signin|sign-in|authenticate|/auth(?:/|$)|/account(?:/|$))", url, re.I):
            continue
        results.append({"title": title[:160], "url": url[:500]})
        if len(results) >= 5:
            break
    if not results:
        provider = "https://www.bing.com/"
        rss_params = urllib.parse.urlencode({"format": "rss", "q": query})
        page = fetch("https://www.bing.com/search?" + rss_params)
        for match in re.finditer(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?</item>", page, re.I | re.S):
            title = re.sub(r"<[^>]+>", "", html.unescape(match.group(1))).strip()
            url = html.unescape(match.group(2)).strip()
            if not url.lower().startswith("https://") or re.search(r"(?:login|log-in|signin|sign-in|authenticate|/auth(?:/|$)|/account(?:/|$))", url, re.I):
                continue
            results.append({"title": title[:160], "url": url[:500]})
            if len(results) >= 5:
                break
        if not results:
            page = fetch("https://www.bing.com/search?" + params)
        for match in re.finditer(r'<li class="b_algo".*?<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
            url = html.unescape(match.group(1))
            title = re.sub(r"<[^>]+>", "", html.unescape(match.group(2))).strip()
            if not url.lower().startswith("https://") or re.search(r"(?:login|log-in|signin|sign-in|authenticate|/auth(?:/|$)|/account(?:/|$))", url, re.I):
                continue
            results.append({"title": title[:160], "url": url[:500]})
            if len(results) >= 5:
                break
    ignored = {"find", "relevant", "latest", "recent", "data", "public", "access", "use", "the", "for", "with"}
    terms = [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 3 and term not in ignored]
    if terms:
        ranked = sorted(results, key=lambda item: sum(term in (item.get("title", "") + " " + item.get("url", "")).lower() for term in terms), reverse=True)
        results = [item for item in ranked if any(term in (item.get("title", "") + " " + item.get("url", "")).lower() for term in terms)][:5]
    return {"tool": "public-search", "query": query, "results": results,
            "source": provider, "status": "completed",
            "contract": TOOL_CONTRACTS["public-search"]}


def public_json(url):
    data = json.loads(fetch(url, RESEARCH_MAX_BYTES))
    if isinstance(data, dict):
        summary = {"type": "object", "keys": sorted(str(key) for key in data)[:100], "items": len(data)}
    elif isinstance(data, list):
        sample_keys = sorted({str(key) for item in data[:10] if isinstance(item, dict) for key in item})[:100]
        summary = {"type": "array", "items": len(data), "sample_keys": sample_keys}
    else:
        summary = {"type": type(data).__name__}
    return {"tool": "public-json", "url": url, "summary": summary, "status": "completed",
            "contract": TOOL_CONTRACTS["public-json"]}


def public_csv(url):
    reader = csv.reader(io.StringIO(fetch(url, RESEARCH_MAX_BYTES)))
    headers = next(reader, [])[:100]
    row_count = 0
    truncated = False
    for _ in reader:
        row_count += 1
        if row_count >= CSV_MAX_ROWS:
            truncated = next(reader, None) is not None
            break
    summary = {"type": "table", "rows": row_count, "columns": len(headers), "headers": headers, "truncated": truncated}
    return {"tool": "public-csv", "url": url, "summary": summary, "status": "completed",
            "contract": TOOL_CONTRACTS["public-csv"]}


CODE_PUNCTUATION = re.compile(r"[{}();=<>]")


def clean_excerpt(text):
    """Drop template braces and minified script residue without touching prose.

    Only a single whitespace-delimited token longer than 60 characters that
    also contains code punctuation is removed; ordinary words such as
    "dataset" or "tap" are never a reason to cut surrounding text.
    """
    text = re.sub(r"\{\{.*?\}\}", " ", text)
    return re.sub(r"\S{61,}", lambda match: " " if CODE_PUNCTUATION.search(match.group(0)) else match.group(0), text)


def public_text(url):
    raw = SCRIPT_STYLE.sub(" ", fetch(url, RESEARCH_MAX_BYTES))
    text = clean_excerpt(re.sub(r"<[^>]+>", " ", html.unescape(raw)))
    text = re.sub(r"\s+", " ", text).strip()
    text = SENSITIVE_ASSIGNMENT.sub("[withheld]", text)
    text = BLOCKED.sub("[withheld]", text)
    return {"tool": "public-text", "url": url, "excerpt": text[:2400], "status": "completed",
            "contract": TOOL_CONTRACTS["public-text"]}


def run(tool, value):
    try:
        if tool == "local-code-read":
            # The broker is normally invoked as a script from this directory,
            # so import the sibling module without changing process paths.
            from code_view import run as read_source
            return {"tool": tool, **read_source(value or None), "contract": TOOL_CONTRACTS[tool]}
        if tool == "code-proposal-gate":
            from code_proposal import archive, validate
            patch = str(value or "")
            reason = validate(patch)
            item = archive(patch, "ready-for-review" if not reason else "rejected", reason, "tool-request")
            return {"tool": tool, "status": item["status"], "proposal": item, "contract": TOOL_CONTRACTS[tool]}
        if tool == "code-review-runner":
            from code_review import review
            return {"tool": tool, **review(str(value or "")), "contract": TOOL_CONTRACTS[tool]}
        if tool == "wikipedia-search":
            return wikipedia(value)
        if tool == "wikipedia-summary":
            return wikipedia_summary(value)
        if tool == "public-search":
            return public_search(value)
        if tool == "public-json":
            return public_json(value)
        if tool == "public-csv":
            return public_csv(value)
        if tool == "public-text":
            return public_text(value)
        return {"tool": tool, "status": "completed", "characters": len(fetch(value)), "contract": TOOL_CONTRACTS[tool]}
    except Exception as error:
        return {"tool": tool, "status": "rejected", "reason": str(error)[:120], "contract": TOOL_CONTRACTS[tool]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=tuple(TOOL_CONTRACTS))
    parser.add_argument("value")
    args = parser.parse_args()
    print(json.dumps(run(args.tool, args.value)))
