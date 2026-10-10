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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", choices=["gate1"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    gate1(a.out, a.jobs)


if __name__ == "__main__":
    main()
