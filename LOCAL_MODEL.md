# Local model baseline

The current Backrooms council baseline is `Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M`, downloaded into the local llama.cpp cache and never committed to this repository.

Recommended launch:

```bash
llama-server -hf Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M --host 127.0.0.1 --port 8080 --ctx-size 4096 --predict 240
```

The model uses local shared state only. A model upgrade is successful when it improves resident distinction and epistemic discipline, not merely fluency.

For a persistent local link, run `python3 scripts/local_daemon.py --interval 900 --publish`. Runtime state is kept in the ignored `state/local-runtime.json`. Each cycle first asks both residents for a bounded next question, validates the proposal, runs one fixed local behavioral probe, and falls back to a fixed question if needed. With `--publish`, the daemon publishes only aggregate council metrics, the selected question, and probe metadata to `docs/local-cycle.json`, which the observatory displays. Raw prompts and model responses remain local. Publishing skips itself if unrelated checkout changes are present or the branch cannot fast-forward safely.
