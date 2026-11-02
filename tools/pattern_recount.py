"""Runs 4 and 5 recounted under the necessary-premise (d) (docs/pattern-recount-4-5.md).

    python tools/pattern_recount.py --run 4=RUN4_DIR --run 5=RUN5_DIR

(d) as frozen counts a proved novel conjecture that names two of the development's
symbols that no development statement names together, less one-step weakenings. A
premise the conjecture's proof never uses is enough to bring a symbol in. Under the
necessary-premise (d), a symbol that is only in premises counts only if they're needed:
each premise that mentions it is replaced by True, and if the conjecture's own recorded
proof still closes the result, the symbol isn't needed. A pair counts if both its
symbols are needed.

Replacing a premise by True keeps the names of the hypotheses the proof uses, so the
proof runs as recorded. The check compiles, from scratch with coqc, the development's
definitions, the corpus lemmas the proof cites, and the replaced statement with the
proof: a compile is a kernel-checked proof of the statement without those premises.
Nothing is re-proved or re-tested: each run's scored rows and corpus are read from its
recorded directory.
"""
import argparse
import hashlib
import os
import re
import sys

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import pattern_run as PR  # noqa: E402
from proventhru import explore, pattern  # noqa: E402

SPEC, CODE_ROW = "docs/pattern-recount-4-5.md", "code:pattern-recount"
RUNS = (4, 5)
REPORT = os.path.join(HERE, "results", "pattern-recount-4-5.md")
GOVERNED = ["pilots/isort/ISort.v", "proventhru/devgen.py", "proventhru/explore.py",
            "proventhru/pattern.py", "tools/pattern_recount.py", "tools/pattern_run.py"]
TRUE = ("id", "True")


def code_hash(repo, paths=GOVERNED):
    h = hashlib.sha256()
    for p in paths:
        with open(os.path.join(repo, p), "rb") as fh:
            h.update(f"{p} {hashlib.sha256(fh.read()).hexdigest()}\n".encode())
    return h.hexdigest()


def preflight(repo=HERE):
    """The recount runs only under the frozen spec and its open code row."""
    with open(os.path.join(repo, "docs", "frozen.md")) as fh:
        rows = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([0-9a-f]{64})`\s*\|",
                          fh.read(), re.M)
    with open(os.path.join(repo, SPEC), "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    spec = [r for r in rows if r[0] == SPEC]
    if not spec or spec[-1][2] != digest:
        raise SystemExit(f"{SPEC} isn't frozen at its current hash ({digest[:16]})")
    codes = [r for r in rows if r[0] == CODE_ROW]
    current = code_hash(repo)
    if not codes or codes[-1][1].strip() == "closed" or codes[-1][2] != current:
        raise SystemExit(f"the recount's code hashes to {current[:16]}, which isn't the "
                         f"latest open `{CODE_ROW}` row")
    return digest, current


def necessity(r, corpus, base_pre, compile_=explore.compile_corpus):
    """r's (d) pairs under the necessary-premise (d).

    {"control": the statement as recorded, rendered here, compiles with its proof;
     "symbols": {symbol: {"where": "conclusion" | "premises" | "elsewhere",
                          "replaced": the statement with its premises replaced,
                          "needed": bool}};
     "kept": the pairs whose symbols are both needed}.
    Without the control, the check doesn't apply, and the pairs stand as frozen."""
    c = {x["statement"]: x for x in corpus}[r["statement"]]
    deps = [x for x in PR.with_deps(c, corpus) if x["name"] != c["name"]]
    pre = explore.preamble(deps, base_pre)
    data, hyps, concl = pattern.specialize(pattern.parse(r["prefix"]))
    bound = {n for n, _ in data}

    def closes(hs):
        stmt = pattern.render(pattern.statement(data, hs, concl))
        text = pre + "\n" + explore.lemma_text("necessity_check", stmt, c["proof"])
        return compile_(text) == "ok", stmt

    out = {"control": closes(hyps)[0], "symbols": {}, "kept": r["connects"]}
    if not out["control"]:
        return out
    for s in sorted({s for pair in r["connects"] for s in pair}):
        if s in set(pattern.free(concl)) - bound:
            out["symbols"][s] = {"where": "conclusion", "needed": True}
            continue
        idx = {i for i, h in enumerate(hyps) if s in set(pattern.free(h)) - bound}
        if not idx:                     # only in a binder's type: left needed, and shown
            out["symbols"][s] = {"where": "elsewhere", "needed": True}
            continue
        ok, stmt = closes([TRUE if i in idx else h for i, h in enumerate(hyps)])
        out["symbols"][s] = {"where": "premises", "replaced": stmt, "needed": not ok}
    out["kept"] = [p for p in r["connects"] if all(out["symbols"][s]["needed"] for s in p)]
    return out


def recount(run_dir, base_pre, log=print):
    """The run's conjectures significant as frozen, each with its recount."""
    rows = PR.load(os.path.join(run_dir, "scored.jsonl"))
    corpus = PR.load(os.path.join(run_dir, "run", "corpus.jsonl"))
    out = []
    for r in rows:
        sig = r.get("significant") or {}
        if not (r.get("proved") and r.get("novel") and any(sig.values())):
            continue
        nec = necessity(r, corpus, base_pre) if sig.get("connects") else None
        other = any(v for k, v in sig.items() if k != "connects")
        out.append({"statement": r["statement"], "frozen": sig, "connects": r["connects"],
                    "necessity": nec, "significant": other or bool(nec and nec["kept"])})
        log(f"{r['statement']}: {'significant' if out[-1]['significant'] else 'not significant'}")
    return rows, out


def report(results, rows, spec, code):
    pairs = lambda ps: ", ".join("–".join(p) for p in ps) or "none"   # noqa: E731
    counts = {n: sum(r["significant"] for r in results[n]) for n in RUNS}
    new_buckets = sorted(PR.buckets(rows[5]) - PR.buckets(rows[4]), key=str)
    out = ["# Pattern extractor: runs 4 and 5 recounted under the necessary-premise (d)", "",
           f"Run under `{SPEC}` (sha256 `{spec[:16]}…`) and the governed code `{CODE_ROW}` "
           f"(`{code[:16]}…`), from runs 4 and 5's recorded directories (their scored rows "
           "and corpus; nothing re-proved or re-tested). Generated by "
           "`tools/pattern_recount.py`; nothing here is edited by hand.", "",
           "## The recount", "",
           "| run | significant as frozen | significant under the necessary-premise (d) |",
           "|---|---|---|"]
    out += [f"| {n} | {len(results[n])} | {counts[n]} |" for n in RUNS]
    out += ["", "## Each conjecture significant as frozen", ""]
    for n in RUNS:
        for r in results[n]:
            nec = r["necessity"]
            out.append(f"- run {n}: `{r['statement']}`")
            if nec is None:
                out.append("  - significant by (a)–(c), which this recount doesn't change")
                continue
            control = "yes" if nec["control"] else "no, so the pairs stand as frozen"
            out.append(f"  - Pairs as frozen: {pairs(r['connects'])}. Control (the statement "
                       f"as recorded compiles with its proof): {control}.")
            for s, v in nec["symbols"].items():
                if v["where"] == "premises":
                    verdict = ("still closes it, so it isn't needed" if not v["needed"]
                               else "no longer closes it, so it's needed")
                    out.append(f"  - `{s}` is only in premises. Replaced by True: "
                               f"`{v['replaced']}`. The recorded proof {verdict}.")
                else:
                    out.append(f"  - `{s}` is in the {v['where']}: needed.")
            out.append(f"  - Pairs kept: {pairs(nec['kept'])}. Significant: "
                       f"{'yes' if r['significant'] else 'no'}.")
    out += ["", "## What it means, as the spec registered it", "",
            f"- Residue buckets (kind, test, gate) new in run 5 against run 4: "
            f"{', '.join(map(str, new_buckets)) or 'none'}."]
    if any(counts.values()):
        out.append("- **At least one run keeps a significant conjecture, so the signal stands, "
                   "and the registered next step is unchanged: expand the signature.**")
    elif new_buckets:
        out.append("- **Both runs recount to 0, so the signal registered in runs 4 and 5 "
                   "doesn't stand. Run 5's residue has a new bucket, so the metrics doc's "
                   "stopping rule doesn't stop the proposer either. The next step is the "
                   "owner's: a third batch (run 6) scored under this (d), or stopping the "
                   "proposer by decision.**")
    else:
        out.append("- **Both runs recount to 0, and run 5's residue has no new bucket: by the "
                   "metrics doc's stopping rule, `pattern/model-m1-v1` stops, and this null is "
                   "the finding.**")
    out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="N=DIR, for runs 4 and 5")
    ap.add_argument("--report", default=REPORT)
    a = ap.parse_args(argv)
    dirs = {int(k): v for k, v in (x.split("=", 1) for x in a.run)}
    if set(dirs) != set(RUNS):
        raise SystemExit(f"the recount is of runs {RUNS}, both")
    spec, code = preflight()
    PR.configure(4)                     # runs 4 and 5 share their preamble (Sorted first)
    base_pre = PR.base_preamble()
    rows, results = {}, {}
    for n in RUNS:
        rows[n], results[n] = recount(dirs[n], base_pre)
    with open(a.report, "w") as fh:
        fh.write(report(results, rows, spec, code))
    print({n: sum(r["significant"] for r in results[n]) for n in RUNS}, a.report)


if __name__ == "__main__":
    main()
