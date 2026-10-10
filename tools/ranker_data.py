"""Extract the ranker's training rows from run records (docs/rsi-target1-ranker.md).

    python tools/ranker_data.py RUN_DIR_OR_RECORDS... --out results/ranker/D0.jsonl

A row is a (node, lemma) pair: the node lies on a kernel-accepted proof,
and the lemma is a library lemma retrieval offered there (proposal
cost.lemmas; corpus `pt_` names, in run 3's lists, are left out). Its label:
  1  the proof's next tactic at the node is, as a string, one of the forms
     retrieval offered for the lemma there (a tactic that merely names it,
     like structural-tactics/v2's `rewrite ?list_sum_app`, is not);
  0  every form offered for it there was tried there and every one failed
     (error, timeout or refused);
  -  otherwise, including a form that succeeded off the found path: no row.
Episodes are read once by id (exploration run 5's rounds 0-5 are copies of
run 4's), and a row repeated across runs (same statement up to bound names,
same goal, same lemma) is kept once.

Proposal records hold the offered names, not the goal, so each proof's
prefix is replayed under the episode's own preamble to read the goal at
each such node, and Search is rerun there (library only, as B's pool) for
each lemma's statement and its position in B's order. A replay that fails,
or a lemma missing from the rerun pool, is dropped and counted."""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proventhru.explore import LEMMA_NAME, LibraryRetriever  # noqa: E402
from proventhru.ranker import features  # noqa: E402
from proventhru.retrieval import terms  # noqa: E402
from proventhru.session import open_session  # noqa: E402
from ranker_sets import key as statement_key  # noqa: E402

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUNS = "/tmp/claude-0/runs"


def forms(name):
    return {f"rewrite {name}.", f"rewrite <- {name}.", f"apply {name}."}


def tasks_from(path):
    """One task per accepted episode with at least one labelled node."""
    episodes, outcomes = {}, {}
    props = defaultdict(list)
    tried = defaultdict(dict)     # (episode, path) -> {tactic: outcome}
    observed = {}                 # (episode, path after the step) -> first goal
    with open(path) as fh:
        for ln in fh:
            r = json.loads(ln)
            d = r["data"]
            if r["kind"] == "episode":
                episodes[d["episode"]] = d
            elif r["kind"] == "proposal":
                props[(d["episode"], tuple(d["path"]))].append(d)
            elif r["kind"] == "step":
                sess = d.get("session") or {}
                tried[(d["episode"], tuple(d["path"]))][d["tactic"]] = sess.get("outcome")
                goals = ((sess.get("observation") or {}).get("goals") or [])
                if sess.get("outcome") == "ok" and goals:
                    observed[(d["episode"], tuple(d["path"]) + (d["tactic"],))] = goals[0]
            elif r["kind"] == "outcome":
                outcomes[d["episode"]] = d
    out = []
    for ep, o in outcomes.items():
        if o.get("kernel") != "accepted" or ep not in episodes:
            continue
        proof = o["proof"]
        nodes = []
        for i, nxt in enumerate(proof):
            key = (ep, tuple(proof[:i]))
            offered = {}
            for p in props.get(key, []):
                cands = {t for t, _ in p["candidates"]}
                for name in (p.get("cost") or {}).get("lemmas") or []:
                    if LEMMA_NAME.fullmatch(name):
                        continue
                    offered.setdefault(name, set()).update(forms(name) & cands)
            labels = {}
            here = tried[key]
            for name, fs in offered.items():
                if nxt in fs:
                    labels[name] = 1
                elif fs and all(here.get(f) in ("error", "timeout", "refused") for f in fs):
                    labels[name] = 0
            if labels:
                nodes.append((i, labels, observed.get(key)))
        if nodes:
            e = episodes[ep]
            out.append({"source": os.path.relpath(path, RUNS) if path.startswith(RUNS) else path,
                        "episode": ep, "statement": e["statement"], "preamble": e["preamble"],
                        "proof": proof, "nodes": nodes})
    return out


def replay(task, timeout=20):
    """Rows for one task, and what was dropped."""
    rows, dropped = [], {"replay": 0, "not_in_pool": 0, "no_goal": 0, "goal_mismatch": 0}
    nodes = {i: labels for i, labels, _ in task["nodes"]}
    recorded = {i: goal for i, _, goal in task["nodes"]}
    try:
        s = open_session(task["preamble"], task["statement"], backend="coqtop")
    except Exception:
        dropped["replay"] += sum(len(v) for v in nodes.values())
        return rows, dropped
    try:
        h, obs = s.root, s.root_obs
        retriever = LibraryRetriever(clean=True)
        for i, tac in enumerate(task["proof"]):
            if i in nodes:
                labels = nodes[i]
                if not obs.goals:
                    dropped["no_goal"] += len(labels)
                elif recorded[i] is not None and (
                        " ".join(recorded[i]["conclusion"].split()) != " ".join(obs.goals[0].conclusion.split())):
                    dropped["goal_mismatch"] += len(labels)
                else:
                    g = obs.goals[0]
                    found = retriever.lemmas(s, terms(g.conclusion, g.hypotheses))
                    where = {n: k for k, (n, _) in enumerate(found)}
                    for name, label in sorted(labels.items()):
                        if name not in where:
                            dropped["not_in_pool"] += 1
                            continue
                        k = where[name]
                        f = features(g.conclusion, g.hypotheses, name, found[k][1], k, 0.0)
                        del f["prior"]
                        rows.append({"source": task["source"], "episode": task["episode"],
                                     "statement": task["statement"], "depth": i,
                                     "goal": [list(g.hypotheses), g.conclusion],
                                     "lemma": name, "label": label, "position": k,
                                     "pool": len(found), "features": f})
            if i == len(task["proof"]) - 1:
                break
            try:
                h, obs = s.run(h, tac, timeout)
            except Exception:
                rest = sum(len(v) for j, v in nodes.items() if j > i)
                dropped["replay"] += rest
                break
    finally:
        s.close()
    return rows, dropped


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+", help="run directories or records.jsonl files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args(argv)

    files = []
    for p in a.sources:
        files += [p] if os.path.isfile(p) else sorted(
            glob.glob(os.path.join(p, "**", "records.jsonl"), recursive=True))
    tasks, seen = [], set()
    for f in files:
        for t in tasks_from(f):
            if t["episode"] not in seen:
                seen.add(t["episode"])
                tasks.append(t)
    print(f"{len(files)} record files, {len(tasks)} episodes to replay, "
          f"{sum(len(t['nodes']) for t in tasks)} nodes", flush=True)
    rows, dropped = [], defaultdict(int)
    with ThreadPoolExecutor(a.jobs) as ex:
        for k, (r, d) in enumerate(ex.map(replay, tasks), 1):
            rows += r
            for key, v in d.items():
                dropped[key] += v
            if k % 25 == 0:
                print(f"  {k}/{len(tasks)} episodes, {len(rows)} rows", flush=True)
    rows.sort(key=lambda r: (r["source"], r["episode"], r["depth"], r["lemma"]))
    unique, keys = [], set()
    for r in rows:
        k = (statement_key(r["statement"]), json.dumps(r["goal"]), r["lemma"])
        if k not in keys:
            keys.add(k)
            unique.append(r)
    dropped["repeated"] = len(rows) - len(unique)
    rows = unique
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    stats = {"files": [os.path.relpath(f, RUNS) if f.startswith(RUNS) else f for f in files],
             "episodes": len(tasks), "rows": len(rows),
             "positives": sum(r["label"] for r in rows),
             "distinct_positive_lemmas": len({r["lemma"] for r in rows if r["label"]}),
             "dropped": dict(dropped)}
    with open(os.path.splitext(a.out)[0] + ".stats.json", "w") as fh:
        json.dump(stats, fh, indent=1, sort_keys=True)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
