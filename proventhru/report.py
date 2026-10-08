"""Compare runs from their run records alone.

    proventhru report out/baseline/records.jsonl out/claude/records.jsonl

For each record: what was proved, how many steps and model calls it took,
what the calls cost, and how the policy's choices were distributed over the
tactic vocabulary: over everything it proposed, over the steps that ran, and
over the finished proofs. That is the degenerate-policy check: a policy that
has collapsed to "lia, auto, congruence on every step" shows a top-3 share
near 1 and a low normalised entropy, whatever its proof count says. Read
"succeeded" with care: auto and trivial succeed without changing anything.
"""
import math
import re
from collections import Counter

from . import record as rec

# $ per million tokens, from the Claude API price list (2026-10-06).
PRICES = {"claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20,
                              "cache_write": 5.00},
          "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20,
                                "cache_write": 2.50},
          "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01,
                               "cache_write": 0.125}}


def head(tactic):
    """The tactic's name: 'simpl; rewrite IHn.' -> 'simpl'."""
    t = re.split(r"[\s;]", tactic.strip().rstrip("."), maxsplit=1)[0]
    return t


def distribution(tactics):
    """Counts by tactic name, top-3 share, and entropy normalised to [0, 1]
    over the names that occur (1 = uniform, 0 = one name only)."""
    c = Counter(head(t) for t in tactics)
    n = sum(c.values())
    if not n:
        return {"n": 0, "counts": {}, "top3_share": None, "entropy": None}
    ps = [v / n for v in c.values()]
    h = -sum(p * math.log(p) for p in ps)
    hmax = math.log(len(c)) if len(c) > 1 else 1.0
    return {"n": n, "counts": dict(c.most_common()),
            "top3_share": round(sum(v for _, v in c.most_common(3)) / n, 3),
            "entropy": round(h / hmax, 3) if len(c) > 1 else 0.0}


def dollars(cost):
    p = PRICES.get((cost or {}).get("model"))
    if not p:
        return None
    return (cost.get("input_tokens", 0) * p["input"]
            + cost.get("output_tokens", 0) * p["output"]
            + cost.get("cache_read_input_tokens", 0) * p["cache_read"]
            + cost.get("cache_creation_input_tokens", 0) * p["cache_write"]) / 1e6


def summarize(entries):
    corpus = rec.corpus(entries)
    proposals = [e["data"] for e in entries if e["kind"] == "proposal"]
    steps = rec.steps(entries)
    costs = [p["cost"] for p in proposals if p.get("cost")]
    spent = [dollars(c) for c in costs]
    proposed = [t for p in proposals for t, _ in p["candidates"]]
    succeeded = [s["tactic"] for s in steps if s["session"]["outcome"] == "ok"]
    policy = next((e["data"].get("policy") for e in entries if e["kind"] == "episode"), None)
    return {
        "policy": (policy or {}).get("id"),
        "model": (policy or {}).get("model"),
        "episodes": len(corpus),
        "standings": dict(Counter(r["standing"] for r in corpus)),
        "proved": sorted(r["statement"] for r in corpus if r["standing"] == "proved"),
        "searched": sum(1 for e in entries if e["kind"] == "episode" and e["data"].get("search")),
        "model_calls": sum(1 for c in costs if "input_tokens" in c),
        "steps": len(steps),
        "outcomes": dict(Counter(s["session"]["outcome"] for s in steps)),
        "dropped_candidates": sum(len(c.get("dropped", [])) for c in costs),
        "no_candidates": sum(1 for p in proposals if not p["candidates"]),
        "dollars": round(sum(x for x in spent if x is not None), 4) if any(x is not None for x in spent) else None,
        "tokens": {k: sum(c.get(k, 0) for c in costs)
                   for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                             "cache_creation_input_tokens")},
        "proposed": distribution(proposed),
        "succeeded": distribution(succeeded),
        "in_proofs": distribution([t for r in corpus if r["standing"] == "proved"
                                   for t in r["proof"]]),
    }


def render(paths):
    rows = [(p, summarize(rec.load(p))) for p in paths]
    out = []
    for path, s in rows:
        out.append(f"== {path}")
        out.append(f"   policy {s['policy']}  model {s['model']}")
        out.append(f"   proved {s['standings'].get('proved', 0)} of {s['searched']} searched"
                   f" ({s['episodes']} episodes: {s['standings']})")
        out.append(f"   steps {s['steps']} {s['outcomes']}  model calls {s['model_calls']}"
                   f"  no-candidate calls {s['no_candidates']}  dropped {s['dropped_candidates']}")
        if s["dollars"] is not None:
            out.append(f"   cost ${s['dollars']}  tokens {s['tokens']}")
        for which in ("proposed", "succeeded", "in_proofs"):
            d = s[which]
            out.append(f"   {which:9} n={d['n']} top3={d['top3_share']} entropy={d['entropy']}"
                       f"  {dict(list(d['counts'].items())[:8])}")
    if len(rows) > 1:
        sets = [set(s["proved"]) for _, s in rows]
        base = sets[0]
        for (path, s), got in zip(rows[1:], sets[1:]):
            out.append(f"-- vs {rows[0][0]}: {path}")
            out.append(f"   only here: {sorted(got - base)}")
            out.append(f"   only there: {sorted(base - got)}")
    return "\n".join(out)
