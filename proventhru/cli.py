"""proventhru gate STATEMENT | prove STATEMENT | run FILE
          | verify RECORD | corpus RECORD | annotate RECORD SEQ | report RECORD...
          | protocol {check PROTOCOL | set FILE | prompt}"""
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
    elif a.policy == "openai":
        from .policy_openai import OpenAICompatPolicy
        if not a.base_url:
            raise SystemExit("--policy openai needs --base-url")
        pol = OpenAICompatPolicy(preamble, model=a.model, base_url=a.base_url,
                                 key_env=a.key_env or None, k=a.k, temperature=a.temperature,
                                 seed=a.seed, response_format=a.response_format,
                                 cache=a.cache, max_calls=a.max_calls,
                                 provider=a.provider, reexpand=a.reexpand)
    else:
        from .policy_claude import ClaudePolicy
        pol = ClaudePolicy(preamble, model=a.model, effort=a.effort, k=a.k,
                           max_calls=a.max_calls)
    if a.retrieval:
        from .retrieval import RetrievalPolicy
        pol = RetrievalPolicy(pol, top=a.retrieval)
    return pol


def _protocol(a, policy):
    """A model policy runs only under a committed protocol."""
    if not a.protocol:
        if policy.identity.get("prompt_sha256"):
            raise SystemExit("a model policy runs only under a committed protocol: --protocol "
                             "PROTOCOL.md")
        return None
    from .protocol import load, ProtocolError
    try:
        return load(a.protocol)
    except ProtocolError as e:
        raise SystemExit(f"protocol: {e}")


def _budget(n):
    return None if n == 0 else n


def _policy_args(p):
    p.add_argument("--policy", choices=["fixed", "claude", "openai"], default="fixed")
    p.add_argument("--model", default="claude-opus-5-5",
                   help="for openai: the served name, e.g. org/model:provider on the HF router")
    p.add_argument("--base-url", default=None,
                   help="openai: e.g. https://router.huggingface.co/v1, http://localhost:8000/v1")
    p.add_argument("--key-env", default="HF_TOKEN",
                   help="openai: environment variable holding the key ('' for none)")
    p.add_argument("--response-format", default="json_object",
                   choices=["json_schema", "json_object", "none"])
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--cache", default=None, help="openai: response cache file (JSONL)")
    p.add_argument("--reexpand", type=int, default=3,
                   help="openai: times a node may be re-asked, shown what was tried there")
    p.add_argument("--provider", default=None,
                   help="openai: what serves the model, recorded in the identity "
                        "(e.g. 'vllm 0.6.6.post1, fp16, T4'); default: the base URL")
    p.add_argument("--protocol", default=None,
                   help="the committed PROTOCOL.md the run is checked against and cites")
    p.add_argument("--step-budget", type=int, default=None,
                   help="cap on steps: tactics submitted, whatever their outcome")
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
    p.add_argument("--budget", type=int, default=200, help="cap on expansions (0: none)")
    p.add_argument("--trace", action="store_true", help="print every step")
    _policy_args(p)
    r = sub.add_parser("run", help="the loop over a file of conjectures, one per line")
    r.add_argument("file")
    r.add_argument("--out", default="out")
    r.add_argument("--budget", type=int, default=200, help="cap on expansions (0: none)")
    r.add_argument("--jobs", type=int, default=1,
                   help="statements attempted at once, each with its own policy and Coq session")
    _policy_args(r)
    rp = sub.add_parser("report", help="compare runs from their records")
    rp.add_argument("records", nargs="+")
    x = sub.add_parser("explore", help="the conjecture loop: generate, gate, prove, keep")
    x.add_argument("--out", required=True)
    x.add_argument("--rounds", type=int, default=4)
    x.add_argument("--per-round", type=int, default=80, help="candidates gated per round")
    x.add_argument("--step-budget", type=int, default=600)
    x.add_argument("--jobs", type=int, default=1)
    x.add_argument("--seed", type=int, default=2, help="generator seed (the test set used 1)")
    x.add_argument("--max-term", type=int, default=5)
    x.add_argument("--min-size", type=int, default=3)
    x.add_argument("--signature", choices=["base", "wide"], default="base")
    x.add_argument("--prover", choices=["fixed", "structural"], default="fixed")
    x.add_argument("--new-only", action="store_true",
                   help="with --signature wide: only candidates using nth, last or count_occ")
    x.add_argument("--max-size", type=int, default=9)
    x.add_argument("--exclude", action="append", default=[],
                   help="statement file never to propose from (repeatable): held-out and dev sets")
    pr = sub.add_parser("protocol", help="hashes the protocol registers, and its check")
    pr.add_argument("what", choices=["check", "set", "prompt"])
    pr.add_argument("path", nargs="?")
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

    if a.cmd == "explore":
        from .explore import explore
        ex = set()
        for f in a.exclude:
            ex |= set(_statements(f)[1])
        corpus, rounds = explore(a.out, rounds=a.rounds, per_round=a.per_round,
                                 step_budget=a.step_budget, jobs=a.jobs, exclude=ex,
                                 seed=a.seed, max_term=a.max_term, min_size=a.min_size,
                                 max_size=a.max_size, backend=a.backend or "coqtop",
                                 signature=a.signature, require_new=a.new_only,
                                 prover=a.prover)
        print(json.dumps({"corpus": len(corpus), "rounds": rounds[-1:] and rounds[-1]}))
        return 0
    if a.cmd == "protocol":
        from . import protocol as proto
        if a.what == "set":
            file_preamble, stmts = _statements(a.path)
            print(proto.statements_sha256(file_preamble or a.preamble, stmts))
        elif a.what == "prompt":
            from .policy_openai import prompt_sha256
            print(prompt_sha256())
        else:
            try:
                p = proto.load(a.path)
            except proto.ProtocolError as e:
                print(f"FAILS: {e}")
                return 1
            print(f"holds: {p['path']} sha256 {p['sha256']} commit {p['commit']}")
            print(json.dumps(p["frozen"], indent=2))
        return 0
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
        pol = _policy(a, a.preamble)
        _protocol(a, pol)
        with CoqEnv(a.statement, a.preamble, backend=a.backend) as env:
            res = best_first(env, pol, budget=_budget(a.budget), step_budget=a.step_budget)
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
        pol = _policy(a, preamble)
        from .pipeline import PolicyUnavailable
        from .protocol import ProtocolError
        try:
            summary = run(stmts, a.out, preamble, policy=pol, budget=_budget(a.budget),
                          backend=a.backend, step_budget=a.step_budget,
                          protocol=_protocol(a, pol), jobs=a.jobs,
                          policy_factory=lambda: _policy(a, preamble))
        except ProtocolError as e:
            raise SystemExit(f"protocol: {e}")
        except PolicyUnavailable as e:
            print(f"stopped: {e}. Rerun the same command to resume.")
            return 2
        print(json.dumps(summary))
        return 0


if __name__ == "__main__":
    sys.exit(main())
