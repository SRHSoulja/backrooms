# Local model baseline

The current Backrooms council baseline is `Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M`, downloaded into the local llama.cpp cache and never committed to this repository.

Recommended launch:

```bash
llama-server -hf Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M --host 127.0.0.1 --port 8080 --ctx-size 4096 --predict 240
```

The model uses local shared state only. A model upgrade is successful when it improves resident distinction and epistemic discipline, not merely fluency.

For a persistent local link, run `python3 scripts/local_daemon.py --interval 900`. It keeps the model on localhost and records only a cycle summary in `state/world.json`; it does not push to GitHub or expose the model publicly.
