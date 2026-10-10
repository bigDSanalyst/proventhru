"""Where an exploration run used its corpus, round by round.

    python tools/explore_report.py OUT

For each round: lemmas admitted, derivations (each cites the lemma it
follows from, used at the top: intros; pose proof (L l1); lia), and the
corpus lemmas cited inside new proofs, split by position: top, or inner
(after an induction or case split, at a subgoal the statement does not
show). Inner citations are the sign the loop deepens rather than just
closing. Reads corpus.jsonl and round-N/derived.jsonl, so it works on runs
made before rounds.jsonl carried these counts.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru.explore import citation_sites  # noqa: E402


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def main(argv=None):
    out = (argv or sys.argv[1:])[0]
    corpus = _load(os.path.join(out, "corpus.jsonl"))
    rounds = {r["round"]: r for r in _load(os.path.join(out, "rounds.jsonl"))}
    names = set()
    for r in sorted(rounds):
        new = [c for c in corpus if c["round"] == r]
        derived = _load(os.path.join(out, f"round-{r}", "derived.jsonl"))
        sites = [dict(x, statement=c["statement"]) for c in new
                 for x in citation_sites(c["proof"], names)]
        cited = Counter(x for d in derived for x in d.get("cites", []))
        cited.update(x["lemma"] for x in sites)
        print(f"round {r}: {len(new)} admitted; {len(derived)} derived "
              f"({sum(d.get('stage') == 'after_proof' for d in derived)} after proof); "
              f"gate closed {rounds[r].get('known_by_corpus', 0)} with one lemma; "
              f"citations in proofs: {sum(not x['inner'] for x in sites)} top, "
              f"{sum(x['inner'] for x in sites)} inner; corpus compile "
              f"{rounds[r].get('corpus_compile_s', '?')} s")
        for x in sites:
            print(f"    {'INNER' if x['inner'] else 'top  '} {x['lemma']} at tactic {x['index']}: "
                  f"{x['statement']}")
        if cited:
            print("    most cited:", ", ".join(f"{k} ({v})" for k, v in cited.most_common(5)))
        names.update(c["name"] for c in new)


if __name__ == "__main__":
    main()
