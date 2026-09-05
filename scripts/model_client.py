"""One door for every model call: a router over free hosted providers with the local model last.

Providers speak the OpenAI-style chat completions dialect that the world has
always used (llama.cpp, Mistral, Gemini's compatibility endpoint, Groq,
Cerebras, OpenRouter, or any custom endpoint). Keys are read from an
out-of-tree file (``~/.config/backrooms/env`` by default) into a module-level
dictionary, never into ``os.environ``, so child processes such as the broker
and the sandbox cannot inherit them. Usage and cooldowns are recorded in a
local, gitignored ledger so budgets survive across the subprocesses that make
up one cycle. The summary published to health.json contains counts only.
"""

import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USAGE = ROOT / "state/provider-usage.json"
DEFAULT_ENV_FILE = Path.home() / ".config/backrooms/env"
DEFAULT_ORDER = ("mistral", "mistral-8b", "mistral-small", "gemini", "cerebras", "groq", "openrouter", "custom", "local")
SECRET_NAME = re.compile(r"(?i)(key|token|secret|password|mnemonic|credential)")


class ModelUnavailable(OSError):
    """Every configured provider failed or is out of budget for this call."""


def _load_env_file(path=None):
    """Parse KEY=VALUE lines from the out-of-tree secrets file (never exported)."""
    path = Path(path or os.getenv("BACKROOMS_ENV_FILE") or DEFAULT_ENV_FILE)
    values = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


SECRETS = _load_env_file()


def setting(name, default=None):
    """Configuration lookup: the secrets file first, then the process environment."""
    value = SECRETS.get(name)
    if value is None:
        value = os.getenv(name)
    return default if value in (None, "") else value


BUILTIN = {
    # Mistral limits are per model, not per account: on the free tier mistral-small
    # allows 20k tokens a minute while the Ministral models allow 600k+ and many
    # more requests. The family shares one key but each entry keeps its own
    # window and cooldown, so a throttled model hands over to the next.
    # Daily token budgets keep a month of cycles inside the free tier's monthly
    # credit (about ten dollars): 900k + 400k + 100k tokens a day is roughly
    # five dollars a month at these models' list prices.
    "mistral": {"base_url": "https://api.mistral.ai", "key": "MISTRAL_API_KEY", "model": "ministral-14b-2512",
                "rpm": 20, "rpd": None, "tpd": 900_000, "json_schema": True},
    "mistral-8b": {"base_url": "https://api.mistral.ai", "key": "MISTRAL_API_KEY", "model": "ministral-8b-2512",
                   "rpm": 120, "rpd": None, "tpd": 400_000, "json_schema": True},
    "mistral-small": {"base_url": "https://api.mistral.ai", "key": "MISTRAL_API_KEY", "model": "mistral-small-latest",
                      "rpm": 10, "rpd": None, "tpd": 100_000, "json_schema": True},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": "GEMINI_API_KEY",
               "model": "gemini-2.5-flash", "rpm": 8, "rpd": 240, "tpd": None, "json_schema": True,
               "chat_path": "/chat/completions", "models_path": "/models", "resolve_model": "gemini-flash",
               # Gemini 3 models think before answering and the thinking counts as output:
               # ask for the lightest setting and never cap a call below this many tokens.
               "reasoning_effort": "low", "min_max_tokens": 1024},
    "cerebras": {"base_url": "https://api.cerebras.ai", "key": "CEREBRAS_API_KEY", "model": "qwen-3-32b",
                 "rpm": 25, "rpd": None, "tpd": 900000, "json_schema": True},
    "groq": {"base_url": "https://api.groq.com/openai", "key": "GROQ_API_KEY", "model": "llama-3.3-70b-versatile",
             "rpm": 4, "rpd": 900, "tpd": None, "json_schema": True},
    "openrouter": {"base_url": "https://openrouter.ai/api", "key": "OPENROUTER_API_KEY",
                   "model": "mistralai/mistral-small-3.2-24b-instruct:free", "rpm": 15, "rpd": 45, "tpd": None,
                   "json_schema": False},
}


def providers(local_base_url=None):
    """Ordered provider list built from whatever keys exist; local is always last."""
    order = [item.strip() for item in str(setting("BACKROOMS_PROVIDER_ORDER", ",".join(DEFAULT_ORDER))).split(",") if item.strip()]
    built = []
    for name in order:
        if name == "local":
            url = local_base_url or setting("BACKROOMS_LOCAL_BASE_URL", "http://127.0.0.1:8080")
            built.append({"name": "local", "base_url": url, "api_key": None, "model": setting("BACKROOMS_LLM_MODEL", "local"),
                          "rpm": None, "rpd": None, "tpd": None, "json_schema": True})
            continue
        if name == "custom":
            url = setting("BACKROOMS_LLM_BASE_URL")
            if not url or url.rstrip("/") == (local_base_url or "").rstrip("/"):
                continue
            built.append({"name": "custom", "base_url": url, "api_key": setting("BACKROOMS_LLM_API_KEY"),
                          "model": setting("BACKROOMS_LLM_MODEL", "default"), "rpm": _int(setting("BACKROOMS_CUSTOM_RPM")),
                          "rpd": _int(setting("BACKROOMS_CUSTOM_RPD")), "tpd": None,
                          "json_schema": setting("BACKROOMS_CUSTOM_JSON_SCHEMA", "1") == "1"})
            continue
        spec = BUILTIN.get(name)
        if not spec:
            continue
        api_key = setting(spec["key"])
        if not api_key:
            continue
        prefix = "BACKROOMS_" + name.upper().replace("-", "_")
        built.append({"name": name, "base_url": spec["base_url"], "api_key": api_key,
                      "model": setting(prefix + "_MODEL", spec["model"]),
                      "rpm": _int(setting(prefix + "_RPM"), spec["rpm"]), "rpd": _int(setting(prefix + "_RPD"), spec["rpd"]),
                      "tpd": _int(setting(prefix + "_TPD"), spec["tpd"]), "json_schema": spec["json_schema"],
                      # endpoint quirks and live model resolution travel with the provider
                      **{key: spec[key] for key in ("chat_path", "models_path", "resolve_model", "reasoning_effort", "min_max_tokens") if key in spec},
                      "model_overridden": bool(setting(prefix + "_MODEL"))})
    return built


def _int(value, default=None):
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def configured_remote():
    return any(item["name"] != "local" for item in providers())


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _load_usage():
    try:
        usage = json.loads(USAGE.read_text())
    except (OSError, json.JSONDecodeError):
        usage = {}
    if usage.get("day") != _today():
        usage = {"day": _today(), "providers": {}}
    usage.setdefault("providers", {})
    return usage


def _save_usage(usage):
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    temporary = USAGE.with_suffix(".tmp")
    temporary.write_text(json.dumps(usage, indent=2) + "\n")
    os.replace(temporary, USAGE)


def _record(usage, name, **fields):
    entry = usage["providers"].setdefault(name, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0,
                                                 "last_error": "", "cooldown_until": 0, "last_call_at": 0, "disabled": False})
    for key, value in fields.items():
        if key in ("calls", "input_tokens", "output_tokens", "errors"):
            entry[key] = entry.get(key, 0) + value
        else:
            entry[key] = value
    return entry


def _available(provider, usage, now):
    entry = usage["providers"].get(provider["name"], {})
    if entry.get("disabled"):
        return False, "disabled"
    if entry.get("cooldown_until", 0) > now:
        return False, "cooldown"
    if provider["rpd"] and entry.get("calls", 0) >= provider["rpd"]:
        return False, "daily-request-budget"
    if provider["tpd"] and entry.get("input_tokens", 0) + entry.get("output_tokens", 0) >= provider["tpd"]:
        return False, "daily-token-budget"
    return True, ""


def _note_success(usage, name, prompt_tokens, completion_tokens, limits, now, **fields):
    entry = _record(usage, name, calls=1, input_tokens=prompt_tokens, output_tokens=completion_tokens, last_call_at=now, **fields)
    cost = int(prompt_tokens) + int(completion_tokens)
    entry["last_cost"] = cost
    _window(entry, now).append([now, cost])
    if limits.get("rpm"):
        entry["limit_rpm"] = limits["rpm"]
    if limits.get("tpm"):
        entry["limit_tpm"] = limits["tpm"]
    # The provider says the minute is spent: hold until a fresh one, whatever the local window thinks.
    if limits.get("remaining_rpm") == 0 or (limits.get("remaining_tpm") is not None and limits["remaining_tpm"] < cost):
        entry["hold_until"] = now + WINDOW_SECONDS
    return entry


def _pace(provider, entry, now, sleep=time.sleep):
    wait = 0.0
    rpm = min([limit for limit in (provider.get("rpm"), entry.get("limit_rpm")) if limit] or [0])
    if rpm:
        wait = max(wait, entry.get("last_call_at", 0) + 60.0 / rpm - now)
    wait = max(wait, _minute_wait(provider, entry, now))
    if wait > 0:
        sleep(min(wait, WINDOW_SECONDS + 1))


def _schema_hint(messages, schema):
    """Providers without schema mode get the schema in the prompt instead."""
    hinted = [dict(item) for item in messages]
    hinted[-1]["content"] = str(hinted[-1].get("content", "")) + "\nReturn only a JSON object matching this schema: " + json.dumps(schema)[:2000]
    return hinted


BUSY_MODEL_SECONDS = 300  # an overloaded model is skipped for five minutes, then tried again
GEMINI_FLASH = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash(?:-preview[-\w]*|-\d{2}-\d{4})?$")
UNWANTED_MODEL = re.compile(r"lite|image|tts|live|audio|embed|8b|thinking|native|exp", re.I)


def choose_gemini_model(model_ids, fallback, failed=()):
    """The newest general Flash model the account can see: a released name over a
    preview or dated one, the newest version among those, a 'latest' alias when
    nothing is versioned. Never a lite, image, audio, live, or experimental variant,
    and never a name that already answered 404 today."""
    best = None
    failed = {str(item) for item in (failed or ())}
    for raw in model_ids or []:
        name = str(raw or "").split("/")[-1].strip()
        if name in failed or "flash" not in name or not name.startswith("gemini") or UNWANTED_MODEL.search(name.replace("gemini-", "", 1)):
            continue
        match = re.search(r"gemini-(\d+(?:\.\d+)?)-flash", name)
        try:
            version = float(match.group(1)) if match else 0.0
        except ValueError:
            version = 0.0
        plain = 0 if re.search(r"preview|-\d{2}-\d{4}$", name) else 1
        key = (plain, version, 1 if "latest" in name else 0, -len(name), name)
        if best is None or key > best[0]:
            best = (key, name)
    return best[1] if best else fallback


MINIMAL_THINKING = re.compile(r"gemini-(?:3\.6-flash|3\.5-flash-lite|3\.1-flash-lite)")


def thinking_setting(model, default="low"):
    """The lightest thinking the docs allow: 'minimal' on 3.6 Flash and the Flash-Lite
    models, 'low' on the other Gemini 3 models (thinking cannot be turned off there)."""
    name = str(model or "")
    if MINIMAL_THINKING.search(name):
        return "minimal"
    return default or "low"


def _list_models(provider, opener=None, timeout=20):
    headers = {"Authorization": "Bearer " + provider["api_key"]} if provider.get("api_key") else {}
    request = urllib.request.Request(provider["base_url"].rstrip("/") + provider.get("models_path", "/v1/models"), headers=headers)
    with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
        data = json.load(response)
    return [item.get("id") for item in (data.get("data") or []) if isinstance(item, dict)]


def resolve_model(provider, usage, opener=None):
    """Providers marked ``resolve_model`` pick their model from the live list once
    a day (an override in BACKROOMS_<NAME>_MODEL wins); the choice is recorded."""
    if not provider.get("resolve_model") or provider.get("model_overridden"):
        return provider
    cache = usage.setdefault("models", {})
    if cache.get(provider["name"]):
        return {**provider, "model": cache[provider["name"]], "reasoning_effort": thinking_setting(cache[provider["name"]], provider.get("reasoning_effort"))}
    now = time.time()
    busy = usage.get("models_busy", {}).get(provider["name"], {})
    failed = list(usage.get("models_failed", {}).get(provider["name"], [])) + [name for name, until in busy.items() if float(until or 0) > now]
    try:
        listed = _list_models(provider, opener)
    except Exception as error:  # noqa: BLE001 - the configured name is used and the listing retried on the next call
        usage.setdefault("models_seen", {})[provider["name"]] = ["listing failed: " + type(error).__name__]
        return provider
    usage.setdefault("models_seen", {})[provider["name"]] = [str(item).split("/")[-1][:48] for item in listed[:40]]
    chosen = choose_gemini_model(listed, provider["model"], failed)
    cache[provider["name"]] = chosen
    return {**provider, "model": chosen, "reasoning_effort": thinking_setting(chosen, provider.get("reasoning_effort"))}


def _request(provider, messages, temperature, max_tokens, schema, schema_name, timeout, opener=None):
    payload = {"model": provider["model"], "messages": messages, "temperature": temperature,
               "max_tokens": max(int(max_tokens), int(provider.get("min_max_tokens") or 0))}
    if provider.get("reasoning_effort"):
        payload["reasoning_effort"] = provider["reasoning_effort"]
    if schema is not None:
        if provider["json_schema"]:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
        else:
            payload["messages"] = _schema_hint(messages, schema)
    headers = {"Content-Type": "application/json"}
    if provider["api_key"]:
        headers["Authorization"] = "Bearer " + provider["api_key"]
    request = urllib.request.Request(provider["base_url"].rstrip("/") + provider.get("chat_path", "/v1/chat/completions"),
                                     data=json.dumps(payload).encode(), headers=headers, method="POST")
    with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
        data = json.load(response)
        limits = _limits_from_headers(getattr(response, "headers", None))
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # some servers return content parts
        content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
    if not content:
        raise ValueError(f"empty reply (finish_reason={choice.get('finish_reason')})")
    usage = data.get("usage") or {}
    return str(content or "").strip(), int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), limits


WINDOW_SECONDS = 60.0
DEFAULT_CALL_COST = 1500


def _limits_from_headers(headers):
    """Per-minute limits the provider states on every response (OpenAI-style
    x-ratelimit headers). Learned limits override the built-in defaults, so
    the router paces to what the account actually has, not to the brochure."""
    if not headers:
        return {}
    found = {}
    for key, value in headers.items():
        name = str(key).lower()
        if not name.startswith("x-ratelimit-"):
            continue
        number = _int(value)
        if number is None:
            continue
        if name in ("x-ratelimit-limit-req-minute", "x-ratelimit-limit-requests"):
            found["rpm"] = number
        elif name in ("x-ratelimit-limit-tokens-minute", "x-ratelimit-limit-tokens"):
            found["tpm"] = number
        elif name in ("x-ratelimit-remaining-req-minute", "x-ratelimit-remaining-requests"):
            found["remaining_rpm"] = number
        elif name in ("x-ratelimit-remaining-tokens-minute", "x-ratelimit-remaining-tokens"):
            found["remaining_tpm"] = number
    return found


def _window(entry, now):
    """Calls made in the last minute as [timestamp, tokens] pairs."""
    window = [item for item in entry.get("window", []) if isinstance(item, list) and len(item) == 2 and now - float(item[0]) < WINDOW_SECONDS]
    entry["window"] = window
    return window


def _minute_wait(provider, entry, now):
    """Seconds to wait so the next call stays inside the per-minute request and
    token limits, using the learned limits when the provider stated them."""
    rpm = min([limit for limit in (provider.get("rpm"), entry.get("limit_rpm")) if limit] or [0])
    tpm = entry.get("limit_tpm") or provider.get("tpm")
    window = _window(entry, now)
    wait = 0.0
    if rpm and len(window) >= rpm:
        wait = max(wait, float(window[-rpm][0]) + WINDOW_SECONDS - now)
    if tpm:
        expected = int(entry.get("last_cost") or DEFAULT_CALL_COST)
        used = sum(int(item[1]) for item in window)
        for stamp, tokens in window:
            if used + expected <= tpm:
                break
            wait = max(wait, float(stamp) + WINDOW_SECONDS - now)
            used -= int(tokens)
    hold = float(entry.get("hold_until", 0) or 0) - now
    return max(0.0, wait, hold)


RETRY_429_MAX_WAIT = 10
COOLDOWN_WAIT_MAX = 60


def _soonest_cooldown(ordered, usage, now):
    """Seconds until the first rate-limited provider is usable again, or None."""
    waits = []
    for provider in ordered:
        entry = usage["providers"].get(provider["name"], {})
        if entry.get("disabled") or provider["name"] == "local":
            continue
        ok, why = _available(provider, usage, now)
        if why == "cooldown":
            waits.append(max(0.0, entry.get("cooldown_until", 0) - now))
    return min(waits) if waits else None


def _error_detail(error):
    """The provider's own one-line reason for a 429, without anything secret."""
    try:
        body = error.read().decode("utf-8", "replace")[:400]
    except Exception:  # noqa: BLE001
        return ""
    try:
        data = json.loads(body)
        if isinstance(data, list) and data:
            data = data[0]  # Google wraps its error object in a list
        text = data.get("message") or (data.get("error") or {}).get("message") if isinstance(data, dict) else ""
    except (ValueError, AttributeError):
        text = body
    return re.sub(r"[A-Za-z0-9_\-]{24,}", "[redacted]", str(text or ""))[:80]


def _retry_after(error):
    """Seconds the provider asked us to wait; a per-second limit without the
    header needs only a short pause, not a minute."""
    headers = getattr(error, "headers", None)
    return _int(headers.get("Retry-After"), 15) if headers else 15


TRANSIENT_STATUSES = (408, 429, 500, 502, 503, 504)
TRANSIENT_RETRIES = 3


def _request_with_retry(provider, messages, temperature, max_tokens, schema, schema_name, timeout, opener, sleep):
    """Transient answers (429, 408, 5xx) are retried on the same provider with
    exponential backoff and jitter, as the provider's own guidance says: about a
    second, then two, then four. A Retry-After longer than the backoff cap means
    a real cooldown, so the error is raised for the provider loop to handle."""
    delay = 1.0
    for attempt in range(TRANSIENT_RETRIES + 1):
        try:
            return _request(provider, messages, temperature, max_tokens, schema, schema_name, timeout, opener)
        except urllib.error.HTTPError as error:
            status = getattr(error, "code", 0)
            if status not in TRANSIENT_STATUSES or attempt == TRANSIENT_RETRIES:
                raise
            wait = delay
            if getattr(error, "headers", None) and (error.headers or {}).get("Retry-After"):
                wait = max(wait, _retry_after(error))
            if wait > RETRY_429_MAX_WAIT:
                raise
            sleep(wait)
            delay *= 2


def ordered_providers(available, prefer=None):
    """The configured order, with the caller's preferred providers moved to the front in the order given."""
    prefer = [name for name in (prefer or ()) if name]
    if not prefer:
        return list(available)
    by_name = {item["name"]: item for item in available}
    front = [by_name[name] for name in prefer if name in by_name]
    return front + [item for item in available if item["name"] not in set(prefer)]


def _note_call(usage, call_class, provider, model, messages, clock=time.time):
    """Lineage for the record: which provider and model answered which prompt (by hash), never the text."""
    prompt_hash = hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:16]
    calls = usage.setdefault("calls", [])
    calls.append({"at": round(clock(), 1), "class": str(call_class)[:24], "provider": provider, "model": str(model)[:60], "prompt_sha256_16": prompt_hash})
    usage["calls"] = calls[-60:]


def complete(messages, *, temperature=0.3, max_tokens=400, schema=None, schema_name="response", call_class="general",
             base_url=None, timeout=90, opener=None, sleep=time.sleep, clock=time.time, prefer=None):
    """Return the model's text from the first provider that answers; raise ModelUnavailable if none does.

    When every provider is out and at least one is only cooling down briefly (a
    rate limit rather than a budget or bad credentials), the cooldown is waited
    out once and the providers are tried again, so a single free-tier provider
    can carry the world without a call being lost to a momentary 429.
    """
    usage = _load_usage()
    failures = []
    ordered = ordered_providers(providers(base_url), prefer)
    for attempt in range(2):
        for provider in ordered:
            now = clock()
            ok, why = _available(provider, usage, now)
            if not ok:
                failures.append(f"{provider['name']}:{why}")
                continue
            provider = resolve_model(provider, usage, opener)
            entry = _record(usage, provider["name"])
            _pace(provider, entry, now, sleep)
            try:
                content, prompt_tokens, completion_tokens, limits = _request_with_retry(provider, messages, temperature, max_tokens, schema, schema_name, timeout, opener, sleep)
            except urllib.error.HTTPError as error:
                status = getattr(error, "code", 0)
                if status == 429:
                    retry_after = _retry_after(error)
                    detail = _error_detail(error)
                    _record(usage, provider["name"], errors=1, last_call_at=clock(),
                            last_error=f"429 rate limited ({call_class})" + (f": {detail}" if detail else ""),
                            cooldown_until=clock() + max(15, min(retry_after, 900)))
                elif status in (401, 403):
                    _record(usage, provider["name"], errors=1, last_error=f"{status} rejected credentials", disabled=True)
                elif status == 400 and schema is not None and provider["json_schema"]:
                    # Some endpoints reject schema mode for a given model; retry once with a prompt hint.
                    try:
                        content, prompt_tokens, completion_tokens, limits = _request({**provider, "json_schema": False}, messages, temperature, max_tokens, schema, schema_name, timeout, opener)
                        _note_success(usage, provider["name"], prompt_tokens, completion_tokens, limits, clock(), last_error="400 on schema mode; prompt hint used")
                        _note_call(usage, call_class, provider["name"], provider.get("model"), messages, clock)
                        _save_usage(usage)
                        return content, provider["name"]
                    except Exception as retry_error:  # noqa: BLE001 - recorded and passed to the next provider
                        _record(usage, provider["name"], errors=1, last_error=f"400 {str(retry_error)[:80]}", cooldown_until=clock() + 30)
                else:
                    detail = _error_detail(error)
                    _record(usage, provider["name"], errors=1, last_error=(f"{status} {call_class}" + (f": {detail}" if detail else ""))[:160],
                            cooldown_until=clock() + (0 if status in (502, 503) and provider.get("resolve_model") else 30))
                    if status in (502, 503) and provider.get("resolve_model"):
                        # The newest model is overloaded on the free tier: step down to the next
                        # one for a while instead of losing the provider, and try again at once.
                        usage.setdefault("models_busy", {}).setdefault(provider["name"], {})[provider["model"]] = clock() + BUSY_MODEL_SECONDS
                        usage.get("models", {}).pop(provider["name"], None)
                    if status == 404 and provider.get("resolve_model"):
                        # A stale model name: remember it failed, take the provider's own
                        # suggestion when the message names one, and otherwise list again.
                        usage.get("models", {}).pop(provider["name"], None)
                        failed = usage.setdefault("models_failed", {}).setdefault(provider["name"], [])
                        if provider["model"] not in failed:
                            failed.append(provider["model"])
                        hint = re.search(r"use models/([a-z0-9][a-z0-9.\-]+)", detail or "")
                        if hint and hint.group(1) not in failed:
                            usage.setdefault("models", {})[provider["name"]] = hint.group(1)
                failures.append(f"{provider['name']}:{status}")
                continue
            except Exception as error:  # noqa: BLE001 - any transport failure moves to the next provider
                _record(usage, provider["name"], errors=1, last_error=f"{type(error).__name__} ({call_class})", cooldown_until=clock() + (5 if provider["name"] == "local" else 30))
                failures.append(f"{provider['name']}:{type(error).__name__}")
                continue
            _note_success(usage, provider["name"], prompt_tokens, completion_tokens, limits, clock())
            _note_call(usage, call_class, provider["name"], provider.get("model"), messages, clock)
            _save_usage(usage)
            return content, provider["name"]
        if attempt == 0:
            wait = _soonest_cooldown(ordered, usage, clock())
            if wait is None or wait > COOLDOWN_WAIT_MAX:
                break
            _save_usage(usage)
            sleep(wait + 0.5)
    _save_usage(usage)
    raise ModelUnavailable("no model provider answered: " + ", ".join(failures)[:300])


def complete_json(messages, **kwargs):
    """Return (parsed object or None, provider)."""
    content, provider = complete(messages, **kwargs)
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", content or "", re.S)
        try:
            parsed = json.loads(match.group(0)) if match else None
        except ValueError:
            parsed = None
    return parsed, provider


def probe(local_base_url=None, opener=None, timeout=8):
    """A cheap, measured check of the first usable provider (GET /v1/models, or /health locally)."""
    for provider in providers(local_base_url):
        try:
            if provider["name"] == "local":
                request = urllib.request.Request(provider["base_url"].rstrip("/") + "/health")
            else:
                request = urllib.request.Request(provider["base_url"].rstrip("/") + "/v1/models",
                                                 headers={"Authorization": "Bearer " + provider["api_key"]})
            with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
                if response.status == 200:
                    return {"ok": True, "provider": provider["name"], "model": provider["model"]}
        except Exception as error:  # noqa: BLE001 - reported, not raised
            last = f"{provider['name']}: {type(error).__name__}"
            continue
    return {"ok": False, "provider": None, "model": None, "error": locals().get("last", "no providers configured")}


def usage_summary(local_base_url=None):
    """Counts only; never keys or endpoints beyond the provider's name."""
    usage = _load_usage()
    summary = {"day": usage.get("day"), "providers": [], "recent_calls": list(usage.get("calls", []))[-30:],
               "models_seen": usage.get("models_seen", {})}
    for provider in providers(local_base_url):
        entry = usage["providers"].get(provider["name"], {})
        summary["providers"].append({
            "name": provider["name"], "model": usage.get("models", {}).get(provider["name"]) or provider["model"], "calls": entry.get("calls", 0),
            "input_tokens": entry.get("input_tokens", 0), "output_tokens": entry.get("output_tokens", 0),
            "errors": entry.get("errors", 0), "last_error": str(entry.get("last_error", ""))[:120],
            "daily_request_budget": provider["rpd"], "daily_token_budget": provider["tpd"],
            "limit_rpm": entry.get("limit_rpm") or provider.get("rpm"), "limit_tpm": entry.get("limit_tpm") or provider.get("tpm"),
            "requests_last_minute": len(_window(entry, time.time())), "tokens_last_minute": sum(int(item[1]) for item in entry.get("window", [])),
            "status": ("disabled" if entry.get("disabled") else "cooldown" if entry.get("cooldown_until", 0) > time.time() else "ready")})
    return summary


def child_env(environ=None):
    """Environment for subprocesses that must never see model or wallet credentials."""
    return {key: value for key, value in (environ if environ is not None else os.environ).items() if not SECRET_NAME.search(key)}
