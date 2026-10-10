# Registered result: M1 against the fixed baselines on the held-out set

Run under `PROTOCOL.md` v5 (sha256 `7ab3c8f76a529001bc317220d8d22ddcdafb15602375904ed512bebc868e529b`,
commit `8ddcc48`). Coqtop, Coq 8.18.0. M1 = `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`,
vLLM 0.31.0, bf16, temperature 0, seed 0, k = 5, re-asking up to 3 times per state,
prompt `e26d4a77…`. 120 statements of `examples/eval_test.txt`. Every record
verifies, every episode cites v5, and no condition has an incomplete episode.
See Deviations for the one bug found during these runs, and what was rerun because of it.

## Primary: 600 steps, paired, exact McNemar, Holm over two

| comparison | proved | only the first | only the second | p | Holm-adjusted p |
|---|---|---|---|---|---|
| **C vs A** (model alone vs fixed tactics) | 17 vs 22 | 4 | 9 | 0.267 | 0.53 |
| **D vs B** (model + retrieval vs fixed + retrieval) | 26 vs 22 | 6 | 2 | 0.289 | 0.53 |

**Neither primary comparison is significant.** C proves 5 fewer statements than A,
and D proves 4 more than B. At 120 statements these differences can't be told
from chance (see Limitations). Under the protocol, M2 is not run: it was to
be a replication of a significant M1 effect, and there is none.

The direction of D vs B on test (26 vs 22) is the reverse of dev (12 vs 15).
Dev was 29 statements, and both differences are within noise.

## Secondary

**Retrieval-solved vs retrieval-unsolved.** A statement is retrieval-solved if B proves it at
600 steps (22 statements). The rest (98) are retrieval-unsolved.

| condition | retrieval-solved (22) | retrieval-unsolved (98) | total |
|---|---|---|---|
| A, fixed | 13 | 9 | 22 |
| B, fixed + retrieval | 22 | 0 | 22 |
| C, model alone | 10 | 7 | 17 |
| D, model + retrieval | 20 | 6 | 26 |

C proves 7 statements B cannot, and D proves 6. A, without retrieval, proves 9
that B cannot. So where retrieval doesn't reach, the model alone does no better
than the fixed list: 7 against 9. Across all four conditions, 37 distinct
statements are proved. A ∪ C covers 26 and B ∪ D covers 28: the conditions
overlap only partly, so combining sources would cover more than any one.

**Budget used.** At 600 steps, A and B used their full budget in every unproved search.
C ran out of candidates in 66 of its 103 unproved searches. D ran out in 14 of 94.
C's loss to A is partly a policy that cannot spend the effort it is matched on,
not one that spent it and lost.

| | steps | invocations | candidates per call | ended: proved / step budget / frontier |
|---|---|---|---|---|
| A | 62,661 | 3,626 | 17.65 | 22 / 98 / 0 |
| B | 61,876 | 1,922 | 33.38 | 22 / 98 / 0 |
| C | 33,048 | 13,579 | 4.95 | 17 / 37 / 66 |
| D | 55,272 | 5,514 | 20.6 | 26 / 80 / 14 |

C needed 3.7 times A's policy invocations and still took about half A's steps.

**Failures of the model's own tactics** (api / invalid / unproductive):
- C: 0 api failures; 614 invalid candidates (under 1% of those emitted);
  27,330 of 33,048 steps unproductive (83%).
- D: 14,469 of the model's 16,507 steps unproductive (88%). D's other 38,765 steps
  were retrieval's.

**Memorisation (Q3).** C on `test` 17, C on `test_renamed` 15, with 4 and 6 discordant,
p = 0.75. No sign that the model relies on surface forms. The test can only
detect large effects.

**2000 steps** (M1's comparisons at the high budget).
- C2000 vs A2000: 18 vs 26, with 2 only C and 10 only A, p = 0.039. This is
  unadjusted and secondary, so it is not a confirmatory test. It is consistent
  with the primary direction: given more budget, the fixed list gains and the
  model mostly can't use it (88 of C's 102 unproved searches ended by frontier).
- D2000 vs B2000 is not reported. The D2000 record was affected by the bug below
  and was not rerun (Deviations).

**Tactic distributions.**
- C's proofs: top-3 share 0.66 and normalised entropy 0.83 (`simpl`, `induction`, `lia`).
- A's proofs: 0.61 and 0.91.
- Not a collapsed policy.

## Deviations

1. **A coqtop backend bug, found during these runs, fixed, and measured.** Coq prints the
   same "Toplevel input, characters …" header before a deprecation warning as before an
   error, and the session treated that header as an error. So a tactic that succeeded
   while naming a deprecated lemma was recorded as a failure, and coqtop's real state
   moved on while the session's path did not.

   It surfaced as a crash in D600 and D2000: a replay failed on one statement. It was
   reproduced step for step from the record (`rewrite le_plus_r.`, deprecated since 8.16,
   succeeded and was recorded as an error). It was fixed in `a6b163f`. The session now
   also refuses to continue if coqtop's state moves on what it classified as an error.

   `tools/deprecated_impact.py` replays every step the bug could have touched, with the
   fixed session:

   | record | suspect steps | hidden successes | episodes affected | source |
   |---|---|---|---|---|
   | A600, A2000 | 0 | 0 | 0 | – |
   | B600 / B2000 | 6 / 40 | 0 / 0 | 0 / 0 | – |
   | C600, C600r, C2000 | 0 | 0 | 0 | – |
   | D600 | 13 | 2 | 2 (both unproved) | the model |
   | D2000 | 44 | 2 | 2 (both unproved) | the model |

   The gate, rerun with the fixed session, classifies all 120 test and 29 dev statements
   as before. So the test set is unaffected.

   Rule applied, set before the rerun's result was known: a condition with any hidden
   success is rerun in full. D600 was rerun with the fixed code as `D600fix`
   (commit `812ade7`; unaffected episodes made the same cached model requests). The old
   D600 record is superseded. D600 proved 26 and D600fix proves 26. D2000 is secondary,
   and it was superseded and not rerun, to save compute.

   Proofs were never at risk: every proved outcome is certified by the kernel from the
   recorded path in a fresh compile.

2. **GPU variant.** Dev ran on an A100-SXM4-40GB. The test model runs ran on an
   A100-SXM4-80GB, whichever Colab assigned. Same GPU class, bf16, same vLLM, as v3
   requires. Every record's provider field names the GPU.

3. **Interrupted model runs.** The vLLM server stopped once, when a cell was stopped.
   The episodes it cut short are recorded as incomplete (`policy_unavailable`) and are
   not counted; the run resumed from Drive. That's why the C600 record holds more
   episode entries than 120. Each statement counts once, by its latest complete episode.

4. **Pre-registration is not externally witnessed.** The protocol's hashes and commits
   show that what ran matches what was committed. They don't prove *when* it was
   committed. Commit times are on GitHub, but no independent timestamp was taken.

## Records

Heads, `(entries, hash of the last entry)`, from `proventhru verify`. The records are in
the project's Drive folder `proventhru/runs/`.

| record | head |
|---|---|
| test-A600 | 66,527 `8e1b0c84…9217` |
| test-B600 | 64,038 `34c62be9…db5d` |
| test-A2000 | 206,627 `a9c41cc4…5720` |
| test-B2000 | 197,037 `9cce9d1b…412f` |
| test-C600 | 50,281 `40f44a2f…c7c1` |
| test-D600fix | 61,026 `e30e73a0…1688` |
| test-C600r | 41,931 `4da67139…5599` |
| test-C2000 | 92,745 `ea6e28bc…2da1` |

## What this shows, and what it doesn't

At matched effort on 120 generated list and arithmetic statements, a 7B open
model is not detectably better or worse than a fixed tactic list, with or
without retrieval.

Two signals point the same way:
- the model's own tactics fail 83–88% of the time;
- without retrieval, its search runs out of ideas before the budget.

The likeliest source of gains is combining sources rather than replacing one
with another: the four conditions together prove 37 statements, while the best
single one proves 26.

This agrees with earlier Coq work, where learned or LLM provers alone trail
automation and add most in combination (ASTactic with CoqHammer; Tactician with
CoqHammer; CoqPilot; LLM2Ltac). The natural next condition is the model's
candidates *added to* B, under its own amendment.

**Limitations.**
- At 120 statements only large effects are detectable. Non-significant results here
  mean an effect is smaller than this study can see, not that there is none.
- The statements come from one generator over one signature.
- One prover version.
- One model.
