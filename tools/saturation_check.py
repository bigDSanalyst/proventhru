"""Does saturation prove what the prover alone cannot, and at what cost?

    python tools/saturation_check.py RUN --out OUT [--jobs 4] [--steps 600]

On a finished exploration run (its final corpus as the preamble), three
policies on the run's open statements, paired, at the same step budget:

  P   the run's second-pass policy: structural-tactics/v2, library retrieval,
      the corpus index (one discovered lemma per candidate)
  PS  P plus saturation: one step that states every discovered lemma the goal
      allows, then the closers
  V0  the control of docs/conjecture-metrics.md: structural-tactics/v2 and
      library retrieval, with no corpus index

For every PS proof of a statement P leaves open, the saturation step is
minimized (each stated lemma dropped if the proof closes without it), and the
proof is classified:

  derivation         one corpus lemma plus arithmetic closes it (the
                     derivation check), so not novel
  composed           cites two or more corpus lemmas after minimizing
  necessary          composed, not a derivation, and V0 fails on it
  inner              a corpus lemma cited after an induction or case split

Crowding: every round's retrieval pass replayed exactly, with the corpus that
round saw and that pass's budget (half of --steps), as P and as PS. If PS
proves fewer, saturation spends the budget that simpler steps needed.

Writes OUT/summary.json and OUT/proofs.jsonl. CPU only.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru import record as rec  # noqa: E402
from proventhru.explore import (LEMMA_NAME, CorpusRetrievalPolicy, StructuralTacticsV2,  # noqa: E402
                                citation_sites, corollary, minimize, preamble)
from proventhru.pipeline import RECORD, run  # noqa: E402


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def proved(out_dir):
    return {r["statement"]: r for r in rec.corpus(rec.load(os.path.join(out_dir, RECORD)))
            if r["standing"] == "proved"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--crowding", type=int, default=40)
    ap.add_argument("--backend", default="coqtop")
    a = ap.parse_args(argv)
    corpus = _load(os.path.join(a.run, "corpus.jsonl"))
    pre = preamble(corpus)
    names = {c["name"] for c in corpus}
    opens = [r["statement"] for r in _load(os.path.join(a.run, "opens.jsonl"))]
    policies = {
        "P": lambda: CorpusRetrievalPolicy(StructuralTacticsV2(), corpus),
        "PS": lambda: CorpusRetrievalPolicy(StructuralTacticsV2(), corpus, saturate=True),
        "V0": lambda: CorpusRetrievalPolicy(StructuralTacticsV2(), []),
    }
    got = {}
    for k, f in policies.items():
        d = os.path.join(a.out, k)
        run(opens, d, pre, budget=None, step_budget=a.steps, backend=a.backend, jobs=a.jobs,
            log=lambda *_: None, policy_factory=f)
        got[k] = proved(d)
        print(f"{k}: {len(got[k])} of {len(opens)} open statements proved", flush=True)

    rows = []
    for stmt in sorted(set(got["PS"]) - set(got["P"])):
        proof = minimize(stmt, pre, got["PS"][stmt]["proof"], a.backend)
        cites = sorted(set(LEMMA_NAME.findall(" ".join(proof))) & names)
        derived = corollary(stmt, pre, corpus, a.backend)
        sites = citation_sites(proof, names)
        rows.append({"statement": stmt, "proof": proof, "cites": cites,
                     "derivation": derived, "composed": len(cites) >= 2,
                     "v0_proves": stmt in got["V0"],
                     "necessary": len(cites) >= 2 and not derived and stmt not in got["V0"],
                     "inner": any(x["inner"] for x in sites), "sites": sites})
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "proofs.jsonl"), "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)

    # Crowding: replay each round's retrieval pass exactly, with the corpus
    # that round saw (earlier rounds only) and that pass's budget, as P and as
    # PS. Statements the run already proved can't be rerun under the final
    # corpus: the gate closes them with one corpus lemma (trivial), so they
    # never reach the prover.
    crowd = {"P": 0, "PS": 0, "lost": [], "statements": 0}
    r = 0
    while os.path.isdir(os.path.join(a.run, f"round-{r}")):
        p = os.path.join(a.run, f"round-{r}", "retrieval", RECORD)
        if os.path.exists(p):
            stmts = [x["statement"] for x in rec.corpus(rec.load(p))]
            seen = [c for c in corpus if c["round"] < r]
            got_r = {}
            for k, sat in (("P", False), ("PS", True)):
                d = os.path.join(a.out, f"crowding-r{r}-{k}")
                run(stmts, d, preamble(seen), budget=None, step_budget=a.steps // 2,
                    backend=a.backend, jobs=a.jobs, log=lambda *_: None,
                    policy_factory=lambda: CorpusRetrievalPolicy(StructuralTacticsV2(), seen,
                                                                 saturate=sat))
                got_r[k] = set(proved(d))
                crowd[k] += len(got_r[k])
            crowd["lost"] += sorted(got_r["P"] - got_r["PS"])
            crowd["statements"] += len(stmts)
        r += 1

    summary = {
        "run": a.run, "steps": a.steps, "corpus": len(corpus), "open": len(opens),
        "proved": {k: len(v) for k, v in got.items()},
        "ps_only": len(rows), "p_only": len(set(got["P"]) - set(got["PS"])),
        "ps_only_derivations": sum(bool(x["derivation"]) for x in rows),
        "ps_only_composed": sum(x["composed"] for x in rows),
        "ps_only_v0_proves": sum(x["v0_proves"] for x in rows),
        "necessary_composition": sum(x["necessary"] for x in rows),
        "inner_citations": sum(x["inner"] for x in rows),
        "crowding": {"budget": a.steps // 2, **crowd},
    }
    with open(os.path.join(a.out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
