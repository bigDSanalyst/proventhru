# RSI target 1: a lemma ranker that learns from its own proofs

Version: v1
Written: 2026-10-10, before any ranker code exists
Status: draft, under review. It takes effect at the commit that removes this line; from
then on, changes are dated amendments, and nothing is amended after a held-out result
is seen.

Seeking-layer work: a learned component of the policy, trained on the system's own
output. Nothing in the truth layer changes.

## Why this target, and what it decides

`PROTOCOL.md` v5 found that library retrieval adds nothing net at matched steps. On
`test` at 600 steps, B (fixed tactics plus the top 6 retrieved lemmas) and A (fixed
tactics) both proved 22 of 120, with 9 discordant statements each way. Retrieval gains
list laws that need a lemma and loses arithmetic statements whose steps it spent on
lemmas. The dev check (`results/dev-lemma-forms.md`) located the loss: the lemmas
retrieval ranks first are mostly unrelated to the step needed (`Nat.even_0` for a goal
mentioning `Nat.even`), and no tactic form helps.

This target asks: does a ranker trained on the system's own kernel-accepted proofs,
choosing which library lemmas fill retrieval's 6 slots, raise B's proof rate on
statements it never trained on? And does training it again on the proofs it helps
produce raise it further?

Its result decides how the prover's limit is read before any A100 time goes to target 2
(`docs/rsi-target2-prover-dpo.md`): is the limit which lemmas are offered (ranking), or
what the policy does with them?

## Why the B setting, not exploration run 9's

Two facts about the code and the records decided this. Both were checked before writing.

- **Order within a node doesn't decide what's proved.** `search.best_first` tries every
  candidate at each expanded node, in list order, until the step budget runs out or a
  proof closes. Reordering a node's candidates changes only which tactic runs first,
  which matters only at the node where the proof closes or the budget ends. So the
  ranker doesn't reorder candidates. It chooses which lemmas are offered at all, from
  the full list `Search` returns, keeping the number of slots and the tactic forms per
  lemma fixed. Steps per expansion stay matched.
- **Under run 9's policy, library lemmas almost never lie on a proof.** In the records
  of exploration runs 3–9, library lemmas are on 112 of the 2,151 on-path nodes of
  1,171 kernel-accepted proofs. Run 9 accounts for 2 of them, in 255 proofs; there the
  corpus index, saturation and the structural tactics do the work. A library ranker
  tested there would be null by construction. B is the registered condition where
  library ranking is the documented failure, and it's the retrieval M1 runs inside in
  condition D, which target 2 builds on.

## The three conditions that make this a self-improvement loop

1. **The training data is the system's own output.** Every example comes from proof
   searches this repository ran, and from iteration 2 on, from searches run under the
   previous ranker.
2. **The judge is non-reciprocal.** A label is positive only if the lemma lies on a
   kernel-accepted proof. Nothing in the ranker can change what the kernel accepts.
3. **Improvement is measured on held-out statements,** over a fixed number of iterations,
   with the update rule fixed in advance and no hand fixes between iterations. The
   reported result is the whole curve, not its best point.

## Statement sets, fixed before any ranker runs

- **Source:** `tools/make_eval.py --n 3000 --seed 7 --max-term 5 --min-size 5
  --max-size 9`. That's v5's generator and parameters with a new seed; `test` used
  seed 1. Then `tools/gate_eval.py --backend coqtop` keeps the statements the gate
  leaves `open`, under v5's preamble (`Require Import Arith Lia List. Import
  ListNotations.`).
- **Exclusions, up to bound variable names:** every statement of `eval_test.txt`,
  `eval_test_renamed.txt` and `eval_open.txt`.
- **Split:** the remaining statements, in a shuffle seeded with 7, are split into:
  - **H, held out:** the first 300, written to `examples/ranker_H.txt`. No record of a
    search on H is ever used for training.
  - **T1 and T2, training pools:** the next 300 and the next 300, written to
    `examples/ranker_T1.txt` and `examples/ranker_T2.txt`.
  - **The rest,** written to `examples/ranker_rest.txt`. It's reserved for target 2's
    pool, and target 1 never reads it.
  - If fewer than 900 statements survive, H keeps 300, and T1 and T2 split the rest
    equally.
- All four files are hashed into `docs/frozen.md` (with `proventhru protocol set`)
  before iteration 0 runs.

## The policy under test

- **Base:** B as registered in v5: `RetrievalPolicy(FixedTactics(), top=6)`, 600 steps,
  expansions unbounded, the `coqtop` backend, Coq 8.18.0, v5's preamble, and v5's
  per-step timeout.
- **With a ranker:**
  - At each node, the ranker scores every lemma in the list `Retriever.lemmas` returns
    for the first goal (the full list, including the per-term fallback).
  - The 6 highest-scoring lemmas fill the slots; ties keep the original order.
  - They're offered in score order, with exactly B's forms (`rewrite`, `rewrite <-` for
    equations, `apply`) and B's scores (0.7 − 0.01 × slot), so node priorities follow
    the same rule.
  - Nothing else in the policy changes.
- **The policy id** is `retrieval/v1+ranker/<Rk>+fixed-tactics/v1`, where `<Rk>` is the
  sha256 of the fitted ranker's weights file, which is committed.
- **Jobs:** all runs use the same `--jobs` setting, recorded with the results.

## The ranker

- **Unit:** a (node, lemma) pair, where the node lies on a kernel-accepted proof and the
  lemma was one of the library lemmas offered there (the proposal record's
  `cost.lemmas`). The corpus lemmas (`pt_` names) in runs 3–7's lists are left out.
  B has no corpus.
- **Label:**
  - **positive** if a tactic built from the lemma is the proof's next tactic at that
    node;
  - **negative** if every form of the lemma was tried at that node and none is the
    proof's next tactic;
  - **unlabelled** otherwise: forms left untried because the proof closed or the budget
    ran out first. Unlabelled rows are dropped.
  - Lemmas in `Search`'s list that weren't offered carry no label.
  - Nodes off the proof path aren't used.
- **Features,** fixed now, for a goal G (the node's first goal) and a lemma L (its
  statement as `Search` prints it):
  1. the share of G's terms (`retrieval.terms`) that L mentions, which is B's own rank
     key;
  2. whether L mentions all of them;
  3. the share of L's own terms that occur in G (the corpus index's criterion);
  4. whether all of them do;
  5. whether L's conclusion is an equation;
  6. whether L's conclusion relation (`=`, `<=`, `<`, other) is G's;
  7. L's number of premises (`->` before the conclusion), capped at 3;
  8. the log of L's statement length;
  9. whether a head symbol of either side of L's conclusion is a head symbol of either
     side of G's;
  10. log(1 + L's position in B's order);
  11. whether L's name starts with `Nat.`;
  12. L's usage prior, (positives + 0.5) / (labelled rows + 5) for L's name in the
      training rows:
      - out of fold for the training rows (5 folds by statement, so a row never sees its
        own label);
      - on all training rows at selection time;
      - the global rate for a name not seen in training.

  Features constant over a node (goal size, depth, number of goals) are left out, since
  they can't change the order within a node in a linear model.
- **Model:**
  - L2-regularized logistic regression in numpy, with penalty ½‖w‖² (the intercept
    unpenalized) on features standardized on the training rows;
  - fitted by Newton's method until the gradient norm is below 1e-8 (at most 100
    iterations);
  - no class weighting, no other model, no hyperparameter search.
- **Feature extraction from old records:**
  - Proposal records hold the offered lemma names, not the goal text. So each proof's
    prefix is replayed under the episode's own preamble, from the episode record, to
    read the goal at each on-path node.
  - At the same node, `Search` is rerun to recover each lemma's statement and its
    position in B's order.
  - A replay that fails, or whose `Search` list doesn't contain the recorded lemmas, is
    dropped and counted.
  - The extracted rows are committed (`results/ranker/D*.jsonl`) and hashed in
    `docs/frozen.md` before the model trained on them is fitted.

## Iterations: the update rule, fixed

| iteration | policy on H | ranker trained on | then |
|---|---|---|---|
| ref | A (fixed tactics) | — | reference only |
| 0a, 0b | B, run twice | — | the two runs measure run-to-run noise |
| 1 | B + R1 | D0: runs 3–9 retrieval passes, and B's dev runs at 600 steps | run B + R1 on T1, giving D1 |
| 2 | B + R2 | D0 + D1 | run B + R2 on T2, giving D2 |
| 3 | B + R3 | D0 + D1 + D2 | stop |

- **The control for self-generated data:**
  - B (no ranker) is also run on T1, giving D1′, and R2′ is fitted on D0 + D1′ and run
    on H.
  - R2 against R2′ asks whether data from the improved policy helps more than the same
    statements searched by the unimproved one.
- **Stopping:** let θ be 4, or, if larger, one more than the number of H statements
  that 0b proves and 0a doesn't. If iteration k proves fewer than θ H statements that
  iteration k−1 didn't (0a for k = 1), the loop stops after k, and that's reported as
  the plateau.
- No record of a search on H, and nothing in `ranker_rest.txt`, ever enters a D.

## Outcomes

- **Primary:** H statements proved per iteration.
  - Exact two-sided McNemar tests: 1 against 0a; 2 against 1; 3 against 2; and 3
    against 1, the gain beyond the first round. They're Holm-adjusted over the tests
    actually run.
  - **A per-statement table:** each H statement that changes between consecutive
    iterations, with:
    - the proof;
    - the library lemmas on it;
    - for each, its position in B's order at that node, which says whether the ranker
      brought in a lemma B's top 6 left out.

    The count is the summary. The per-statement delta is the evidence.
- **Secondary:**
  - **Recall@6 and mean reciprocal rank** of on-path library lemmas under B's order and
    under each ranker. These are computed on every on-path node of every H proof found
    by any iteration, replayed. This separates "the ranker ranks better" from "better
    ranking proves more".
  - A against B on H: does retrieval add anything here at all? (On `test` it didn't.)
  - R2 against R2′ (the control above), by McNemar.
  - Steps to proof on H statements proved by both iterations compared.
  - **Contamination:** each H statement's nearest training statement, by the Jaccard
    index of their term sets. Proof deltas are reported split by whether that index
    is 1.
  - Replays dropped in extraction, per D.

## How the result is read, stated now

- **Ranking is a limit:** the Holm-adjusted McNemar test of iteration 1 against 0a is
  significant at 0.05, with more statements gained than lost.
- **Ranking is not the binding limit:** recall@6 of on-path lemmas improves under R1,
  but the proof test isn't significant. The ranker offers the needed lemmas more
  often, and that doesn't turn into proofs, so the limit is elsewhere: in what the
  policy does with the lemmas. That's the ground target 2 stands on.
- **No conclusion about ranking:** recall@6 doesn't improve. This ranker class didn't
  learn to rank, and the question stays open. It's reported as a failure of this
  learner, not as evidence about ranking.
- **Self-improvement:** iterations 2 and 3 each pass the stopping threshold, and 3
  against 1 is significant after adjustment. One iteration of gain followed by a
  plateau is a one-shot gain from existing data, not a self-improving loop, and is
  reported as that.

## What D0 holds, as of writing

Counted from the run records on 2026-10-10. Extraction recounts and records the exact
figures.
- Exploration runs 3–9: 1,171 kernel-accepted proofs, 2,151 on-path nodes. Of those
  nodes, 535 had library lemmas offered, and 112 had one on the path. Most of the 112
  are a few list lemmas (`list_sum_app` 50, `map_app` 12, `list_max_app` 7).
- B's dev runs: `eval_open.txt`, 15 of 29 proved at 600 steps.

So positives are few, and concentrated. That's why the model is small and fixed, why
the usage prior is out of fold, and why the loop's own data (D1, D2) is the part that
can teach it something new: every lemma a ranker offers from outside B's top 6 is a
lemma that has never been labelled before.

## Not done here

- **Variable slot counts.** A ranker that offers fewer than 6 lemmas when none looks
  useful would save steps for the fixed tactics, which is the trade v5 measured. It's a
  different question from ranking.
- **Ranking the corpus index or saturation.** These belong to exploration, not B.
- **Any change to the test set,** or to conditions A–D on it.

## Cost

CPU only, and small. B at 600 steps took about 5 seconds per statement on dev and
`test`. The runs are A, 0a, 0b, iterations 1–3 on H, the three T runs and R2′, about
10 runs of 300 statements, roughly 4 hours serially, less with jobs. Replaying D0's
proofs is the larger cost. Cost decided nothing in this design.
