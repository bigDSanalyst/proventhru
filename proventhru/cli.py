"""proventhru gate STATEMENT | prove STATEMENT | run FILE"""
import argparse
import json
import sys

from .env import CoqEnv, DEFAULT_PREAMBLE
from .gate import classify
from .search import best_first, FixedTactics
from .pipeline import run


def _statements(path):
    with open(path) as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="proventhru")
    ap.add_argument("--preamble", default=DEFAULT_PREAMBLE,
                    help="Coq sentences loaded before every statement")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate", help="Position 1: classify a conjecture")
    g.add_argument("statement")
    p = sub.add_parser("prove", help="Position 2+3: search, then certify")
    p.add_argument("statement")
    p.add_argument("--budget", type=int, default=200)
    p.add_argument("--trace", action="store_true", help="print every step")
    r = sub.add_parser("run", help="the loop over a file of conjectures, one per line")
    r.add_argument("file")
    r.add_argument("--out", default="out")
    r.add_argument("--budget", type=int, default=200)
    a = ap.parse_args(argv)

    if a.cmd == "gate":
        res = classify(a.statement, a.preamble)
        print(json.dumps(res.record(), indent=2))
        return 0 if res.status != "ill_formed" else 1
    if a.cmd == "prove":
        with CoqEnv(a.statement, a.preamble) as env:
            res = best_first(env, FixedTactics(), budget=a.budget)
        if a.trace:
            for s in res.steps:
                print(f"{s.reward:+.2f} {s.tactic:30} {s.error or ('done' if s.done else '')}")
        print("proved" if res.proved else "not proved",
              f"({res.expansions} expansions, {len(res.steps)} steps, {res.seconds:.1f}s)")
        if res.proved:
            print("\n".join(res.proof))
            print(res.certificate.detail)
        return 0 if res.proved else 1
    if a.cmd == "run":
        summary = run(_statements(a.file), a.out, a.preamble, budget=a.budget)
        print(json.dumps(summary))
        return 0


if __name__ == "__main__":
    sys.exit(main())
