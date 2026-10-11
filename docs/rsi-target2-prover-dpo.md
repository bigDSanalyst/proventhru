# RSI target 2: does the prover improve from its own output? (DPO)

Written: 2026-10-10. Edited 2026-10-11: the adversarial review's edit plan of 2026-10-10 is
applied, since target 1 read (i) and this target now runs.
Status: **draft, not frozen.**
- It's frozen after target 1 reports and before any model call on P or `test`.
- Its numbers go into the next `PROTOCOL.md` amendment: v6, unless another amendment freezes
  first. `docs/model-experiment-spec.md` also names v6.
- No A100 time was spent before target 1 reported. After it, the only A100 time before the
  amendment is the smoke test, capped at U_smoke.

Seeking-layer work: the policy's learning step, trained on its own kernel-judged search
trees. Nothing in the truth layer changes.

Drift, stated: P comes from the nat / list nat generator, where nine exploration runs found
no inner citation. Target 3 names its own signature.

`PROTOCOL.md` v5 named DPO, then GRPO. On the owner's pin, the follow-up to DPO is expert
iteration, registered separately.

## What it answers, and what it doesn't

It tests whether M1, the prover model frozen in `PROTOCOL.md` v5, improves at proving when
trained on its own kernel-judged search trees, over iterations, on held-out statements.

That's a prerequisite for the repo's question (can the system get better at conjecturing),
not the question itself:
- **If target 2 compounds,** a trained conjecturer (target 3) becomes meaningful.
- **If DPO doesn't improve M1, or plateaus at iteration 1,** the finding is about DPO with this
  pair rule and this update rule: no gain larger than about 6–8 of 120 appeared. It doesn't
  show that M1's class is the ceiling. Expert iteration comes next, and target 3 waits for it.

## Held out: the frozen v5 test set, never trained on

- `examples/eval_test.txt` (120 statements) and `examples/eval_test_renamed.txt` (its
  variable-renamed copy).
- **Baseline at 600 steps:** M1 alone (C) proved 17; M1 with retrieval (D, D600fix) proved 26.
- **Iteration 0** is M1 rerun under the amendment with v5's response cache: C and D on `test`,
  and C on `test_renamed`, at 600 steps.
  - They must reproduce 17, 26 (D600fix) and 15, item for item. Otherwise the difference is
    reported and investigated before any iteration is read.
  - An arm with other retrieval (D+R3) gets its own iteration-0 run.
  - An uncached C run on `test` measures run-to-run noise.
  - If the cache is unavailable, the A100 cost of these runs comes out of the budget.
- **No twin of a `test` or `test_renamed` statement is in P.** `ranker_sets.py` excludes them;
  the first build left 3 in `rest`, and the rebuild has 0.
- **Before each fine-tune,** every goal in every training prompt is re-quantified over its free
  variables, with their types taken from the hypotheses, and its key is compared with the test
  statements' keys. Matches are dropped and counted, and the fine-tune starts only from the
  filtered file.

## Training source: new statements, M1's own searches

- M1's recorded trees are v5's test runs, which are excluded, and dev rounds 3–5 (Drive
  `runs/dev-{C,D}600-p*`). Round 5 ran under the frozen prompt and settings
  (`dev-{C,D}600-pe26d4a77`).
- **P** is the 29 dev statements plus the first N statements of `examples/ranker_rest.txt` in
  file order (625 as built), with 200 ≤ N ≤ 625.
- A carried ranker saw P's 29 dev statements (devB600 is in D0), and none of the rest.
- Every P search runs with `--cache`.
- Each iteration, the current model (M1, then M1′, …) searches P at 600 steps, alone and with
  retrieval, under the frozen v5 prompt and settings. Those search trees are the iteration's
  data.

## The selection criterion: the frontier, not the easy tail

A proved tree (C and D separately) is on the frontier if any of these holds:
1. its proof took more steps (`stats.steps`) than the median over proved trees of the same
   condition in the same iteration;
2. it's a D tree of a statement C didn't prove that iteration;
3. some on-path step's proposal isn't the first proposal at its path, so the tactic came from a
   re-ask.

A tree proved in 10 steps or fewer is excluded, whatever 1–3 say. Pairs come only from
frontier trees, each tree on its own. Counts per criterion are reported.

## The DPO pair, pinned

**Why the pair can't be a reordering.** A proposal's order changes four things:
- which tactic runs first at that node;
- the order its children are expanded, through the score's 0.01 weight in priority;
- which failure later prompts show as `last_failure`;
- which path first reaches a repeated state.

It doesn't change which tactics are tried at that node, unless the proof closes or the budget
ends there. A pair that only reorders the same five tactics mostly teaches those side effects.
So a pair must differ in which tactics the proposal contains.

**Terms.**
- A proposal's **model response** is its candidates that aren't in `cost.added`, in their
  slots. Slot = 5 × (1 − score), and `cost.dropped` entries fill the missing slots in order.
- **"As generated"** means the cached response's message content for `cost.cache_key`.
- At an on-path state s of a frontier tree, **t\*** is the on-path tactic, and **j** is the ask
  whose proposal the on-path step names.

**The rule.**
- t\* must be in P_j's model response. A state whose t\* was appended by retrieval yields no
  pair. These states are counted per iteration, for C and for D.
- **f** is a tactic in the model response of another ask i ≠ j at s, which ran at s and which
  Coq refused (session outcome `error`).
  - Timeouts (undecided, per `env.py`), guard refusals (invalid, per `PROTOCOL.md`) and
    retrieval's failed lemmas aren't used. Each is counted.
- **If i > j:** the prompt is P_j's prompt; chosen = P_j as generated; rejected = P_j with t\*
  replaced in its slot by f (f not already in P_j).
- **If i < j** (f is in P_j's `tried_here`): the prompt is P_i's prompt; rejected = P_i as
  generated; chosen = P_i with f replaced in its slot by t\*.
- **Limits and counts:**
  - Replacements are made at the JSON level.
  - There are up to 3 pairs per state, taking the first in record order.
  - Each branch is counted per iteration.
  - A triple found in both the C and the D trees counts once.
- Refused by Coq is the only rejected class.

**Prompts are verified.**
- Every run that yields pairs runs with `--cache`. The cache is kept with the records and
  hashed into `docs/frozen.md` (Drive `cache/m1.jsonl` for v5 and dev round 5).
- A prompt is rebuilt with `view.state` from three things:
  - the node's recorded observation (the root's from a fresh session);
  - the episode's latest refused or timed-out step before the proposal;
  - the tactics tried at that path before it.
- A rebuilt prompt is used only if sha256(canon({url, body})) equals `cost.cache_key`. Pairs
  that don't verify are dropped and counted.

The prompt is the proposal's own prompt under the frozen v5 template, so training and
evaluation use one format.

**Pair yield, counted before any A100 time.**
- The rule is applied on CPU to the round-5 dev C and D records and reported. Dev was the
  tuning set, so its yield may run high.
- **N_min = 500 pairs per iteration** is fixed here, before that count. It's projected to |P|
  from dev pairs per proved tree.
- Below N_min, this target doesn't run in this form.

## The update rule, fixed

- **The model and adapter:**
  - LoRA on `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`;
  - rank 16, α 32, dropout 0.05, on the attention and MLP projections.
- **DPO:**
  - β = 0.1, learning rate 5e-6, 1 epoch;
  - sigmoid loss, no label smoothing.
- **Training settings:**
  - effective batch size (per-device batch × accumulation), fixed in the amendment;
  - max length 3,072 tokens;
  - AdamW (β 0.9/0.999, weight decay 0), a linear schedule with 10% warmup;
  - data seed 0, bf16, gradient checkpointing;
  - exact trl, peft, transformers and torch versions, pinned in the amendment.
- **One adapter, continued.** Iteration k starts from adapter k − 1. Its reference model is the
  base plus adapter k − 1, frozen. This keeps `PROTOCOL.md`'s "plus each stage's adapter".
- **Serving:**
  - M_k is served by the registered vLLM, in bf16, on the registered GPU class, with
    `--enable-lora`, as `Qwen/Qwen2.5-7B-Instruct@a09a3545…+dpo-it<k>`.
  - The amendment registers k = 1..3 in its models, and the D+R3 policy id.
  - Before any held-out run of M_k, adapter k's sha256 is written to `docs/frozen.md`, and
    `--provider` carries it.
  - A record whose `cost.served_model` doesn't match its identity's model isn't counted.
- **Code:** the amendment pins the training and serving code by commit.
- **Bug rule:** as in target 1.

These values are pinned in the amendment after a smoke test on 50 pairs confirms the pipeline
runs. The smoke test's loss curve is recorded and doesn't change them. There are no hand fixes
between iterations: the same pipeline runs on the new model's own trees.

**Iterations:** K, fixed in the amendment by the cost rule below, at most 3.

**Stopping.**
- A held-out statement counts as proved by an iteration if C or D proves it.
- θ = max(7, 1 + the test statements the uncached iteration-0 C run proves and the cached one
  doesn't). 7 is one more than v5's largest one-sided discordance between C on `test` and C on
  `test_renamed`.
- **The rule (OWNER'S DECISION PENDING: gains, as pinned, or net):**
  - gains: the loop stops after k if k proves fewer than θ statements of this union that
    k − 1 didn't;
  - net: it stops if k's net gain over k − 1 is below θ.

  Whichever rule is chosen, net gain is reported with it.
- A budget stop is reported as incomplete, never as a plateau.

## Outcomes

- **Primary:** held-out statements proved per iteration, alone and with retrieval.
  - **The per-statement table:** which test statements each iteration newly proves or loses,
    and with which tactics, in particular tactics the previous model never proposed on that
    statement.
  - **Manipulation check, every iteration:**
    - how many of the 120 test statements' first root proposals (path [], empty `tried_here`)
      in held-out C differ between M_k and M_{k−1};
    - DPO reward accuracy and mean margin.

    If fewer than 5 differ, the iteration is reported as "the update didn't move the policy"
    and isn't read as a plateau.
- **Secondary:**
  - the tactic distribution of proofs and proposals, as top-3 share and normalized entropy as
    in v5, so a real shift can be told from collapse onto majority tactics, which we test for;
  - invalid and unproductive rates;
  - C on `test_renamed` every iteration, by McNemar against C on `test` in the same iteration.
    A widening gap shows reliance on variable names learned from P;
  - the share of searches that ran out of candidates, and the share of re-ask candidates
    already in `tried_here`, per iteration and condition;
  - **contamination:** test statements split by whether P has one with the same term set, or
    one within token edit distance 1;
  - pair, branch and drop counts; tokens, calls and wall time.

## How the result is read, stated now

- **The improvement family:** iteration 1 vs 0, for C and for D, Holm over 2.
- **The compounding family:** k vs k − 1 for k = 2..K, and K vs 1, for C and D. Holm runs over
  all of them, whether or not they run; a test that isn't run enters with p = 1.
- **The tests:** all exact two-sided McNemar at α = 0.05, with G, L and the G − L interval as in
  target 1. Final vs M1 is a secondary, outside both families.

Readings, first that applies:
- **Compounds:** the improvement family is rejected with G > L, and K vs 1 (2 vs 1 if K = 2) is
  rejected with G > L.
- **Improves, then plateaus:** improvement is rejected, but compounding isn't shown.
- **No improvement:** otherwise. Reported as "DPO with this pair rule didn't improve M1".
  Expert iteration follows, separately registered.
- **Collapse** is reported alongside any of these: normalized entropy falls by at least 0.1,
  and top-3 share rises by at least 0.1, without a significant gain.
- **A budget stop** is reported as incomplete, and supports no conclusion about target 3.

## Cost, measured before freezing the amendment

- **The budget:** U = 97 A100 units, less the 30 that `docs/model-experiment-spec.md` reserves,
  unless that spec is withdrawn in a dated commit (OWNER'S DECISION PENDING: U = 67 or 97).
- **What's spent:**
  - per iteration: the P search (C and D), the fine-tune, and held-out C, D and C on
    `test_renamed` (plus D+R3);
  - once: iteration 0's runs.
- **Time per call** comes from v5's records (`cost.model_ms`, `stats.seconds`), time per pair
  from the smoke test, and units per hour from the Colab page.
- **The rule:**
  - N_lo is the smallest N ≥ 200 whose projected pairs reach N_min.
  - K = 3 if three iterations fit within 85% of U at N_lo, else 2.
  - If not even 2 fit, this target doesn't run in this form. That's reported next to the 3
    iterations the design needs.
  - N is then the largest value, up to 625, at which K fits.
  - `--jobs` is fixed in the amendment.
- Cost decides K and N, nothing else.
- The fine-tune's size is dev pairs per proved tree × expected proofs on P.
- If after 10% of an iteration the projection exceeds the ceiling, the run stops and is
  reported as incomplete.

## Order (the owner's decision, 2026-10-10, also fixed in target 1's frozen text)

Target 1 measures ranking for the fixed tactics. What it shows about M1 inside D is an
assumption.

Sequence:
0. target 1 reports (done: `results/rsi-target1.md`, read (i));
1. this file is frozen, with N_min and U_smoke;
2. the CPU pair count on dev round 5;
3. the smoke test, on the 29 dev statements only (dev is registered and not held out), capped
   at U_smoke;
4. the amendment, with measured costs;
5. the runs.

Mapping, fixed before target 1 reported:
- **(i) Ranking is a limit** (target 1's reading): D as registered stays primary. D+R3 (exactly
  R3; retrieval/v2) is a registered secondary arm at iteration 0 and at every iteration, with
  policy id `retrieval/v2+ranker/<sha16>+openai-compat/v1`.
- **(ii)–(v):** D as registered. Under (v), the report says it can't separate ranking from
  policy as the limit.
- After target 1, the pattern extractor is the main line of work. This target runs behind it.

## Decisions for the owner before freezing

1. **D's retrieval:** v1 as registered, so iteration 0 can reproduce 26, with v2 only in the
   D+R3 arm (recommended); or v2 throughout, as a new baseline.
2. **The A100 budget:** does `docs/model-experiment-spec.md` keep its 30-unit reservation
   (U = 67) or not (U = 97)? And what is U_smoke?
3. **The stop rule:** gains, as pinned, or net. A gains-only stop at 7 can end the loop after a
   significant 6–0 iteration, and can continue after +7/−9.
4. **Two readings of the pins to confirm:**
   - "attempted and failed" means refused by Coq, not timeouts or guard refusals;
   - expert iteration also follows when iteration 1 shows no gain, not only after a plateau.
