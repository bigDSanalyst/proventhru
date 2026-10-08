"""The loop: gate each conjecture, search the open ones, keep everything.

Everything goes into one run record (record.py, SCHEMA.md): an episode per
conjecture, every policy call and every step of its search, and its outcome:

  proved     the kernel accepted a proof
  refuted    the kernel accepted a disproof (from the gate)
  open       formal, not settled within budget
  rejected   ill_formed, vacuous or trivial (the gate's reason is kept)

The corpus and the trajectories are views of that record (record.corpus,
record.steps), not files of their own, so they cannot drift from it.
"""
import os
import time
from dataclasses import asdict

from . import record as rec
from .env import CoqEnv, DEFAULT_PREAMBLE, RewardWeights
from .gate import classify
from .search import best_first, FixedTactics
from .session import open_session

RECORD = "records.jsonl"


def environment(preamble, backend=None):
    s = open_session(preamble, "True", backend)
    try:
        return dict(s.environment)
    finally:
        s.close()


def run(statements, out_dir, preamble=DEFAULT_PREAMBLE, policy=None, budget=200,
        observers=(), log=print, backend=None, weights=None):
    policy = policy or FixedTactics()
    weights = weights or RewardWeights()
    os.makedirs(out_dir, exist_ok=True)
    book = rec.RecordLog(os.path.join(out_dir, RECORD))
    env_id = environment(preamble, backend)
    summary = {}
    for stmt in statements:
        t0 = time.perf_counter()
        gate = classify(stmt, preamble, backend=backend)
        search = ({"algorithm": "best_first", "budget": budget} if gate.status == "open" else None)
        ep = book.episode(stmt, preamble, env_id, gate=gate.record(), policy=policy.identity,
                          search=search, weights=asdict(weights) if search else None)
        if gate.status == "refuted":
            standing = "refuted" if gate.kernel == "accepted" else "open"
            ep.outcome(standing, gate.script, kernel=gate.kernel,
                       stats={"seconds": round(time.perf_counter() - t0, 3)})
        elif gate.status != "open":
            standing = "rejected"
            ep.outcome(standing, stats={"seconds": round(time.perf_counter() - t0, 3)})
        else:
            try:
                with CoqEnv(stmt, preamble, observers=observers, backend=backend,
                            weights=weights) as env:
                    res = best_first(env, policy, budget=budget, episode=ep)
            except Exception as e:
                # The episode still closes: an attempt that crashed is open,
                # and the record says why rather than ending mid-episode.
                ep.outcome("open", stats={"error": repr(e)[:500],
                                          "seconds": round(time.perf_counter() - t0, 3)})
                summary["open"] = summary.get("open", 0) + 1
                log(f"{'open':9} {gate.status:10} {stmt}  (crashed: {e!r:.80})")
                continue
            cert = res.certificate
            standing = "proved" if res.proved and cert is not None and cert.ok else "open"
            ep.outcome(standing, res.proof if standing == "proved" else (),
                       kernel=None if cert is None else cert.verdict,
                       certificate_sha256=None if cert is None else cert.sha256,
                       stats={"expansions": res.expansions, "steps": len(res.steps),
                              "seconds": round(time.perf_counter() - t0, 3)})
        summary[standing] = summary.get(standing, 0) + 1
        log(f"{standing:9} {gate.status:10} {stmt}")
    return summary
