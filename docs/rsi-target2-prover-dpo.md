# RSI target 2: does the prover improve from its own output? (DPO, then expert iteration)

Written: 2026-10-11
Status: **draft, not frozen.** It's frozen into a `PROTOCOL.md` amendment (v6) after
target 1 reports and before any model call. The pipeline refuses model runs without
that amendment. No A100 time is spent before then.

## What it answers, and what it doesn't

It tests whether M1, the prover model frozen in `PROTOCOL.md` v5, improves at proving
when trained on its own kernel-judged search trees, over iterations, on held-out
statements.

That's a prerequisite for the repo's question (can the system get better at conjecturing),
not the question itself:
- **If target 2 compounds,** a trained conjecturer (target 3) becomes meaningful.
- **If it plateaus at iteration 1,** the finding is that the prover's class is the
  ceiling, and target 3 is off the table until that changes.

## Held out: the frozen v5 test set, never trained on

- `examples/eval_test.txt` (120 statements) and `examples/eval_test_renamed.txt` (its
  variable-renamed copy).
- **Baseline at 600 steps:** M1 alone (C) proved 17; M1 with retrieval (D) proved 26.
- No statement of either set, or equal to one up to bound variable names, appears in any
  training example. The check runs against the training file before each fine-tune, and
  its result is recorded.

## Training source: new statements, M1's own searches

- The v5 records hold M1's only search trees so far, but their statements are the test
  set, so they're excluded.
- **The training pool P:** drawn from `examples/ranker_rest.txt`, the statements target 1
  generated (`make_eval.py --seed 7`, gated `open`, excluded as above) and reserved
  without reading. It's disjoint from target 1's H, T1 and T2, so a ranker carried
  into this target's control never trained on P. The dev set's 29 statements are added.
  Its size is fixed by the cost estimate below.
- Each iteration, the current model (M1, then M1′, …) searches P at 600 steps, alone
  and with retrieval, under the frozen v5 prompt and settings. Those search trees are
  the iteration's data.

## The selection criterion (frontier, not the easy tail)

A statement of P contributes pairs only if the current model's proof of it is on the
frontier, meaning at least one of these:
- the proof was found after more than the median number of steps among that iteration's
  proofs;
- it was proved with retrieval but not without;
- it was proved after re-asking (re-asking is on in v5's settings).

Statements proved within the first 10 steps contribute nothing: they teach the model only
what it already does.

## The DPO pair, pinned

**Why the pair can't be a reordering.** `search.best_first` tries every tactic of a
proposal at each expanded node. A proposal's order matters only at the node where the
proof closes or the budget ends. So a pair that reorders the same five tactics teaches
nothing the search uses. The pair must differ in which tactics the proposal contains.

At a state s on a kernel-accepted proof's path, P is the model's recorded proposal that
contained the on-path tactic t\*: k = 5 tactics in the frozen JSON schema, for the
prompt it was generated from (the first ask at s, or a re-ask, whose prompt lists the
tactics already tried).
- **Chosen response:** P as generated.
- **Rejected response:** P with t\* replaced, in its slot, by a tactic f that was
  attempted at s and failed (an error, refusal or timeout) and isn't already in P. f
  comes from another ask at s. One rejected response per such f, up to 3 per state,
  taking the first in record order.
- A state where every failed tactic is already in P contributes no pair.
- Never-attempted tactics, and tactics that succeeded but led off the proof, aren't used
  as rejected. "Attempted and failed" is the only rejected class.
- **Open until the smoke test:** how many states have such an f depends on how often
  re-asking produces new tactics that fail. The smoke test counts the pairs this rule
  yields. If it's too few for an iteration (a number set in the amendment before the
  count is seen), the amendment says so, and this target doesn't run in this form.

The prompt is P's own prompt under the frozen v5 template, so training and evaluation
use one format.

## The update rule, fixed

- LoRA on `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`;
- rank 16, α 32, dropout 0.05, on the attention and MLP projections;
- DPO with β = 0.1, learning rate 5e-6, 1 epoch;
- the reference model is the iteration's starting model.

These values are pinned in the amendment after a smoke test on 50 pairs confirms the
pipeline runs; the smoke test's loss curve is recorded and doesn't change them. There are
no hand fixes between iterations: the same pipeline runs, on the new model's own trees.

**Iterations:** as many as the A100 budget allows, fixed in the amendment, at most 3.
**Stopping:** if iteration k proves fewer than 3 held-out statements that iteration k−1
didn't (alone and with retrieval combined), or the budget runs out, the loop stops.

## Outcomes

- **Primary:** held-out statements proved per iteration, alone and with retrieval.
  - Exact McNemar of each iteration against the previous one, Holm-adjusted.
  - **The per-statement table:** which test statements each iteration newly proves or
    loses, and with which tactics (in particular, tactics the previous model never
    proposed on that statement).
- **Secondary:**
  - the tactic distribution of proofs and proposals, as top-3 share and normalized
    entropy as in v5, so a real shift can be told from collapse onto majority tactics
    (DPO's known failure);
  - invalid and unproductive rates;
  - the renamed copy, checking that memorization doesn't grow with training.
- **If DPO plateaus at iteration 1:** expert iteration (fine-tuning on the frontier proofs
  themselves) is a separate, separately registered experiment, not a replacement within
  this one.

## Cost, to be measured before freezing

- **The fine-tune itself:** a few thousand pairs of about 2k tokens each. On one A100,
  LoRA in bf16, it's likely on the order of 1–3 hours per iteration. That's an estimate,
  not a measurement.
- **What dominates is search, not training:** M1's searches on P each iteration, plus
  the held-out evaluation (120 statements × 600 steps, alone and with retrieval, as in
  v5's C600 and D600).
- **The amendment fixes the budget from measurement.** A smoke test on 10 statements
  gives wall time per statement, the training step on 50 pairs gives time per pair, and
  units per hour come from the Colab balance page. Iterations are then fixed so the
  total stays within a ceiling the project owner sets. If after 10% of an iteration the
  projection exceeds the ceiling, the run stops and is reported as incomplete.

## Order

Target 1 (`docs/rsi-target1-ranker.md`) reports first. It runs in condition B's setting,
the library retrieval that condition D wraps around M1.
- **If it shows ranking is a binding limit,** this target's retrieval condition uses
  the learned ranker (D with the last ranker that passed target 1's stopping rule), so
  DPO is measured against the stronger baseline.
- **If it shows the limit is elsewhere,** D stays as registered.
