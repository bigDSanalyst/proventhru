"""A pattern extractor run, end to end, as its spec fixes it
(docs/pattern-run-1.md, docs/pattern-run-2.md).

    python tools/pattern_run.py --run N --out OUT [--jobs 3]

Each step resumes from its output in OUT:
  1. propose  harvest.json, proposals.jsonl: every library theorem of List and
              Permutation carried over to the isort development (pattern.py)
  2. test     tests.jsonl: each distinct candidate elaborated and decided in
              Coq on its falsifier space; refutations certified by the kernel
  3. prove    run/: the loop (isort pilot 2b-ii settings) on what passed, what
              couldn't be tested, and refutations that didn't certify
  4. score    significance/ (the (b) searches), score.json
  5. report   results/pattern-run-N.md

Before anything runs, it refuses unless the run's spec and the governed code
(GOVERNED) match their docs/frozen.md rows, and docs/pattern-metrics.md matches
its own. A run whose code row is closed doesn't run again. Every record the run writes is annotated with those hashes
and the harvest's.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

from proventhru import devgen, pattern  # noqa: E402
from proventhru import record as rec  # noqa: E402
from proventhru.session import CoqTimeout  # noqa: E402

METRICS = "docs/pattern-metrics.md"
# What each registered run is. Run 1's settings are the code's v1 behaviour.
RUNS = {
    1: {"spec": "docs/pattern-run-1.md", "row": "code:pattern-run-1",
        "proposer": pattern.PROPOSER, "sources": pattern.SOURCES, "relation": None,
        "equations": False, "extra": (), "strict_connects": False},
    2: {"spec": "docs/pattern-run-2.md", "row": "code:pattern-run-2",
        "proposer": pattern.PROPOSER_V2, "sources": pattern.SOURCES_V2,
        "relation": pattern.RELATION, "equations": True, "extra": ("Require Import Sorted.",),
        "strict_connects": True},
    3: {"spec": "docs/pattern-run-3.md", "row": "code:pattern-run-3",
        "proposer": pattern.PROPOSER_V2, "sources": pattern.SOURCES_V2,
        "relation": pattern.RELATION, "equations": True, "extra": ("Require Import Sorted.",),
        "strict_connects": True, "closed_novelty": True, "previous": 2},
    # The model proposer (docs/pattern-run-4.md): its two seed batches are two runs,
    # scored as run 3 scores, the proposals made in Colab by tools/pattern_m1.py.
    4: {"spec": "docs/pattern-run-4.md", "row": "code:pattern-run-4",
        "proposer": "pattern/model-m1-v1", "model_batch": "A", "sources": (), "relation": None,
        "equations": False, "extra": ("Require Import Sorted.",), "strict_connects": True,
        "closed_novelty": True, "previous": None, "compare": 3},
    5: {"spec": "docs/pattern-run-4.md", "row": "code:pattern-run-4",
        "proposer": "pattern/model-m1-v1", "model_batch": "B", "sources": (), "relation": None,
        "equations": False, "extra": ("Require Import Sorted.",), "strict_connects": True,
        "closed_novelty": True, "previous": 4, "compare": 3},
}
# Run 3's novelty: a statement one constructor step closes is present in the
# development (its own inductives' constructors) or the library (theirs).
CONSTRUCTOR_CLOSERS = ("intros; constructor.", "intros; constructor; assumption.")
RUN = 1
CFG = RUNS[RUN]
SPEC, CODE_ROW = CFG["spec"], CFG["row"]


def configure(n):
    global RUN, CFG, SPEC, CODE_ROW, CANDIDATES
    RUN, CFG = n, RUNS[n]
    SPEC, CODE_ROW = CFG["spec"], CFG["row"]
    CANDIDATES = os.path.join(HERE, "results", f"pattern-run-{n}-candidates.jsonl")


def base_preamble():
    """The prover's preamble: the development's definitions, with what the run
    adds imported before them (see pattern.with_extra: Sorted's notation sort
    must not cover the development's sort)."""
    pre, mark = devgen.preamble(), "Import ListNotations."
    if not CFG["extra"]:
        return pre
    if mark not in pre:
        raise RuntimeError("the development's preamble has no ListNotations import to follow")
    return pre.replace(mark, " ".join((mark,) + tuple(CFG["extra"])), 1)
GOVERNED = [
    "pilots/isort/ISort.v", "pilots/isort/ISortTest.v", "pilots/isort/ISortDec.v",
    "proventhru/conjecture.py", "proventhru/coqtop.py", "proventhru/devgen.py", "proventhru/env.py",
    "proventhru/explore.py",
    "proventhru/gate.py", "proventhru/goals.py", "proventhru/kernel.py", "proventhru/pattern.py",
    "proventhru/pipeline.py", "proventhru/record.py", "proventhru/retrieval.py",
    "proventhru/search.py", "proventhru/session.py", "tools/pattern_run.py",
]
JOBS = 3
STEPS = 600
TEST_DEADLINE = 120.0           # seconds per test command; past it, the candidate is untested
ROUNDS = 4
GOLD_FILE = os.path.join(pattern.HERE, "ISortGold.v")
CANDIDATES = os.path.join(HERE, "results", f"pattern-run-{RUN}-candidates.jsonl")
LOGICAL = {"eq", "iff", "and", "or", "not", "True", "False", "le", "lt"}
VOCAB_OWN = set(pattern.OWN)


def code_hash(repo, paths=GOVERNED):
    """sha256 over the governed files' paths and contents, in order."""
    h = hashlib.sha256()
    for p in paths:
        with open(os.path.join(repo, p), "rb") as fh:
            h.update(f"{p} {hashlib.sha256(fh.read()).hexdigest()}\n".encode())
    return h.hexdigest()


def frozen_rows():
    with open(os.path.join(HERE, "docs", "frozen.md")) as fh:
        text = fh.read()
    return re.findall(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([0-9a-f]{64})`\s*\|\s*`([0-9a-f]+)`\s*\|",
                      text, re.M)


def preflight():
    """{spec, metrics, code}: the hashes this run is registered under, or SystemExit."""
    rows = frozen_rows()
    out = {}
    for label, path in (("spec", SPEC), ("metrics", METRICS)):
        mine = [r for r in rows if r[0] == path]
        digest = pattern.file_sha256(os.path.join(HERE, path))
        if not mine:
            raise SystemExit(f"{path} has no row in docs/frozen.md: it isn't frozen")
        if mine[-1][2] != digest:
            raise SystemExit(f"{path} (sha256 {digest[:16]}) doesn't match its docs/frozen.md row")
        out[label] = digest
    codes = [r for r in rows if r[0] == CODE_ROW]
    current = code_hash(HERE)
    if codes and codes[-1][1].strip() == "closed":
        raise SystemExit(f"`{CODE_ROW}` is closed: run {RUN} is finished")
    if not codes or codes[-1][2] != current:
        raise SystemExit(f"the governed code hashes to {current[:16]}, which isn't the latest "
                         f"`{CODE_ROW}` row: register it before anything runs under it")
    out["code"] = current
    return out


def load(path):
    with open(path) as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def dump(rows, path):
    with open(path, "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)


# ---------------------------------------------------------------- 1, 2

def propose_model(out, proposals, log=print):
    """A model run's candidates: its batch's rows of the proposals file Colab wrote."""
    with open(proposals, "rb") as fh:
        raw = fh.read()
    rows = [json.loads(ln) for ln in raw.decode().splitlines() if ln.strip()]
    mine = [r for r in rows if r.get("batch") == CFG["model_batch"]]
    if not mine:
        raise SystemExit(f"{proposals} has no rows of batch {CFG['model_batch']}")
    coq = pattern.Coq(notations=False, extra=CFG["extra"])
    try:
        cands, counts = pattern.from_statements(coq, mine, log)
    finally:
        coq.close()
    harvest = {"proposer": CFG["proposer"], "batch": CFG["model_batch"], "entries": len(mine),
               "modules": [], "sha256": hashlib.sha256(raw).hexdigest(), "skipped": counts,
               "prompt_sha256": sorted({r.get("prompt_sha256") for r in mine}),
               "served_model": sorted({r.get("served_model") for r in mine if "failure" not in r})}
    with open(os.path.join(out, "harvest.json"), "w") as fh:
        json.dump(harvest, fh, indent=1)
    dump(cands, os.path.join(out, "proposals.jsonl"))
    return cands, harvest


def propose(out, log=print, proposals=None):
    path = os.path.join(out, "proposals.jsonl")
    if os.path.exists(path):
        return load(path), json.load(open(os.path.join(out, "harvest.json")))
    if CFG.get("model_batch"):
        if not proposals:
            raise SystemExit("a model run needs --proposals: the file tools/pattern_m1.py wrote")
        return propose_model(out, proposals, log)
    coq = pattern.Coq(notations=False, extra=CFG["extra"])
    try:
        entries = pattern.harvest(coq, CFG["sources"])
        eqs = pattern.equations(coq, log=log) if CFG["equations"] else []
        cands, counts = pattern.proposals(coq, entries + eqs, log, relation=CFG["relation"])
    finally:
        coq.close()
    entries = entries + eqs
    text = json.dumps(entries)
    harvest = {"modules": list(CFG["sources"]), "entries": len(entries), "equations": len(eqs),
               "relation": CFG["relation"], "sha256": hashlib.sha256(text.encode()).hexdigest(),
               "skipped": counts, "proposer": CFG["proposer"]}
    with open(os.path.join(out, "harvest-entries.json"), "w") as fh:
        fh.write(text)
    with open(os.path.join(out, "harvest.json"), "w") as fh:
        json.dump(harvest, fh, indent=1)
    dump(cands, path)
    return cands, harvest


def distinct(cands):
    """One row per key, in first-proposed order, with every source listed."""
    rows = {}
    for c in cands:
        r = rows.setdefault(c["key"], dict(c, sources=[], kinds=[]))
        r["sources"].append({"source": c["source"], "substitution": c["substitution"],
                             "kind": c["kind"]})
        if c["kind"] not in r["kinds"]:
            r["kinds"].append(c["kind"])
    return list(rows.values())


def test_all(out, cands, log=print):
    path = os.path.join(out, "tests.jsonl")
    if os.path.exists(path):
        return load(path)
    rows = distinct(cands)
    coq = pattern.Coq(notations=True, deadline=TEST_DEADLINE, extra=CFG["extra"])
    try:
        for i, r in enumerate(rows):
            try:
                pretty = coq.term(r["prefix"])
                r["statement"] = pretty
                r["test"] = {"status": "ill_formed"} if pretty is None else pattern.test(coq, r)
            except CoqTimeout as e:         # past the deadline: the session is gone
                r.setdefault("statement", None)
                r["test"] = {"status": "untestable", "reason": f"timed out: {e}"[:200]}
                coq.close()
                coq = pattern.Coq(notations=True, deadline=TEST_DEADLINE, extra=CFG["extra"])
            if r["statement"] is None and r["test"]["status"] != "ill_formed":
                r["test"] = {"status": "ill_formed", "reason": "timed out elaborating"}
            if i % 25 == 0:
                log(f"tested {i + 1}/{len(rows)}")
    finally:
        coq.close()
    refuted = [r for r in rows if r["test"]["status"] == "refuted"]
    verdicts = pattern.certify_disproofs([pattern.disproof(r, r["test"]) for r in refuted],
                                         extra=CFG["extra"])
    for r, v in zip(refuted, verdicts):
        r["test"]["certified"] = v
    dump(rows, path)
    return rows


# ---------------------------------------------------------------- 3

def to_prove(rows):
    return [r["statement"] for r in rows
            if r["test"]["status"] in ("passed", "untestable")
            or (r["test"]["status"] == "refuted" and r["test"].get("certified") != "accepted")]


def prove(out, stmts, jobs, rounds=ROUNDS, steps=STEPS, log=print):
    from proventhru.explore import explore
    run_dir = os.path.join(out, "run")
    return explore(run_dir, rounds=rounds, per_round=len(stmts), step_budget=steps, jobs=jobs,
                   prover=devgen.isort_tactics(), saturate=True, base=base_preamble(),
                   retry_open=True, statements=stmts, log=log, corpus_forms="all")


def annotate_all(root, line):
    for dirpath, _, files in os.walk(root):
        if "records.jsonl" in files:
            book = rec.RecordLog(os.path.join(dirpath, "records.jsonl"))
            if not any(e.get("kind") == "annotation" and line in (e["data"].get("reason") or "")
                       for e in book.entries):
                book.annotate(0, "note", line, by="tools/pattern_run.py")


# ---------------------------------------------------------------- 4

def gold():
    """[(name, statement, block)] from ISortGold.v: read only to score."""
    text = open(GOLD_FILE).read()
    out = []
    for m in re.finditer(r"^Lemma (\w+) : (.*?)\.\nProof\.(.*?)Qed\.", text, re.M | re.S):
        out.append((m.group(1), m.group(2).strip(),
                    f"Lemma {m.group(1)} : {m.group(2).strip()}.\nProof.{m.group(3)}Qed."))
    if len(out) != 9:
        raise RuntimeError(f"expected 9 gold statements in {GOLD_FILE}, read {len(out)}")
    return out


def keys_of(prefix):
    data, hyps, concl = pattern.specialize(pattern.parse(prefix))
    return {pattern.key(data, hyps, concl), pattern.swapped_key(data, hyps, concl)} - {None}


def one_step_tactics(name, stmt, entry):
    from proventhru.explore import corollary_tactics
    tacs = [f"exact {name}.", f"intros; apply {name}.", f"intros; apply {name}; assumption.",
            f"intros; eapply {name}; eauto.", f"intros; rewrite {name}; reflexivity.",
            f"intros; rewrite <- {name}; reflexivity.", f"intros; rewrite {name}; auto.",
            f"intros; apply {name}; auto."]
    return tacs + list(corollary_tactics(stmt, [entry]))


def follows(pre, stmt, tactics, timeout=2):
    from proventhru.gate import _first_closing
    from proventhru.session import open_session
    try:
        s = open_session(pre, stmt, "coqtop")
    except ValueError as e:
        # a statement that doesn't elaborate there doesn't follow; a preamble
        # that doesn't load is a bug in the check, never a "no"
        if "preamble does not load" in str(e):
            raise RuntimeError(f"the check's preamble doesn't load: {e}") from e
        return None
    try:
        return _first_closing(s, tactics, timeout)
    finally:
        s.close()


def symbols(stmt_prefix):
    data, hyps, concl = pattern.specialize(pattern.parse(stmt_prefix))
    bound = {n for n, _ in data}
    return {s for s in pattern.free(pattern.statement([], hyps, concl)) if s not in bound}


def with_deps(c, corpus):
    """c and the corpus lemmas its proof cites, transitively, in corpus order:
    what a preamble needs for c's own proof to compile."""
    by_name = {x["name"]: x for x in corpus}
    need, todo = set(), [c["name"]]
    while todo:
        n = todo.pop()
        if n not in need:
            need.add(n)
            todo += by_name[n]["cites"]
    return [x for x in corpus if x["name"] in need]


def search(stmts, corpus, out_dir, jobs, steps=STEPS, loaded=None):
    """The loop's two provers on stmts, offered corpus as the only corpus
    lemmas: {statement: (proved, steps, proof)}. loaded is what the preamble
    holds, when it needs more than corpus to compile (the lemmas they cite)."""
    from proventhru.explore import CorpusRetrievalPolicy, preamble
    from proventhru.pipeline import run
    base = devgen.isort_tactics()
    pre = preamble(loaded or corpus, base_preamble())
    half = steps // 2
    run(stmts, os.path.join(out_dir, "fixed"), pre, budget=None, step_budget=half, jobs=jobs,
        log=lambda *_: None, policy_factory=base, backend="coqtop")
    first = rec.corpus(rec.load(os.path.join(out_dir, "fixed", "records.jsonl")))
    res = {r["statement"]: (r["standing"] == "proved", (r["stats"] or {}).get("steps"), r["proof"])
           for r in first}
    left = [s for s in stmts if not res.get(s, (False,))[0]]
    if left:
        run(left, os.path.join(out_dir, "retrieval"), pre, budget=None,
            step_budget=steps - half, jobs=jobs, log=lambda *_: None, backend="coqtop",
            policy_factory=lambda: CorpusRetrievalPolicy(base(), corpus, top=6, saturate=True,
                                                         corpus_forms="all"))
        for r in rec.corpus(rec.load(os.path.join(out_dir, "retrieval", "records.jsonl"))):
            if r["standing"] == "proved":
                res[r["statement"]] = (True, half + ((r["stats"] or {}).get("steps") or 0),
                                       r["proof"])
    return res


def score(out, rows, jobs, rounds=ROUNDS, steps=STEPS, log=print):
    from proventhru.explore import citation_sites, preamble
    path = os.path.join(out, "score.json")
    if os.path.exists(path):
        return json.load(open(path))
    run_dir = os.path.join(out, "run")
    corpus = load(os.path.join(run_dir, "corpus.jsonl"))
    by_stmt = {c["statement"]: c for c in corpus}
    derived = {}
    for k in range(rounds):
        p = os.path.join(run_dir, f"round-{k}", "derived.jsonl")
        if os.path.exists(p):
            derived.update({d["statement"]: d for d in load(p)})
    gate = {}
    for k in range(rounds):
        for part in ("fixed", "retrieval"):
            p = os.path.join(run_dir, f"round-{k}", part, "records.jsonl")
            if os.path.exists(p):
                for r in rec.corpus(rec.load(p)):
                    gate.setdefault(r["statement"], r["gate"])
    golds = gold()
    nocoq = pattern.Coq(notations=False, extra=CFG["extra"])
    try:
        gold_prefix = {n: nocoq.term(s) for n, s, _ in golds}
    finally:
        nocoq.close()
    gold_keys = {n: keys_of(p) for n, p in gold_prefix.items()}
    gold_syms = [symbols(p) - LOGICAL for p in gold_prefix.values()]
    vocab = VOCAB_OWN | set().union(*gold_syms)
    together = {frozenset((a, b)) for s in gold_syms for a in s for b in s if a != b}
    base_pre = base_preamble()

    # per candidate: formalizable, refuted, novel, proved
    for r in rows:
        t, st = r["test"], r["statement"]
        r["formalizable"] = t["status"] != "ill_formed"
        r["refuted_by_test"] = t["status"] == "refuted" and t.get("certified") == "accepted"
        r["gate"] = gate.get(st)
        r["derived"] = derived.get(st, {}).get("stage") if st else None
        r["novel"] = r["formalizable"] and r["gate"] not in ("trivial", "vacuous", "ill_formed") \
            and not r["derived"]
        r["refuted"] = r["refuted_by_test"] or r["gate"] == "refuted"
        r["proved"] = st in by_stmt
        r["gold"] = sorted(n for n, ks in gold_keys.items() if r["key"] in ks)
        if CFG.get("closed_novelty") and r["novel"]:
            # run 3: the development is its definitions, its constructors and its
            # held-out lemmas; what's present in it isn't novel
            r["present_by"] = None
            if r["gold"]:
                r["present_by"] = "gold: " + ", ".join(r["gold"])
            elif not r["refuted"]:
                tac = follows(base_pre, st, CONSTRUCTOR_CLOSERS)
                if tac:
                    r["present_by"] = "one constructor step: " + tac
            r["novel"] = r["present_by"] is None
    proved = [r for r in rows if r["novel"] and r["proved"]]
    compared = {}
    if CFG.get("compare"):
        # what the model proposed that pattern transfer did too, and what it proved that
        # pattern transfer didn't
        old_rows = load(os.path.join(HERE, "results",
                                     f"pattern-run-{CFG['compare']}-candidates.jsonl"))
        compared = {r["prefix"]: r for r in old_rows}
        for r in rows:
            r["in_compared_run"] = r["prefix"] in compared

    # (a) implies a development statement; gold overlap up to derivation
    gold_block = "\n".join(b for _, _, b in golds)
    for r in proved:
        c = by_stmt[r["statement"]]
        pre = preamble(with_deps(c, corpus), base_pre)
        r["implies"], r["equivalent"] = [], []
        for n, s, _ in golds:
            if r["key"] in gold_keys[n]:
                continue
            if follows(pre, s, one_step_tactics(c["name"], s, c)):
                r["implies"].append(n)
                back = follows(base_pre + "\n" + gold_block, r["statement"],
                               one_step_tactics(n, r["statement"], {"name": n, "statement": s}))
                if back:
                    r["equivalent"].append(n)

    # (b) simplifies a development proof: gold searched with C as the only lemma
    sig = os.path.join(out, "significance")
    gold_stmts = [s for _, s, _ in golds]
    baseline = search(gold_stmts, [], os.path.join(sig, "baseline"), jobs, steps)
    for r in proved:
        c = by_stmt[r["statement"]]
        targets = [s for n, s, _ in golds if r["key"] not in gold_keys[n]]
        res = search(targets, [c], os.path.join(sig, c["name"]), jobs, steps,
                     loaded=with_deps(c, corpus))
        r["simplifies"], r["gold_proofs"] = [], {}
        for n, s, _ in golds:
            if s not in res or not res[s][0]:
                continue
            ok, steps, proof = res[s]
            cites = any(x["lemma"] == c["name"] for x in citation_sites(proof, {c["name"]}))
            b_ok, b_steps, _ = baseline.get(s, (False, None, None))
            if cites and (not b_ok or (steps or 0) < (b_steps or 0)):
                r["simplifies"].append(n)
                r["gold_proofs"][n] = proof

    # (c) used in a later proof; inner use
    names = {by_stmt[r["statement"]]["name"]: r for r in proved}
    for r in proved:
        r["used_by"], r["inner"] = [], False
    for c in corpus:
        for x in citation_sites(c["proof"], set(names)):
            if x["lemma"] != c["name"]:
                names[x["lemma"]]["used_by"].append(c["name"])
                names[x["lemma"]]["inner"] |= x["inner"]
    for r in proved:
        name = by_stmt[r["statement"]]["name"]
        for g, proof in r["gold_proofs"].items():
            for x in citation_sites(proof, {name}):
                r["used_by"].append(f"gold:{g}")
                r["inner"] |= x["inner"]

    # (d) connects two of the development's symbols it treats separately
    for r in proved:
        mine = (symbols(r["prefix"]) - LOGICAL) & vocab
        r["connects"] = sorted(sorted(p) for p in {frozenset((a, b)) for a in mine for b in mine
                                                   if a != b and (a in VOCAB_OWN or b in VOCAB_OWN)}
                               - together)
        r["weakening_of"] = []
        if CFG["strict_connects"] and r["connects"]:
            # run 2: a statement another proved conjecture or a gold statement
            # gives in one step is a weakening, and connects nothing new
            for o in proved:
                if o is not r:
                    oc = by_stmt[o["statement"]]
                    if follows(preamble(with_deps(oc, corpus), base_pre), r["statement"],
                               one_step_tactics(oc["name"], r["statement"], oc)):
                        r["weakening_of"].append(oc["name"])
            for n, st, _ in golds:
                if r["key"] not in gold_keys[n] and follows(
                        base_pre + "\n" + gold_block, r["statement"],
                        one_step_tactics(n, r["statement"], {"name": n, "statement": st})):
                    r["weakening_of"].append(f"gold:{n}")
            if r["weakening_of"]:
                r["connects"] = []
        r["significant"] = {"implies": bool(r["implies"]), "simplifies": bool(r["simplifies"]),
                            "used": bool(r["used_by"]), "connects": bool(r["connects"])}

    total = len(rows)
    formal = [r for r in rows if r["formalizable"]]
    novel = [r for r in rows if r["novel"]]
    signif = [r for r in proved if any(r["significant"].values())]

    def rate(a, b):
        return round(a / b, 3) if b else None

    def by(field):
        out_ = defaultdict(Counter)
        for r in rows:
            for k in (r["kinds"] if field == "kind" else [r["test"]["status"]]):
                out_[k]["proposed"] += 1
                out_[k]["formalizable"] += r["formalizable"]
                out_[k]["refuted"] += r["refuted"]
                out_[k]["novel"] += r["novel"]
                out_[k]["proved"] += r["novel"] and r["proved"]
                out_[k]["significant"] += r in signif
        return {k: dict(v) for k, v in out_.items()}

    summary = {
        "proposed": total, "proposed_with_duplicates": sum(len(r["sources"]) for r in rows),
        "formalizable": len(formal), "refuted_by_test": sum(r["refuted_by_test"] for r in rows),
        # elaborated in the test harness, ill_formed at the gate (the prover's preamble)
        "formalizable_disagreements": sorted(r["statement"] for r in formal
                                             if r["gate"] == "ill_formed"),
        "refuted_by_gate": sum(r["gate"] == "refuted" for r in rows),
        "tested": dict(Counter(r["test"]["status"] for r in rows)),
        "tested_vacuously": sum(r["test"].get("premises_held") is False for r in rows),
        "uncertified_refutations": sum(r["test"]["status"] == "refuted"
                                       and r["test"].get("certified") != "accepted" for r in rows),
        "gate": dict(Counter(r["gate"] for r in rows if r["gate"])),
        "derived": dict(Counter(r["derived"] for r in rows if r["derived"])),
        "novel": len(novel), "novel_not_refuted": sum(not r["refuted"] for r in novel),
        "proved_novel": len(proved), "significant": len(signif),
        "present_in_development": sum(bool(r.get("present_by")) for r in rows),
        "gold_proved": sorted({g for r in rows if r["proved"] for g in r["gold"]}),
        "in_compared_run": sum(bool(r.get("in_compared_run")) for r in rows),
        "proved_not_compared": sorted(r["statement"] for r in proved
                                      if not (compared.get(r["prefix"]) or {}).get("proved")),
        "significant_not_gold": sum(not r["gold"] for r in signif),
        "significant_by": {k: sum(r["significant"][k] for r in proved)
                           for k in ("implies", "simplifies", "used", "connects")},
        "rates": {"formalizability": rate(len(formal), total),
                  "novelty": rate(len(novel), len(formal)),
                  "novelty_excluding_refuted": rate(sum(not r["refuted"] for r in novel),
                                                    sum(not r["refuted"] for r in formal)),
                  "provability": rate(len(proved), len(novel)),
                  "provability_excluding_refuted": rate(len(proved),
                                                        sum(not r["refuted"] for r in novel)),
                  "significance": rate(len(signif), len(proved)),
                  "inner_use": rate(sum(r["inner"] for r in proved), len(proved))},
        "gold_overlap": sorted({g for r in novel for g in r["gold"]}),
        "gold_overlap_up_to_derivation": sorted({g for r in proved for g in r["equivalent"]}),
        "necessary_novelty": len(novel),
        "baseline_gold": {s: v[0] for s, v in baseline.items()},
        "by_kind": by("kind"), "by_test": by("test"),
        "loop_seed_lemmas": sorted(c["statement"] for c in corpus
                                   if c["statement"] not in {r["statement"] for r in rows}),
    }
    dump(rows, os.path.join(out, "scored.jsonl"))
    with open(path, "w") as fh:
        json.dump(summary, fh, indent=1)
    return summary


# ---------------------------------------------------------------- 5

def candidates_file(rows, dest):
    keep = ("statement", "prefix", "sources", "kinds", "test", "formalizable", "gate", "derived",
            "novel", "refuted", "proved", "gold", "implies", "equivalent", "simplifies",
            "used_by", "inner", "connects", "significant", "present_by", "weakening_of",
            "why", "in_compared_run")
    dump([{k: r[k] for k in keep if k in r} for r in rows], dest)


def buckets(rows):
    """The residue's buckets: (kind, test outcome, gate status) of the novel,
    unrefuted, unproved candidates."""
    return {(k, r["test"]["status"], r.get("gate")) for r in rows
            if r.get("novel") and not r.get("refuted") and not r.get("proved")
            for k in r["kinds"]}


def stopping(s, rows):
    """Run 3's reading of the stopping rule (docs/pattern-run-3.md): the
    previous run counted under this run's novelty, and the residue's buckets
    against the previous run's."""
    prev = CFG["previous"]
    if prev is None:
        return ["## The stopping rule", "",
                f"- Statements present in the development (a held-out lemma, or one "
                f"constructor step), so not novel here: {s['present_in_development']}. Held-out "
                f"lemmas proved: {', '.join(s['gold_proved']) or 'none'}.",
                f"- Significant novel conjectures: {s['significant']}. This is the first of "
                f"`{CFG['proposer']}`'s two registered runs; the second reads the rule.",
                f"- Proposed by `pattern/analogy-v2` too (run {CFG['compare']}): "
                f"{s.get('in_compared_run', 0)} of {s['proposed']}; proved here and not "
                f"there: {len(s.get('proved_not_compared', []))}.", ""]
    old = load(os.path.join(HERE, "results", f"pattern-run-{prev}-candidates.jsonl"))
    base_pre = base_preamble()
    old_sig = [r for r in old if r.get("novel") and r.get("proved")
               and any((r.get("significant") or {}).values())]
    kept = [r for r in old_sig if not r.get("gold")
            and not follows(base_pre, r["statement"], CONSTRUCTOR_CLOSERS)]
    new_buckets = sorted(buckets(rows) - buckets(old), key=str)
    out = ["## The stopping rule, as docs/pattern-run-3.md reads it", "",
           f"- Statements present in the development (a held-out lemma, or one constructor "
           f"step), so not novel here: {s['present_in_development']}. Held-out lemmas proved: "
           f"{', '.join(s['gold_proved']) or 'none'}.",
           f"- Significant novel conjectures under this run's novelty: run {prev} "
           f"{len(kept)} (of its {len(old_sig)} by its own rules), run {RUN} {s['significant']}.",
           f"- Residue buckets (kind, test, gate) new against run {prev}: "
           f"{', '.join(map(str, new_buckets)) or 'none'}."]
    if not kept and not s["significant"] and not new_buckets:
        out.append(f"- **Two consecutive runs with no significant novel conjecture, and no new "
                   f"residue bucket: by the metrics doc's stopping rule, `{CFG['proposer']}` "
                   f"stops here, and this null is the finding.**")
    out.append("")
    return out


def report(out, summary, rows, reg, harvest, dest):
    proved = [r for r in rows if r["novel"] and r["proved"]]
    L = [f"# Pattern extractor, run {RUN}: results", "",
         f"Run under `{SPEC}` (sha256 `{reg['spec'][:16]}…`), `{METRICS}` v1 "
         f"(`{reg['metrics'][:16]}…`) and the governed code `{CODE_ROW}` (`{reg['code'][:16]}…`).",
         (f"Proposer `{CFG['proposer']}`, batch {harvest['batch']}: {harvest['entries']} "
          f"model rows (proposals file sha256 `{harvest['sha256'][:16]}…`; prompt "
          f"{', '.join(p[:16] + '…' for p in harvest['prompt_sha256'] if p)}; served as "
          f"{', '.join(map(str, harvest['served_model']))}). " if CFG.get("model_batch") else
          f"Proposer `{CFG['proposer']}`; harvest of {harvest['entries']} entries from "
          f"{', '.join(harvest['modules'])}"
          + (f", with {harvest.get('equations', 0)} constructor equations and relation "
             f"variables set to `{harvest.get('relation')}`" if harvest.get("equations") else "")
          + f" (sha256 `{harvest['sha256'][:16]}…`). ")
         +
         "Generated by `tools/pattern_run.py` from the run directory; nothing here is "
         "edited by hand.", "",
         "## The metrics", "",
         "| metric | count | rate |", "|---|---|---|"]
    s, rt = summary, summary["rates"]
    L += [f"| proposed (distinct) | {s['proposed']} | |",
          f"| formalizable | {s['formalizable']} | {rt['formalizability']} |",
          f"| novel | {s['novel']} | {rt['novelty']} |",
          f"| novel, not refuted | {s['novel_not_refuted']} | {rt['novelty_excluding_refuted']} |",
          f"| proved (novel) | {s['proved_novel']} | {rt['provability']} "
          f"({rt['provability_excluding_refuted']} of those not refuted) |",
          f"| **significant** | **{s['significant']}** | {rt['significance']} |",
          f"| significant, not gold | {s['significant_not_gold']} | |",
          f"| inner use | {sum(r['inner'] for r in proved)} | {rt['inner_use']} |",
          f"| necessary novelty | {s['necessary_novelty']} | |", "",
          f"Significant by criterion: {s['significant_by']}.",
          f"Gold overlap (exact): {', '.join(s['gold_overlap']) or 'none'}. "
          f"Up to derivation: {', '.join(s['gold_overlap_up_to_derivation']) or 'none'}.", ""]
    if CFG.get("closed_novelty"):
        L += stopping(s, rows)
    L += ["## Where the candidates went", "",
          f"- Testing: {s['tested']}; refuted and certified {s['refuted_by_test']}; "
          f"uncertified refutations sent on {s['uncertified_refutations']}; tested vacuously "
          f"{s['tested_vacuously']}.",
          f"- The gate, on what was sent to the loop: {s['gate']}. Elaborated in the harness "
          f"but ill_formed at the gate: {len(s['formalizable_disagreements'])}.",
          f"- Derived from the corpus: {s['derived']}.",
          f"- Library entries skipped, by reason: {harvest['skipped']}.",
          f"- Lemmas the loop proved from its own seeds (not the extractor's): "
          f"{len(s['loop_seed_lemmas'])}.", "",
          "## By pattern kind", "", "| kind | proposed | formalizable | refuted | novel | proved "
          "| significant |", "|---|---|---|---|---|---|---|"]
    for k, v in sorted(s["by_kind"].items()):
        L.append(f"| {k} | {v.get('proposed', 0)} | {v.get('formalizable', 0)} | "
                 f"{v.get('refuted', 0)} | {v.get('novel', 0)} | {v.get('proved', 0)} | "
                 f"{v.get('significant', 0)} |")
    L += ["", "## By test outcome", "", "| test | proposed | formalizable | refuted | novel | "
          "proved | significant |", "|---|---|---|---|---|---|---|"]
    for k, v in sorted(s["by_test"].items()):
        L.append(f"| {k} | {v.get('proposed', 0)} | {v.get('formalizable', 0)} | "
                 f"{v.get('refuted', 0)} | {v.get('novel', 0)} | {v.get('proved', 0)} | "
                 f"{v.get('significant', 0)} |")
    open_ = [r for r in rows if r["novel"] and not r["refuted"] and not r["proved"]]
    L += ["", f"## Novel, not refuted, not proved ({len(open_)}): the prover's residue", ""]
    L += [f"- `{r['statement']}` ({', '.join(r['kinds'])}; test {r['test']['status']}; "
          f"gate {r['gate']})" for r in sorted(open_, key=lambda r: r["statement"])]
    L += ["", "## Every proved novel conjecture", ""]
    for r in sorted(proved, key=lambda r: r["statement"]):
        sig = [k for k, v in r["significant"].items() if v]
        L.append(f"- `{r['statement']}`")
        L.append(f"  - from {', '.join(sorted({x['source'] for x in r['sources']}))} "
                 f"({', '.join(r['kinds'])}); gold: {', '.join(r['gold']) or '—'}; "
                 f"significant: {', '.join(sig) or 'no'}")
        if r["implies"]:
            L.append(f"  - implies: {', '.join(r['implies'])}")
        if r["simplifies"]:
            L.append(f"  - simplifies: {', '.join(r['simplifies'])}")
        if r["used_by"]:
            L.append(f"  - used by: {', '.join(r['used_by'])}{' (inner)' if r['inner'] else ''}")
        if r["connects"]:
            L.append(f"  - connects: {', '.join('–'.join(p) for p in r['connects'])}")
        if r.get("weakening_of"):
            L.append(f"  - a weakening of {', '.join(r['weakening_of'])}: (d) doesn't count it")
    L += ["", "## Gold, searched without and with each conjecture", "",
          f"Baseline (the prover on the development's definitions alone): "
          f"{sum(s['baseline_gold'].values())} of {len(s['baseline_gold'])} proved.", "",
          "| gold | baseline | with a conjecture (which) |", "|---|---|---|"]
    for n, st, _ in gold():
        by = sorted(r["statement"] for r in proved if n in r["simplifies"])
        L.append(f"| {n} | {'proved' if s['baseline_gold'].get(st) else '—'} | "
                 f"{'; '.join(f'`{b}`' for b in by) or '—'} |")
    L += ["", "Every candidate, with its test, gate and scores: "
          f"`{os.path.relpath(CANDIDATES, HERE)}`.", ""]
    with open(dest, "w") as fh:
        fh.write("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, default=1, choices=sorted(RUNS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=JOBS)
    ap.add_argument("--proposals", default=None,
                    help="a model run's proposals file (tools/pattern_m1.py's output)")
    ap.add_argument("--smoke", type=int, default=0,
                    help="check the code paths: the first N statements sent to the loop, "
                         "one round at 60 steps, no preflight, the report kept in OUT. Its "
                         "outcomes aren't results")
    a = ap.parse_args(argv)
    configure(a.run)
    rounds, steps = (1, 60) if a.smoke else (ROUNDS, STEPS)
    reg = {"spec": "smoke", "metrics": "smoke", "code": code_hash(HERE)} if a.smoke else preflight()
    os.makedirs(a.out, exist_ok=True)
    cands, harvest = propose(a.out, proposals=a.proposals)
    rows = test_all(a.out, cands)
    stmts = to_prove(rows)
    if a.smoke:
        keep = set(stmts[:a.smoke])
        rows = [r for r in rows if r["statement"] in keep]
        stmts = stmts[:a.smoke]
    print(f"{len(rows)} distinct candidates; {len(stmts)} to the loop", flush=True)
    prove(a.out, stmts, a.jobs, rounds, steps)
    line = (f"pattern run {RUN}{' (smoke)' if a.smoke else ''}: {SPEC} sha256 {reg['spec']}; "
            f"{METRICS} sha256 {reg['metrics']}; governed code sha256 {reg['code']}; "
            f"harvest sha256 {harvest['sha256']}")
    annotate_all(os.path.join(a.out, "run"), line)
    summary = score(a.out, rows, a.jobs, rounds, steps)
    annotate_all(os.path.join(a.out, "significance"), line)
    dest = os.path.join(a.out, "report.md") if a.smoke else \
        os.path.join(HERE, "results", f"pattern-run-{RUN}.md")
    scored = load(os.path.join(a.out, "scored.jsonl"))
    candidates_file(scored, os.path.join(a.out, "candidates.jsonl") if a.smoke else CANDIDATES)
    report(a.out, summary, scored, reg, harvest, dest)
    print(json.dumps({"done": True, "significant": summary["significant"], "report": dest}))


if __name__ == "__main__":
    main()
