"""Drive RSI target 1 (docs/rsi-target1-ranker.md): fit, run, report.

    python tools/ranker_iterate.py fit --rows D0.jsonl [D1.jsonl ...] --out results/ranker/R1.json
    python tools/ranker_iterate.py run --set examples/ranker_H.txt --out RUN_DIR \
        [--ranker results/ranker/R1.json] [--fixed-only] [--jobs 3]
    python tools/ranker_iterate.py report --runs ref=DIR 0a=DIR 0b=DIR 1=DIR ... \
        --set examples/ranker_H.txt --out results/rsi-target1.md

`run` is condition B as registered in PROTOCOL.md v5 (fixed-tactics/v1 plus
retrieval's 6 slots, 600 steps, expansions unbounded, coqtop), with the
ranker choosing the slots when one is given; --fixed-only is condition A.
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru.cli import _statements  # noqa: E402
from proventhru.ranker import Ranker  # noqa: E402

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def cmd_fit(a):
    rows, sources = [], []
    for p in a.rows:
        with open(p) as fh:
            rows += [json.loads(ln) for ln in fh if ln.strip()]
        sources.append({"path": os.path.relpath(p, HERE), "sha256": sha256_file(p)})
    r = Ranker.train(rows, sources)
    r.dump(a.out)
    m = r.model
    print(json.dumps({"out": a.out, "sha256": r.sha256, "rows": m["rows"],
                      "positives": m["positives"], "iterations": m["iterations"],
                      "gradient_norm": m["gradient_norm"],
                      "weights": dict(zip(m["features"], [round(w, 3) for w in m["weights"]]))}))


def cmd_run(a):
    argv = [sys.executable, "-m", "proventhru.cli", "--backend", "coqtop", "run", a.set,
            "--out", a.out, "--policy", "fixed", "--budget", "0", "--step-budget", "600",
            "--jobs", str(a.jobs)]
    if not a.fixed_only:
        argv += ["--retrieval", "6"]
        if a.ranker:
            argv += ["--ranker", a.ranker]
    print(" ".join(argv), flush=True)
    return subprocess.call(argv, cwd=HERE)


def outcomes(run_dir):
    """{statement: (proved, proof, steps, episode policy id)} from a run's record."""
    out = {}
    path = os.path.join(run_dir, "records.jsonl")
    ep_stmt, ep_pol = {}, {}
    with open(path) as fh:
        for ln in fh:
            r = json.loads(ln)
            d = r["data"]
            if r["kind"] == "episode":
                ep_stmt[d["episode"]] = d["statement"]
                ep_pol[d["episode"]] = d["policy"]["id"]
            elif r["kind"] == "outcome":
                s = ep_stmt.get(d["episode"])
                if s is not None:
                    out[s] = {"proved": d.get("kernel") == "accepted",
                              "proof": d.get("proof") or [],
                              "steps": (d.get("stats") or {}).get("steps"),
                              "policy": ep_pol[d["episode"]], "episode": d["episode"]}
    return out


def mcnemar(b, c):
    """Exact two-sided McNemar p for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def holm(ps):
    """Holm-adjusted p values, in input order."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = run
    return adj


def cmd_report(a):
    _, stmts = _statements(a.set)
    runs = dict(x.split("=", 1) for x in a.runs)
    res = {k: outcomes(v) for k, v in runs.items()}
    lines = [f"# RSI target 1: results on {os.path.relpath(a.set, HERE)}", ""]
    lines.append("| run | policy | proved | of |")
    lines.append("|---|---|---|---|")
    for k, o in res.items():
        pol = sorted({v["policy"] for v in o.values()})
        lines.append(f"| {k} | {', '.join(pol)} | {sum(v['proved'] for v in o.values())} | "
                     f"{len(stmts)} |")
    missing = {k: len([s for s in stmts if s not in o]) for k, o in res.items()}
    if any(missing.values()):
        lines += ["", f"Statements without an outcome: {missing}"]
    pairs = [p.split(":") for p in a.compare]
    stats = []
    for x, y in pairs:
        if x not in res or y not in res:
            continue
        gained = [s for s in stmts if res[y].get(s, {}).get("proved") and not res[x].get(s, {}).get("proved")]
        lost = [s for s in stmts if res[x].get(s, {}).get("proved") and not res[y].get(s, {}).get("proved")]
        stats.append((x, y, gained, lost, mcnemar(len(gained), len(lost))))
    adj = holm([s[4] for s in stats if f"{s[0]}:{s[1]}" in a.family])
    fam = [s for s in stats if f"{s[0]}:{s[1]}" in a.family]
    adjusted = {(s[0], s[1]): q for s, q in zip(fam, adj)}
    lines += ["", "| comparison | gained | lost | exact McNemar p | Holm p |", "|---|---|---|---|---|"]
    for x, y, g, l, p in stats:
        q = adjusted.get((x, y))
        lines.append(f"| {y} vs {x} | {len(g)} | {len(l)} | {p:.4g} | "
                     f"{'–' if q is None else f'{q:.4g}'} |")
    lines += ["", "## Per statement", ""]
    for x, y, g, l, p in stats:
        lines.append(f"### {y} vs {x}")
        for tag, ss, src in (("gained", g, y), ("lost", l, x)):
            for s in ss:
                lines.append(f"- {tag}: `{s}`")
                lines.append(f"  - proof under {src}: `{' '.join(res[src][s]['proof'])}`")
        lines.append("")
    with open(a.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines[:20]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--rows", nargs="+", required=True)
    f.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--set", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--ranker", default=None)
    r.add_argument("--fixed-only", action="store_true")
    r.add_argument("--jobs", type=int, default=3)
    p = sub.add_parser("report")
    p.add_argument("--runs", nargs="+", required=True, help="label=RUN_DIR")
    p.add_argument("--set", required=True)
    p.add_argument("--compare", nargs="*", default=["0a:0b", "ref:0a", "0a:1", "1:2", "2:3", "1:3", "2p:2"],
                   help="x:y pairs, y against x")
    p.add_argument("--family", nargs="*", default=["0a:1", "1:2", "2:3", "1:3"],
                   help="the comparisons Holm adjusts over (those run)")
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return {"fit": cmd_fit, "run": cmd_run, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main() or 0)
