# RSI target 1: a lemma ranker that learns from its own proofs

Version: v1
Written: 2026-10-10. A draft first (a19ea21). The code it governs came after the draft
and was reconciled with it before freezing: 4397977, 95d301d and the freezing commit.
Status: draft, under review. It takes effect at the commit that removes this line. That
commit and this file's sha256 go in a `docs/frozen.md` row, which
`tools/ranker_schedule.py` checks before it runs anything, and every target-1 run record
gets a note annotation citing the hash. From then on, changes are dated amendments, and
nothing is amended after a held-out result is seen, except under the bug rule below.

Seeking-layer work: a learned component of the policy, trained on the system's own
output. Nothing in the truth layer changes. One substrate fix comes first (retrieval/v2,
below).

## Done before freezing, and disclosed

- **The statement sets were built.** The first build is superseded: its set files hashed
  the wrong preamble, and it missed twins.
- **The gate was run on H and on `test`,** with each of the two Search parsers. All 420
  statements were `open` both ways.
- **D0 was extracted:** 157 episodes, 1,467 rows, 72 positives.
- **B′ was run on dev.**
- **During the review,** a reviewer ran B in scratch on 100 statements of the superseded
  H (4 proved) and 100 of the superseded T1 (9 proved), with no records kept. 33 of those
  statements are in this H.
- **A smoke test of the pipeline,** on 10 dev statements (dev isn't held out):
  - R1 was fitted on D0. The fit is deterministic, so its weights were seen before
    freezing; no feature or setting was changed after.
  - B′, P0, B′ + R1 and the interleaved run were run on those 10 statements; each proved
    4.
  - Rows were extracted from the R1 run, R2 was fitted on them with D0, and the report
    was generated. On those statements, R1 filled 84.5% of its slots from outside B′'s top
    6.
  - Nothing from H, T1 or T2 was run.

## Why this target, and what it decides

`PROTOCOL.md` v5 found that library retrieval adds nothing net at matched steps. On
`test` at 600 steps, B (fixed tactics plus the top 6 retrieved lemmas) and A (fixed
tactics) both proved 22 of 120, with 9 discordant statements each way. Retrieval gains
list laws that need a lemma and loses arithmetic statements whose steps it spent on
lemmas. The dev check (`results/dev-lemma-forms.md`) found the lemmas ranked first mostly
unrelated to the step needed.

This target asks two questions:
- Does a ranker trained on the system's own kernel-accepted proofs, choosing which library
  lemmas fill retrieval's 6 slots, raise the proof rate on statements it never trained on?
- Does training it again on the proofs it helps produce raise the rate further?

**Scope.** Target 1 measures ranking for the fixed tactics on H's population. Whether a
result carries over to M1 inside D is an assumption it doesn't test.

## What happens after it reports (the owner's decision, fixed now)

- **The pattern extractor becomes the main line of work:** `proventhru/pattern.py`,
  against `docs/pattern-metrics.md` v1.
- **Target 2** (`docs/rsi-target2-prover-dpo.md`, prover DPO) runs behind it, and only if
  this target reads (i) "ranking is a limit" or (iv) "ranking gains are bounded", that is,
  only if the prover shows headroom here. Under (ii), (iii) or (v), target 2 doesn't run in
  its current form.

## Why the B setting, not exploration run 9's

- **Which lemmas are offered matters more than their order.**
  - `search.best_first` tries every candidate of an expanded node in list order (base
    tactics first, then lemma forms), until the budget runs out or a proof closes.
  - Reordering a node's candidates doesn't change how many steps the node costs. It can
    change three things:
    - which tactic is credited with a state two tactics reach (the first in list order);
    - the order in which near-equal children are expanded (scores enter priority as
      −0.01 × score, and B's scores follow the slot);
    - where the step budget cuts.
  - On dev, 5 of 62 successful lemma steps at proof nodes reached a state already seen.
  - So the ranker chooses which lemmas fill the 6 slots, with B's forms. It doesn't
    reorder candidates.
  - The number of lemmas per expansion stays fixed, but the number of lemma tactics
    doesn't: 3 for a statement whose text contains " = ", 1 otherwise. So a ranker can
    move steps between lemmas and the fixed tactics, and that trade is measured.
- **Under run 9's policy, retrieval's library lemmas almost never lie on a proof.**
  - In the retrieval passes of exploration runs 3–9, with each episode counted once, a
    retrieval form of an offered library lemma is the next tactic at 87 of the 471 on-path
    nodes of 151 kernel-accepted proofs.
  - Run 9 accounts for 1 of them (2 counting any mention), in 69 retrieval-pass proofs.
    The fixed passes offer no library lemma.
  - A library ranker tested there would have almost nothing to learn from or to gain.
  - B is the registered condition where library ranking is the documented failure, and
    its retrieval is the one M1 runs inside in condition D.
- **Drift from the aim, flagged.**
  - This target is two steps from conjecturing: it ranks library lemmas for the fixed
    tactics on generated statements, not the system's own discovered lemmas. A ranker over
    the corpus index is left for a later target.
  - Library lemmas are rarely *retrieved* on run 8–9 proofs partly because
    structural-tactics/v2 hardcodes them: `rewrite ?list_max_app, ?list_sum_app,
    ?app_length` (explore.py:194) is in 40 of 191 run-8 and 38 of 255 run-9 proofs, and 38
    and 36 of those fail to compile without it.
  - That's the hand-picked kind of choice the retrospective lists as drift 2.

## The three conditions that make this a self-improvement loop

1. **The training data is the system's own output.** Every example comes from proof
   searches this repository ran, and from iteration 2 on, from searches run under the
   previous ranker.
2. **The judge is non-reciprocal.** A label is positive only if the lemma lies on a
   kernel-accepted proof, and negative only if Coq refused every form of it. Nothing in the
   ranker can change what the kernel accepts.
3. **Improvement is measured on held-out statements,** over a fixed number of iterations,
   with the update rule fixed in advance and no hand fixes between iterations.
   `tools/ranker_schedule.py` runs every step, and the reported result is the whole curve,
   not its best point.

## Statement sets, fixed before any ranker runs

- **Source:** `tools/make_eval.py --n 3000 --seed 7 --max-term 5 --min-size 5
  --max-size 9`. These are v5's parameters; `test` used seed 1.
- **Exclusions,** as twins: equal up to bound variable names, a permutation of the
  variables, and the commutativity of +, *, Nat.max and Nat.min (`proventhru/keys.py`).
  Excluded are:
  - every statement of `eval_test.txt`, `eval_test_renamed.txt` and `eval_open.txt` (149
    up to bound names);
  - every statement searched in the records under `devA200`, `devA30`, `devA30-check`,
    `devA600`, `devB600`, `devforms`, `explore-smoke` and `explore1`–`explore9` (904).

  The record list is written in each set file's header.
- **Gate:** `tools/ranker_sets.py CANDIDATES --records <those> --log GATE_LOG` gates every
  non-excluded candidate (`gate.classify`, coqtop, v5's preamble) and keeps every open
  one. The gate log is committed with the sets. As built on 2026-10-10: 491 excluded, 984
  trivial, 1,525 open.
- **Split:** the open statements are grouped into twin groups, 1,499 of them. The groups
  are shuffled with Python's `random.Random(7)`, in generator order, and dealt whole:
  - **H, held out:** 300, `examples/ranker_H.txt`. No record of a search on H is ever used
    for training.
  - **T1 and T2, training pools:** 300 each, `examples/ranker_T1.txt` and
    `examples/ranker_T2.txt`.
  - **The rest:** 625, `examples/ranker_rest.txt`, reserved for target 2. Target 1 never
    reads it.
- **Composition, measured 2026-10-10:**
  - make_eval samples round-robin over (relation, left head), and the equation groups run
    out after about 600 picks.
  - H has 11 equations in 300, T1 2, T2 5 and the rest 10, against `test`'s 54 in 120.
  - B proved 9 of 100 statements of the superseded T1, against 22 of 120 on `test`.
  - The owner accepted this population. Every reading is about it.
- **Preamble:** every set file's `# preamble:` line is v5's (`Require Import Arith Lia
  List. Import ListNotations.`), and the hash covers it. `docs/frozen.md` records each
  file's sha256 and the output of `proventhru protocol set FILE`. A run whose episodes'
  `preamble_sha256` isn't `d5c6561a…` is invalid.
- **In-run gate:** `pipeline.run` gates every statement again. A statement the in-run gate
  doesn't classify open in some run is listed and dropped from every paired comparison
  involving that run.

## The policy under test

- **Substrate fix, made before iteration 0 (substrate work, not seeking-layer).**
  - After `BackTo`, coqtop prints the root goal after the next command's output, and
    v1's `retrieval.parse` appended it to the last Search entry. That entry then mentioned
    every goal term and ranked first.
  - On dev, 104 of B's 374 lists carry such an entry, 40 of them in the top 6.
  - retrieval/v2 (95d301d) stops at a goal display. v1 is kept unchanged, so v5's B and D
    reproduce.
  - On dev, B′ proves the same 15 of 29 as v1, with the same proofs. The gate's verdicts on
    H and `test` are the same under both parsers.
  - Every run here uses v2, except A (no retrieval) and the one reference run of B v1 on H.
    Target 2 states which version its D uses.
- **B′:** `RetrievalPolicy(FixedTactics(), top=6, version=2)`.
  - 600 steps, expansions unbounded, coqtop, Coq 8.18.0, v5's preamble.
  - v5's per-step limits: Coq `Timeout 5` per tactic and a 30 s hard deadline, the
    `CoqEnv` defaults at the freezing commit, which v5's runs used.
  - Run as `proventhru --backend coqtop run FILE --policy fixed --retrieval 6
    --retrieval-version 2 [--ranker Rk] [--slots …] --budget 0 --step-budget 600 --jobs J
    --out DIR`. `tools/ranker_iterate.py run` builds this command, and every run uses
    J = 3.
- **With a ranker** (`ranker.RankedRetrievalPolicy`):
  - At each node, the ranker scores every lemma in the list `Retriever.lemmas` returns for
    the first goal (the full list, including the per-term fallback).
  - The 6 highest-scoring lemmas fill the slots; ties keep B′'s order.
  - They're offered in score order, with exactly B's forms and B's scores (0.7 − 0.01 ×
    slot). B's forms are `rewrite L.` and `rewrite <- L.` when the statement text Search
    prints contains " = " anywhere, as retrieval.py does, and `apply L.`
  - `cost.ranker` records the pool size and, for each offered lemma, its position in B′'s
    list and its statement text.
- **Policy id:** `retrieval/v2+ranker/<Rk>+fixed-tactics/v1`, where `<Rk>` is the first 16
  hex digits of the sha256 of the fitted ranker's file. The full hash is in
  `identity.retrieval.ranker.sha256`. Ranker files are committed before use.

## The ranker

- **Unit:** a (node, lemma) pair. The node lies on a kernel-accepted proof, and the lemma
  was one of the library lemmas offered there (the proposal record's `cost.lemmas`). The
  corpus lemmas (`pt_` names) in run 3's lists are left out; runs 4–9 had already filtered
  them.
- **Label:**
  - **Positive** if the proof's next tactic at that node equals, as a string, one of the
    forms offered for the lemma there. A tactic that merely names L, such as
    structural-tactics/v2's `rewrite ?list_sum_app`, is not.
  - **Negative** if every form offered for it there was tried there and Coq refused every
    one (session outcome `error`).
  - **Unlabelled** otherwise: a form that timed out, was refused by the guard, succeeded
    off the found path, or wasn't tried. Unlabelled rows are dropped.
  - Unoffered lemmas and off-path nodes carry no label. D0 labels only B's top 6, so every
    D0 label sits at positions 0–5.
- **Features,** fixed now, for a goal G (the node's first goal) and a lemma L (its
  statement as Search prints it):
  1. the share of G's terms (`retrieval.terms`) that L mentions, which is B's own rank
     key;
  2. whether L mentions all of them;
  3. the share of L's own terms that occur in G (the corpus index's criterion);
  4. whether all of them do;
  5. whether L's conclusion is an equation;
  6. whether L's conclusion relation is G's, among `<->`, `=`, `<=`, `<`, `>=`, `>`, `<>`
     and other;
  7. L's number of premises, capped at 3;
  8. the log of L's statement length;
  9. whether a head symbol of either side of L's conclusion is a head symbol of either
     side of G's;
  10. log(1 + min(p, 6)), where p is L's position in the library-only list Search returns
      under v5's preamble (D0 labels only positions 0–5);
  11. whether L's name starts with `Nat.`;
  12. L's usage prior, (positives + 5g) / (labelled rows + 5):
      - g is the positive rate over the rows used: the other four folds for a training row
        (5 folds by statement up to bound names), all training rows at selection time;
      - an unseen name gets g.

  Features 5–7 and 9 use `ranker.py`'s `conclusion()`, `premises()`, `relation()` and
  `heads()` at the freezing commit. Binders are stripped at the top-level comma, and
  premises are the " -> " at bracket depth 0. Features constant over a node are left out,
  since they can't change the order within a node in a linear model.
- **Model:**
  - L2-regularized logistic regression in numpy, with penalty ½‖w‖² (the intercept
    unpenalized) on features standardized on the training rows;
  - fitted by Newton's method until the gradient norm is below 1e-8 (at most 100
    iterations);
  - no class weighting, no other model, no hyperparameter search.
- **Extraction** (`tools/ranker_data.py`):
  - Each episode is read once by id. Rounds 0–5 of exploration run 5 are byte copies of
    run 4's.
  - Each proof's prefix is replayed under the episode's own preamble. The replayed goal at
    each labelled node is checked against the `session.observation` of the step that
    reached it, and a mismatch is dropped and counted.
  - Search is rerun from the session root, never at the node (where it would also list
    local hypotheses). It uses v2's parser with `pt_` names removed, which gives B′'s
    library list under v5's base preamble. Position is the lemma's index in that list.
  - A failed replay, or a recorded lemma missing from the list, is dropped and counted.
    Nodes of B-family records whose recomputed head of the list differs from the recorded
    one are counted per D.
  - A row repeated across runs (same statement up to bound names, same goal, same lemma)
    is kept once. Repeats, and repeats whose labels disagree, are counted.
  - The extracted rows are committed (`results/ranker/D*.jsonl` and `.stats.json`) before
    the model trained on them is fitted.
  - `ranker_iterate.py fit` drops, and counts in the model file, any row whose statement is
    a twin of a statement in `ranker_H.txt`, `ranker_rest.txt`, `eval_test.txt` or
    `eval_test_renamed.txt`.

## Iterations: the update rule, fixed

`tools/ranker_schedule.py` runs these in this order:

| run | policy on H | ranker trained on | then |
|---|---|---|---|
| ref | A (fixed tactics) | — | reference only |
| v1 | B as registered (retrieval/v1) | — | reference only: the parser bug's effect on H |
| 0a, 0b | B′, twice | — | 0b is a determinism check |
| P0 | B′, placebo slots | — | sets θ |
| 1 | B′ + R1 | D0 | B′ + R1 on T1 → D1 |
| 2 | B′ + R2 | D0 + D1 | B′ + R2 on T2 → D2 |
| 3 | B′ + R3 | D0 + D1 + D2 | the interleaved run on H |
| 2p | B′ + R2′ | D0 + D1′ | — |
| 3p | B′ + R3′ | D0 + D1′ + D2′ | — |

- **D0:**
  - the retrieval passes of explore3–9 (`round-*/retrieval/records.jsonl`, each episode
    read once);
  - `runs/devB600/records.jsonl` (11,357 entries, head `e07b1916…`).

  Not `devforms/B`, a content-identical rerun, and nothing in `runs/v1`.
- **0b:** B′ is deterministic. If 0b differs from 0a in any item, the schedule stops and
  the cause is found before iteration 1.
- **P0** (`ranker.PlaceboRetrievalPolicy`): B′'s forms and scores, with the 6 slots filled
  by the lemmas of smallest sha256("0|" + goal + "|" + name). Here goal is the first goal's
  conclusion, with whitespace collapsed.
- **Controls:**
  - B′ is run on T1 (giving D1′) and on T2 (giving D2′).
  - R2′ is fitted on D0 + D1′ and R3′ on D0 + D1′ + D2′, and both are run on H.
  - R2 against R2′ asks whether data from the improved policy teaches more than the same
    statements searched by B′.
- **The interleaved run** (`ranker.InterleavedRetrievalPolicy`), after R3 is fitted:
  - One run on H at 600 steps offers, at each node, the union of B′'s top 6 and R3's top
    6, with B's forms.
  - A lemma's slot is the smaller of its two ranks, with ties going by sha256(goal + "|" +
    name). Scores are 0.7 − 0.01 × slot.
  - Its records are for evaluation only and never enter a D.
- **Every row is always run.** There's no early stop.
- **Plateau, named after the fact:** θ = max(4, 1 + the number of H statements P0 proves
  and 0a doesn't). The plateau is the first k whose net gain over k − 1 (0a for k = 1) is
  below θ. It doesn't stop the loop or enter any reading.
- No record of a search on H, and nothing in `ranker_rest.txt`, ever enters a D.

## Outcomes

- **Primary: the tests run in a fixed sequence.** Each is an exact two-sided McNemar test
  at α = 0.05, and the sequence stops at the first test that isn't rejected:
  1. 3 against 0a;
  2. 3 against 1;
  3. 1 against 0a.
- **Descriptive comparisons,** reported unadjusted and marked descriptive: 2 vs 1, 3 vs 2,
  R2 vs R2′, R3 vs R3′, R1 vs R2′, P0 vs 0a, A vs 0a, and v1 vs 0a.
- **Intervals.** Each comparison reports G, L and a 95% interval for G − L: Clopper–Pearson
  on G out of G + L, scaled to G − L.
- **Power, stated now:** at H = 300, a true net gain of +10 is detected with probability
  about 0.6 at 20 discordant pairs and about 0.3 at 40. A null means the effect is below
  roughly +10 to +15 statements.
- **The per-statement table:**
  - It covers each consecutive pair of iterations and 0a vs 3.
  - It lists every H statement that changes, with its proof, the library lemmas on it, and
    each lemma's position in B′'s order at that node.
  - Each gained statement is classed (a) if its proof uses, at some node, a library lemma
    outside B′'s top 6 there, and (b) otherwise (step reallocation or priority).

  The count is the summary. The per-statement delta is the evidence.
- **Recall@6 and MRR, on the interleaved run:**
  - A reference node is an on-path node of the run's proofs whose next tactic is a form of
    a library lemma L.
  - At each reference node, recall@6 of B′ (or R3) is whether L is in B′'s (R3's) top 6
    there. MRR uses L's rank in that order.
  - B′ and R3 are compared by statement: the mean over the statement's reference nodes,
    with an exact two-sided sign test.
  - Also reported: the reference statements where R3's top 6 holds every reference lemma
    and iteration 3 didn't prove the statement.
  - Below 20 reference nodes, recall is "not measured".
  - The run offers up to 12 lemmas, so it measures what is offered, not what is proved.
    Recall on a policy's own proofs is 1 by construction and isn't reported.
- **Secondary:**
  - lemma tactics per expansion and expansions per statement, for every run;
  - the share of offered slots filled from outside B′'s top 6, and the fitted weights, per
    ranker;
  - A against B′ on H (H is a different, harder population from `test`, so this isn't
    compared with `test`'s 22 vs 22), and v1 against B′ on H;
  - every table also by relation (= and <=), descriptive;
  - **contamination,** fixed once against the statements of D0, T1 and T2: each H statement
    is classed by whether its root term set equals a training statement's, and proof
    deltas are reported by class;
  - extraction drops, repeats and head mismatches, per D;
  - in-run gate drops.

## How the result is read, stated now

The rows are checked in order, and the first that applies is reported. G and L are R3's
gains and losses against 0a, and test (1) is the first test of the sequence above.
- **(i) Ranking is a limit:** test (1) rejected with G > L, and at least half the gained
  statements are class (a).
- **(ii) A gain, not from ranking:** test (1) rejected with G > L, but fewer than half are
  class (a). Reported as a gain from step reallocation or priority.
- **(iii) The learned ranker is harmful:** test (1) rejected with L > G.
- **(iv) Ranking gains are bounded:** test (1) not rejected, and R3 beats B′'s order on the
  interleaved run's recall@6 (sign test p < 0.05).
  - Read as "better ranking at the reference nodes yielded at most U more proofs", where U
    is the upper end of the 95% interval for G − L.
  - The count of reference statements where R3 offered every lemma and didn't prove the
    statement is reported with it.
- **(v) No conclusion about ranking:** otherwise, including recall "not measured". Reported
  as a failure of this learner or this test, not as evidence about ranking.

Self-improvement is read separately:
- **Self-improving loop:** tests (1) and (2) rejected with G > L, and R2 ahead of R2′ and
  R3 ahead of R3′ in net (G − L > 0, each reported with its p and interval).
- **More of the system's own data helps:** (1) and (2) rejected, but R2 or R3 isn't ahead
  of its control. Reported as "a gain consistent with more of the system's own training
  statements; no evidence that the improved policy's output taught more than B′'s".
- **One-shot gain:** (1) rejected, (2) not. A gain from existing data, not a loop.
- R1 against R2′ is reported as the effect of D1′'s statements alone.

Scope: every reading is about the fixed tactics and H's population, which is almost all
inequalities. None says whether ranking limits B on equations (54 of `test`'s 120), or M1
inside D.

## Bug rule, fixed now

A bug found after iteration 0 starts is fixed in a dated commit. Every run the fix could
change is rerun in full under the fix, from the earliest affected iteration, and both
results are reported. Nothing else changes.

## What D0 holds

Extracted at the freezing commit's code on 2026-10-10 (the figures in
`results/ranker/D0.stats.json` are the ones that count):
- 157 episodes, 1,467 rows, 72 positives, over 56 statements and 14 lemmas: list_sum_app
  23, app_length 8, rev_length 7, count_occ_bound 6, list_max_app 6, map_length 5, map_app
  4, and 13 others.
- 278 repeats dropped; nothing else dropped.
- devB600 contributes 213 rows, 11 of them positive. Run 9 contributes 630 rows, none
  positive once repeats are removed.

So positives are few and concentrated, and 41 of the 72 sit at position 0. That's why the
model is small and fixed, why the usage prior is out of fold, and why the loop's own data
(D1, D2) is the part that can teach it something new: every lemma a ranker offers from
outside B′'s top 6 is a lemma that has never been labelled before. R1 learns only from
labels at B′'s top-6 positions, and the lemmas it brings in from outside are labelled only
by the loop, which is why the primary test is R3 against 0a, not R1.

## Not done here

- **Variable slot counts.** A ranker that offers fewer than 6 lemmas when none looks useful
  would save steps for the fixed tactics, which is the trade v5 measured. That's a
  different question from ranking.
- **Off-path negatives:** about 53k all-failed rows at off-path nodes. A separately
  registered variant, if wanted.
- **Ranking the corpus index or saturation:** see the drift note above.
- **Any change to the `test` set,** or to conditions A–D on it.

## Cost

CPU only. B at 600 steps takes about 5 seconds per statement. There are 15 runs of 300
statements, roughly 6 h serially and less with jobs:
- on H: ref, v1, 0a, 0b, P0, iterations 1–3, R2′, R3′ and the interleaved run;
- on T1/T2: B′ + R1, B′ + R2, B′ on T1 and B′ on T2.

The gate took under an hour at 3 jobs, and extraction takes minutes. Cost decided nothing
in this design.
