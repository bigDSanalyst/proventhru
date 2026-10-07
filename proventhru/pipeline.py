"""The loop: gate each conjecture, search the open ones, keep everything.

corpus.jsonl gets one line per conjecture with its final standing:
  proved     kernel-certified proof
  refuted    kernel-certified disproof (from the gate)
  open       formal, not settled within budget
  rejected   ill_formed, vacuous or trivial (the gate's reason is kept)
trajectories.jsonl gets every step of every search, for training.
"""
import json
import os
import time

from .env import CoqEnv, DEFAULT_PREAMBLE
from .gate import classify
from .search import best_first, FixedTactics


def run(statements, out_dir, preamble=DEFAULT_PREAMBLE, policy=None, budget=200,
        observers=(), log=print):
    policy = policy or FixedTactics()
    os.makedirs(out_dir, exist_ok=True)
    corpus_path = os.path.join(out_dir, "corpus.jsonl")
    traj_path = os.path.join(out_dir, "trajectories.jsonl")
    summary = {}
    with open(corpus_path, "a") as corpus, open(traj_path, "a") as traj:
        for stmt in statements:
            gate = classify(stmt, preamble)
            entry = {"statement": stmt, "preamble": preamble, "gate": gate.record(),
                     "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            if gate.status == "refuted":
                entry["standing"] = "refuted" if gate.kernel else "open"
            elif gate.status != "open":
                entry["standing"] = "rejected"
            else:
                with CoqEnv(stmt, preamble, observers=observers) as env:
                    res = best_first(env, policy, budget=budget)
                rec = res.record()
                traj.write(json.dumps(rec) + "\n")
                entry["standing"] = "proved" if res.proved else "open"
                entry["proof"] = rec["proof"]
                entry["search"] = {k: rec[k] for k in ("expansions", "seconds", "kernel")}
                entry["search"]["steps"] = len(rec["steps"])
            corpus.write(json.dumps(entry) + "\n")
            corpus.flush()
            traj.flush()
            summary[entry["standing"]] = summary.get(entry["standing"], 0) + 1
            log(f"{entry['standing']:9} {gate.status:10} {stmt}")
    return summary
