"""Dev check: does B lose library lemmas at the tactic form, as the
exploration loop lost discovered ones?

    python tools/dev_lemma_forms.py --out out/dev-forms --jobs 4

Retrieval (B) offers a retrieved lemma as rewrite / rewrite <- / apply. A
lemma that is a step inside arithmetic (length (filter f l) <= length l, for
a goal length (filter f l) <= n + length l) is closed by none of them. Three
conditions on the dev set, at the same step budget:

  B        retrieval/v1, as registered
  B+pose   B, and each retrieved lemma also as pose proof (L x ..); lia,
           its explicit arguments filled from the goal's variables (nat,
           list) and the goal's function names (for f : A -> bool), at most
           `fill` ways per lemma
  B+chain  B, and each retrieved inequality also as a step of a chain:
           eapply Nat.le_trans; [eapply L|]; lia and
           eapply Nat.le_trans; [|eapply L]; lia
           (Coq fills the arguments by unification)

Dev only: the dev set is not held out, so this needs no amendment. A form
that helps here is a candidate for an amendment, run then on the test set.
"""
import argparse
import itertools
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru import record as rec  # noqa: E402
from proventhru.cli import _statements  # noqa: E402
from proventhru.pipeline import RECORD, run  # noqa: E402
from proventhru.retrieval import IDENT, RetrievalPolicy, terms  # noqa: E402
from proventhru.search import FixedTactics  # noqa: E402

EXPLICIT = re.compile(r"\(([^():]+) : ([^()]+(?:\([^()]*\)[^()]*)*)\)")


def explicit_binders(stmt):
    """[(name, type)] of the leading forall's explicit binders; implicit
    ones ([A : Type], {A}) are left for Coq to infer."""
    m = re.match(r"\s*forall\s+(.*?),\s", stmt)
    if not m:
        return []
    if not re.search(r"[(\[{]", m.group(1)):          # forall n m : nat, ...
        names, _, ty = m.group(1).partition(" : ")
        return [(n, ty.strip()) for n in names.split()]
    return [(n, ty.strip()) for names, ty in EXPLICIT.findall(m.group(1)) for n in names.split()]


def context(hyps):
    out = {"nat": [], "list": []}
    for h in hyps:
        names, _, ty = h.partition(" : ")
        ty = ty.strip()
        key = "nat" if ty == "nat" else "list" if ty.startswith("list ") else None
        if key:
            out[key].extend(x.strip() for x in names.split(","))
    return out


class Extra(RetrievalPolicy):
    def __init__(self, form, top=6, fill=3):
        super().__init__(FixedTactics(), top=top)
        self.form, self.fill = form, fill
        self.identity = dict(self.identity, id=f"retrieval/v1+{form}/dev+fixed-tactics/v1")

    def propose(self, obs, path, last_failure=None, tried=None):
        out = super().propose(obs, path, last_failure, tried)
        if not obs.goals or self.env is None or self.env.session is None:
            return out
        g = obs.goals[0]
        found = dict(self.retriever.lemmas(self.env.session, terms(g.conclusion, g.hypotheses)))
        ctx = context(g.hypotheses)
        funcs = [t for t in IDENT.findall(g.conclusion) if "." in t or t in ("S",)]
        have = {t for t, _ in out}
        new = []
        for i, name in enumerate(self.last_cost["lemmas"]):
            stmt = found.get(name, "")
            concl = stmt.rsplit(",", 1)[-1]
            if self.form == "pose":
                pools = []
                for _, ty in explicit_binders(stmt):
                    pools.append(ctx["nat"] if ty == "nat" else ctx["list"] if ty.startswith("list")
                                 else funcs if "->" in ty else [])
                if any(not p for p in pools):
                    continue
                for args in itertools.islice(itertools.product(*pools), self.fill):
                    new.append(f"pose proof ({' '.join((name,) + args)}); lia.")
            elif self.form == "chain" and "<=" in concl:
                new += [f"eapply Nat.le_trans; [eapply {name}|]; lia.",
                        f"eapply Nat.le_trans; [|eapply {name}]; lia."]
            for t in new:
                if t not in have:
                    have.add(t)
                    out.append((t, self.score - 0.01 * i))
                    self.last_cost["added"].append(t)
            new = []
        return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="examples/eval_open.txt")
    ap.add_argument("--out", required=True)
    ap.add_argument("--step-budget", type=int, default=600)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--backend", default="coqtop")
    a = ap.parse_args(argv)
    pre, stmts = _statements(a.set)
    factories = {"B": lambda: RetrievalPolicy(FixedTactics(), top=6),
                 "B+pose": lambda: Extra("pose"), "B+chain": lambda: Extra("chain")}
    proved = {}
    for k, f in factories.items():
        d = os.path.join(a.out, k)
        run(stmts, d, pre, budget=None, step_budget=a.step_budget, backend=a.backend,
            jobs=a.jobs, log=lambda *_: None, policy_factory=f)
        rows = rec.corpus(rec.load(os.path.join(d, RECORD)))
        proved[k] = {r["statement"]: r for r in rows if r["standing"] == "proved"}
        print(f"{k}: {len(proved[k])} / {len(stmts)}", flush=True)
    for k in ("B+pose", "B+chain"):
        gain = sorted(set(proved[k]) - set(proved["B"]))
        loss = sorted(set(proved["B"]) - set(proved[k]))
        print(f"\n{k} vs B: +{len(gain)} -{len(loss)}")
        for s in gain:
            print(f"  + {s}\n      {' '.join(proved[k][s]['proof'])}")
        for s in loss:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
