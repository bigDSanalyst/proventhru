"""proventhru gate STATEMENT | prove STATEMENT | run FILE
          | verify RECORD | corpus RECORD | annotate RECORD SEQ | report RECORD..."""
import argparse
import json
import sys

from .env import CoqEnv, DEFAULT_PREAMBLE
from .gate import classify
from .search import best_first, FixedTactics
from .pipeline import run
from . import record as rec


def _statements(path):
    """Statements one per line; '#' lines are comments, except a
    '# preamble: ...' line, which sets the preamble for the file."""
    preamble, out = None, []
    with open(path) as fh:
        for ln in fh:
            s = ln.strip()
            if s.startswith("# preamble:"):
                preamble = s[len("# preamble:"):].strip()
            elif s and not s.startswith("#"):
                out.append(s)
    return preamble, out


def _policy(a, preamble):
    if a.policy == "fixed":
        pol = FixedTactics()
    else:
        from .policy_claude import ClaudePolicy
        pol = ClaudePolicy(preamble, model=a.model, effort=a.effort, k=a.k,
                           max_calls=a.max_calls)
    if a.retrieval:
        from .retrieval import RetrievalPolicy
        pol = RetrievalPolicy(pol, top=a.retrieval)
    return pol


def _policy_args(p):
    p.add_argument("--policy", choices=["fixed", "claude"], default="fixed")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--effort", default="medium",
                   choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--k", type=int, default=5, help="candidates per model call")
    p.add_argument("--max-calls", type=int, default=None,
                   help="stop calling the model after this many calls (cost cap)")
    p.add_argument("--retrieval", type=int, default=0, metavar="N",
                   help="also offer the N best-matching library lemmas at each node")


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
    _policy_args(p)
    r = sub.add_parser("run", help="the loop over a file of conjectures, one per line")
    r.add_argument("file")
    r.add_argument("--out", default="out")
    r.add_argument("--budget", type=int, default=200)
    _policy_args(r)
    rp = sub.add_parser("report", help="compare runs from their records")
    rp.add_argument("records", nargs="+")
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

    if a.cmd == "report":
        from .report import render
        print(render(a.records))
        return 0
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
            res = best_first(env, _policy(a, a.preamble), budget=a.budget)
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
        file_preamble, stmts = _statements(a.file)
        preamble = file_preamble or a.preamble
        summary = run(stmts, a.out, preamble, policy=_policy(a, preamble),
                      budget=a.budget, backend=a.backend)
        print(json.dumps(summary))
        return 0


if __name__ == "__main__":
    sys.exit(main())
