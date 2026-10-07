"""Run the same conjectures through each installed backend and compare.

    python tools/compare_backends.py examples/conjectures.txt --budget 60

For each statement: the gate's verdict, whether search proved it, the proof,
steps taken and seconds, per backend. Disagreements are listed at the end;
the two backends should agree on every verdict and differ only in time.
"""
import argparse
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))

from proventhru.env import CoqEnv, DEFAULT_PREAMBLE  # noqa: E402
from proventhru.gate import classify  # noqa: E402
from proventhru.search import best_first, FixedTactics  # noqa: E402
from proventhru.session import petanque_available  # noqa: E402


def one(stmt, backend, budget):
    t0 = time.perf_counter()
    gate = classify(stmt, DEFAULT_PREAMBLE, backend=backend)
    row = {"gate": gate.status, "proved": None, "proof": "", "steps": 0}
    if gate.status == "open":
        with CoqEnv(stmt, DEFAULT_PREAMBLE, backend=backend) as env:
            res = best_first(env, FixedTactics(), budget=budget)
        row.update(proved=res.proved, proof=" ".join(res.proof), steps=len(res.steps))
    row["seconds"] = time.perf_counter() - t0
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--budget", type=int, default=60)
    a = ap.parse_args()
    with open(a.file) as fh:
        stmts = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    backends = ["coqtop"] + (["petanque"] if petanque_available() else [])
    rows = {b: [one(s, b, a.budget) for s in stmts] for b in backends}
    head = f"{'statement':52}" + "".join(f" | {b:>8} gate  proved steps   secs" for b in backends)
    print(head)
    print("-" * len(head))
    disagree = []
    for i, s in enumerate(stmts):
        cells = []
        for b in backends:
            r = rows[b][i]
            p = "-" if r["proved"] is None else ("yes" if r["proved"] else "no")
            cells.append(f" | {r['gate']:>13} {p:>6} {r['steps']:5} {r['seconds']:6.2f}")
        print(f"{s[:52]:52}" + "".join(cells))
        verdicts = {(rows[b][i]["gate"], rows[b][i]["proved"]) for b in backends}
        if len(verdicts) > 1:
            disagree.append(s)
    for b in backends:
        print(f"{b}: {sum(r['seconds'] for r in rows[b]):.1f}s total, "
              f"{sum(r['steps'] for r in rows[b])} search steps")
    print("disagreements:", disagree or "none")
    return 1 if disagree else 0


if __name__ == "__main__":
    sys.exit(main())
