"""Why did an exploration run leave its open statements open?

    python tools/classify_opens.py RUN [--jobs 4] [--out RUN/opens.jsonl]

Every statement a run's gate passed as open, never proved, derived or
settled later, is tried against a fixed ladder of scripted proofs, with the
run's final corpus loaded. Its class is the first rung that closes it:

  1  in the prover's class, missed by search: closed by the prover's own
     tactics (intros, induction / destruct, simpl, lia / nia, rewrite of a
     library lemma), alone or with one corpus lemma at the top
     (pose proof (L a); lia, as the corpus index offers). A bigger step
     budget or a better search order would have found it.
  1r the same, but the corpus lemma it needs was found in the statement's own
     round or later: the corpus grew past it and nothing retried it.
  2  a wider proof class: closed only with a corpus lemma inside an
     induction (at the step case's tail) or with two corpus lemmas in one
     proof. A prover that uses the corpus structurally would find it; the
     fixed one does not.
  2s a composition: closed by stating every corpus lemma the statement's
     terms allow, at its variables and subterms, then one lia / nia: a chain
     of several discovered lemmas (removelast and filter are monotone, max is
     at most the sum), at the top.
  3v outside the vocabulary: closed only by proof shapes the run's prover
     (--prover) did not have: those of structural-tactics/v1 (a case on the
     tail, on an if, a number reverted first) and /v2 (a case on a match
     keeping its equation, simpl again after a library rewrite). The run's
     own shapes are rung 1.
  F  false: refuted by wider random inputs than the generator's (values to
     100, lists to 12). It passed the generator's tests (0..5) only.
  3  unexplained: no rung closes it. It may need a lemma the corpus lacks, a
     different induction, or be false (it passed testing, not a proof).

The ladder is a probe, not a decision procedure: class 1 and 2 are proved
memberships (each comes with the closing script, checked by Coq), class 3 is
"not found by these scripts". Run on CPU; no model.
"""
import argparse
import itertools
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru import record as rec  # noqa: E402
from proventhru.explore import LEMMA_NAME, _goal_terms, binders, lemma_terms, preamble  # noqa: E402
from proventhru.gate import _first_closing  # noqa: E402
from proventhru.session import open_session  # noqa: E402

REWRITES = ("rewrite ?app_length, ?list_sum_app, ?list_max_app, ?map_length, ?rev_length, "
            "?firstn_length, ?skipn_length, ?repeat_length, ?seq_length")
CLOSE = "first [lia | nia]"


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def open_statements(run):
    """{statement: round} left open by the gate and the provers, and never
    admitted, derived or closed at the gate later."""
    settled = {c["statement"] for c in _load(os.path.join(run, "corpus.jsonl"))}
    opens = {}
    r = 0
    while os.path.isdir(os.path.join(run, f"round-{r}")):
        rdir = os.path.join(run, f"round-{r}")
        settled |= {d["statement"] for d in _load(os.path.join(rdir, "derived.jsonl"))}
        for k in ("fixed", "retrieval"):
            p = os.path.join(rdir, k, "records.jsonl")
            if os.path.exists(p):
                for row in rec.corpus(rec.load(p)):
                    if row["gate"] == "open" and row["standing"] == "open":
                        opens.setdefault(row["statement"], r)
                    elif row["gate"] != "open":
                        settled.add(row["statement"])
        r += 1
    return {s: r for s, r in opens.items() if s not in settled}


def ladder(stmt, corpus, prover="fixed"):
    """[(class, script)] in the order tried."""
    lists = [v for v, ty in binders(stmt) if ty == "list nat"]
    goal = _goal_terms(stmt)
    mentions = lemma_terms(stmt)
    # corpus lemmas the corpus index would retrieve (everything they mention
    # is in the statement), then ones sharing a function, most shared first.
    # Ranking by shared terms alone crowds out the general lemma behind
    # instances that mention more (list_max l <= list_sum l behind
    # list_max l <= list_sum (l ++ rev l)), as Search does.
    def key(c):
        ts = lemma_terms(c["statement"])
        return (not ts <= mentions, -len(ts & mentions), len(c["statement"]))
    rel = sorted((c for c in corpus if lemma_terms(c["statement"]) & mentions - {'"<="', '"="'}),
                 key=key)[:12]

    def fills(c, pool, limit=3):
        need = [pool[t] for _, t in binders(c["statement"])]
        return [" ".join((c["name"],) + a) for a in itertools.islice(itertools.product(*need),
                                                                       limit)]
    one = []
    for v in lists:
        one += [f"intros; induction {v}; simpl in *; {CLOSE}.",
                f"intros; induction {v}; simpl in *; {REWRITES}; {CLOSE}.",
                f"intros; destruct {v}; simpl in *; {CLOSE}."]
    one += [f"intros; {REWRITES}; {CLOSE}.", f"intros; simpl; {REWRITES}; {CLOSE}."]
    for c in rel:
        for a in fills(c, goal):
            one.append(f"intros; {REWRITES}; pose proof ({a}); {CLOSE}.")
            one.append(f"intros; simpl; {REWRITES}; pose proof ({a}); {CLOSE}.")
    two = []
    for v in lists:
        for c in rel:
            # at the step case the tail is t; offer L at t and at the other lists
            pool = {"list nat": ["t"] + [w for w in lists if w != v], "nat": goal["nat"][:3]}
            for a in fills(c, pool):
                two.append(f"intros; induction {v} as [|h t IH]; simpl in *; "
                           f"[{CLOSE} | {REWRITES}; pose proof ({a}); {CLOSE}].")
    for c1, c2 in itertools.combinations(rel[:6], 2):
        for a1 in fills(c1, goal, 2):
            for a2 in fills(c2, goal, 2):
                two.append(f"intros; {REWRITES}; pose proof ({a1}); pose proof ({a2}); {CLOSE}.")
    shapes = {"structural": [], "structural2": []}
    nats = [v for v, ty in binders(stmt) if ty == "nat"]
    ifs = "repeat match goal with |- context [if ?b then _ else _] => destruct b end"
    cases_eq = ("repeat match goal with |- context [match ?x with _ => _ end] => "
                "let E := fresh in destruct x eqn:E end")
    close_eq = ("first [lia | nia | congruence | (rewrite IH; reflexivity) | "
                "(f_equal; assumption)]")
    again = "rewrite ?list_max_app, ?list_sum_app, ?app_length in *; simpl in *"
    for v in lists:
        # structural-tactics/v1: a case on the tail in the step case
        # (removelast), on an if (filter), a number reverted first (skipn)
        shapes["structural"] += [
            f"intros; induction {v} as [|a t IH]; simpl in *; [{CLOSE} | destruct t; "
            f"simpl in *; try {REWRITES}; {CLOSE}].",
            f"intros; induction {v} as [|a t IH]; simpl in *; {ifs}; simpl in *; "
            f"try {REWRITES}; {CLOSE}."]
        for n in nats:
            shapes["structural"].append(
                f"intros; revert {n}; induction {v} as [|a t IH]; intros [|{n}]; "
                f"simpl in *; try specialize (IH {n}); try {REWRITES}; {CLOSE}.")
        # structural-tactics/v2: a case on a match simpl leaves, keeping its
        # equation; simpl again after a library rewrite
        shapes["structural2"] += [
            f"intros; induction {v} as [|a t IH]; simpl in *; {cases_eq}; simpl in *; "
            f"{cases_eq}; simpl in *; {close_eq}.",
            f"intros; induction {v} as [|a t IH]; simpl in *; {again}; {ifs}; simpl in *; "
            f"{CLOSE}."]
    vocab = []
    for v in lists:
        for n in nats:
            vocab += [f"intros; revert {n}; induction {v}; intros [|{n}]; simpl in *; "
                      f"try {REWRITES}; {CLOSE}.",
                      f"intros; revert {n}; induction {v}; intros; simpl in *; "
                      f"try {REWRITES}; {CLOSE}."]
    # a shape the run's prover had is rung 1 (search missed it); one it
    # lacked is 3v (outside its vocabulary)
    inside = {"fixed": [], "structural": ["structural"],
              "structural2": ["structural", "structural2"]}[prover]
    for k, ss in shapes.items():
        (one if k in inside else vocab)[:0] = ss
    return [("1", s) for s in one] + [("2", s) for s in two] + [("3v", s) for s in vocab]


def false_by_wider_tests(stmt, tests=3000, seed=11):
    """A counterexample with values up to 100 and lists up to 12 long, where
    the generator tested 0..5 and up to 6: list_max (filter Nat.even l) <=
    S (S (S (S n))) holds on the generator's inputs and is false."""
    import random
    from proventhru.conjecture import holds, parse_statement, wide_env
    rng = random.Random(seed)
    envs = [wide_env(rng) for _ in range(tests)]
    try:
        lhs, rhs, rel = parse_statement(stmt)
    except (ValueError, AssertionError, IndexError, TypeError):
        return False
    return not holds(lhs, rhs, rel, envs)


def saturation(stmt, corpus, cap=60):
    goal = _goal_terms(stmt)
    mentions = lemma_terms(stmt) | {'"<="', '"="'}
    poses = [f"pose proof ({' '.join((c['name'],) + a)})" for c in corpus
             if lemma_terms(c["statement"]) <= mentions
             for a in itertools.product(*[goal[t] for _, t in binders(c["statement"])])]
    return f"intros; {'; '.join(poses[:cap])}; {CLOSE}." if poses else None


def classify(stmt, pre, corpus, backend="coqtop", timeout=3, prover="fixed"):
    if false_by_wider_tests(stmt):
        return "F", "counterexample with wider random inputs"
    s = open_session(pre, stmt, backend)
    try:
        steps = ladder(stmt, corpus, prover)
        for cls in ("1", "2", "2s", "3v"):
            if cls == "2s":
                sat = saturation(stmt, corpus)
                tac = sat and _first_closing(s, [sat], 10)
            else:
                tac = _first_closing(s, [t for c, t in steps if c == cls], timeout)
            if tac:
                return cls, tac
        return "3", None
    finally:
        s.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default=None)
    ap.add_argument("--backend", default="coqtop")
    ap.add_argument("--prover", choices=["fixed", "structural", "structural2"], default="fixed",
                    help="the run's prover: its shapes are rung 1, the others rung 3v")
    a = ap.parse_args(argv)
    corpus = _load(os.path.join(a.run, "corpus.jsonl"))
    pre = preamble(corpus)
    opens = open_statements(a.run)
    stmts = sorted(opens, key=lambda s: (opens[s], s))

    def one(s):
        try:
            return classify(s, pre, corpus, a.backend, prover=a.prover)
        except Exception as e:      # does not elaborate etc.
            return "error", f"{type(e).__name__}: {str(e)[:200]}"
    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(one, stmts))
    found = {c["name"]: c["round"] for c in corpus}
    rows = []
    for s, (c, t) in zip(stmts, results):
        cites = sorted(set(LEMMA_NAME.findall(t or "")))
        if c == "1" and any(found.get(n, -1) >= opens[s] for n in cites):
            c = "1r"
        rows.append({"statement": s, "round": opens[s], "class": c, "script": t,
                     "cites": cites})
    out = a.out or os.path.join(a.run, "opens.jsonl")
    with open(out, "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)
    total = Counter(r["class"] for r in rows)
    print(f"{len(rows)} open statements, corpus {len(corpus)} lemmas: "
          + ", ".join(f"class {k}: {v}" for k, v in sorted(total.items())))
    by_round = {}
    for r in rows:
        by_round.setdefault(r["round"], Counter())[r["class"]] += 1
    for k in sorted(by_round):
        print(f"  round {k}: " + ", ".join(f"{c} {n}" for c, n in sorted(by_round[k].items())))
    multi = [r for r in rows if len(r["cites"]) > 1]
    print(f"  proofs citing two or more corpus lemmas: {len(multi)}")
    for cls in ("1r", "2", "3v"):
        for r in [r for r in rows if r["class"] == cls][:8]:
            print(f"  [{cls}] {r['statement']}\n        {r['script']}")


if __name__ == "__main__":
    main()
