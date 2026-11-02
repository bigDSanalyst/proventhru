"""The pattern extractor's model proposer, pattern/model-m1-v1 (docs/pattern-run-4.md).

    python tools/pattern_m1.py --base-url http://localhost:8000/v1 --model SERVED \\
        --out DIR --cache CACHE.jsonl

It runs where M1 is served: Colab, vLLM on an A100. For each of the metrics doc's six
pattern kinds and each registered seed, M1 is shown the development's definitions
(pilots/isort/ISort.v with its comments removed, never the held-out ISortGold.v), and
asked for K conjectures of that kind, as JSON under a schema. The prompt is fixed here:
its hash (prompt_sha256) is part of the run's identity, and a change to it is a new
version of the proposer.

The proposals go to DIR/proposals.jsonl, each with its batch, kind, seed and request
cache key. They are scored elsewhere, on CPU, by tools/pattern_run.py --run 4 (batch
A), --run 5 (batch B) and --run 6 (batch C). Responses are cached by request hash, so
a rerun makes no calls it has already made.
"""
import argparse
import hashlib
import inspect
import json
import os
import re
import sys

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, HERE)

from proventhru.record import canon  # noqa: E402

PROPOSER = "pattern/model-m1-v1"
SPEC, CODE_ROW = "docs/pattern-run-6.md", "code:pattern-m1"
MODEL = "Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28"   # M1, PROTOCOL.md v5
K = 8                           # conjectures per call
TEMPERATURE, TOP_P, MAX_TOKENS = 0.8, 0.95, 2000
# seeds: run 4 is batch A, run 5 batch B, run 6 batch C (docs/pattern-run-6.md)
BATCHES = {"A": (0, 1, 2, 3), "B": (4, 5, 6, 7), "C": (8, 9, 10, 11)}
# The metrics doc's pattern kinds, in its words, each with one line on what it asks.
KINDS = {
    "symmetry": "the statement is unchanged when two of its arguments are exchanged",
    "invariance": "some quantity or property is unchanged under a transformation",
    "duality": "the statement has a counterpart with dual operations or relations "
               "exchanged (for example, an order and its reverse)",
    "general form": "the statement is an instance of a more general statement, which is "
                    "the conjecture",
    "composition": "an operation composed with a known operation, or with itself",
    "boundary": "a boundary or limiting case of the development's functions (empty lists, "
                "single elements, extreme values)",
}

PROMPT = """You propose conjectures about a small Coq (Rocq 8.18) development, for a system that tests them on many inputs and tries to prove them in Coq.

The development, exactly as Coq sees it:

{development}

A pattern is a structural property a statement can have. The kind of pattern asked for here is {kind}: {definition}.

Propose exactly {k} distinct conjectures of that kind about the development's functions insert, sort and the predicate sorted. Each conjecture:
- is one closed Coq proposition that starts with forall, written in Coq syntax, using the development's definitions and the standard library (nat arithmetic, lists, length, ++, rev, In, Permutation, NoDup, count_occ, ...);
- states something you believe is true and that would be useful to a reader of this development;
- is not a restatement of a definition.

Reply with one JSON object and nothing else: {{"conjectures": [{{"statement": "forall ...", "why": "one sentence"}}, ...]}}."""

SCHEMA = {"type": "object",
          "properties": {"conjectures": {
              "type": "array", "minItems": K, "maxItems": K,
              "items": {"type": "object",
                        "properties": {"statement": {"type": "string", "minLength": 8},
                                       "why": {"type": "string"}},
                        "required": ["statement", "why"], "additionalProperties": False}}},
          "required": ["conjectures"], "additionalProperties": False}


def development():
    """ISort.v as the model sees it: its definitions, comments removed."""
    with open(os.path.join(HERE, "pilots", "isort", "ISort.v")) as fh:
        text = fh.read()
    return re.sub(r"\(\*.*?\*\)\s*", "", text, flags=re.S).strip()


def prompt_sha256():
    """Everything that decides what the model is shown and asked for."""
    return hashlib.sha256(canon({
        "template": PROMPT, "kinds": KINDS, "k": K, "schema": SCHEMA,
        "sampling": [TEMPERATURE, TOP_P, MAX_TOKENS], "batches": BATCHES,
        "development": development(), "code": inspect.getsource(body)}).encode()).hexdigest()


def body(model, kind, seed):
    return {"model": model,
            "messages": [{"role": "user", "content": PROMPT.format(
                development=development(), kind=kind, definition=KINDS[kind], k=K)}],
            "temperature": TEMPERATURE, "top_p": TOP_P, "seed": seed, "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "conjectures", "schema": SCHEMA, "strict": True}}}


GOVERNED = ["pilots/isort/ISort.v", "proventhru/record.py", "tools/pattern_m1.py"]


def code_hash(repo, paths=GOVERNED):
    h = hashlib.sha256()
    for p in paths:
        with open(os.path.join(repo, p), "rb") as fh:
            h.update(f"{p} {hashlib.sha256(fh.read()).hexdigest()}\n".encode())
    return h.hexdigest()


def preflight(model, repo=HERE):
    """Proposals are made only by the pinned model, under the frozen spec and code."""
    if model != MODEL:
        raise SystemExit(f"the model is pinned: {MODEL}, not {model}")
    with open(os.path.join(repo, "docs", "frozen.md")) as fh:
        rows = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([0-9a-f]{64})`\s*\|",
                          fh.read(), re.M)
    with open(os.path.join(repo, SPEC), "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    spec = [r for r in rows if r[0] == SPEC]
    if not spec or spec[-1][2] != digest:
        raise SystemExit(f"{SPEC} isn't frozen at its current hash ({digest[:16]})")
    codes = [r for r in rows if r[0] == CODE_ROW]
    if not codes or codes[-1][1].strip() == "closed" or codes[-1][2] != code_hash(repo):
        raise SystemExit(f"the proposer's code isn't the registered `{CODE_ROW}`")
    return digest


def propose(base_url, model, out, cache_path, transport=None, log=print, batches=None):
    from proventhru.policy_openai import HTTPTransport, ResponseCache, extract_json
    url = base_url.rstrip("/") + "/chat/completions"
    cache, transport = ResponseCache(cache_path), transport or HTTPTransport()
    rows = []
    for batch, seeds in BATCHES.items():
        if batches and batch not in batches:
            continue
        for kind in KINDS:
            for seed in seeds:
                b = body(model, kind, seed)
                key = hashlib.sha256(canon({"url": url, "body": b}).encode()).hexdigest()
                hit = cache.get(key)
                if hit:
                    status, text = hit["status"], hit["body"]
                else:
                    status, _, text = transport.post(url, {"Content-Type": "application/json"},
                                                     canon(b), 600)
                    if status == 200:
                        cache.put(key, status, {}, text)
                base = {"batch": batch, "kind": kind, "seed": seed, "cache_key": key,
                        "prompt_sha256": prompt_sha256()}
                if status != 200:
                    rows.append(dict(base, failure=f"status {status}: {text[:200]}"))
                    continue
                resp = json.loads(text)
                choice = resp["choices"][0]
                parsed = extract_json(choice["message"].get("content") or "")
                items = parsed.get("conjectures") if isinstance(parsed, dict) else None
                if not isinstance(items, list):
                    rows.append(dict(base, failure="no conjectures list",
                                     finish=choice.get("finish_reason")))
                    continue
                for i, it in enumerate(items):
                    rows.append(dict(base, index=i, served_model=resp.get("model"),
                                     statement=str(it.get("statement", "")).strip(),
                                     why=str(it.get("why", ""))))
                log(f"{batch} {kind} seed {seed}: {len(items)} conjectures")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "proposals.jsonl"), "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True, help="the served model name, pinned to MODEL")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--batch", action="append", choices=sorted(BATCHES),
                    help="only these batches (default: all); run 6 is --batch C")
    a = ap.parse_args(argv)
    spec = preflight(a.model)
    rows = propose(a.base_url, a.model, a.out, a.cache, batches=a.batch)
    print(json.dumps({"done": True, "rows": len(rows), "spec_sha256": spec,
                      "prompt_sha256": prompt_sha256(),
                      "failures": sum("failure" in r for r in rows)}))


if __name__ == "__main__":
    main()
