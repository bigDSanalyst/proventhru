"""Compare runs from their run records alone.

    proventhru report out/baseline/records.jsonl out/claude/records.jsonl

For each record: what was proved, how many steps (tactics submitted) and
policy invocations it took, what the calls cost,
what the calls cost, and how the policy's choices were distributed over the
tactic vocabulary: over everything it proposed, over the steps that ran, and
over the finished proofs. That is the degenerate-policy check: a policy that
has collapsed to "lia, auto, congruence on every step" shows a top-3 share
near 1 and a low normalised entropy, whatever its proof count says. Read
"succeeded" with care: auto and trivial succeed without changing anything.

Failures of a model policy are split three ways (policy_openai): api (the
call failed), invalid (the answer was unusable, or a candidate was), and
unproductive (a valid tactic that Coq refused, that timed out, or that led
back to a seen state). Only the last is about the model's reasoning.
Candidates retrieval appended (cost.added) are not the model's and are
counted apart.

Each statement counts once: its latest episode that was not cut short.
A statement whose only episodes were cut short (a crash, a policy that
stayed unavailable) makes the record incomplete, and the report says so: an
incomplete condition is not a result.

Comparing records: the first is the reference. Statements are paired by
text, or by position in the set (episode `item`) when the texts differ (the
renamed copy), and an exact McNemar test is run on the discordant pairs.
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


def mcnemar(only_a, only_b):
    """Exact two-sided McNemar p-value from the discordant counts."""
    n, k = only_a + only_b, min(only_a, only_b)
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def latest(rows):
    """Per statement, its latest episode not cut short; and the statements
    that only have episodes that were."""
    best, cut = {}, set()
    for r in rows:
        if r["standing"] is None or "incomplete" in (r.get("stats") or {}):
            cut.add(r["statement"])
            continue
        best[r["statement"]] = r
    return list(best.values()), sorted(cut - set(best))


def failures(proposals, steps):
    """api / invalid / unproductive, for proposals with a model cost."""
    model = [p for p in proposals if (p.get("cost") or {}).get("cache_key") is not None
             or "input_tokens" in (p.get("cost") or {})]
    by_seq = {p["_seq"]: p for p in model}
    out = {"model_calls": len(model),
           "api_failed_calls": sum(1 for p in model
                                   if ((p["cost"].get("failure") or {}).get("kind")) == "api"),
           "api_retries": sum(p["cost"].get("retries", 0) for p in model),
           "invalid_responses": sum(1 for p in model
                                    if ((p["cost"].get("failure") or {}).get("kind")) == "invalid"),
           "invalid_candidates": sum(len(p["cost"].get("dropped", [])) for p in model),
           "cache_hits": sum(1 for p in model if p["cost"].get("cache") == "hit"),
           "model_steps": 0, "model_refused": 0, "unproductive": 0, "productive": 0,
           "retrieval_steps": 0}
    for s in steps:
        p = by_seq.get(s.get("proposal"))
        if p is None:
            continue
        if s["tactic"] in (p["cost"].get("added") or []):
            out["retrieval_steps"] += 1
            continue
        out["model_steps"] += 1
        sess = s["session"]
        if sess["outcome"] == "refused":
            out["model_refused"] += 1          # the guard refused it: invalid, not reasoning
        elif sess["outcome"] in ("error", "timeout") or sess.get("revisit"):
            out["unproductive"] += 1
        else:
            out["productive"] += 1
    return out


def summarize(entries):
    rows, incomplete = latest(rec.corpus(entries))
    corpus = rows
    kept = {r["episode"] for r in rows}
    proposals = [dict(e["data"], _seq=e["seq"]) for e in entries
                 if e["kind"] == "proposal" and e["data"]["episode"] in kept]
    steps = [s for s in rec.steps(entries) if s["episode"] in kept]
    costs = [p["cost"] for p in proposals if p.get("cost")]
    spent = [dollars(c) for c in costs]
    proposed = [t for p in proposals for t, _ in p["candidates"]]
    succeeded = [s["tactic"] for s in steps if s["session"]["outcome"] == "ok"]
    policy = next((e["data"].get("policy") for e in entries if e["kind"] == "episode"), None)
    protocols = sorted({(r.get("protocol") or {}).get("sha256") or "none" for r in rows})
    provers = sorted({(r.get("environment") or {}).get("prover") or "?" for r in rows})
    searched = [r for r in rows if r.get("search")]
    return {
        "incomplete": incomplete,
        "protocols": protocols,
        "sets": sorted({(r.get("protocol") or {}).get("set") or "-" for r in rows}),
        "provers": provers,
        "search": searched[0]["search"] if searched else None,
        "invocations": sum((r.get("stats") or {}).get("expansions", 0) for r in rows),
        "stopped": dict(Counter((r.get("stats") or {}).get("stopped") or "proved"
                                for r in searched)),
        "candidates_per_call": (round(sum(len(p["candidates"]) for p in proposals)
                                      / len(proposals), 2) if proposals else None),
        "failures": failures(proposals, steps),
        "by_item": {r["item"]: r["standing"] == "proved" for r in searched
                    if r.get("item") is not None},
        "policy": (policy or {}).get("id"),
        "model": (policy or {}).get("model"),
        "episodes": len(corpus),
        "standings": dict(Counter(r["standing"] for r in corpus)),
        "proved": sorted(r["statement"] for r in corpus if r["standing"] == "proved"),
        "searched": len(searched),
        "searched_statements": [r["statement"] for r in searched],
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


def paired(a, b):
    """{key: (proved in a, proved in b)} over statements both searched."""
    sa, sb = set(a["searched_statements"]), set(b["searched_statements"])
    if sa & sb:
        common = sa & sb
        pa, pb = set(a["proved"]), set(b["proved"])
        return {k: (k in pa, k in pb) for k in common}
    common = set(a["by_item"]) & set(b["by_item"])
    if not common:
        return None
    return {f"item {k}": (a["by_item"][k], b["by_item"][k]) for k in sorted(common)}


def render(paths):
    rows = [(p, summarize(rec.load(p))) for p in paths]
    out = []
    for path, s in rows:
        out.append(f"== {path}")
        out.append(f"   policy {s['policy']}  model {s['model']}")
        out.append(f"   proved {s['standings'].get('proved', 0)} of {s['searched']} searched"
                   f" ({s['episodes']} episodes: {s['standings']})")
        out.append(f"   search {s['search']}  set {s['sets']}  prover {s['provers']}"
                   f"  protocol {[p[:12] for p in s['protocols']]}")
        if s["incomplete"]:
            out.append(f"   INCOMPLETE: {len(s['incomplete'])} statements have no finished "
                       f"episode; this is not a result yet")
        stop = s["stopped"]
        out.append(f"   searches ended by: {stop}  candidates per call {s['candidates_per_call']}")
        if s["search"] and s["search"].get("step_budget") and stop.get("frontier"):
            out.append(f"   !! {stop['frontier']} searches ran out of candidates before the step "
                       f"budget: they did not use the effort the comparison matches on")
        out.append(f"   steps {s['steps']} {s['outcomes']}  invocations {s['invocations']}"
                   f"  model calls {s['model_calls']}  no-candidate calls {s['no_candidates']}")
        f = s["failures"]
        if f["model_calls"]:
            out.append(f"   failures: api {f['api_failed_calls']} calls ({f['api_retries']} retries)"
                       f"  invalid {f['invalid_responses']} responses, {f['invalid_candidates']}"
                       f" candidates, {f['model_refused']} guard-refused"
                       f"  unproductive {f['unproductive']} of {f['model_steps']} model steps"
                       f"  (retrieval steps {f['retrieval_steps']}, cache hits {f['cache_hits']})")
        if s["dollars"] is not None:
            out.append(f"   cost ${s['dollars']}  tokens {s['tokens']}")
        for which in ("proposed", "succeeded", "in_proofs"):
            d = s[which]
            out.append(f"   {which:9} n={d['n']} top3={d['top3_share']} entropy={d['entropy']}"
                       f"  {dict(list(d['counts'].items())[:8])}")
    if len(rows) > 1:
        ref_path, ref = rows[0]
        if len({p for _, s in rows for p in s["provers"]}) > 1:
            out.append("!! the records ran on different provers: not one comparison")
        if len({p for _, s in rows for p in s["protocols"]}) > 1:
            out.append("!! the records cite different protocols")
        for path, s in rows[1:]:
            out.append(f"-- vs {ref_path}: {path}")
            pairs = paired(ref, s)
            if pairs is None:
                out.append("   no common statements to pair")
                continue
            a_only = [k for k, (x, y) in pairs.items() if x and not y]
            b_only = [k for k, (x, y) in pairs.items() if y and not x]
            out.append(f"   paired on {len(pairs)}: only here {len(b_only)}, only there "
                       f"{len(a_only)}, exact McNemar p = {mcnemar(len(a_only), len(b_only)):.3g}")
            out.append(f"   only here: {sorted(map(str, b_only))}")
            out.append(f"   only there: {sorted(map(str, a_only))}")
    return "\n".join(out)
