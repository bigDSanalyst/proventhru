"""Drive RSI target 1 (docs/rsi-target1-ranker.md): fit, run, report.

    python tools/ranker_iterate.py fit --rows D0.jsonl [D1.jsonl ...] --out results/ranker/R1.json
    python tools/ranker_iterate.py run --set examples/ranker_H.txt --out RUN_DIR \
        [--ranker R.json] [--slots ranked|placebo|interleave] [--retrieval-version 1|2] \
        [--fixed-only] [--jobs 3]
    python tools/ranker_iterate.py report --runs ref=DIR 0a=DIR ... --set examples/ranker_H.txt \
        --models 1=R1.json ... --training T1 T2 --rows D0.jsonl ... --out results/rsi-target1.md

`run` is B' (PROTOCOL.md v5's condition B on retrieval/v2: fixed-tactics/v1,
6 slots, 600 steps, expansions unbounded, coqtop), with a slot rule when
one is given; --retrieval-version 1 is B as registered, --fixed-only is A.
`report` applies the reading rules the pre-registration fixes."""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru.cli import _statements  # noqa: E402
from proventhru.keys import twin_key  # noqa: E402
from proventhru.ranker import Ranker  # noqa: E402
from proventhru.retrieval import terms  # noqa: E402

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FORBIDDEN = ["examples/ranker_H.txt", "examples/ranker_rest.txt", "examples/eval_test.txt",
             "examples/eval_test_renamed.txt"]
ALPHA = 0.05


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --- fit -------------------------------------------------------------------

def cmd_fit(a):
    forbidden = set()
    for p in a.forbid:
        forbidden |= {twin_key(s) for s in _statements(os.path.join(HERE, p))[1]}
    rows, sources, refused = [], [], 0
    for p in a.rows:
        with open(p) as fh:
            for ln in fh:
                if not ln.strip():
                    continue
                r = json.loads(ln)
                if twin_key(r["statement"]) in forbidden:
                    refused += 1
                    continue
                rows.append(r)
        sources.append({"path": os.path.relpath(os.path.abspath(p), HERE), "sha256": sha256_file(p)})
    r = Ranker.train(rows, sources)
    r.model["refused_rows"] = refused
    r.model["forbidden_sets"] = a.forbid
    r.dump(a.out)
    m = r.model
    print(json.dumps({"out": a.out, "sha256": r.sha256, "rows": m["rows"], "refused": refused,
                      "positives": m["positives"], "iterations": m["iterations"],
                      "gradient_norm": m["gradient_norm"],
                      "weights": dict(zip(m["features"], [round(w, 3) for w in m["weights"]]))}))


# --- run -------------------------------------------------------------------

def cmd_run(a):
    argv = [sys.executable, "-m", "proventhru.cli", "--backend", "coqtop", "run", a.set,
            "--out", a.out, "--policy", "fixed", "--budget", "0", "--step-budget", "600",
            "--jobs", str(a.jobs)]
    if not a.fixed_only:
        argv += ["--retrieval", "6", "--retrieval-version", str(a.retrieval_version)]
        if a.ranker:
            argv += ["--ranker", a.ranker]
        if a.slots:
            argv += ["--slots", a.slots]
    print(" ".join(argv), flush=True)
    return subprocess.call(argv, cwd=HERE)


# --- reading records --------------------------------------------------------

class Run:
    """A run's record, by statement: outcome, gate status, its proof's
    nodes, and per-expansion costs."""

    def __init__(self, run_dir):
        self.dir = run_dir
        self.by_stmt = {}
        ep_stmt, ep = {}, {}
        props = defaultdict(list)
        with open(os.path.join(run_dir, "records.jsonl")) as fh:
            for ln in fh:
                r = json.loads(ln)
                d = r["data"]
                if r["kind"] == "episode":
                    ep_stmt[d["episode"]] = d["statement"]
                    ep[d["episode"]] = {"policy": d["policy"]["id"],
                                        "gate": (d.get("gate") or {}).get("status"),
                                        "preamble_sha256": d.get("preamble_sha256")}
                elif r["kind"] == "proposal":
                    props[d["episode"]].append(d)
                elif r["kind"] == "outcome":
                    e = d["episode"]
                    s = ep_stmt.get(e)
                    if s is None:
                        continue
                    ps = props.get(e, [])
                    self.by_stmt[s] = dict(ep[e], episode=e,
                                           proved=d.get("kernel") == "accepted",
                                           proof=d.get("proof") or [],
                                           steps=(d.get("stats") or {}).get("steps"),
                                           expansions=len(ps),
                                           lemma_tactics=sum(len((p.get("cost") or {}).get("added") or [])
                                                             for p in ps),
                                           props={tuple(p["path"]): p for p in ps})

    def proved(self, s):
        return bool(self.by_stmt.get(s, {}).get("proved"))

    def gate_open(self, s):
        return self.by_stmt.get(s, {}).get("gate") == "open"

    def lemma_nodes(self, s):
        """[(depth, lemma, position in B's list or None, offered record)] for
        each node of s's proof whose tactic is a form of an offered library
        lemma."""
        o = self.by_stmt.get(s)
        if not o or not o["proved"]:
            return []
        out = []
        for i, tac in enumerate(o["proof"]):
            p = o["props"].get(tuple(o["proof"][:i]))
            if not p:
                continue
            cost = p.get("cost") or {}
            offered = {x["name"]: x for x in (cost.get("ranker") or {}).get("offered") or []}
            for k, name in enumerate(cost.get("lemmas") or []):
                if tac in (f"rewrite {name}.", f"rewrite <- {name}.", f"apply {name}."):
                    rec = offered.get(name)
                    pos = rec["position"] if rec else k     # plain B: its own order
                    out.append((i, name, pos, rec))
        return out


# --- statistics -------------------------------------------------------------

def binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def mcnemar(g, l):
    """Exact two-sided McNemar p for g and l discordant pairs."""
    n = g + l
    if n == 0:
        return 1.0
    return min(1.0, 2 * binom_cdf(min(g, l), n, 0.5))


def clopper_pearson(k, n, conf=0.95):
    if n == 0:
        return 0.0, 1.0
    a = (1 - conf) / 2

    def solve(f):
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if f(mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lower = 0.0 if k == 0 else solve(lambda p: 1 - binom_cdf(k - 1, n, p) < a)
    upper = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p) > a)
    return lower, upper


def net_interval(g, l):
    """95% interval for G - L: Clopper-Pearson on G of G + L, scaled."""
    n = g + l
    lo, hi = clopper_pearson(g, n)
    return (2 * lo - 1) * n, (2 * hi - 1) * n


def sign_test(diffs):
    pos = sum(d > 0 for d in diffs)
    neg = sum(d < 0 for d in diffs)
    return pos, neg, mcnemar(pos, neg)


# --- report -----------------------------------------------------------------

def compare(runs, stmts, x, y):
    """y against x on the statements both gated open."""
    rx, ry = runs[x], runs[y]
    both = [s for s in stmts if rx.gate_open(s) and ry.gate_open(s)]
    gained = [s for s in both if ry.proved(s) and not rx.proved(s)]
    lost = [s for s in both if rx.proved(s) and not ry.proved(s)]
    g, l = len(gained), len(lost)
    lo, hi = net_interval(g, l)
    return {"x": x, "y": y, "n": len(both), "dropped": len(stmts) - len(both),
            "gained": gained, "lost": lost, "G": g, "L": l, "p": mcnemar(g, l),
            "interval": (lo, hi)}


def class_a(run, s):
    """A gained statement is class (a) if its proof uses, at some node, a
    library lemma outside B's top 6 there."""
    return any(pos is not None and pos >= 6 for _, _, pos, _ in run.lemma_nodes(s))


def body_terms(statement):
    st = " ".join(statement.split())
    m = re.match(r"forall\s+(.*?),\s*(.*)$", st)
    if not m:
        return frozenset(terms(st))
    hyps = [f"{v} : x" for g in re.findall(r"\(([^():]+):", m.group(1)) for v in g.split()]
    return frozenset(terms(m.group(2), hyps))


def fmt_cmp(c, tested=None):
    lo, hi = c["interval"]
    tag = "" if tested is None else tested
    return (f"| {c['y']} vs {c['x']} | {c['n']} | {c['G']} | {c['L']} | {c['G'] - c['L']:+d} | "
            f"[{lo:+.1f}, {hi:+.1f}] | {c['p']:.4g} | {tag} |")


def cmd_report(a):
    _, stmts = _statements(a.set)
    runs = {k: Run(v) for k, v in (x.split("=", 1) for x in a.runs)}
    L = [f"# RSI target 1: results on {os.path.relpath(os.path.abspath(a.set), HERE)}", "",
         "Generated by `tools/ranker_iterate.py report` from the run records named below.", ""]

    # runs
    L += ["## Runs", "", "| run | policy | proved | gate-open | expansions/stmt | lemma tactics/expansion | record |",
          "|---|---|---|---|---|---|---|"]
    for k, r in runs.items():
        o = r.by_stmt.values()
        pol = ", ".join(sorted({v["policy"] for v in o}))
        ex = sum(v["expansions"] for v in o)
        lt = sum(v["lemma_tactics"] for v in o)
        L.append(f"| {k} | `{pol}` | {sum(v['proved'] for v in o)} | {sum(v['gate'] == 'open' for v in o)} "
                 f"of {len(stmts)} | {ex / max(len(o), 1):.1f} | {lt / max(ex, 1):.2f} | `{r.dir}` |")
    pre = {v["preamble_sha256"] for r in runs.values() for v in r.by_stmt.values()}
    L += ["", f"Preamble hashes across all episodes: {sorted(pre)}."]

    # determinism
    if "0a" in runs and "0b" in runs:
        diff = [s for s in stmts if runs["0a"].by_stmt.get(s, {}).get("proof") !=
                runs["0b"].by_stmt.get(s, {}).get("proof")]
        L += ["", f"**Determinism (0b against 0a):** {len(diff)} statements differ in outcome or proof."]

    # primary sequence
    seq = [("0a", "3"), ("1", "3"), ("0a", "1")]
    L += ["", "## Primary: the fixed test sequence", "",
          "Exact two-sided McNemar at α = 0.05, in order, stopping at the first test not rejected.", "",
          "| comparison | n | G | L | G − L | 95% interval | p | |", "|---|---|---|---|---|---|---|---|"]
    results, stopped = {}, False
    for x, y in seq:
        if x not in runs or y not in runs:
            L.append(f"| {y} vs {x} | – | – | – | – | – | – | not run |")
            stopped = True
            continue
        c = compare(runs, stmts, x, y)
        results[(x, y)] = c
        if stopped:
            L.append(fmt_cmp(c, "not reached (descriptive)"))
            continue
        rej = c["p"] < ALPHA
        L.append(fmt_cmp(c, "rejected" if rej else "not rejected"))
        c["rejected"] = rej
        if not rej:
            stopped = True
    t1 = results.get(("0a", "3"), {})
    t2 = results.get(("1", "3"), {})

    # descriptive
    desc = [("1", "2"), ("2", "3"), ("2p", "2"), ("3p", "3"), ("2p", "1"), ("0a", "P0"),
            ("0a", "ref"), ("0a", "v1")]
    L += ["", "## Descriptive comparisons (unadjusted)", "",
          "| comparison | n | G | L | G − L | 95% interval | p | |", "|---|---|---|---|---|---|---|---|"]
    dres = {}
    for x, y in desc:
        if x in runs and y in runs:
            dres[(x, y)] = compare(runs, stmts, x, y)
            L.append(fmt_cmp(dres[(x, y)], "descriptive"))

    # plateau
    if ("0a", "P0") in dres:
        theta = max(4, 1 + dres[("0a", "P0")]["G"])
        chain = [("0a", "1"), ("1", "2"), ("2", "3")]
        plateau = None
        for x, y in chain:
            c = results.get((x, y)) or dres.get((x, y))
            if c is None and x in runs and y in runs:
                c = compare(runs, stmts, x, y)
            if c is not None and c["G"] - c["L"] < theta:
                plateau = y
                break
        L += ["", f"**Plateau (named after the fact):** θ = max(4, 1 + {dres[('0a', 'P0')]['G']}) = {theta}. "
              f"First iteration whose net gain over the previous is below θ: {plateau or 'none'}."]

    # interleaved recall
    rec_lines, recall_ok, recall_better = [], False, None
    if "X" in runs:
        X = runs["X"]
        per = defaultdict(list)
        for s, o in X.by_stmt.items():
            for depth, name, pos, rec in X.lemma_nodes(s):
                if rec is None:
                    continue
                per[s].append((float(rec["in_b6"]), float(rec["in_r6"]),
                               1 / (rec["position"] + 1), 1 / (rec["r_rank"] + 1), name))
        nodes = sum(len(v) for v in per.values())
        if nodes >= 20:
            recall_ok = True
            d_rec = [sum(r for _, r, _, _, _ in v) / len(v) - sum(b for b, _, _, _, _ in v) / len(v)
                     for v in per.values()]
            d_mrr = [sum(r for _, _, _, r, _ in v) / len(v) - sum(b for _, _, b, _, _ in v) / len(v)
                     for v in per.values()]
            pr, nr, pp = sign_test(d_rec)
            pm, nm, pmrr = sign_test(d_mrr)
            recall_better = pr > nr and pp < ALPHA
            r3 = runs.get("3")
            missed = [s for s, v in per.items()
                      if all(rr for _, rr, _, _, _ in v) and r3 is not None and not r3.proved(s)]
            b_rec = sum(b for v in per.values() for b, *_ in v) / nodes
            r_rec = sum(r for v in per.values() for _, r, *_ in v) / nodes
            rec_lines += [f"Reference nodes: {nodes}, over {len(per)} statements.",
                          f"Recall@6: B′ {b_rec:.3f}, R3 {r_rec:.3f}. By statement, R3 higher in {pr}, "
                          f"lower in {nr}: sign test p = {pp:.4g}.",
                          f"MRR by statement: R3 higher in {pm}, lower in {nm}: p = {pmrr:.4g}.",
                          f"Reference statements where R3's top 6 held every reference lemma and "
                          f"iteration 3 didn't prove the statement: {len(missed)}."]
        else:
            rec_lines.append(f"Reference nodes: {nodes} (< 20): recall not measured.")
    L += ["", "## Interleaved run: recall@6 and MRR", ""] + (rec_lines or ["Not run."])

    # class (a)/(b) and the reading
    reading = "(v) No conclusion about ranking"
    share_a = None
    if t1:
        G, Lo = t1["G"], t1["L"]
        n_a = sum(class_a(runs["3"], s) for s in t1["gained"])
        share_a = n_a / G if G else 0.0
        if t1.get("rejected") and G > Lo:
            reading = ("(i) Ranking is a limit" if share_a >= 0.5 else "(ii) A gain, not from ranking")
        elif t1.get("rejected") and Lo > G:
            reading = "(iii) The learned ranker is harmful"
        elif not t1.get("rejected") and recall_ok and recall_better:
            reading = (f"(iv) Ranking gains are bounded: at most {t1['interval'][1]:+.1f} more proofs "
                       f"at the reference nodes")
    L += ["", "## Reading (first row that applies)", "",
          f"**{reading}.**" + (f" Class (a) share of 3's gains over 0a: {share_a:.2f}." if share_a is not None else "")]
    if t1:
        if t1.get("rejected") and t1["G"] > t1["L"] and t2.get("rejected") and t2["G"] > t2["L"]:
            c2, c3 = dres.get(("2p", "2")), dres.get(("3p", "3"))
            ahead = (c2 and c2["G"] - c2["L"] > 0) and (c3 and c3["G"] - c3["L"] > 0)
            si = "Self-improving loop" if ahead else "More of the system's own data helps"
        elif t1.get("rejected") and t1["G"] > t1["L"]:
            si = "One-shot gain"
        else:
            si = "No gain to read as self-improvement"
        L.append(f"**Self-improvement reading:** {si}.")
    L += ["", "Scope: about the fixed tactics and H's population (almost all inequalities). Nothing here "
          "says whether ranking limits B on equations, or M1 inside D."]

    # by relation
    L += ["", "## By relation (descriptive)", "", "| run | = proved | <= proved |", "|---|---|---|"]
    for k, r in runs.items():
        eq = sum(r.proved(s) for s in stmts if " = " in s.split(", ", 1)[-1])
        le = sum(r.proved(s) for s in stmts if " = " not in s.split(", ", 1)[-1])
        L.append(f"| {k} | {eq} | {le} |")

    # slots from outside B's top 6, per ranked run
    L += ["", "## Slots filled from outside B′'s top 6", "", "| run | slots | outside top 6 | share |",
          "|---|---|---|---|"]
    for k, r in runs.items():
        tot = out6 = 0
        for o in r.by_stmt.values():
            for p in o["props"].values():
                for x in ((p.get("cost") or {}).get("ranker") or {}).get("offered") or []:
                    tot += 1
                    out6 += x["position"] >= 6
        if tot:
            L.append(f"| {k} | {tot} | {out6} | {out6 / tot:.3f} |")

    # weights
    if a.models:
        L += ["", "## Fitted rankers", ""]
        for k, p in (x.split("=", 1) for x in a.models):
            m = json.load(open(p))
            w = ", ".join(f"{f} {v:+.3f}" for f, v in zip(m["features"], m["weights"]))
            L.append(f"- **R{k}** (`{os.path.relpath(os.path.abspath(p), HERE)}`, sha256 "
                     f"{sha256_file(p)[:16]}): {m['rows']} rows, {m['positives']} positive, "
                     f"{m.get('refused_rows', 0)} refused; Newton {m['iterations']} iterations. {w}.")

    # contamination
    if a.training and "3" in runs and "0a" in runs:
        train = set()
        for p in a.training:
            train |= {body_terms(s) for s in _statements(os.path.join(HERE, p))[1]}
        for p in a.rows:
            with open(p) as fh:
                train |= {body_terms(json.loads(ln)["statement"]) for ln in fh if ln.strip()}
        c = results.get(("0a", "3")) or compare(runs, stmts, "0a", "3")
        same = {s for s in stmts if body_terms(s) in train}
        L += ["", "## Contamination (fixed against the training statements)", "",
              f"H statements whose root term set equals a training statement's: {len(same)} of {len(stmts)}.",
              f"3 vs 0a gains among them: {len([s for s in c['gained'] if s in same])}; losses: "
              f"{len([s for s in c['lost'] if s in same])}. Among the rest: gains "
              f"{len([s for s in c['gained'] if s not in same])}, losses {len([s for s in c['lost'] if s not in same])}."]

    # extraction stats
    if a.stats:
        L += ["", "## Extraction, per D", ""]
        for p in a.stats:
            st = json.load(open(p))
            L.append(f"- `{os.path.relpath(os.path.abspath(p), HERE)}`: {st['episodes']} episodes, {st['rows']} rows, "
                     f"{st['positives']} positive; dropped {st['dropped']}.")

    # gate flips
    flips = {k: [s for s in stmts if not r.gate_open(s)] for k, r in runs.items()}
    L += ["", "## In-run gate", "", "Statements the in-run gate didn't classify open, dropped from every "
          "comparison involving that run: " + (", ".join(f"{k}: {len(v)}" for k, v in flips.items() if v) or "none") + "."]

    # per statement
    L += ["", "## Per statement", ""]
    tables = [("0a", "1"), ("1", "2"), ("2", "3"), ("0a", "3")]
    for x, y in tables:
        if x not in runs or y not in runs:
            continue
        c = results.get((x, y)) or dres.get((x, y)) or compare(runs, stmts, x, y)
        L.append(f"### {y} vs {x}: gained {c['G']}, lost {c['L']}")
        for tag, ss, src in (("gained", c["gained"], y), ("lost", c["lost"], x)):
            for s in ss:
                r = runs[src]
                lem = ", ".join(f"{n} (B′ position {p})" for _, n, p, _ in r.lemma_nodes(s)) or "none"
                cls = (" class (a)" if class_a(r, s) else " class (b)") if tag == "gained" else ""
                L.append(f"- {tag}{cls}: `{s}`")
                L.append(f"  - proof under {src}: `{' '.join(r.by_stmt[s]['proof'])}`; library lemmas: {lem}")
        L.append("")

    with open(a.out, "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L[:60]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--rows", nargs="+", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--forbid", nargs="*", default=FORBIDDEN,
                   help="set files whose statements' twins may not be trained on")
    r = sub.add_parser("run")
    r.add_argument("--set", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--ranker", default=None)
    r.add_argument("--slots", choices=["ranked", "placebo", "interleave"], default=None)
    r.add_argument("--retrieval-version", type=int, choices=[1, 2], default=2)
    r.add_argument("--fixed-only", action="store_true")
    r.add_argument("--jobs", type=int, default=3)
    p = sub.add_parser("report")
    p.add_argument("--runs", nargs="+", required=True,
                   help="label=RUN_DIR; labels ref, v1, 0a, 0b, P0, 1, 2, 3, 2p, 3p, X")
    p.add_argument("--set", required=True)
    p.add_argument("--models", nargs="*", default=[], help="k=R.json")
    p.add_argument("--training", nargs="*", default=[], help="training set files (T1, T2)")
    p.add_argument("--rows", nargs="*", default=[], help="D files, for the contamination split")
    p.add_argument("--stats", nargs="*", default=[], help="D stats files")
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return {"fit": cmd_fit, "run": cmd_run, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main() or 0)
