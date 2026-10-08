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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


class PolicyUnavailable(RuntimeError):
    """A policy's backing service stayed down (policy_openai.ModelUnavailable
    and the like set .unavailable = True). The run stops rather than turning
    the rest of the list into failures that have nothing to do with the policy:
    rerun the same command and it resumes."""


def completed(entries, policy, search, protocol_sha):
    """Statements already settled in this record under the same policy,
    search and protocol: closed by an outcome that is not a crash. An
    episode the gate settled has no search, and is settled too."""
    eps, done = {}, set()
    for e in entries:
        d = e["data"]
        if e["kind"] == "episode":
            if (d.get("policy") == policy and d.get("search") in (search, None)
                    and (d.get("protocol") or {}).get("sha256") == protocol_sha):
                eps[d["episode"]] = d["statement"]
        elif e["kind"] == "outcome" and d["episode"] in eps and "error" not in (d.get("stats") or {}):
            done.add(eps[d["episode"]])
    return done


def run(statements, out_dir, preamble=DEFAULT_PREAMBLE, policy=None, budget=200,
        observers=(), log=print, backend=None, weights=None, step_budget=None,
        protocol=None, resume=True, jobs=1, policy_factory=None):
    """protocol is protocol.load()'s result, or None. With one, the run is
    checked against the frozen block before anything starts, and every
    episode carries the protocol's hash. With resume, statements already
    settled in the record under the same policy, search and protocol are
    skipped, so an interrupted run continues where it stopped.

    jobs > 1 attempts that many statements at once (each in its own Coq
    session), so a model server can batch their calls. A policy keeps
    per-call state (last_cost, a bound env), so each worker thread gets its
    own instance from policy_factory, which must build identical policies.
    Episodes interleave in the record, as the schema allows; each episode is
    independent of the others, so the outcomes do not depend on jobs."""
    if jobs > 1 and policy_factory is None:
        raise ValueError("jobs > 1 needs a policy_factory: one policy per worker")
    if policy is None:
        policy = policy_factory() if policy_factory else FixedTactics()
    weights = weights or RewardWeights()
    statements = list(statements)
    os.makedirs(out_dir, exist_ok=True)
    book = rec.RecordLog(os.path.join(out_dir, RECORD))
    env_id = environment(preamble, backend)
    planned = {"algorithm": "best_first", "budget": budget}
    if step_budget is not None:
        planned["step_budget"] = step_budget
    stamp = None
    if protocol is not None:
        from .protocol import check
        stamp = check(protocol, preamble, statements, policy.identity, env_id,
                      {"budget": budget, "step_budget": step_budget})
    elif (policy.identity or {}).get("prompt_sha256"):
        log("warning: a model policy running without a protocol; its records cite none")
    done = (completed(book.entries, policy.identity, planned, stamp and stamp["sha256"])
            if resume else set())
    summary, lock, stop = {}, threading.Lock(), threading.Event()
    local = threading.local()

    def count(key):
        with lock:
            summary[key] = summary.get(key, 0) + 1

    def worker_policy():
        if jobs == 1:
            return policy
        if not hasattr(local, "policy"):
            local.policy = policy_factory()
            if local.policy.identity != policy.identity:
                raise ValueError("policy_factory built a policy with a different identity")
        return local.policy

    def attempt(item, stmt):
        if stop.is_set():
            return
        pol = worker_policy()
        t0 = time.perf_counter()
        gate = classify(stmt, preamble, backend=backend)
        search = dict(planned) if gate.status == "open" else None
        ep = book.episode(stmt, preamble, env_id, gate=gate.record(), policy=pol.identity,
                          search=search, weights=asdict(weights) if search else None,
                          protocol=stamp, item=item)
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
                    res = best_first(env, pol, budget=budget, episode=ep,
                                     step_budget=step_budget)
            except Exception as e:
                # The episode still closes: an attempt that crashed is open,
                # and the record says why rather than ending mid-episode.
                unavailable = getattr(e, "unavailable", False)
                ep.outcome("open", stats={"error": repr(e)[:500],
                                          "incomplete": "policy_unavailable" if unavailable
                                          else "crashed",
                                          "seconds": round(time.perf_counter() - t0, 3)})
                if unavailable:
                    stop.set()
                    raise PolicyUnavailable(f"stopped at item {item}: {e}") from e
                count("open")
                log(f"{'open':9} {gate.status:10} {stmt}  (crashed: {e!r:.80})")
                return
            cert = res.certificate
            standing = "proved" if res.proved and cert is not None and cert.ok else "open"
            ep.outcome(standing, res.proof if standing == "proved" else (),
                       kernel=None if cert is None else cert.verdict,
                       certificate_sha256=None if cert is None else cert.sha256,
                       stats={"expansions": res.expansions, "invocations": res.expansions,
                              "steps": len(res.steps), "stopped": res.stopped,
                              "seconds": round(time.perf_counter() - t0, 3)})
        count(standing)
        log(f"{standing:9} {gate.status:10} {stmt}")

    todo = []
    for item, stmt in enumerate(statements):
        if stmt in done:
            count("resumed")
        else:
            todo.append((item, stmt))
    if jobs == 1:
        for item, stmt in todo:
            attempt(item, stmt)
        return summary
    first = None
    with ThreadPoolExecutor(jobs) as ex:
        for fut in [ex.submit(attempt, i, s) for i, s in todo]:
            try:
                fut.result()
            except PolicyUnavailable as e:
                first = first or e
    if first:
        raise first
    return summary
