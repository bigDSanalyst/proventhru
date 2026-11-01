"""Target 2's DPO pairs from recorded search trees (docs/rsi-target2-prover-dpo.md).

    python tools/dpo_pairs.py --run C=DIR --run D=DIR --cache CACHE.jsonl \\
        --out PAIRS.jsonl --stats STATS.json [--no-root]

The selection criterion picks the frontier trees. At each on-path state of a
frontier tree, the pair rule turns the state's asks into (prompt, chosen,
rejected). Every prompt is rebuilt with view.state from the record and used
only if the hash of its request is the recorded cache key. Everything not used
is counted under its reason, so the yield and its losses are both reported.

A root state's observation isn't in the record: it's rebuilt by opening the
statement in a fresh session, which needs Coq. Without it (--no-root), root
states are counted as not rebuilt."""
import argparse
import hashlib
import json
import os
import re
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru import record as rec  # noqa: E402
from proventhru import view  # noqa: E402
from proventhru.goals import Goal, Observation  # noqa: E402
from proventhru.policy_claude import assemble  # noqa: E402
from proventhru.policy_openai import OpenAICompatPolicy, extract_json, prompt_sha256  # noqa: E402

MIN_STEPS = 10          # a tree proved in this many steps or fewer is excluded
PER_STATE = 3           # pairs per state, the first in record order
HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOC, CODE_ROW = "docs/rsi-target2-prover-dpo.md", "code:target-2-pairs"
# What the count's result depends on: the rule, and the code that rebuilds a
# prompt (the view, the policy's request body, the schema and vocabulary, canon).
GOVERNED = [
    "proventhru/coqtop.py", "proventhru/goals.py", "proventhru/policy_claude.py",
    "proventhru/policy_openai.py", "proventhru/record.py", "proventhru/session.py",
    "proventhru/view.py", "tools/dpo_pairs.py",
]


def code_hash(repo, paths=GOVERNED):
    """sha256 over the governed files' paths and contents, in order."""
    h = hashlib.sha256()
    for p in paths:
        with open(os.path.join(repo, p), "rb") as fh:
            h.update(f"{p} {hashlib.sha256(fh.read()).hexdigest()}\n".encode())
    return h.hexdigest()


def preflight(repo=HERE):
    """The count runs only under the frozen doc and the registered code."""
    with open(os.path.join(repo, "docs", "frozen.md")) as fh:
        rows = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([0-9a-f]{64})`\s*\|",
                          fh.read(), re.M)
    with open(os.path.join(repo, DOC), "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    docs = [r for r in rows if r[0] == DOC]
    if not docs or docs[-1][2] != digest:
        raise SystemExit(f"{DOC} isn't frozen at its current hash ({digest[:16]}): the count "
                         "runs only after the freeze")
    codes = [r for r in rows if r[0] == CODE_ROW]
    current = code_hash(repo)
    if not codes or codes[-1][2] != current:
        raise SystemExit(f"the pair-count code hashes to {current[:16]}, which isn't the latest "
                         f"`{CODE_ROW}` row")
    return digest, current


class Tree:
    """One episode: its statement, policy, proposals and steps in record order."""

    def __init__(self, episode):
        self.ep, self.proposals, self.steps, self.outcome = episode, [], [], None

    @property
    def proved(self):
        return bool(self.outcome) and self.outcome["standing"] == "proved"

    @property
    def n_steps(self):
        return (self.outcome or {}).get("stats", {}).get("steps") or len(self.steps)


def load(run_dir, aside=None):
    """One tree per statement: the first of its episodes that ended (an outcome
    with a standing, and no error). A rerun into the same directory appends later
    episodes of the same statements (the notebook's dev cell, run again after
    round 5, does): they're counted in aside and not used, so each statement's
    tree is its round-5 one, and C isn't read twice."""
    eps = {}
    for e in rec.load(os.path.join(run_dir, "records.jsonl")):
        d = dict(e["data"], seq=e["seq"])
        if e["kind"] == "episode":
            eps[d["episode"]] = Tree(d)
        elif e["kind"] == "proposal":
            eps[d["episode"]].proposals.append(d)
        elif e["kind"] == "step":
            eps[d["episode"]].steps.append(d)
        elif e["kind"] == "outcome":
            eps[d["episode"]].outcome = d
    trees, aside = {}, Counter() if aside is None else aside
    for t in eps.values():                      # in record order
        stats = (t.outcome or {}).get("stats") or {}
        if (not t.outcome or t.outcome.get("standing") is None
                or "error" in stats or "incomplete" in stats):
            aside["episodes cut short"] += 1
        elif t.ep["statement"] in trees:
            aside["later episodes of a statement (a rerun)"] += 1
        else:
            trees[t.ep["statement"]] = t
    return list(trees.values())


def on_path(tree):
    """[(state path, step)] for the proof's tactics, each with the step that took it."""
    proof, out = list(tree.outcome["proof"]), []
    for i, tac in enumerate(proof):
        s = proof[:i]
        step = next((x for x in tree.steps if x["path"] == s and x["tactic"] == tac), None)
        if step is None:
            return None
        out.append((s, step))
    return out


def frontier(trees, other_proved=None):
    """{episode: [criteria]} for the proved trees on the frontier, and the counts."""
    proved = [t for t in trees if t.proved]
    if not proved:
        return {}, Counter()
    median = statistics.median(t.n_steps for t in proved)
    counts, out = Counter(proved=len(proved)), {}
    for t in proved:
        if t.n_steps <= MIN_STEPS:
            counts["excluded: proved in 10 steps or fewer"] += 1
            continue
        why = []
        if t.n_steps > median:
            why.append("steps above the median")
        if other_proved is not None and t.ep["statement"] not in other_proved:
            why.append("proved with retrieval, not without")
        path = on_path(t) or []
        firsts = {}
        for p in t.proposals:
            firsts.setdefault(tuple(p["path"]), p["seq"])
        if any(st["proposal"] != firsts.get(tuple(s)) for s, st in path):
            why.append("an on-path tactic from a re-ask")
        for w in why:
            counts[w] += 1
        if why:
            out[t.ep["episode"]] = why
    counts["frontier"] = len(out)
    return out, counts


def slots(p, k):
    """{slot: tactic} of the proposal's model response: its candidates that
    retrieval didn't add, at slot k (1 - score), dropped ones in the gaps."""
    cost = p.get("cost") or {}
    added = set(cost.get("added") or [])
    out = {}
    for tac, score in p["candidates"]:
        if tac not in added:
            out[round(k * (1 - score))] = tac
    gaps = [i for i in range(k) if i not in out]
    for i, _ in zip(gaps, cost.get("dropped") or []):
        out[i] = None                       # a dropped candidate holds its slot
    return out


def split(tactic):
    """'rewrite <- IHn.' -> {'tactic': 'rewrite', 'argument': '<- IHn'}, or None."""
    name, _, arg = tactic.rstrip(".").partition(" ")
    if assemble(name, arg)[0] != tactic:
        return None
    return {"tactic": name, "argument": arg}


def result(step):
    s = step["session"]
    if s["outcome"] != "ok":
        return (s["error"] or "")[:160]
    return "finished" if s["finished"] else \
        "back to a state already seen" if s["revisit"] else "new state"


def observation(d):
    return Observation(goals=tuple(Goal(i, g["conclusion"], tuple(g["hypotheses"]))
                                   for i, g in enumerate(d["goals"], 1)),
                       shelved=d["shelved"], finished=d["finished"])


class Prompts:
    """Rebuilds a proposal's request and checks it against its cache key."""

    def __init__(self, root=True):
        self.root, self.roots, self.policies = root, {}, {}

    def policy(self, tree):
        ident = tree.ep["policy"]
        key = json.dumps(ident, sort_keys=True) + tree.ep["preamble"]
        if key not in self.policies:
            self.policies[key] = OpenAICompatPolicy(
                tree.ep["preamble"], ident["model"], ident["base_url"], key_env=None,
                k=ident["k"], temperature=ident["temperature"], seed=ident["seed"],
                max_tokens=ident["max_tokens"], response_format=ident["response_format"],
                reexpand=ident.get("reexpand", 3))
        return self.policies[key]

    def obs(self, tree, path):
        if not path:
            if not self.root:
                return None
            st = tree.ep["statement"]
            if st not in self.roots:
                from proventhru.session import open_session
                s = open_session(tree.ep["preamble"], st, "coqtop")
                try:
                    self.roots[st] = s.root_obs
                finally:
                    s.close()
            return self.roots[st]
        for x in tree.steps:
            if x["path"] + [x["tactic"]] == path and x["session"]["observation"]:
                return observation(x["session"]["observation"])
        return None

    def request(self, tree, p):
        """(body, key) of proposal p's request as rebuilt, or (None, reason)."""
        obs = self.obs(tree, p["path"])
        if obs is None:
            return None, "root not rebuilt" if not p["path"] else "node observation missing"
        before = [x for x in tree.steps if x["seq"] < p["seq"]]
        fail = next((x for x in reversed(before) if x["session"]["outcome"] != "ok"), None)
        last_failure = None if fail is None else {
            "path": fail["path"], "tactic": fail["tactic"],
            "outcome": fail["session"]["outcome"], "error": fail["session"]["error"]}
        first = next(q for q in tree.proposals if q["path"] == p["path"])
        tried = None if first["seq"] == p["seq"] else [
            {"tactic": x["tactic"], "outcome": x["session"]["outcome"], "result": result(x)}
            for x in before if x["path"] == p["path"]]
        pol = self.policy(tree)
        body = pol._body(view.state(obs, p["path"], last_failure, tried))
        key = hashlib.sha256(rec.canon({"url": pol.base_url + "/chat/completions",
                                        "body": body}).encode()).hexdigest()
        return body, key


def generated(cache, key):
    """The model's message content cached under key, and its parsed candidates."""
    hit = cache.get(key)
    if not hit:
        return None, None
    try:
        content = json.loads(hit["body"])["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None, None
    parsed = extract_json(content)
    cands = parsed.get("candidates") if isinstance(parsed, dict) else None
    return content, (cands if isinstance(cands, list) else None)


def replaced(cands, slot, tactic):
    new = split(tactic)
    if new is None or slot >= len(cands):
        return None
    out = list(cands)
    out[slot] = new
    return json.dumps({"candidates": out})


def pairs(label, trees, chosen_trees, cache, prompts, seen, counts):
    """The pairs from one condition's frontier trees (chosen_trees: their
    episodes), appended under the rule; counts and seen updated."""
    out = []
    for t in trees:
        if t.ep["episode"] not in chosen_trees:
            continue
        k = t.ep["policy"]["k"]
        by_path = {}
        for p in t.proposals:
            by_path.setdefault(tuple(p["path"]), []).append(p)
        for s, step in on_path(t) or []:
            counts[f"{label}: on-path states"] += 1
            asks = by_path.get(tuple(s), [])
            pj = next((p for p in asks if p["seq"] == step["proposal"]), None)
            if pj is None:
                counts[f"{label}: dropped: no proposal for the on-path step"] += 1
                continue
            tstar = step["tactic"]
            sj = slots(pj, k)
            if tstar not in sj.values():
                counts[f"{label}: no pair: t* from retrieval"] += 1
                continue
            # f: a tactic of another ask's model response that ran at s and Coq refused
            ran = {x["tactic"]: x for x in t.steps if x["path"] == s}
            found = []
            for pi in asks:
                if pi["seq"] == pj["seq"]:
                    continue
                si, added = slots(pi, k), set((pi.get("cost") or {}).get("added") or [])
                for slot, f in sorted((i, x) for i, x in si.items() if x):
                    x = ran.get(f)
                    if x is None:
                        continue
                    oc = x["session"]["outcome"]
                    if oc != "error":
                        counts[f"{label}: f not used: {oc}"] += 1
                        continue
                    found.append((x["seq"], pi, slot, f))
                for f in added:
                    if ran.get(f) and ran[f]["session"]["outcome"] == "error":
                        counts[f"{label}: f not used: a retrieval lemma"] += 1
            made = 0
            for _, pi, fslot, f in sorted(found, key=lambda z: z[0]):
                if made >= PER_STATE:
                    counts[f"{label}: beyond {PER_STATE} per state"] += 1
                    break
                triple = (t.ep["statement"], tuple(s), f, tstar)
                if triple in seen:
                    where = ("in another condition" if seen[triple] != label
                             else "earlier in this condition")
                    counts[f"{label}: the same triple {where}"] += 1
                    continue
                if pi["seq"] > pj["seq"]:
                    branch, base, slot, swap_in = "i > j", pj, \
                        next(i for i, x in sj.items() if x == tstar), f
                    if f in sj.values():
                        counts[f"{label}: dropped: f already in P_j"] += 1
                        continue
                else:
                    branch, base, slot, swap_in = "i < j", pi, fslot, tstar
                    if tstar in slots(pi, k).values():
                        counts[f"{label}: dropped: t* already in P_i"] += 1
                        continue
                body, key = prompts.request(t, base)
                if body is None:
                    counts[f"{label}: dropped: {key}"] += 1
                    continue
                if key != (base.get("cost") or {}).get("cache_key"):
                    counts[f"{label}: dropped: prompt doesn't verify"] += 1
                    continue
                content, cands = generated(cache, key)
                if cands is None:
                    counts[f"{label}: dropped: response not in the cache"] += 1
                    continue
                other = replaced(cands, slot, swap_in)
                if other is None:
                    counts[f"{label}: dropped: replacement not expressible"] += 1
                    continue
                chosen, rejected = (content, other) if branch == "i > j" else (other, content)
                seen[triple] = label
                made += 1
                counts[f"{label}: pairs ({branch})"] += 1
                out.append({"condition": label, "statement": t.ep["statement"], "path": s,
                            "t_star": tstar, "f": f, "branch": branch,
                            "prompt": body["messages"], "chosen": chosen, "rejected": rejected})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True,
                    help="LABEL=DIR, C (M1 alone) first, then D (with retrieval)")
    ap.add_argument("--cache", required=True, help="the response cache the runs used")
    ap.add_argument("--out", required=True)
    ap.add_argument("--stats", required=True)
    ap.add_argument("--no-root", action="store_true", help="don't open Coq for root states")
    a = ap.parse_args(argv)
    doc_sha, code_sha = preflight()
    runs = [r.split("=", 1) for r in a.run]
    cache = {}
    with open(a.cache) as fh:
        for ln in fh:
            if ln.strip():
                e = json.loads(ln)
                cache[e["key"]] = e
    prompts, seen, counts, out, summary = Prompts(root=not a.no_root), {}, Counter(), [], {}
    proved_c = None
    for label, d in runs:
        aside = Counter()
        trees = load(d, aside)
        for t in trees:
            ps = (t.ep.get("policy") or {}).get("prompt_sha256")
            if ps != prompt_sha256():
                raise SystemExit(f"{d}: an episode ran under prompt {ps}, not this code's "
                                 f"{prompt_sha256()}: its prompts can't be rebuilt here")
        chosen, fc = frontier(trees, proved_c if label != runs[0][0] else None)
        summary[label] = {"trees": len(trees), **{f"set aside: {k}": v for k, v in aside.items()},
                          **dict(fc)}
        out += pairs(label, trees, chosen, cache, prompts, seen, counts)
        if proved_c is None:
            proved_c = {t.ep["statement"] for t in trees if t.proved}
    with open(a.out, "w") as fh:
        fh.writelines(json.dumps(p) + "\n" for p in out)
    proved = sum(v.get("proved", 0) for v in summary.values())
    stats = {"pairs": len(out), "per_proved_tree": round(len(out) / proved, 3) if proved else None,
             "frontier": summary, "counts": dict(sorted(counts.items())),
             "prompt_sha256": prompt_sha256(), "cache_entries": len(cache),
             "doc_sha256": doc_sha, "code_sha256": code_sha}
    with open(a.stats, "w") as fh:
        json.dump(stats, fh, indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
