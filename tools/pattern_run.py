"""Pattern extractor run 1, end to end, as docs/pattern-run-1.md fixes it.

    python tools/pattern_run.py --out OUT [--jobs 3]

Each step resumes from its output in OUT:
  1. propose  harvest.json, proposals.jsonl: every library theorem of List and
              Permutation carried over to the isort development (pattern.py)
  2. test     tests.jsonl: each distinct candidate elaborated and decided in
              Coq on its falsifier space; refutations certified by the kernel
  3. prove    run/: the loop (isort pilot 2b-ii settings) on what passed, what
              couldn't be tested, and refutations that didn't certify
  4. score    significance/ (the (b) searches), score.json
  5. report   results/pattern-run-1.md

Before anything runs, it refuses unless docs/pattern-run-1.md and the governed
code (GOVERNED) match their docs/frozen.md rows, and docs/pattern-metrics.md
matches its own. Every record the run writes is annotated with those hashes
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

SPEC, METRICS, CODE_ROW = "docs/pattern-run-1.md", "docs/pattern-metrics.md", "code:pattern-run-1"
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
CANDIDATES = os.path.join(HERE, "results", "pattern-run-1-candidates.jsonl")
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

def propose(out, log=print):
    path = os.path.join(out, "proposals.jsonl")
    if os.path.exists(path):
        return load(path), json.load(open(os.path.join(out, "harvest.json")))
    coq = pattern.Coq(notations=False)
    try:
        entries = pattern.harvest(coq)
        cands, counts = pattern.proposals(coq, entries, log)
    finally:
        coq.close()
    text = json.dumps(entries)
    harvest = {"modules": list(pattern.SOURCES), "entries": len(entries),
               "sha256": hashlib.sha256(text.encode()).hexdigest(),
               "skipped": counts, "proposer": pattern.PROPOSER}
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
    coq = pattern.Coq(notations=True, deadline=TEST_DEADLINE)
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
                coq = pattern.Coq(notations=True, deadline=TEST_DEADLINE)
            if r["statement"] is None and r["test"]["status"] != "ill_formed":
                r["test"] = {"status": "ill_formed", "reason": "timed out elaborating"}
            if i % 25 == 0:
                log(f"tested {i + 1}/{len(rows)}")
    finally:
        coq.close()
    refuted = [r for r in rows if r["test"]["status"] == "refuted"]
    verdicts = pattern.certify_disproofs([pattern.disproof(r, r["test"]) for r in refuted])
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
                   prover=devgen.isort_tactics(), saturate=True, base=devgen.preamble(),
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
    except Exception:           # doesn't elaborate there, or the preamble doesn't load
        return None
    try:
        return _first_closing(s, tactics, timeout)
    finally:
        s.close()


def symbols(stmt_prefix):
    data, hyps, concl = pattern.specialize(pattern.parse(stmt_prefix))
    bound = {n for n, _ in data}
    return {s for s in pattern.free(pattern.statement([], hyps, concl)) if s not in bound}


def search(stmts, corpus, out_dir, jobs, steps=STEPS):
    """The loop's two provers on stmts, with corpus as the only corpus lemmas:
    {statement: (proved, steps, proof)}."""
    from proventhru.explore import CorpusRetrievalPolicy, preamble
    from proventhru.pipeline import run
    base = devgen.isort_tactics()
    pre = preamble(corpus, devgen.preamble())
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
    nocoq = pattern.Coq(notations=False)
    try:
        gold_prefix = {n: nocoq.term(s) for n, s, _ in golds}
    finally:
        nocoq.close()
    gold_keys = {n: keys_of(p) for n, p in gold_prefix.items()}
    gold_syms = [symbols(p) - LOGICAL for p in gold_prefix.values()]
    vocab = VOCAB_OWN | set().union(*gold_syms)
    together = {frozenset((a, b)) for s in gold_syms for a in s for b in s if a != b}
    base_pre = devgen.preamble()

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
    proved = [r for r in rows if r["novel"] and r["proved"]]

    # (a) implies a development statement; gold overlap up to derivation
    gold_block = "\n".join(b for _, _, b in golds)
    for r in proved:
        c = by_stmt[r["statement"]]
        pre = preamble([c], base_pre)
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
        res = search(targets, [c], os.path.join(sig, c["name"]), jobs, steps)
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
            "used_by", "inner", "connects", "significant")
    dump([{k: r[k] for k in keep if k in r} for r in rows], dest)


def report(out, summary, rows, reg, harvest, dest):
    proved = [r for r in rows if r["novel"] and r["proved"]]
    L = ["# Pattern extractor, run 1: results", "",
         f"Run under `{SPEC}` (sha256 `{reg['spec'][:16]}…`), `{METRICS}` v1 "
         f"(`{reg['metrics'][:16]}…`) and the governed code `{CODE_ROW}` (`{reg['code'][:16]}…`).",
         f"Proposer `{pattern.PROPOSER}`; harvest of {harvest['entries']} entries from "
         f"{', '.join(harvest['modules'])} (sha256 `{harvest['sha256'][:16]}…`). "
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
          f"| inner use | {sum(r['inner'] for r in proved)} | {rt['inner_use']} |",
          f"| necessary novelty | {s['necessary_novelty']} | |", "",
          f"Significant by criterion: {s['significant_by']}.",
          f"Gold overlap (exact): {', '.join(s['gold_overlap']) or 'none'}. "
          f"Up to derivation: {', '.join(s['gold_overlap_up_to_derivation']) or 'none'}.", "",
          "## Where the candidates went", "",
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
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=JOBS)
    ap.add_argument("--smoke", type=int, default=0,
                    help="check the code paths: the first N statements sent to the loop, "
                         "one round at 60 steps, no preflight, the report kept in OUT. Its "
                         "outcomes aren't results")
    a = ap.parse_args(argv)
    rounds, steps = (1, 60) if a.smoke else (ROUNDS, STEPS)
    reg = {"spec": "smoke", "metrics": "smoke", "code": code_hash(HERE)} if a.smoke else preflight()
    os.makedirs(a.out, exist_ok=True)
    cands, harvest = propose(a.out)
    rows = test_all(a.out, cands)
    stmts = to_prove(rows)
    if a.smoke:
        keep = set(stmts[:a.smoke])
        rows = [r for r in rows if r["statement"] in keep]
        stmts = stmts[:a.smoke]
    print(f"{len(rows)} distinct candidates; {len(stmts)} to the loop", flush=True)
    prove(a.out, stmts, a.jobs, rounds, steps)
    line = (f"pattern run 1{' (smoke)' if a.smoke else ''}: {SPEC} sha256 {reg['spec']}; "
            f"{METRICS} sha256 {reg['metrics']}; governed code sha256 {reg['code']}; "
            f"harvest sha256 {harvest['sha256']}")
    annotate_all(os.path.join(a.out, "run"), line)
    summary = score(a.out, rows, a.jobs, rounds, steps)
    annotate_all(os.path.join(a.out, "significance"), line)
    dest = os.path.join(a.out, "report.md") if a.smoke else \
        os.path.join(HERE, "results", "pattern-run-1.md")
    scored = load(os.path.join(a.out, "scored.jsonl"))
    candidates_file(scored, os.path.join(a.out, "candidates.jsonl") if a.smoke else CANDIDATES)
    report(a.out, summary, scored, reg, harvest, dest)
    print(json.dumps({"done": True, "significant": summary["significant"], "report": dest}))


if __name__ == "__main__":
    main()
