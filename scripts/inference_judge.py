#!/usr/bin/env python3
"""Reproducible verdicts: a small natural-language-inference model and a
sentence-embedding model, both ONNX on CPU, pinned to one revision each.

The language model that judges a pair can be prompted, biased, or replaced;
this judge cannot. Given the two quoted passages it returns the same
entailment and contradiction scores for anyone who runs it, so every verdict
in the ledger can be recomputed from the record. The models are public,
small (about 110 MB together, quantized), and need no key.

Optional at runtime: when the dependencies or the model files are missing
the world records that the inference judge was unavailable and falls back to
its deterministic word rules; nothing is guessed.
"""

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

NLI_REPO = "cross-encoder/nli-deberta-v3-xsmall"
NLI_REVISION = "a150876415327c80daeff35ca6f68f5ed8cf5c24"
NLI_FILE = "onnx/model_quint8_avx2.onnx"
EMBED_REPO = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBED_FILE = "onnx/model_quint8_avx2.onnx"
SUPPORT_MIN = 0.5        # a supporting verdict needs this much entailment between the quotes
CONTRADICTION_MIN = 0.6  # this much contradiction flags a dispute candidate
CONTRADICTION_VETO = 0.2 # a model 'contradicts' with less than this is not a contradiction
SAME_TEXT_MIN = 0.92     # cosine similarity above which two quotes are one passage
MAX_CHARS = 480
CACHE_DIR = Path(os.getenv("BACKROOMS_MODEL_CACHE", "~/.cache/backrooms-models")).expanduser()
_STATUS = {"checked": False, "available": False, "reason": ""}


def enabled():
    """Opt-in: the workflow sets BACKROOMS_INFERENCE_JUDGE=1; tests and local runs leave it off."""
    return os.getenv("BACKROOMS_INFERENCE_JUDGE", "0") == "1"


def status():
    """{"enabled", "available", "reason", "nli", "embed"} without loading anything twice."""
    if not enabled():
        return {"enabled": False, "available": False, "reason": "not enabled (BACKROOMS_INFERENCE_JUDGE is not 1)",
                "nli": {"model": NLI_REPO, "revision": NLI_REVISION}, "embed": {"model": EMBED_REPO, "revision": EMBED_REVISION}}
    if not _STATUS["checked"]:
        try:
            _nli_session()
            _embed_session()
            _STATUS.update({"checked": True, "available": True, "reason": ""})
        except Exception as error:  # noqa: BLE001 - the reason is recorded, never raised into a cycle
            _STATUS.update({"checked": True, "available": False, "reason": f"{type(error).__name__}: {str(error)[:160]}"})
    return {"enabled": True, "available": _STATUS["available"], "reason": _STATUS["reason"],
            "nli": {"model": NLI_REPO, "revision": NLI_REVISION, "file": NLI_FILE},
            "embed": {"model": EMBED_REPO, "revision": EMBED_REVISION, "file": EMBED_FILE}}


def available():
    return bool(status().get("available"))


def _fetch(repo, revision, filename):
    from huggingface_hub import hf_hub_download
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return hf_hub_download(repo_id=repo, filename=filename, revision=revision, cache_dir=str(CACHE_DIR))


def _session(path):
    import onnxruntime
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    return onnxruntime.InferenceSession(path, options, providers=["CPUExecutionProvider"])


@lru_cache(maxsize=1)
def _nli_session():
    from tokenizers import Tokenizer
    model = _fetch(NLI_REPO, NLI_REVISION, NLI_FILE)
    tokenizer = Tokenizer.from_file(_fetch(NLI_REPO, NLI_REVISION, "tokenizer.json"))
    tokenizer.enable_truncation(512)
    config = json.loads(Path(_fetch(NLI_REPO, NLI_REVISION, "config.json")).read_text())
    labels = {int(key): str(value).lower() for key, value in (config.get("id2label") or {}).items()}
    return _session(model), tokenizer, labels


@lru_cache(maxsize=1)
def _embed_session():
    from tokenizers import Tokenizer
    model = _fetch(EMBED_REPO, EMBED_REVISION, EMBED_FILE)
    tokenizer = Tokenizer.from_file(_fetch(EMBED_REPO, EMBED_REVISION, "tokenizer.json"))
    tokenizer.enable_truncation(256)
    return _session(model), tokenizer


def _feed(session, encoding):
    import numpy
    wanted = {item.name for item in session.get_inputs()}
    feed = {}
    if "input_ids" in wanted:
        feed["input_ids"] = numpy.asarray([encoding.ids], dtype=numpy.int64)
    if "attention_mask" in wanted:
        feed["attention_mask"] = numpy.asarray([encoding.attention_mask], dtype=numpy.int64)
    if "token_type_ids" in wanted:
        feed["token_type_ids"] = numpy.asarray([encoding.type_ids], dtype=numpy.int64)
    return feed


def _text(finding):
    quote = str(finding.get("quote") or "").strip()
    claim = str(finding.get("claim") or "").strip()
    return (quote if len(quote) >= 20 else claim)[:MAX_CHARS]


def nli(premise, hypothesis):
    """Probabilities that the hypothesis is entailed by, contradicted by, or unrelated to the premise."""
    import numpy
    session, tokenizer, labels = _nli_session()
    encoding = tokenizer.encode(str(premise)[:MAX_CHARS], str(hypothesis)[:MAX_CHARS])
    logits = session.run(None, _feed(session, encoding))[0][0].astype(numpy.float64)
    scores = numpy.exp(logits - logits.max())
    scores = scores / scores.sum()
    result = {labels.get(index, str(index)): round(float(value), 4) for index, value in enumerate(scores)}
    return {"entailment": result.get("entailment", 0.0), "contradiction": result.get("contradiction", 0.0),
            "neutral": result.get("neutral", 0.0)}


def judge_pair(first, second):
    """Both directions between the two passages; the pair's support is the stronger
    entailment, its contradiction the stronger contradiction. None when unavailable."""
    if not available():
        return None
    a, b = _text(first), _text(second)
    if not a or not b:
        return None
    ab, ba = nli(a, b), nli(b, a)
    support = max(ab["entailment"], ba["entailment"])
    contradiction = max(ab["contradiction"], ba["contradiction"])
    verdict = "supports" if support >= SUPPORT_MIN and contradiction < SUPPORT_MIN else \
        "contradicts" if contradiction >= CONTRADICTION_MIN else "unrelated"
    return {"model": NLI_REPO, "revision": NLI_REVISION, "a_to_b": ab, "b_to_a": ba,
            "support": round(support, 4), "contradiction": round(contradiction, 4), "verdict": verdict,
            "inputs": [hashlib.sha256(a.encode()).hexdigest()[:16], hashlib.sha256(b.encode()).hexdigest()[:16]]}


def embed(text):
    """Mean-pooled, unit-length sentence embedding."""
    import numpy
    session, tokenizer = _embed_session()
    encoding = tokenizer.encode(str(text)[:MAX_CHARS])
    hidden = session.run(None, _feed(session, encoding))[0][0]
    mask = numpy.asarray(encoding.attention_mask, dtype=numpy.float64)[:, None]
    vector = (hidden * mask).sum(axis=0) / max(mask.sum(), 1.0)
    norm = numpy.linalg.norm(vector)
    return vector / norm if norm else vector


@lru_cache(maxsize=512)
def _cached_embed(text):
    return embed(text)


def similarity(text_a, text_b):
    """Cosine similarity of two passages, or None when the embedding model is unavailable."""
    if not available():
        return None
    a, b = str(text_a or "").strip()[:MAX_CHARS], str(text_b or "").strip()[:MAX_CHARS]
    if not a or not b:
        return None
    return round(float(_cached_embed(a) @ _cached_embed(b)), 4)


def same_passage(first, second):
    """True when two findings quote what is, in meaning, one passage."""
    score = similarity(first.get("quote", ""), second.get("quote", ""))
    return score is not None and score >= SAME_TEXT_MIN


if __name__ == "__main__":
    print(json.dumps(status(), indent=2))
