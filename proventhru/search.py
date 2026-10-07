"""Proof search as interaction with CoqEnv.

A Policy proposes scored tactics for an observation; search expands the most
promising open node, one tactic at a time, reading Coq's response before
choosing again. Every step taken, failed or not, goes into the trajectory:
failures are training data too.

FixedTactics is a baseline policy with no learning in it, so the loop runs
end to end before any model is attached. An LLM policy implements the same
propose() and plugs in unchanged.
"""
import heapq
import itertools
import re
import time
from dataclasses import dataclass, field

from .env import CoqEnv


class Policy:
    def propose(self, obs, path):
        """Return [(tactic, score)], higher score tried first."""
        raise NotImplementedError


class FixedTactics(Policy):
    CLOSERS = ["reflexivity.", "lia.", "auto.", "congruence.", "discriminate.",
               "assumption.", "trivial.", "nia."]
    SHAPERS = ["intros.", "simpl.", "split.", "constructor.", "f_equal."]

    def propose(self, obs, path):
        out = [(t, 1.0) for t in self.CLOSERS] + [(t, 0.5) for t in self.SHAPERS]
        if obs.goals:
            g = obs.goals[0]
            names = [n for h in g.hypotheses
                     for n in re.split(r"\s*,\s*", h.split(" : ")[0]) if " : " in h]
            for n in names:
                if not n.startswith("IH"):
                    out.append((f"induction {n}.", 0.4))
                    out.append((f"destruct {n}.", 0.3))
                    out.append((f"rewrite {n}.", 0.3))
                    out.append((f"rewrite <- {n}.", 0.2))
                else:
                    out.append((f"rewrite {n}.", 0.6))
                    out.append((f"simpl; rewrite {n}.", 0.6))
        return out


@dataclass
class SearchResult:
    statement: str
    proved: bool
    proof: tuple = ()
    certificate: object = None
    steps: list = field(default_factory=list)
    expansions: int = 0
    seconds: float = 0.0

    def record(self):
        return {"statement": self.statement, "proved": self.proved,
                "proof": list(self.proof),
                "kernel": None if self.certificate is None else self.certificate.ok,
                "kernel_detail": None if self.certificate is None else self.certificate.detail,
                "expansions": self.expansions, "seconds": round(self.seconds, 2),
                "steps": [s.record() for s in self.steps]}


def best_first(env: CoqEnv, policy: Policy, budget=200, max_depth=12):
    """Expand nodes in order of (cumulative reward, policy score). A kernel
    rejection does not end the search: the trajectory records it and other
    branches continue."""
    t0 = time.perf_counter()
    root = env.reset()
    tie = itertools.count()
    frontier = [(0.0, next(tie), root)]
    seen = {root.obs.key}
    steps, expansions = [], 0
    while frontier and expansions < budget:
        cost, _, node = heapq.heappop(frontier)
        if node.depth >= max_depth:
            continue
        expansions += 1
        for tactic, score in policy.propose(node.obs, node.path):
            st = env.step(node, tactic)
            steps.append(st)
            if st.node is None:
                continue
            if st.done:
                if st.signals.get("kernel") is not False:
                    return SearchResult(env.statement, True, st.node.path, st.certificate,
                                        steps, expansions, time.perf_counter() - t0)
                continue
            if st.node.obs.key in seen:
                continue
            seen.add(st.node.obs.key)
            heapq.heappush(frontier, (cost - st.reward - 0.01 * score
                                      + 0.001 * st.node.obs.size, next(tie), st.node))
    return SearchResult(env.statement, False, (), None, steps, expansions,
                        time.perf_counter() - t0)
