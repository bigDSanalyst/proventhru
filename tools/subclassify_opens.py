"""Split a run's class-3 open statements into what each one lacks.

    python tools/subclassify_opens.py RUN [--jobs 4]

Reads RUN/opens.jsonl (tools/classify_opens.py), so the classes above 3 and
their counts are unchanged; only class 3 is split. Each class-3 statement
goes to the first bucket that explains it:

  false      fails on some list of length up to 6 with elements 0..2,
             checked exhaustively: random testing missed it
             (length (removelast (removelast (removelast l))) <= list_sum l
             fails at [0; 0; 0; 0])
  gap        no corpus lemma mentions only the statement's terms: the corpus
             lacks what it needs (a generator problem, not a prover one)
  cap        saturation closes it once every pose proof is stated, not the
             first 60: an artifact of the probe's cap
  rev        it mentions rev, and closes once list_max (rev l) = list_max l
             and list_sum (rev l) = list_sum l are asserted (proved inline),
             with the corpus lemmas stated: it needs an invariance under rev
             that the corpus lacks
  combined   no lemma, but a shape the ladder's single shapes miss: a case on
             any match left after simpl (Nat.max (S a) x becomes a match on x,
             which lia cannot see through), or a case on the tail and on an if
             in one proof: a tactic-vocabulary gap
  library    a chain that needs library inequalities too (filter_length_le,
             firstn_le_length, ...) stated at the statement's subterms, with
             the corpus lemmas: saturation only states corpus lemmas
  base       closes once a few basic lemmas missing from the corpus are
             asserted (proved inline) and stated at the subterms: the corpus
             lacks a foundation (list_max l <= list_max (map S l))
  interior   induction on a list, then corpus lemmas stated at the step
             case's tail (t, and the statement's subterms with t in place of
             the list), then lia closes it; and the same script without the
             lemmas does not. A corpus lemma is needed inside the induction.
  unknown    none of these

Every bucket but gap and unknown comes with a closing script checked by Coq.
For interior, the lemma-free control is also run and recorded. Writes
RUN/opens_sub.jsonl.
"""
import argparse
import itertools
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from classify_opens import CLOSE, REWRITES, _load, saturation  # noqa: E402
from proventhru.conjecture import L, VARS, _subterms, parse_statement  # noqa: E402
from proventhru.explore import LEMMA_NAME, binders, lemma_terms, preamble  # noqa: E402
from proventhru.gate import _first_closing  # noqa: E402
from proventhru.session import open_session  # noqa: E402

IFS = "repeat match goal with |- context [if ?b then _ else _] => destruct b end"
# a case on any match left in the goal: an if is a match on a bool, and simpl
# turns Nat.max (S a) x into a match on x, which lia cannot see through
CASES = "repeat match goal with |- context [match ?x with _ => _ end] => destruct x end"
# the same, keeping each case's equation, so a branch that contradicts an
# earlier case closes by congruence (filter Nat.even (filter Nat.even l))
CASES_EQ = ("repeat match goal with |- context [match ?x with _ => _ end] => "
            "let E := fresh in destruct x eqn:E end")
CLOSE_EQ = "first [lia | nia | congruence | (rewrite IH; reflexivity) | (f_equal; assumption)]"
AGAIN = ("rewrite ?list_max_app, ?list_sum_app, ?app_length in *; simpl in *")


def relevant(stmt, corpus):
    mentions = lemma_terms(stmt) | {'"<="', '"="'}
    return [c for c in corpus if lemma_terms(c["statement"]) <= mentions]


def _replace_var(t, v, name):
    if t.op == v:
        return name
    if not t.args:
        return t.coq()
    parts = [_replace_var(a, v, name) for a in t.args]
    parts = [p if not a.args else f"({p})" for a, p in zip(t.args, parts)]
    from proventhru.conjecture import ALL_OPS
    return ALL_OPS[t.op][3](*parts)


def interior_scripts(stmt, corpus, cap=40):
    """[(with_lemmas, without_lemmas)] per list variable and shape."""
    try:
        lhs, rhs, _ = parse_statement(stmt)
    except (ValueError, AssertionError, IndexError, TypeError):
        return []
    rel = relevant(stmt, corpus)
    vs = binders(stmt)
    lists = [v for v, ty in vs if ty == "list nat"]
    nats = [v for v, ty in vs if ty == "nat"]
    out = []
    for v in lists:
        # list instances at the step case: t, the other lists, and every list
        # subterm of the statement with t in place of v
        pool = ["t"] + [w for w in lists if w != v]
        for s in list(_subterms(lhs)) + list(_subterms(rhs)):
            if s.type == L and s.op not in VARS and v in s.vars():
                text = f"({_replace_var(s, v, 't')})"
                if text not in pool:
                    pool.append(text)
        poses = []
        for c in rel:
            need = [pool if ty == "list nat" else nats + ["a"] for _, ty in binders(c["statement"])]
            for args in itertools.product(*need):
                poses.append(f"try pose proof ({' '.join((c['name'],) + args)})")
        poses = poses[:cap]
        if not poses:
            continue
        p = "; ".join(poses)
        shapes = [f"induction {v} as [|a t IH]; simpl in *; try {REWRITES}",
                  f"induction {v} as [|a t IH]; simpl in *; {IFS}; simpl in *; try {REWRITES}",
                  f"induction {v} as [|a t IH]; simpl in *; [idtac | destruct t; simpl in *]; "
                  f"try {REWRITES}"]
        shapes += [f"revert {n}; induction {v} as [|a t IH]; intros [|{n}]; simpl in *; "
                   f"try specialize (IH {n}); try {REWRITES}" for n in nats]
        for sh in shapes:
            out.append((f"intros; {sh}; {p}; {CLOSE}.", f"intros; {sh}; {CLOSE}."))
    return out


LIBRARY = [("filter_length_le", ["Nat.even", "L"]), ("firstn_le_length", ["N", "L"]),
           ("skipn_length", ["N", "L"]), ("firstn_length", ["N", "L"]),
           ("rev_length", ["L"]), ("map_length", ["S", "L"]), ("repeat_length", ["N", "N"])]
BASE_LEMMAS = [
    ("b_max_mapS", "forall l : list nat, list_max l <= list_max (map S l)"),
    ("b_mapS_max", "forall l : list nat, list_max (map S l) <= S (list_max l)"),
    ("b_sum_mapS", "forall l : list nat, list_sum (map S l) = list_sum l + length l"),
    ("b_max_rev", "forall l : list nat, list_max (rev l) = list_max l"),
    ("b_sum_rev", "forall l : list nat, list_sum (rev l) = list_sum l"),
]
BASE_PROOF = ("intros l; induction l as [|a t IH]; simpl in *; "
              "rewrite ?list_max_app, ?list_sum_app in *; simpl in *; " + CASES
              + "; first [lia | nia]")


def _subterm_pool(stmt):
    lhs, rhs, _ = parse_statement(stmt)
    pool = {"L": [], "N": []}
    for t in list(_subterms(lhs)) + list(_subterms(rhs)):
        key = "L" if t.type == L else "N"
        text = t.coq() if t.op in VARS else f"({t.coq()})"
        if text not in pool[key]:
            pool[key].append(text)
    return pool


def library_poses(stmt, cap=40):
    try:
        pool = _subterm_pool(stmt)
    except (ValueError, AssertionError, IndexError, TypeError):
        return []
    out = []
    for name, args in LIBRARY:
        pools = [[a] if a not in ("L", "N") else pool[a] for a in args]
        for a in itertools.product(*pools):
            out.append(f"try pose proof ({name} {' '.join(a)})")
    return out[:cap]


def base_script(stmt, corpus):
    asserts = "; ".join(f"assert ({n} : {st}) by ({BASE_PROOF})" for n, st in BASE_LEMMAS)
    try:
        pool = _subterm_pool(stmt)
    except (ValueError, AssertionError, IndexError, TypeError):
        return None
    poses = [f"try pose proof ({n} {x})" for n, _ in BASE_LEMMAS for x in pool["L"]]
    sat = saturation(stmt, corpus, cap=200)
    corp = sat[len("intros; "):-len(f"; {CLOSE}.")] if sat else "idtac"
    return (f"intros; {asserts}; {'; '.join(poses)}; {corp}; "
            f"{'; '.join(library_poses(stmt)) or 'idtac'}; {CLOSE}.")


def combined_scripts(stmt):
    vs = binders(stmt)
    out = []
    for v in [v for v, ty in vs if ty == "list nat"]:
        out += [f"intros; induction {v} as [|a t IH]; simpl in *; {AGAIN}; {CASES}; "
                f"simpl in *; {CLOSE}.",
                f"intros; induction {v} as [|a t IH]; simpl in *; {CASES_EQ}; simpl in *; "
                f"{CASES_EQ}; simpl in *; {CLOSE_EQ}.",
                f"intros; induction {v} as [|a t IH]; simpl in *; {CASES}; simpl in *; "
                f"try {REWRITES}; {CLOSE}.",
                f"intros; induction {v} as [|a t IH]; simpl in *; [{CLOSE} | destruct t; "
                f"simpl in *; {CASES}; simpl in *; {CLOSE}]."]
        out += [f"intros; induction {v} as [|a t IH]; simpl in *; [{CLOSE} | destruct t; "
                f"simpl in *; {IFS}; simpl in *; {CLOSE}].",
                f"intros; induction {v} as [|a t IH]; simpl in *; {IFS}; simpl in *; "
                f"[..|destruct t; simpl in *; {IFS}; simpl in *]; {CLOSE}.",
                f"intros; induction {v} as [|a t IH]; simpl in *; [{CLOSE} | destruct t; "
                f"simpl in *; {IFS}; simpl in *; try {REWRITES}; {CLOSE}]."]
        for n in [n for n, ty in vs if ty == "nat"]:
            out.append(f"intros; revert {n}; induction {v} as [|a t IH]; intros [|{n}]; "
                       f"simpl in *; try specialize (IH {n}); {IFS}; simpl in *; "
                       f"try {REWRITES}; {CLOSE}.")
            out.append(f"intros; revert {n}; induction {v} as [|a t IH]; intros [|{n}]; "
                       f"simpl in *; [..|destruct t]; simpl in *; try specialize (IH {n}); "
                       f"try {REWRITES}; {CLOSE}.")
    return out


def small_envs():
    envs = []
    for n in range(7):
        for lst in itertools.product(range(3), repeat=n):
            for k in range(4):
                envs.append({"l1": lst, "l2": (1, 0), "n": k, "m": 1})
                envs.append({"l1": lst, "l2": lst[::-1], "n": k, "m": 0})
    return envs


SMALL = None


def false_small(stmt):
    global SMALL
    from proventhru.conjecture import holds
    SMALL = SMALL or small_envs()
    try:
        return not holds(*parse_statement(stmt), SMALL)
    except (ValueError, AssertionError, IndexError, TypeError):
        return False


INVARIANCE = ("assert (rmax : forall l : list nat, list_max (rev l) = list_max l) by ({p}); "
              "assert (rsum : forall l : list nat, list_sum (rev l) = list_sum l) by ({p}); "
              "assert (rlen : forall l : list nat, length (rev l) = length l) "
              "by (apply rev_length)")


def subclassify(stmt, corpus, pre, corpus_statements, backend="coqtop"):
    if false_small(stmt):
        return "false", "counterexample among small lists", None
    s = open_session(pre, stmt, backend)
    try:
        tac = _first_closing(s, combined_scripts(stmt), 10)
        if tac:
            return "combined", tac, None
        if not relevant(stmt, corpus):
            return "gap", None, None
        full = saturation(stmt, corpus, cap=10_000)
        if full and _first_closing(s, [full], 20):
            return "cap", full, None
        if "rev " in stmt:
            sat = saturation(stmt, corpus, cap=200)
            body = sat[len("intros; "):-len(f"; {CLOSE}.")] if sat else "idtac"
            inv = INVARIANCE.format(p=BASE_PROOF)
            tac = _first_closing(s, [f"intros; {inv}; {body}; rewrite ?rmax, ?rsum, ?rlen, "
                                     f"?app_length, ?list_sum_app, ?list_max_app in *; "
                                     f"simpl in *; {CLOSE}."], 20)
            if tac:
                return "rev", tac, None
        lib = library_poses(stmt)
        if lib:
            corp = saturation(stmt, corpus, cap=200)
            corp = corp[len("intros; "):-len(f"; {CLOSE}.")] if corp else "idtac"
            tac = _first_closing(s, [f"intros; {corp}; {'; '.join(lib)}; {CLOSE}."], 20)
            if tac:
                return "library", tac, None
        b = base_script(stmt, corpus)
        if b and _first_closing(s, [b], 30):
            return "base", b, None
        for with_l, without in interior_scripts(stmt, corpus):
            if _first_closing(s, [with_l], 10):
                control = _first_closing(s, [without], 10)
                if control:
                    return "interior-lemma-free", without, with_l
                return "interior", with_l, without
        return "unknown", None, None
    finally:
        s.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--backend", default="coqtop")
    a = ap.parse_args(argv)
    corpus = _load(os.path.join(a.run, "corpus.jsonl"))
    pre = preamble(corpus)
    known = {c["statement"] for c in corpus}
    rows = [r for r in _load(os.path.join(a.run, "opens.jsonl")) if r["class"] == "3"]

    def one(r):
        try:
            return subclassify(r["statement"], corpus, pre, known, a.backend)
        except Exception as e:
            return "error", f"{type(e).__name__}: {str(e)[:200]}", None
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, rows))
    out = []
    for r, (bucket, script, control) in zip(rows, res):
        out.append(dict(r, bucket=bucket, bucket_script=script, control=control,
                        bucket_cites=sorted(set(LEMMA_NAME.findall(script or "")))))
    with open(os.path.join(a.run, "opens_sub.jsonl"), "w") as fh:
        fh.writelines(json.dumps(x) + "\n" for x in out)
    counts = Counter(x["bucket"] for x in out)
    print(f"{len(out)} class-3 statements: "
          + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    for b in ("interior", "base", "library", "combined", "rev", "false", "gap", "unknown"):
        for x in [x for x in out if x["bucket"] == b][:5]:
            print(f"  [{b}] {x['statement']}")


if __name__ == "__main__":
    main()
