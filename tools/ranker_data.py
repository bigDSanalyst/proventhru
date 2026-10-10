"""Extract the ranker's training rows from run records (docs/rsi-target1-ranker.md).

    python tools/ranker_data.py RUN_DIR_OR_RECORDS... --out results/ranker/D0.jsonl

A row is a (node, lemma) pair: the node lies on a kernel-accepted proof,
and the lemma is a library lemma retrieval offered there (proposal
cost.lemmas; corpus `pt_` names are left out). Its label:
  1  a form of the lemma is the proof's next tactic at the node;
  0  every form of it offered there was tried there, and none is;
  -  otherwise (the proof closed or the budget ran out first): no row.

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
from proventhru.explore import LEMMA_NAME, LibraryRetriever  # noqa: E402
from proventhru.ranker import features  # noqa: E402
from proventhru.retrieval import terms  # noqa: E402
from proventhru.session import open_session  # noqa: E402

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def forms(name):
    return {f"rewrite {name}.", f"rewrite <- {name}.", f"apply {name}."}


def tasks_from(path):
    """One task per accepted episode with at least one labelled node."""
    episodes, outcomes = {}, {}
    props = defaultdict(list)
    tried = defaultdict(set)
    with open(path) as fh:
        for ln in fh:
            r = json.loads(ln)
            d = r["data"]
            if r["kind"] == "episode":
                episodes[d["episode"]] = d
            elif r["kind"] == "proposal":
                props[(d["episode"], tuple(d["path"]))].append(d)
            elif r["kind"] == "step":
                tried[(d["episode"], tuple(d["path"]))].add(d["tactic"])
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
            for name, fs in offered.items():
                if nxt in fs:
                    labels[name] = 1
                elif fs and fs <= tried[key]:
                    labels[name] = 0
            if labels:
                nodes.append((i, labels))
        if nodes:
            e = episodes[ep]
            out.append({"source": os.path.relpath(path, "/tmp/claude-0/runs") if path.startswith("/tmp/claude-0/runs") else path,
                        "episode": ep, "statement": e["statement"], "preamble": e["preamble"],
                        "proof": proof, "nodes": nodes})
    return out


def replay(task, timeout=20):
    """Rows for one task, and what was dropped."""
    rows, dropped = [], {"replay": 0, "not_in_pool": 0, "no_goal": 0}
    nodes = dict(task["nodes"])
    try:
        s = open_session(task["preamble"], task["statement"], backend="coqtop")
    except Exception:
        dropped["replay"] += sum(len(v) for v in nodes.values())
        return rows, dropped
    try:
        h, obs = s.root, s.root_obs
        retriever = LibraryRetriever()
        for i, tac in enumerate(task["proof"]):
            if i in nodes:
                labels = nodes[i]
                if not obs.goals:
                    dropped["no_goal"] += len(labels)
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
    tasks = [t for f in files for t in tasks_from(f)]
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
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    stats = {"files": len(files), "episodes": len(tasks), "rows": len(rows),
             "positives": sum(r["label"] for r in rows),
             "distinct_positive_lemmas": len({r["lemma"] for r in rows if r["label"]}),
             "dropped": dict(dropped)}
    with open(os.path.splitext(a.out)[0] + ".stats.json", "w") as fh:
        json.dump(stats, fh, indent=1, sort_keys=True)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
