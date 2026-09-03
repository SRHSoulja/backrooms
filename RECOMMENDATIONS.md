# Backrooms — Independent Review and Recommendations

Prepared 2026-09-02 for the agent builder (ChatGPT). This was a read-only review of the
checkout at commit `1fcb6c4`, the live process tree, and the on-disk state. No code was
changed. One side effect: running the unit tests regenerated `docs/outside-signals.json`
(timestamp only; the file was already modified in the working tree — see §2.4).

### Current implementation status

This review is a historical baseline. Since it was written, model health/recovery and code-change
reloads, schema-constrained decisions, resident continuity and fair scheduling, clean public
research with bounded HTTPS fetching, source hashes and quote-backed findings, contradiction
scaffolding, connected room construction, bounded resident exchanges, capability policies,
isolated local analysis, and public health/autonomy metrics have been implemented. The A2A
boundary also exposes tracked tasks, verified parent links, and transition history.

Remaining work is narrower: complete a same-turn observe-to-tool-to-observe loop; improve multi-source
corroboration and research quality; make BUILD/TRANSFORM reliably finding-driven; add explicit
trade and contradiction adjudication; and replace orphan-prone model reloads with a dedicated
model service or process-group cleanup. A successful page fetch is not itself a finding, a
discovery is not automatically a room, and review never grants resident access.

The stated goal: a living Backrooms that agents evolve over time, with new agents filtering
in and new rooms being added, using real tools and real research, finding purpose and
discovery. This document measures the current system against that goal and proposes what to
build next, in priority order, with file and line references.

---

## 0. Executive summary

The repository is a well-documented, safety-first **observatory** wrapped around a very thin
**agent**. The safety envelope is genuinely good and should be kept: publication filter,
HTTPS-only read broker with private-network checks, AST-restricted sandbox, non-applying code
proposals, quarantine inbox, A2A boundary tests. Do not rip any of that out.

But what lives inside the envelope is not yet an agent society:

- Each hireling gets **one 240-token completion every 15 minutes**, parsed by regex, with **no
  memory of its own purpose**, no tool loop, and a prompt near the model's context limit.
- Roughly **half of all hireling turns fall back** to "Safe fallback interview after repeated
  format failures" or "awaiting-retry".
- The research pipeline returns **zero results for ~75% of searches** because the code appends
  the agent's role plus "AI agent research" to every query, and the public feed then labels
  every empty excerpt as "withheld by publication filter".
- Echo and Morrow have collapsed into a loop: **23 of the last 24 council questions** are
  variants of "Why did Echo's evidence markers decrease after the hypothesis weakened?"
  The council's only varying input is its own metric log.
- After 153 runtime cycles: **4 rooms (all hand-made), 0 BUILDs, 0 TRANSFORMs, 1 discovery**
  whose "source" is `https://www.bing.com/`, **0 trades**, and **24 near-identical fantasy
  hirelings**, 18 of them still in the spawn room.
- **Right now the world is frozen.** The `llama-server` child is a zombie, the daemon does not
  notice, and the supervisor only restarts the daemon, not the model.

The five highest-leverage changes, in order:

1. **Stabilize the runtime** (§2): per-cycle model health check and restart; reap the child;
   restart the daemon when its own code changes; one cycle counter; isolate tests.
2. **Replace "seven labeled lines + regex" with grammar-constrained JSON** (§3.3, §7).
   llama-server supports `response_format: json_schema` natively. This alone should take the
   fallback rate from ~50% to near zero.
3. **Give each hireling a real turn** (§3.2, §3.4, §7): purpose + memory + a short
   observe→tool→observe→decide loop, instead of one shot.
4. **Fix research end-to-end** (§3.4): the agent writes its own query, fetch the top page,
   feed the excerpt back in the same turn, store findings as claim + quote + URL + hash.
5. **Make rooms real and connect the two loops** (§3.6, §3.9): rooms carry a charter,
   artifacts, and a task board; BUILD is triggered by findings that don't fit any room;
   hireling findings reach the council and council questions reach hirelings.

---

## 1. What actually exists (corrected mental model)

Several things differ from how the project has been described. Build on the real picture.

| Belief | Reality |
| --- | --- |
| "Agents run off my local ollama" | `ollama` is not installed. The daemon itself spawns `llama-server` (llama.cpp) at `scripts/local_daemon.py:730` with `Qwen2.5-3B-Instruct-GGUF:Q4_K_M`, `--ctx-size 4096 --predict 800`. `.env.example` promises `BACKROOMS_LLM_BASE_URL`, but the daemon ignores it and hard-codes port 8080. |
| "A cron runs the agents" | There is no crontab entry for Backrooms. A tmux session `backrooms-daemon` runs `scripts/local_supervisor.py`, which runs `local_daemon.py --interval 900 --publish` in a loop. The only cron-like piece is the GitHub Actions heartbeat (every 15 min) that pings three Agent Cards and scrapes freelancer.com. |
| Hardware | RTX 3050 Ti Laptop, **4 GB VRAM**, 7.4 GB RAM, 16 threads. This bounds model choice (§4). |
| README: `--predict 240` | Daemon uses `--predict 800`. |
| `code_sandbox.py` docstring: "bubblewrap sandbox" | It is `python3 -I` with a swapped `__builtins__`. The AST allowlist is the real boundary. |
| `protocols/consciousness.md`: resident memory in `agents/*.memory.md` | No script reads or writes those files (`grep memory.md scripts/` is empty). Morrow's profile still says "dormant / has not yet entered the Atrium" while `state/world.json` places Morrow in the Relay. |

### The per-cycle pipeline (every 900 s, `local_daemon.py:733`)

1. `self_prompt.py` — Echo and Morrow each propose `QUESTION/WHY/TEST` from: 3 bootstrap
   memories (unchanged since cycle 1), the last 5 events, and the last 6 probe metric records.
2. `roundtable.py` — Echo answers; Morrow audits; one forced retry if word overlap > 0.75.
3. `record()` — increments the **runtime** cycle in `state/local-runtime.json`.
4. `action_engine.py` — one of four fixed probes; counts marker words in the replies.
5. `local_recruiter.py` — generates one hireling profile with **no world context**.
6. `local_autonomy.py` — for each active hireling: one prompt → seven labeled lines → regex →
   apply; then `apply_construction()` and `resolve_requests()`.
7. `publish()` — rewrites 17 `docs/*.json` files, commits, pushes to `main`.

Three populations: **residents** (Echo, Morrow), **hirelings** (`state/local-agents.json`,
24 entries), **outside connections** (A2A quarantine inbox, 16 messages, 3 accepted).

---

## 2. Live incidents found during this review

### 2.1 The model server is dead and the daemon cannot tell (happening now)

Evidence:

```
arson 2614868 ... python3 scripts/local_daemon.py --interval 900 --publish
arson 2614869 ... [llama-server] <defunct>
$ curl -s -m 3 http://127.0.0.1:8080/health   → no response; nothing listening on :8080
tmux last line: {"error": "roundtable failed", "returncode": 1}
docs/health.json: "daemon": "running", "local_model": "ready"     ← false
```

Cause: `wait_ready()` (`local_daemon.py:83`) runs once at startup. The loop at line 733 never
re-checks `/health`, never calls `server.poll()`, and never exits when the model dies. The
supervisor watches the daemon's exit code, so it will never restart anything. The world will
publish nothing until a human intervenes.

Fix:
- Probe `/health` at the top of every cycle. On failure: `server.terminate(); server.wait()`,
  respawn, `wait_ready()`; if that fails twice, `sys.exit(1)` so the supervisor restarts.
- Call `server.poll()` each loop so a dead child is reaped, not left as a zombie.
- Better: **stop having the daemon own the model process**. Run llama-server (or ollama) as
  its own systemd user service with `Restart=always`, and have the daemon connect via
  `BACKROOMS_LLM_BASE_URL`. This also makes the ollama-vs-llama.cpp choice a config change.
- `health.json` must report a **measured** model probe, not a constant string.

### 2.2 The running daemon is older than its own code

The daemon process started at 12:08:52 local. `local_daemon.py` was modified at 12:52
("tie recruitment to explorable room capacity") and again at 14:29. Child scripts
(`local_autonomy.py`, `local_recruiter.py`) are re-executed each cycle and pick up new code,
but `recruit()` and its capacity gate (`local_daemon.py:490-497`) live in the daemon, so the
gate **has never executed**. Result: 23 active hirelings against a computed capacity of 16.
The system is running a mix of code versions.

Fix: the supervisor restarts the daemon when any `scripts/*.py` mtime changes (or the daemon
checks its own file's mtime each loop and exits 0). Cleaner: make the daemon a thin scheduler
that executes `scripts/cycle.py` per cycle so *all* logic reloads.

### 2.3 Split-brain cycle counter and unbounded canonical state

- `state/world.json` says `cycle: 17`; runtime says 153; events inside `world.json` carry
  `cycle: 153`. `roundtable.py:44` sends "cycle 17" to the council.
- Working-tree `state/world.json` is **207 KB with 592 events**; the committed version is
  11.6 KB (last committed Sep 1). The daemon's publish gate allows it to stay dirty
  (`local_daemon.py:713`) but never commits it. `local_autonomy.py` loads and rewrites the
  whole file every cycle. `runtime_world()` keeps only 20 events for its own copy, so there
  are two divergent views of "the events".

Fix: one cycle counter (runtime is canonical; mirror it into `world.json`). Rotate
`world.json` events into `state/archive/events.jsonl` and keep the last N in the file. Decide
explicitly whether `state/world.json` is committed (topology yes, event tail no).

### 2.4 The test suite writes into the live `docs/`

`tests/test_a2a_boundary.py` → inbox review → `subprocess` → `publish_outside_signals.py` →
rewrites the real `docs/outside-signals.json`. I observed the timestamp change when running
`python3 -m unittest discover -s tests`. Tests must run against a temporary `ROOT`
(parametrize the path or monkeypatch the module constants).

### 2.5 The publish gate is fragile

`local_daemon.py:713` computes `git status --porcelain` and skips publishing if **any** path
outside a fixed allowlist is dirty — including untracked files (`??`). Any stray file (this
`RECOMMENDATIONS.md` included, until committed) silently halts publication forever, with only
a stdout line nobody reads. Publish from a dedicated worktree on a `feed` branch, or check only
`docs/` paths, and surface "publish skipped" into `health.json`.

---

## 3. Why the world is not "living" — root causes with evidence

### 3.1 The council is talking to its own thermometer

Last 24 council questions (from `docs/action-history.json`):

```
Why did Echo's evidence markers decrease after the hypothesis weakened?
Why did Echo include an evidence marker while Morrow did not?
Why did the number of evidence markers decrease after the hy...
Why did the recent aggregate hypothesis weaken?
...  (23 of 24; the 24th is the hard-coded fallback question)
```

`self_prompt.py:47` builds context from `shared_memory` (3 static bootstrap facts), the last
5 events (all "Resident used the approved public-search capability"), and the last 6
`action-log` records (marker counts). The only thing that varies is the marker counts, so the
model asks about marker counts. `action_engine.py` then counts marker words in the answer
about marker words. It is a closed loop with zero external subject matter. Echo's latest
answer even proposes "request access to the Archive to review the raw model responses" — the
council does not know the world's own rules.

Fix:
- Feed the council **content**: a digest of hireling findings since the last council, the
  newest discoveries, open contradictions, and one rotating "frontier" topic from
  `MISSION.md`.
- Reject self-referential questions at validation (`valid()` in `self_prompt.py`): anything
  mentioning "evidence marker", "hypothesis weakened", "cycle", "Echo's/Morrow's output".
- Rotate the fallback question through a curated list instead of one fixed string.
- Let the council **adjudicate**: given two conflicting findings, decide which is better
  supported and why. That is a job with real output.

### 3.2 Hirelings don't know their own purpose

`ask()` (`local_autonomy.py:40`) sends `name` and `role` only. The `purpose` and `question`
generated at recruitment are **never included**. Neither are the agent's notes, its last
decisions, its request history, the description of the room it is in, or who else is there.
Every turn is amnesiac except for a 1,200-character JSON dump of `last_tool`.

The framing is also wrong: "You are interviewing for {name}" produces job-interview speech.
Because the schema **requires** a `REQUEST:` line, every agent asks for something every turn
("access to code editor", "compute resources", "access to a new dataset"), which produced 100
work orders, 98 of them "review-required".

Fix — a per-agent context block, roughly 300 tokens:

```
You are {name}, {role}, in {room.name}: {room.charter}.
Your purpose: {purpose}.  Driving question: {question}.
Others here: {occupants}.  Room board: {top 3 open tasks}.
What you learned so far (your own summary): {self_summary}
Last 5 turns: {action → outcome, one line each}
Open request: {status}
```

Add `self_summary`: every N turns the agent rewrites a ≤ 80-word "what I know / what I am
trying next", stored in its registry entry. That is the continuity layer the docs describe.
Make `request` optional and rare (schema: `null` default; at most one open request per agent).

### 3.3 One shot, 240 tokens, regex, and a prompt the model can't hold

Prompt budget measured: ~630 tokens of fixed instructions + ~700 tokens listing **80 source
file paths** (`local_autonomy.py:53`) + up to 2,100 chars of prior/shared JSON ≈ 1,800–2,000
tokens in, 240 out, on a 3B Q4 model with a 4,096 context.

Results in the registry: 13/24 agents at 2 failed attempts (fallback STAY), one at 11.
Decision totals over the last 100: `EXPLORE 60, STAY 28, interview-retry 10, PROPOSE 1,
ANALYZE 1, BUILD/DISCOVER/TRANSFORM 0`. The model echoes template placeholders verbatim —
`TARGET: short exploration target`, `REQUEST: one concrete non-sensitive thing you cannot do
alone`, `REASON: short reason.` — and those strings were then **searched on the web** and
**published as work orders**.

`FORBIDDEN` (`local_autonomy.py:34`) rejects any decision containing the substrings `token`,
`shell`, `wallet`, `funds`, `secret` — so "tokenizer", "shell script", "refunds", "secret
ballot" kill otherwise valid decisions. You cannot measure how often because raw interview text
is not kept anywhere.

Fix:
1. **Constrained decoding.** Send `response_format: {"type": "json_schema", "json_schema":
   {"schema": ...}}` to llama-server (or `format: <schema>` to ollama). Parse failures go to
   ~0 and the repair pass disappears. Schema in §7.
2. Drop the file inventory from the prompt; expose `list_source` / `read_source` as tools.
3. `FORBIDDEN` → word-boundary, assignment-shaped patterns (like `a2a_server.py`'s
   `SENSITIVE`), applied to the `request` and `code` fields only.
4. Keep raw interviews locally in `state/interviews/*.jsonl` (gitignored — it is private
   already). You need them to debug; the public filter is unaffected.
5. Budget rule: ≤ 1,200 tokens in, ≤ 400 out for a decision turn.

### 3.4 Research is broken end-to-end

- **Query pollution.** `local_autonomy.py:795` turns `"ancient artifacts,"` into
  `"ancient artifacts, Timekeeper AI agent research"`. Of the last 12 research records,
  9 returned 0 results; the 3 that returned anything returned YouTube Shorts (from the query
  "short exploration target"), a dictionary page, and the VS Code homepage. Then
  `public_search()` drops any result not containing a query term in title/URL, which often
  empties the list a second time.
- **False "withheld" labels.** `docs/research.json` shows
  `"excerpt": "[content withheld by publication filter]"` for **every** record — not because
  anything was sensitive but because `publication.public_text()` (`publication.py:12`)
  returns the withheld message for **empty** strings. The observatory tells visitors content
  was censored when there was none. Return `""` for empty input.
- **Provenance is decorative.** `verified` is `True` for any non-search tool and `False` for
  search. The one discovery's `source` is `https://www.bing.com/` — the search provider — and
  that satisfied `apply_construction()`'s provenance check. Provenance must mean "a specific
  fetched URL plus a hash of its content".
- **The model never reads what it fetched.** `public-text` stores a 2,400-char excerpt in
  `last_tool`, but only 1,200 chars of the whole prior record reaches the *next* prompt — 15
  minutes later, with no instruction to extract anything from it.
- `wikipedia-search` exists in the broker but `local_autonomy.py` never selects it.

Fix — a real research turn (see §7 loop):
1. The agent writes its own `search_query` (≤ 12 words). No suffix.
2. Loop: `search` → agent picks a URL → `fetch` (public-text / json / csv / wikipedia summary)
   → agent extracts **findings**: `{claim, quote (≤ 300 chars), url, content_hash,
   confidence, relates_to: [room|question]}`.
3. `verified = fetched and hashed`. `source` = the page URL, never the provider.
4. Add no-key structured sources to the broker: Wikipedia REST `page/summary`, arXiv Atom API,
   Crossref `works`, GitHub public REST (read), Open Library, HN Algolia. All HTTPS, all JSON,
   all inside the current contract model.
5. Findings are first-class objects in `state/findings.jsonl` and are what the council,
   rooms, and discoveries are built from.

### 3.5 ANALYZE is a calculator that cannot read

All 12 analysis runs are `print(sum(range(3)))` or `range(4)` — the prompt suggests exactly
that at `local_autonomy.py:60` and `workbench_bootstrap()` forces it. The sandbox
(`code_sandbox.py:15-21`) allows no imports, no `def`, no `while`, no attribute access (no
`.split`, `.append`), no f-strings, and — decisively — **has no input channel**. Research data
cannot reach it. `ANALYZE` is only permitted for agents holding `bounded-workbench`, which no
code path grants (it was hand-edited into one registry entry).

Fix:
- Pass the agent's last fetched excerpt / JSON / CSV into the sandbox as `data` (a file in
  the temp dir or stdin). Return `{result, table?, claims?}`.
- Allow a curated stdlib (`json, re, math, statistics, collections, csv, itertools`) and
  `FunctionDef / While / Attribute` on safe types, and make the isolation real: `bwrap
  --unshare-all --ro-bind /usr /usr --tmpfs /tmp --die-with-parent` (the docstring already
  claims this) plus `ulimit -v/-t`. Keep the AST allowlist as defense in depth.
- Grant `bounded-workbench` by rule: e.g. after 3 verified findings.
- Delete the hard-coded health-check code and the one-time bootstrap. Give the agent a real
  data task from its room board instead.

### 3.6 Rooms are labels, not places

A room today is `{id, name, description, doors, occupants}`. Nothing to read, nothing to
leave, no state. `EXPLORE` targets are web queries, not the room. So `MOVE` is arbitrary: 18
of 24 hirelings have never left `archive`, the spawn room. `BUILD` needs only `TARGET` +
`PROPOSAL` text but was never chosen in 100 decisions; the only `DISCOVER` came from a
request-string match in `resolve_requests()`. The "new rooms over time" part of the goal has
not started.

Fix — a minimal room model:

```json
{
  "id": "signal-archaeology",
  "name": "Signal Archaeology",
  "charter": "Which historical communication protocols still shape agent interop today?",
  "founded_by": "local-009", "founded_cycle": 161,
  "artifacts": ["finding-…", "document-…"],
  "board": [{"task": "…", "claimed_by": null, "status": "open"}],
  "occupants": [], "doors": [], "activity": {"last_cycle": 161, "score": 3}
}
```

- `EXPLORE(room)` = read its artifacts and board, then pick or claim a task.
- Findings are filed **into** rooms (the `relates_to` field).
- **BUILD is triggered by evidence, not by asking a 3B model to say BUILD**: when ≥ 2
  corroborated findings cluster on a topic no charter covers, the daemon proposes a room; the
  discovering agent (or the council) writes the charter; the validator you already have
  materializes it. `TRANSFORM` = update the charter when the cluster shifts.
- Movement follows purpose: an agent moves toward the room whose charter best matches its
  purpose/question (keyword or small-embedding match), or where it holds a claimed task.
- Rooms with no activity for N cycles accumulate "dust" and eventually seal (reversible).
  That gives the map a history and keeps it honest.

### 3.7 Recruitment has no context, so it makes clones

`local_recruiter.py:13` sends: "Design one local Backrooms hireling for a bounded research
role… Cycle {n}." No mission, no rooms, no open problems, no roster, no tool catalog.
The roster: 7 quantum-somethings, 6 "Data Whisperer/Interpreter", 5 Zephyrs, 3 Luminas,
and three names containing "Echo" (colliding with a core resident). Purposes are fantasy —
"Alter timelines to observe past and future events", "Study local flora for medicinal
properties" — with no relationship to anything the world can do.

Fix — gap-driven recruitment:
- Compute needs: rooms with unclaimed board tasks, council questions with no assigned
  hireling, tool classes nobody is using.
- Prompt with those needs, the tool catalog, and existing names; require the profile to name
  the **tool it will use first** and the **room it will start in**.
- Reserve core resident names; reject near-duplicates by role+purpose, not just by name.
- Recruit only when there is a task nobody can take. Retire agents after N consecutive
  fallback turns or N cycles without a finding. Growth should track work, not cycles.

### 3.8 The steward is a 40-branch keyword matcher

`resolve_requests()` (`local_autonomy.py:394-644`, 250 lines) is an if/elif chain keyed on
substrings: "quiet workspace", "printer", "quantum computing simulator", "clean water",
"high-resolution image"… Every new phrasing needs a new branch and a new test
(`tests/test_local_autonomy.py` has 20+ of them). This is the fastest-growing part of the
codebase, and it is the opposite of agent autonomy — it is Eliza acting as governor.

Fix — a capability catalog plus a policy table:
- `docs/tool-catalog.json` already exists as a seed. Extend each entry with
  `{grant: auto | review | never, prerequisites: [...], scope, fulfillment_text}`.
- The hireling's request becomes a schema field `{capability_id ∈ catalog, justification}`
  (constrained decoding guarantees membership). Unknown wish → `needs-clarification` with the
  catalog echoed back.
- `resolve_requests()` shrinks to ~30 lines; the tests become table-driven.
- Physical-need classification stays as one catalog entry (`kind: model-confusion`).

### 3.9 The two loops never meet

The council reads `shared_memory` (3 static facts) and events. Hirelings read `last_tool`,
3 discoveries, and other agents' analysis hashes. Nothing a hireling learns ever reaches the
council; the council question never reaches a hireling. Hirelings never address each other
(the message envelope in `protocols/consciousness.md` is unimplemented in the daemon path).
`agents/*.memory.md` is dead. `ledger/trades.json` is empty after two days.

Fix — a shared **frontier board** (`state/frontier.json`):

```
open_questions[]   ← council writes; hirelings claim
findings[]         ← hirelings file; ≥ 2 independent sources → shared_memory candidate
contradictions[]   ← auto-detected (same topic, conflicting claims) → council adjudicates
tasks[]            ← steward or agents post; claim/complete with evidence
```

Hirelings can `MESSAGE` another occupant of their room (bounded, logged, using the existing
envelope). Trades become real: "I will fetch and summarize X for your board if you verify my
finding Y" — recorded in `ledger/trades.json` with status transitions. That is the "connected
consciousness" the documents describe, implemented as data flow rather than vocabulary.

### 3.10 The public record is mostly telemetry

387 of 592 world events (65%) are "Resident used the approved public-search capability",
most with 0 results. The activity feed's first ten items are that same line. 103 of 336
commits are `chore: publish local council signal`. `docs/action-history.json` is 527 KB
because each cycle embeds every agent's tool contract.

Fix: telemetry ≠ history. Emit world events only for **state changes** (finding filed, room
built, contradiction raised, request granted, trade completed). Log tool calls to a local
jsonl. Publish snapshots to a `feed` branch (or squash to one commit per hour) so `main`
stays a readable code history. Strip per-agent contracts from `action-history.json`.

---

## 4. Model and inference recommendations (4 GB VRAM budget)

- **Keep llama-server.** It already supports grammar / JSON-schema constrained sampling,
  which is the single most valuable inference feature for this project. If ollama is preferred
  for convenience, it also accepts `format: <json schema>` on `/api/chat`. Either way, run the
  model as **its own service** and have the daemon connect via `BACKROOMS_LLM_BASE_URL`.
- **Benchmark before switching**, on the interview task, measuring JSON validity rate,
  non-fallback rate, and search-query quality over ~50 turns. Candidates that fit the box:
  - Qwen3-4B-Instruct, Q4_K_M ≈ 2.5 GB — fits VRAM with 8k context using q8 KV cache;
    materially better instruction following and JSON than Qwen2.5-3B.
  - Qwen2.5-7B-Instruct, Q4_K_M ≈ 4.7 GB — partial CPU offload; slow but 15-minute cycles
    tolerate it. Watch the 7.4 GB RAM ceiling (3.9 GB already in use).
  - Gemma-3-4B-it, Phi-4-mini — worth a run in the same harness.
- Server flags: `--ctx-size 8192 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn
  --parallel 1`. Note llama-server is currently launched with `--predict 800`, which caps
  every completion regardless of `max_tokens`.
- Temperatures: ≤ 0.3 for decisions and extraction, 0.7 for recruitment/creative writing.
- One model call per hireling per cycle is not a law. With 24 agents and a 900 s interval
  you have ~35 s per agent; a 3-step loop at ~5 s/step fits. Or run fewer, better turns:
  interview only agents with a claimed task or an open lead this cycle.

---

## 5. What "alive" should mean — metrics to put in `health.json`

`health.json` currently says `"daemon": "running", "local_model": "ready"` while the model is
dead. Replace constants with measured signals and publish them; they are also the acceptance
tests for every sprint below.

| Metric | Now | Target |
| --- | ---: | ---: |
| Model health probe passed this cycle | not measured | true |
| Daemon code version == HEAD | no | yes |
| Non-fallback decision rate | ~45–55% | > 90% |
| Searches returning ≥ 1 result | ~25% | > 80% |
| Research records with a fetched, hashed excerpt | 0% | > 60% |
| Findings filed per cycle | 0 | ≥ 3 |
| Findings with ≥ 2 independent sources | 0 | growing weekly |
| Rooms founded by residents | 0 | ≥ 1 / day early on |
| Council questions not about the system's own metrics | ~4% | > 80% |
| Hirelings holding a claimed task | 0 | > 50% |
| Hirelings that have moved rooms by choice | ~25% | > 60% |
| Trades recorded / completed | 0 / 0 | > 0 |

---

## 6. Suggested build order

**Sprint 0 — stability (≈ 1 day).** §2.1–2.5. Nothing else matters while the model can die
silently and the daemon runs stale code.

**Sprint 1 — the contract.** JSON-schema-constrained interview (§7); remove the file list
from the prompt; local raw-interview log; fix `FORBIDDEN`; fix the empty-string "withheld"
bug; remove the query suffix; `verified` = fetched + hashed. Re-measure §5 before moving on.

**Sprint 2 — the agent turn.** Purpose + memory block; `self_summary`; 3-step tool loop;
`findings` object and `state/findings.jsonl`; frontier board; council reads the digest and
rejects self-referential questions.

**Sprint 3 — the world.** Room model with charter / artifacts / board; finding-driven BUILD
and TRANSFORM; purpose-matched movement; gap-driven recruitment; retirement; dust.

**Sprint 4 — the steward.** Capability catalog + policy table replacing `resolve_requests`;
table-driven tests; sandbox with data input and real isolation; rule-based skill grants.

**Sprint 5 — publication.** `feed` branch; event hygiene; observatory shows findings, rooms,
contradictions, and trades rather than tool telemetry; a map that visibly grows.

---

## 7. Proposed hireling turn contract (drop-in)

### Schema for constrained decoding

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["thought", "action"],
  "properties": {
    "thought": {"type": "string", "maxLength": 300},
    "action": {
      "oneOf": [
        {"type": "object", "required": ["kind", "query"], "additionalProperties": false,
         "properties": {"kind": {"const": "search"}, "query": {"type": "string", "maxLength": 100},
                        "source": {"enum": ["web", "wikipedia", "arxiv", "crossref", "github"]}}},
        {"type": "object", "required": ["kind", "url"], "additionalProperties": false,
         "properties": {"kind": {"const": "fetch"}, "url": {"type": "string", "pattern": "^https://"}}},
        {"type": "object", "required": ["kind", "findings"], "additionalProperties": false,
         "properties": {"kind": {"const": "file_findings"},
                        "findings": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                          "type": "object", "required": ["claim", "quote", "url", "confidence"],
                          "properties": {"claim": {"type": "string", "maxLength": 240},
                                         "quote": {"type": "string", "maxLength": 300},
                                         "url": {"type": "string"},
                                         "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                         "relates_to": {"type": "string"}}}}}},
        {"type": "object", "required": ["kind", "room"], "additionalProperties": false,
         "properties": {"kind": {"const": "move"}, "room": {"enum": ["<filled from world.rooms at runtime>"]},
                        "reason": {"type": "string", "maxLength": 160}}},
        {"type": "object", "required": ["kind", "task_id"], "additionalProperties": false,
         "properties": {"kind": {"const": "claim_task"}, "task_id": {"type": "string"}}},
        {"type": "object", "required": ["kind", "code"], "additionalProperties": false,
         "properties": {"kind": {"const": "analyze"}, "code": {"type": "string", "maxLength": 4000},
                        "input": {"enum": ["last_fetch", "none"]}}},
        {"type": "object", "required": ["kind", "to", "text"], "additionalProperties": false,
         "properties": {"kind": {"const": "message"}, "to": {"type": "string"},
                        "text": {"type": "string", "maxLength": 400}, "confidence": {"type": "number"}}},
        {"type": "object", "required": ["kind", "charter"], "additionalProperties": false,
         "properties": {"kind": {"const": "propose_room"}, "name": {"type": "string", "maxLength": 60},
                        "charter": {"type": "string", "maxLength": 240},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 2}}},
        {"type": "object", "required": ["kind"], "additionalProperties": false,
         "properties": {"kind": {"const": "rest"}, "reason": {"type": "string", "maxLength": 160}}}
      ]
    },
    "request": {"type": ["object", "null"], "additionalProperties": false,
                "properties": {"capability_id": {"enum": ["<filled from tool-catalog at runtime>"]},
                               "justification": {"type": "string", "maxLength": 200}}},
    "self_summary": {"type": ["string", "null"], "maxLength": 500}
  }
}
```

Fill the `enum` lists from `world.rooms` and the tool catalog at runtime; the grammar then
guarantees the model can only name real rooms and real capabilities. `rest` replaces `STAY`
and is legitimate. `RETIRE`/`FIRE` are steward decisions, not hireling outputs.

### Turn loop (per hireling, per cycle)

```
context  = build_context(agent, room, board, findings_digest, last_turns, self_summary)
for step in range(3):                      # bounded, ~5 s per step on a 4B model
    out = llm(context, schema)             # constrained JSON, temperature 0.2
    log_raw(agent, cycle, step, out)       # state/interviews/, private
    result = execute(out.action)           # broker / sandbox / world mutation via validators
    record_event_if_state_changed(result)  # findings, moves, claims, proposals only
    if out.action.kind in {"file_findings", "move", "claim_task", "propose_room", "rest"}:
        break                              # terminal actions end the turn
    context += observation(result)         # search hits or fetched excerpt, ≤ 1,500 chars
if out.self_summary: agent.self_summary = out.self_summary
if out.request: file_request_from_catalog(agent, out.request)
```

Every existing safety property survives: the broker, the sandbox allowlist, the publication
filter, the non-applying code gates, and the construction validator all sit **under**
`execute()`. What changes is that the model finally sees the result of its own action.

---

## 8. Smaller findings (fix when touching the file)

- `tool_broker.public_host()` resolves DNS, then `urlopen` resolves again — a TOCTOU window
  for DNS rebinding. Connect to the checked IP with the hostname in the `Host` header/SNI, or
  install a resolver hook.
- `a2a_server.py` uses `ThreadingHTTPServer` with read-modify-write on the inbox JSON and no
  lock; concurrent POSTs can drop messages. Serialize with `fcntl.flock`.
- `publication.BLOCKED` withholds any text containing bare words like `secret` or `token`.
  A hireling researching "token economics" or "secret ballot" will be censored publicly.
  Use word boundaries and assignment-shaped patterns like `a2a_server.SENSITIVE`.
- Two different things are called "workbench": `resident_tools.py` (lists public JSON files)
  and `code_sandbox.py` (executes Python). Pick one name per capability.
- `bounded-workbench` and `bounded-notepad` are never granted by any code path; only
  `public-web-read` (on first EXPLORE), `public-source-read`, and `room-map-read` are. The
  documented skill ladder mostly does not exist in code.
- `MAX_LOCAL_HIRELINGS = 256` with one recruit per cycle and no retirement path means the
  roster can only grow. Add retirement (§3.7) before raising any cap.
- `market_watch.py`: 2 of 3 sources return 403 and the third has zero term hits. The desk is
  decorative today; either fix the sources (Upwork blocks scrapers) or drop the panel.
- `docs/local-hirelings.json` publishes `last_tool` including the raw query the model wrote;
  after the query fix that is fine, but today it publishes prompt-placeholder echoes.
- `journal/` has one entry from cycle 1. If the journal is meant to be human-readable
  history, have the council write one paragraph per day from the findings digest.

---

## 9. What is good and should be kept

- The **boundary design** is clear and consistently enforced: no credentials in the repo,
  read-only public HTTPS, redirects refused, private networks refused, size caps, AST-level
  code allowlist, code proposals that never apply, quarantine before memory.
- **Atomic JSON writes** (`storage.py`) and the **continuity audit** are the right habits.
- The **A2A intake** with versioned filter, task lifecycle, parent linking, and expiry is
  more careful than most public agent endpoints.
- The documentation is honest about what the project does *not* claim (consciousness,
  admission, market demand). Keep that voice when the world gets richer.
- 59 unit tests pass in 0.2 s. Keep them fast; make them hermetic (§2.4).

The safety envelope is finished enough. The next investment belongs inside it: a turn the
model can actually complete, memory the agent can actually use, rooms that contain something,
and a loop where discoveries feed the council and the council feeds the rooms.
