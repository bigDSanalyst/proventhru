"""The oscillate calibration of docs/oscillate-calibration.md: a fixed phase
reading against proof outcomes, with the reward and depth as baselines.

    python tools/oscillate_calibration.py RUN [RUN ...]

Nothing is fitted. The reading, the outcomes, the exclusions and the decision
are the ones the doc's amendment states; this file only computes them.
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru import record as rec  # noqa: E402


def sign(x):
    return (x > 0) - (x < 0)


def auc(scores, labels):
    """Mann-Whitney AUC, ties counted half: P(score of a positive > score of a
    negative)."""
    pairs = sorted(zip(scores, labels))
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if not n_pos or not n_neg:
        return None
    rank, i, rsum = 1, 0, 0.0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        mean_rank = (rank + rank + (j - i) - 1) / 2
        rsum += mean_rank * sum(lab for _, lab in pairs[i:j])
        rank += j - i
        i = j
    return round((rsum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg), 4)


def regime(order):
    return 2 if order > 0.1 else 0 if order < -0.3 else 1


def readings(steps):
    """[(order, regime, reward, depth, step)] for one episode's steps in order."""
    out, window = [], []
    for st in steps:
        s = st["session"]
        last = window[-20:]
        err20 = sum(1 for w in last if w["outcome"] != "ok") / len(last) if last else 0.0
        rev20 = sum(1 for w in last if w["revisit"]) / len(last) if last else 0.0
        ok = s["outcome"] == "ok"
        if ok and s["goals_after"] is not None and s["size_before"]:
            dg = s["goals_before"] - s["goals_after"]
            ds = (s["size_before"] - (s["size_after"] or 0)) / s["size_before"]
            core = ds + 0.5 * sign(dg)
        else:
            core = 0.0
        order = core - err20 - rev20
        out.append((order, regime(order), st["reward"], len(st["path"]) + 1, st))
        window.append({"outcome": s["outcome"], "revisit": bool(s["revisit"])})
    return out


def records(run):
    r = 0
    while os.path.isdir(os.path.join(run, f"round-{r}")):
        for k in ("fixed", "retrieval"):
            p = os.path.join(run, f"round-{r}", k, "records.jsonl")
            if os.path.exists(p):
                yield rec.load(p)
        r += 1


def calibrate(run):
    step_rows, ep_rows = [], []
    for entries in records(run):
        outcomes = {e["data"]["episode"]: e["data"] for e in entries if e["kind"] == "outcome"}
        by_ep = defaultdict(list)
        for st in rec.steps(entries):
            by_ep[st["episode"]].append(st)
        for ep, steps in by_ep.items():
            out = outcomes.get(ep)
            if out is None:
                continue
            proved = out["standing"] == "proved"
            rd = readings(steps)
            if proved:
                proof = out["proof"]
                for order, reg, rew, depth, st in rd:
                    if st["session"]["outcome"] != "ok":
                        continue
                    on = (list(st["path"]) + [st["tactic"]]) == proof[:len(st["path"]) + 1]
                    step_rows.append((order, reg, rew, depth, int(on)))
            if len(steps) >= 50:
                first = rd[:50]
                ep_rows.append((sum(x[0] for x in first) / 50, sum(x[1] for x in first) / 50,
                                sum(x[2] for x in first) / 50, sum(x[3] for x in first) / 50,
                                int(proved)))
    res = {"run": run}
    for name, rows in (("step", step_rows), ("episode", ep_rows)):
        labels = [r[4] for r in rows]
        res[name] = {"n": len(rows), "positives": sum(labels),
                     "order": auc([r[0] for r in rows], labels),
                     "regime": auc([r[1] for r in rows], labels),
                     "reward": auc([r[2] for r in rows], labels),
                     "depth": auc([r[3] for r in rows], labels)}
    a, b = res["step"]["order"], res["episode"]["order"]
    if a is not None and b is not None:
        res["decision"] = ("keep" if a >= 0.70 and b >= 0.70 else
                           "drop" if a < 0.60 and b < 0.60 else "inconclusive")
        res["beats_reward"] = {k: (res[k]["order"] or 0) > (res[k]["reward"] or 0)
                               for k in ("step", "episode")}
    return res


def main(argv=None):
    for run in (argv or sys.argv[1:]):
        print(json.dumps(calibrate(run), indent=1))


if __name__ == "__main__":
    main()
