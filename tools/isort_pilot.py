"""The insertion-sort pilot, gate by gate (docs/isort-pilot.md).

    python tools/isort_pilot.py gate1 --out OUT

Gate 1 (proposal): generate candidates about the development, tested in Coq;
classify each with the gate (the development's definitions as the preamble);
count them by the development's functions they mention; and match them
against the held-out gold (pilots/isort/ISortGold.v).

A gold statement is matched exactly when a candidate is the same statement up
to variable renaming, or the same with the two sides of a symmetric relation
(=, Permutation) swapped. insert_In is an iff, which the generator does not
build, so it is reported as not expressible rather than as missed.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru import devgen  # noqa: E402
from proventhru.gate import classify  # noqa: E402

GOLD = {   # name: (statement in the generator's rendering, helper or main)
    "insert_length": ("forall (l1 : list nat) (n : nat), length (insert n l1) = S (length l1)",
                      "helper"),
    "sort_length": ("forall (l1 : list nat), length (sort l1) = length l1", "helper"),
    "insert_sorted": ("forall (l1 : list nat) (n : nat), sorted l1 -> sorted (insert n l1)",
                      "helper"),
    "insert_perm": ("forall (l1 : list nat) (n : nat), Permutation (n :: l1) (insert n l1)",
                    "helper"),
    "sorted_sort_id": ("forall (l1 : list nat), sorted l1 -> sort l1 = l1", "helper"),
    "insert_In": (None, "helper"),      # an iff: not expressible by the generator
    "sort_sorted": ("forall (l1 : list nat), sorted (sort l1)", "main"),
    "sort_perm": ("forall (l1 : list nat), Permutation l1 (sort l1)", "main"),
    "sort_idem": ("forall (l1 : list nat), sort (sort l1) = sort l1", "main"),
}


def swapped(stmt):
    """The statement with the sides of its final = or Permutation swapped."""
    head, sep, body = stmt.rpartition(", ") if stmt.startswith("forall") else ("", "", stmt)
    prem, arrow, concl = body.rpartition(" -> ")
    m = re.fullmatch(r"(.+) = (.+)", concl)
    if m:
        concl2 = f"{m.group(2)} = {m.group(1)}"
    else:
        m = re.fullmatch(r"Permutation (\(.+?\)|\S+) (\(.+\)|\S+)", concl)
        if not m:
            return None
        concl2 = f"Permutation {m.group(2)} {m.group(1)}"
    return devgen.canonical(head + sep + prem + arrow + concl2)


def gate1(out, jobs=4):
    os.makedirs(out, exist_ok=True)
    good, refuted = devgen.generate(log=print)
    pre = devgen.preamble()

    def gate(stmt):
        try:
            return classify(stmt, pre, backend="coqtop").status
        except Exception as e:
            return f"crashed:{type(e).__name__}"
    with ThreadPoolExecutor(jobs) as ex:
        statuses = list(ex.map(gate, [s for s, _, _ in good]))
    rows = [{"statement": s, "kind": k, "gate": g,
             "mentions": sorted(set(re.findall(r"\b(insert|sort|sorted)\b", s)))}
            for (s, k, _), g in zip(good, statuses)]
    stmts = {r["statement"]: r for r in rows}
    gold = {}
    for name, (st, role) in GOLD.items():
        if st is None:
            gold[name] = {"role": role, "match": "not expressible"}
            continue
        c = devgen.canonical(st)
        hit = stmts.get(c) or stmts.get(swapped(c) or "")
        gold[name] = {"role": role, "statement": c,
                      "match": "exact" if hit else "missed",
                      "candidate": hit["statement"] if hit else None,
                      "gate": hit["gate"] if hit else None}
    summary = {
        "candidates_checked": len(good) + len(refuted), "refuted_by_small_inputs": len(refuted),
        "candidates": len(rows),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "mentioning": {f: sum(f in r["mentions"] for r in rows) for f in ("insert", "sort",
                                                                          "sorted")},
        "gate": dict(Counter(r["gate"] for r in rows)),
        "elaborate": sum(r["gate"] != "ill_formed" and not r["gate"].startswith("crashed")
                         for r in rows),
        "gold": gold,
        "gold_helpers_proposed": sum(g["match"] == "exact" for g in gold.values()
                                     if g["role"] == "helper"),
        "gold_helpers": sum(g["role"] == "helper" for g in gold.values()),
        "gold_main_proposed": sum(g["match"] == "exact" for g in gold.values()
                                  if g["role"] == "main"),
    }
    with open(os.path.join(out, "candidates.jsonl"), "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)
    with open(os.path.join(out, "gate1.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps(summary, indent=1))
    return summary


def gate2(out, jobs=4, prover="structural2", rounds=3, label="2a", corpus_forms="pose"):
    """Gate 2 (proof): the loop on gate 1's candidates, the development as the
    preamble, open statements retried each round. Gold matched exactly (bound
    variable names only), each confirmed in Coq with exact."""
    from proventhru.explore import citation_sites, explore, preamble
    from proventhru.session import open_session
    from proventhru.gate import _first_closing
    gate1_rows = [json.loads(ln) for ln in open(os.path.join(os.path.dirname(out), "gate1",
                                                             "candidates.jsonl"))]
    stmts = [r["statement"] for r in gate1_rows]
    base = devgen.preamble()
    run_dir = os.path.join(out, "run")
    pv = devgen.isort_tactics() if prover == "isort" else prover
    corpus, rounds_ = explore(run_dir, rounds=rounds, per_round=len(stmts), step_budget=600,
                              jobs=jobs, prover=pv, saturate=True, base=base,
                              retry_open=True, statements=stmts, log=print,
                              corpus_forms=corpus_forms)
    by_stmt = {devgen.canonical(c["statement"]): c for c in corpus}
    derived = {}
    for r in range(rounds):
        p = os.path.join(run_dir, f"round-{r}", "derived.jsonl")
        if os.path.exists(p):
            for ln in open(p):
                d = json.loads(ln)
                derived[devgen.canonical(d["statement"])] = d
    pre = preamble(corpus, base)
    gold = {}
    for name, (st, role) in GOLD.items():
        if st is None:
            gold[name] = {"role": role, "result": "not expressible"}
            continue
        c = devgen.canonical(st)
        hit = by_stmt.get(c)
        res = {"role": role, "statement": c}
        if hit:
            s = open_session(pre, c, "coqtop")
            try:
                ok = _first_closing(s, [f"exact {hit['name']}.", f"intros; apply {hit['name']}."], 5)
            finally:
                s.close()
            res.update(result="proved exactly" if ok else "matched but not confirmed",
                       lemma=hit["name"], proof=hit["proof"], cites=hit["cites"],
                       sites=citation_sites(hit["proof"], {x["name"] for x in corpus}))
        else:
            sw = swapped(c)
            if sw and sw in by_stmt:
                res.update(result="proved, other orientation", lemma=by_stmt[sw]["name"])
            elif c in derived:
                res.update(result="derived", script=derived[c]["script"])
            else:
                res.update(result="not proved")
        gold[name] = res
    names = {c["name"] for c in corpus}
    sites = [dict(x, lemma_of=c["name"]) for c in corpus for x in citation_sites(c["proof"], names)]
    summary = {
        "phase": label, "prover": prover, "corpus_forms": corpus_forms, "candidates": len(stmts), "rounds": rounds,
        "corpus": len(corpus),
        "proved_by_round": [r["proved"] for r in rounds_],
        "derived": sum(r["derived_before_gate"] + r["derived_after_proof"] for r in rounds_),
        "gold": gold,
        "gold_helpers_proved_exactly": sum(g.get("result") == "proved exactly"
                                           for g in gold.values() if g["role"] == "helper"),
        "gold_main_proved_exactly": sum(g.get("result") == "proved exactly"
                                        for g in gold.values() if g["role"] == "main"),
        "citing_proofs": sum(bool(c["cites"]) for c in corpus),
        "citations_top": sum(not x["inner"] for x in sites),
        "citations_inner": sum(x["inner"] for x in sites),
        "inner_sites": [x for x in sites if x["inner"]],
        "axiom_free": all(r["axiom_free"] for r in rounds_),
    }
    with open(os.path.join(out, f"gate2{label}.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps(summary, indent=1))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", choices=["gate1", "gate2"])
    ap.add_argument("--prover", default="structural2")
    ap.add_argument("--label", default="2a")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--corpus-forms", default="pose", choices=["pose", "all"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    if a.gate == "gate1":
        gate1(a.out, a.jobs)
    else:
        gate2(a.out, a.jobs, a.prover, a.rounds, a.label, a.corpus_forms)


if __name__ == "__main__":
    main()
