"""The conjecture loop: generate, test, gate, prove, and keep what is proved.

    proventhru explore --out out/explore --rounds 4 --per-round 80 --step-budget 600

Theory exploration over the stdlib nat and list nat signature, in rounds:

  1. generate  the next per_round candidates from conjecture.py, smallest
               first: small laws are proved first and are the lemmas the
               bigger ones need.
  2. test      each candidate on 2,000 fresh random inputs (plausibility),
               and drop instances of laws over nat alone: with every
               list-derived number replaced by a free one, 0 * list_sum l = 0
               is still true, so it says nothing about lists.
  3. gate      ill-formed, refuted, vacuous and trivial candidates are
               dropped. "Trivial" includes "one lemma closes it", and the
               lemmas the gate tries now include every lemma discovered so
               far, so an instance of something already found is not new.
               Before the gate, a candidate that follows from one discovered
               lemma by arithmetic (pose proof (L l1); lia) is recorded as a
               derivation citing that lemma, in round-N/derived.jsonl.
  4. prove     the open ones at a step budget, split in half: the fixed
               tactics (A) on every candidate, then fixed tactics plus
               retrieval (B) on what A left open. B's retrieval also offers
               each discovered lemma it retrieves as pose proof (L x); lia. Retrieval's Search sees the discovered
               lemmas, so later proofs can cite earlier discoveries.
  5. keep      kernel-certified proofs, smallest first; one that follows
               from a lemma admitted before it (this round's included) is a
               derivation, the rest become Lemmas in the corpus, loaded in
               the preamble of every later round.

What stays fixed (the truth layer): the kernel certifies every lemma, and
the whole corpus is recompiled from scratch after every round. The gate
decides what counts as new. Statements of the held-out and dev sets are
excluded, so the corpus cannot leak into an evaluation on them.

What "novel" means here: not closed by one tactic, by one standard-library
lemma, or by one lemma discovered earlier in this run. It is novelty
relative to the library and the corpus, not to mathematics.

Each round is two run records (round-N/fixed/, round-N/retrieval/) under a preamble that
names the corpus it saw. corpus.jsonl lists every lemma with its provenance,
and corpus.v is the whole corpus as one compilable file. A rerun resumes:
finished rounds are read back, and the round in progress continues from its
record.
"""
import json
import os
import random
import re
import itertools
import shutil
import subprocess
import tempfile
import time
from collections import Counter

from . import record as rec
from .conjecture import (EDGE, L, N, canonical_names, candidates, enumerate_classes, holds,
                         nat_abstraction, nat_instance, random_env, statement)
from .env import DEFAULT_PREAMBLE
from .pipeline import RECORD, run
from .retrieval import RetrievalPolicy
from .search import FixedTactics
from .gate import _first_closing
from .session import open_session

BASE = DEFAULT_PREAMBLE + " Import ListNotations."
LEMMA_NAME = re.compile(r"\bpt_r\d+_\d+\b")
BINDER = re.compile(r"\(([\w ]+) : (list nat|nat)\)")


def binders(stmt):
    """[(name, type)] of a generated statement's leading forall."""
    head = stmt.split(",", 1)[0]
    return [(v, ty) for vs, ty in BINDER.findall(head) for v in vs.split()]


def corollary_tactics(stmt, corpus):
    """intros; pose proof (L x y); lia for every corpus lemma L and every
    way to fill its binders with the goal's variables of the same type: a
    statement that this closes follows from a lemma already found by
    arithmetic alone (list_max l - n <= list_sum l from list_max l <=
    list_sum l), so it is not new."""
    goal = binders(stmt)
    for c in corpus:
        need = binders(c["statement"])
        pools = [[v for v, ty in goal if ty == t] for _, t in need]
        for args in itertools.product(*pools):
            yield f"intros; pose proof ({' '.join((c['name'],) + args)}); lia."


def hypothesis_vars(hypotheses):
    """{type: [names]} for the nat and list nat variables of a goal's context
    ('l1 : list nat', 'n, m : nat')."""
    out = {}
    for h in hypotheses:
        names, _, ty = h.partition(" : ")
        if ty.strip() in (L, N):
            out.setdefault(ty.strip(), []).extend(x.strip() for x in names.split(","))
    return out


class CorpusRetrievalPolicy(RetrievalPolicy):
    """Retrieval (B), and for each discovered lemma among the lemmas Search
    retrieved for this goal, also `pose proof (L x ..); lia` with the goal's
    variables: apply only closes a goal the lemma matches exactly, and a
    discovered inequality is mostly used inside arithmetic. Only retrieved
    lemmas get the form, so the candidates grow with what the goal mentions,
    not with the size of the corpus."""

    def __init__(self, base, corpus, top=6, score=0.7, per_lemma=3):
        super().__init__(base, top, score)
        self.corpus = {c["name"]: c for c in corpus}
        self.per_lemma = per_lemma
        self.identity = dict(self.identity, id=f"retrieval/v1+corpus-lia/v1+{base.identity['id']}")

    def propose(self, obs, path, last_failure=None, tried=None):
        out = super().propose(obs, path, last_failure, tried)
        cost = self.last_cost
        if not obs.goals:
            return out
        ctx = hypothesis_vars(obs.goals[0].hypotheses)
        have = {t for t, _ in out}
        for i, name in enumerate(cost.get("lemmas", [])):
            if name not in self.corpus:
                continue
            pools = [ctx.get(ty, []) for _, ty in binders(self.corpus[name]["statement"])]
            for args in itertools.islice(itertools.product(*pools), self.per_lemma):
                t = f"pose proof ({' '.join((name,) + args)}); lia."
                if t not in have:
                    have.add(t)
                    out.append((t, self.score + 0.05 - 0.01 * i))
                    cost["added"].append(t)
        return out


def corollary(stmt, pre, corpus, backend="coqtop", timeout=2):
    """The closing tactic if stmt is an arithmetic corollary of the corpus."""
    if not corpus:
        return None
    try:
        s = open_session(pre, stmt, backend)
    except ValueError:      # does not elaborate: the gate will say so
        return None
    try:
        return _first_closing(s, corollary_tactics(stmt, corpus), timeout)
    finally:
        s.close()


def candidate_stream(seed=2, max_term=5, min_size=3, max_size=9, exclude=(), stats=None):
    """Plausible candidate statements, smallest first, deterministic in seed.
    exclude: statements never to propose (the held-out and dev sets).
    Instances of laws over nat alone (0 * list_sum l = 0) are dropped before
    the gate: they are true of any number, so they say nothing about lists.
    stats, if given, counts what each filter dropped."""
    stats = {} if stats is None else stats
    rng = random.Random(seed)
    arng = random.Random(seed + 1)
    envs = EDGE + [random_env(rng) for _ in range(40)]
    check = EDGE + [random_env(rng) for _ in range(2000)]
    classes = enumerate_classes(max_term, envs)
    seen, pool = set(exclude), []
    for c in candidates(classes, min_size, max_size):
        s = statement(*c, canonical_names(c[0], c[1]))
        if s not in seen:
            seen.add(s)
            pool.append((c[0].size + c[1].size, s, c))
    pool.sort(key=lambda p: (p[0], p[1]))
    for _, s, c in pool:
        if not holds(c[0], c[1], c[2], check):
            stats["refuted_by_testing"] = stats.get("refuted_by_testing", 0) + 1
        elif nat_instance(*c, arng):
            stats["nat_instance"] = stats.get("nat_instance", 0) + 1
            stats.setdefault("nat_forms", []).append((s, nat_abstraction(*c)))
        else:
            yield s


def derivation(stmt, script, stage, proof=None):
    """A statement derived from discovered lemmas: the script cites them.
    stage: before_gate (from earlier rounds' lemmas, so never searched) or
    after_proof (proved this round, then found to follow from a smaller
    lemma admitted before it); proof is the search's own proof then."""
    return {"statement": stmt, "script": script, "cites": sorted(set(LEMMA_NAME.findall(script))),
            "stage": stage, "proof": proof}


def lemma_text(name, stmt, proof):
    return f"Lemma {name} : {stmt}.\nProof. {' '.join(proof)} Qed.\n"


def preamble(corpus):
    return BASE + ("\n" + "".join(lemma_text(c["name"], c["statement"], c["proof"])
                                  for c in corpus) if corpus else "")


def compile_corpus(text, coqc="coqc"):
    """Compile the corpus as one file from scratch; ('ok' | error text)."""
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, "corpus.v")
        with open(path, "w") as fh:
            fh.write(text)
        p = subprocess.run([shutil.which(coqc) or coqc, "-q", path], cwd=d,
                           capture_output=True, text=True, timeout=600)
        return "ok" if p.returncode == 0 else (p.stdout + p.stderr)[-1500:]
    finally:
        shutil.rmtree(d, ignore_errors=True)


INDUCTIVE = re.compile(r"^\s*(intros?[^.]*;\s*)?(induction|destruct|case|elim)\b")


def citation_sites(proof, names=None):
    """Where a proof uses a discovered lemma: [{lemma, index, inner}]. inner
    means an induction or case split comes before it in the proof, so the
    lemma is used at a subgoal the statement does not show; otherwise it is
    used at the top (intros; pose proof (L l1); lia)."""
    out, split = [], False
    for i, tac in enumerate(proof):
        for name in LEMMA_NAME.findall(tac):
            if names is None or name in names:
                out.append({"lemma": name, "index": i, "inner": split})
        if INDUCTIVE.search(tac):
            split = True
    return out


def certify_drops(forms, coqc="coqc"):
    """Prove each dropped candidate's nat law: [(statement, form)] -> the
    statements whose law did not go through (they go back to the prover).
    One compile for all; one per form only if that fails."""
    def text(fs):
        return BASE + "\n" + "".join(f"Goal {f}.\nProof. intros; first [lia | nia]. Qed.\n"
                                      for _, f in fs)
    if not forms or compile_corpus(text(forms), coqc) == "ok":
        return []
    return [s for s, f in forms if compile_corpus(text([(s, f)]), coqc) != "ok"]


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def explore(out, rounds=4, per_round=80, step_budget=600, jobs=1, exclude=(), seed=2,
            max_term=5, min_size=3, max_size=9, backend="coqtop", retrieval_top=6,
            log=print, statements=None):
    """statements: an explicit candidate list to use instead of the generator
    (tests; or a curated batch). Excluded statements are dropped from it too."""
    os.makedirs(out, exist_ok=True)
    corpus_path = os.path.join(out, "corpus.jsonl")
    summary_path = os.path.join(out, "rounds.jsonl")
    corpus, done = _load(corpus_path), {r["round"]: r for r in _load(summary_path)}
    dropped = {}
    stream = (iter([x for x in statements if x not in set(exclude)]) if statements is not None
              else candidate_stream(seed, max_term, min_size, max_size, set(exclude), dropped))
    requeue, certified = [], 0
    for r in range(rounds):
        batch = requeue + [s for _, s in zip(range(per_round - len(requeue)), stream)]
        requeue = []
        if not batch:
            log("no candidates left")
            break
        if r in done:
            log(f"round {r}: done before ({done[r]['proved']} proved)")
            continue
        seen_names = {c["name"] for c in corpus}
        pre = preamble(corpus)
        rdir = os.path.join(out, f"round-{r}")
        log(f"round {r}: {len(batch)} candidates, corpus {len(corpus)} lemmas")
        os.makedirs(rdir, exist_ok=True)
        # Derived: follows from one discovered lemma by arithmetic. Kept as
        # a derivation that cites the lemma, not as a new lemma.
        der_path = os.path.join(rdir, "derived.jsonl")
        if os.path.exists(der_path):
            derived = [d for d in _load(der_path) if d["stage"] == "before_gate"]
        else:
            derived = [derivation(x, t, "before_gate") for x in batch
                       for t in [corollary(x, pre, corpus, backend)] if t]
            with open(der_path, "w") as fh:
                fh.writelines(json.dumps(d) + "\n" for d in derived)
        offered = len(batch)
        batch = [x for x in batch if x not in {d["statement"] for d in derived}]
        # Two provers, half the step budget each: fixed tactics (A) on every
        # candidate, then fixed tactics + retrieval (B) on what A left open.
        # They prove different things (results/v5-test-results.md): A goes
        # deep on few tactics, B wide on library lemmas.
        half = step_budget // 2
        first = []
        if batch:
            run(batch, os.path.join(rdir, "fixed"), pre, budget=None, step_budget=half,
                backend=backend, jobs=jobs, log=lambda *_: None, policy_factory=FixedTactics)
            first = rec.load(os.path.join(rdir, "fixed", RECORD))
        rows = [x for x in rec.corpus(first)]
        left = [x["statement"] for x in rows if x["standing"] == "open"]
        if left:
            run(left, os.path.join(rdir, "retrieval"), pre, budget=None,
                step_budget=step_budget - half, backend=backend, jobs=jobs,
                log=lambda *_: None,
                policy_factory=lambda: CorpusRetrievalPolicy(FixedTactics(), corpus,
                                                             top=retrieval_top))
            second = rec.load(os.path.join(rdir, "retrieval", RECORD))
            rows = [x for x in rows if x["standing"] != "open"] + rec.corpus(second)
        eps = {e["data"]["episode"]: e["data"] for e in first if e["kind"] == "episode"}
        gate = Counter()
        known_by_corpus = 0
        for e in eps.values():
            g = e.get("gate") or {}
            gate[g.get("status")] += 1
            if g.get("status") == "trivial" and LEMMA_NAME.search(" ".join(g.get("script") or [])):
                known_by_corpus += 1
        # Admit smallest first, each checked against everything admitted
        # before it, this round's lemmas included: a lemma that follows from
        # a smaller one found in the same round is a derivation too.
        new, citing = [], 0
        known = {c["statement"] for c in corpus}
        proved = sorted((x for x in rows if x["standing"] == "proved"
                         and x["statement"] not in known),
                        key=lambda x: (len(x["statement"]), x["statement"]))
        for row in proved:
            t = corollary(row["statement"], preamble(corpus + new), corpus + new, backend) \
                if new else None
            if t:
                derived.append(derivation(row["statement"], t, "after_proof", row["proof"]))
                continue
            name = f"pt_r{r}_{len(new)}"
            cites = sorted(set(LEMMA_NAME.findall(" ".join(row["proof"]))) & seen_names)
            citing += bool(cites)
            new.append({"name": name, "statement": row["statement"], "proof": row["proof"],
                        "round": r, "episode": row["episode"], "cites": cites,
                        "prover": (row.get("policy") or {}).get("id"),
                        "kernel": row["kernel"]})
        with open(der_path, "w") as fh:
            fh.writelines(json.dumps(d) + "\n" for d in derived)
        t0 = time.perf_counter()
        check = compile_corpus(preamble(corpus + new))
        compile_s = round(time.perf_counter() - t0, 2)
        if check != "ok":
            raise RuntimeError(f"round {r}: the corpus does not compile with the new lemmas: "
                               f"{check}")
        corpus += new
        with open(corpus_path, "a") as fh:
            fh.writelines(json.dumps(c) + "\n" for c in new)
        with open(os.path.join(out, "corpus.v"), "w") as fh:
            fh.write(preamble(corpus))
        # The number-only drops are certified, not just tested: each one's
        # nat law is proved by lia / nia. One that is not goes back to the
        # prover in the next round.
        forms = dropped.get("nat_forms", [])[certified:]
        requeue = certify_drops(forms)
        certified += len(forms)
        sites = [dict(x, statement=c["statement"]) for c in new
                 for x in citation_sites(c["proof"], seen_names)]
        heads = {k: list(rec.head(rec.load(os.path.join(rdir, k, RECORD))))
                 for k in ("fixed", "retrieval") if os.path.exists(os.path.join(rdir, k, RECORD))}
        summary = {"round": r, "candidates": offered,
                   "dropped_before_gate_so_far": {k: v for k, v in dropped.items()
                                                  if k != "nat_forms"},
                   "nat_drops_certified": len(forms) - len(requeue),
                   "nat_drops_requeued": requeue, "gate": dict(gate),
                   "known_by_corpus": known_by_corpus,
                   "derived_before_gate": sum(d["stage"] == "before_gate" for d in derived),
                   "derived_after_proof": sum(d["stage"] == "after_proof" for d in derived),
                   "searched": gate.get("open", 0), "proved": len(new),
                   "proofs_citing_corpus": citing,
                   # every place the corpus did work: closed at the gate by one
                   # lemma, derived from one, or cited inside a new proof
                   "uses_of_corpus": known_by_corpus + len(derived) + citing,
                   # by position: the gate and derivations use a lemma at the
                   # top by construction; inner = after an induction or case
                   # split, at a subgoal the statement does not show
                   "citations": {"gate_one_lemma": known_by_corpus,
                                 "derived_top": len(derived),
                                 "proofs_top": sum(not x["inner"] for x in sites),
                                 "proofs_inner": sum(x["inner"] for x in sites)},
                   "citation_sites": sites, "corpus_compile_s": compile_s, "corpus_size": len(corpus),
                   "preamble_sha256": rec.sha256(pre), "record_heads": heads}
        with open(summary_path, "a") as fh:
            fh.write(json.dumps(summary) + "\n")
        done[r] = summary
        log(f"round {r}: gate {dict(gate)}; {known_by_corpus} already known from the corpus, "
            f"{len(derived)} derived from it; "
            f"proved {len(new)} new ({citing} citing earlier lemmas); corpus {len(corpus)}")
    return corpus, [done[k] for k in sorted(done)]
