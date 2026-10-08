"""proventhru gate STATEMENT | prove STATEMENT | run FILE
          | verify RECORD | corpus RECORD | annotate RECORD SEQ"""
import argparse
import json
import sys

from .env import CoqEnv, DEFAULT_PREAMBLE
from .gate import classify
from .search import best_first, FixedTactics
from .pipeline import run
from . import record as rec


def _statements(path):
    with open(path) as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="proventhru")
    ap.add_argument("--preamble", default=DEFAULT_PREAMBLE,
                    help="Coq sentences loaded before every statement")
    ap.add_argument("--backend", default=None, choices=["auto", "coqtop", "petanque"],
                    help="default: $PROVENTHRU_BACKEND, else petanque if installed, else coqtop")
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
    v = sub.add_parser("verify", help="check a run record's chain and every entry")
    v.add_argument("record")
    c = sub.add_parser("corpus", help="each episode's standing, annotations applied")
    c.add_argument("record")
    n = sub.add_parser("annotate", help="append a statement about an earlier entry")
    n.add_argument("record")
    n.add_argument("seq", type=int)
    n.add_argument("--label", required=True, choices=rec.LABELS)
    n.add_argument("--reason", required=True)
    n.add_argument("--by", default="unknown")
    a = ap.parse_args(argv)

    if a.cmd == "verify":
        entries = rec.load(a.record)
        problems = rec.verify(entries)
        size, head = rec.head(entries)
        for m in problems:
            print("  " + m)
        print(f"{'FAILS' if problems else 'holds'}: {size} entries, head {head}")
        return 1 if problems else 0
    if a.cmd == "corpus":
        for row in rec.corpus(rec.load(a.record)):
            print(json.dumps(row))
        return 0
    if a.cmd == "annotate":
        e = rec.RecordLog(a.record).annotate(a.seq, a.label, a.reason, a.by)
        print(f"annotation {e['seq']} on entry {a.seq}: {a.label}")
        return 0
    if a.cmd == "gate":
        res = classify(a.statement, a.preamble, backend=a.backend)
        print(json.dumps(res.record(), indent=2))
        return 0 if res.status != "ill_formed" else 1
    if a.cmd == "prove":
        with CoqEnv(a.statement, a.preamble, backend=a.backend) as env:
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
        summary = run(_statements(a.file), a.out, a.preamble, budget=a.budget,
                      backend=a.backend)
        print(json.dumps(summary))
        return 0


if __name__ == "__main__":
    sys.exit(main())
