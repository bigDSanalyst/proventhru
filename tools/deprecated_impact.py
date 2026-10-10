"""How much of a coqtop run record the warning-as-error bug touched.

    python tools/deprecated_impact.py RECORD [RECORD ...] [--replay]

Until the fix in coqtop.py, a tactic that succeeded while naming a deprecated
lemma was recorded as an error (Coq prints the same "Toplevel input,
characters ..." header before a deprecation warning as before an error), and
coqtop's real state moved on while the session's path did not. Only steps
recorded as errors whose tactic names a deprecated identifier can have been
misclassified. This finds them and, with --replay, reruns each at its recorded
path in a fresh, fixed session: a step that now succeeds was a hidden success,
and every later step of its episode at that node or below ran in a state the
record does not describe.

The episode-level numbers are what matter: an episode with a hidden success
may have been searched from the wrong states after it. Proofs are not
affected in soundness: every "proved" outcome was certified by the kernel
from the recorded path alone.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru import record as rec  # noqa: E402
from proventhru.coqtop import Coqtop  # noqa: E402

LEMMA = re.compile(r"^(?:intros;\s*)?(?:rewrite(?:\s*<-)?|apply|exact|eapply)\s+([A-Za-z_][\w.']*)\s*\.$")


def deprecated_names(preamble, names):
    t = Coqtop()
    out = set()
    try:
        for s in [x.strip() + ("." if not x.strip().endswith(".") else "")
                  for x in re.split(r"(?<=\.)\s+", preamble) if x.strip()]:
            t.run(s)
        for n in sorted(names):
            text, _, _ = t.run(f"Check {n}.")
            if "deprecated" in text:
                out.add(n)
    finally:
        t.close()
    return out


def analyse(path, replay=False):
    entries = rec.load(path)
    eps = {e["data"]["episode"]: e["data"] for e in entries if e["kind"] == "episode"}
    steps = rec.steps(entries)
    preamble = next(iter(eps.values()))["preamble"] if eps else ""
    errs = []
    for s in steps:
        if s["session"]["outcome"] != "error":
            continue
        m = LEMMA.match(s["tactic"].strip())
        if m:
            errs.append((s, m.group(1)))
    dep = deprecated_names(preamble, {n for _, n in errs})
    suspect = [(s, n) for s, n in errs if n in dep]
    by_ep = defaultdict(list)
    for s, _ in suspect:
        by_ep[s["episode"]].append(s)
    hidden = None
    if replay and suspect:
        from proventhru.session import open_session
        hidden = defaultdict(list)
        for ep, ss in by_ep.items():
            stmt = eps[ep]["statement"]
            for s in ss:
                sess = open_session(preamble, stmt, "coqtop")
                try:
                    h = sess.root
                    for t in s["path"]:
                        h, _ = sess.run(h, t, timeout=10)
                    sess.run(h, s["tactic"], timeout=10)
                    hidden[ep].append(s["tactic"])
                except Exception:
                    pass
                finally:
                    sess.close()
    proved = {e["data"]["episode"] for e in entries
              if e["kind"] == "outcome" and e["data"]["standing"] == "proved"}
    searched = {k for k, v in eps.items() if v.get("search")}
    res = {"record": path, "searched_episodes": len(searched),
           "error_steps_naming_a_lemma": len(errs), "deprecated_names": sorted(dep),
           "suspect_steps": len(suspect), "episodes_with_suspect_steps": len(by_ep)}
    if hidden is not None:
        affected = {ep for ep, v in hidden.items() if v}
        res.update(hidden_successes=sum(len(v) for v in hidden.values()),
                   episodes_affected=len(affected),
                   affected_and_proved=len(affected & proved),
                   affected_and_unproved=len(affected - proved),
                   affected_statements=sorted(eps[e]["statement"] for e in affected))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("records", nargs="+")
    ap.add_argument("--replay", action="store_true")
    a = ap.parse_args(argv)
    for r in a.records:
        print(json.dumps(analyse(r, a.replay), indent=1))


if __name__ == "__main__":
    main()
