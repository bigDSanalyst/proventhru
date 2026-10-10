# Exploration run 8: structural-tactics/v2, and the stopping rule applied

6 rounds × 80, 600 steps, `--prover structural2`, exhaustive small-list testing on, the
held-out and dev sets excluded, at `8ea7ac5`. Classified with
`tools/classify_opens.py --prover structural2` and `tools/subclassify_opens.py`. Run 7
is shown on the same ladder (`--prover structural`, rechecked as the amendment requires).

| | run 7 (v1) | run 8 (v2) |
|---|---|---|
| lemmas admitted | 111 | **180** |
| derivations | 149 | 164 |
| open statements | 176 | **88** |
| 2 / 2s (compositions of corpus lemmas) | 4 / 66 | 6 / 66 |
| 3v (shapes the run's prover lacked) | 48 | 0 |
| 3 (unexplained) | 54 | **15** |
| proofs citing the corpus (top / inner) | 0 / 0 | **0 / 0** |
| small-list drops (with counterexamples) | – | 4 |

Every corpus lemma is axiom-free. The corpus compile rose from 1.0 s at 51 lemmas to 4.1 s
at 180: not yet a constraint, but growing faster than linearly over rounds 3 to 5.

Run 8's 15 unexplained, subclassified:

| bucket | count | statements |
|---|---|---|
| unknown | 9 | `filter` commuting with `rev` or `removelast` (3), `removelast` after `filter (map S …)` (3), `length (removelast (rev l)) = length (removelast l)`, `skipn (list_max l) l` / `skipn (list_sum l) l` (2) |
| combined | 4 | `firstn` with `filter` or `removelast`: a shape outside v2 |
| library | 1 | needs library inequalities in the chain |
| rev | 1 | |
| interior | 0 | |

## The stopping rule, as written (docs/conjecture-metrics.md, amendment of 2026-10-10)

1. **Inner citations: zero.** At 180 lemmas, no proof in run 8 cites the corpus at all.
2. **Is half or more of the unexplained residue again "another missing tactic shape"?
   No:** 4 of 15 (27%) are a missing shape (combined). The rest are unknown (9), and
   library or rev (2).
3. So neither branch fires: the rule doesn't stop shape-adding for a shape problem,
   because the residue isn't one, and there's no interior bucket to run the model on.

The rule didn't name this case. The plan agreed before it was written, v2 then
saturation, covers it, and no v3 is added.

## What run 8 shows

The open statements are now mostly composition: **72 of 88 (82%)** close by stating two
or more corpus lemmas and calling `lia` (classes 2 and 2s). The fixed prover never does
that, and no run-8 proof cites the corpus. The corpus holds what those proofs need, and
the prover doesn't combine it. Saturation is the step that tests this.

It's also the stronger null you anticipated: zero citations of any kind at 180 lemmas
(run 7: 111).

## Next, under the plan as agreed

Saturation as a prover step, judged by `docs/conjecture-metrics.md`. A composed proof
counts as necessary only if V (`structural-tactics/v2` + library retrieval, no corpus
index) fails on the statement at the same budget. Its target is the 72 composition
statements.

The model experiment (`docs/model-experiment-spec.md`) stays specified and unrun.
