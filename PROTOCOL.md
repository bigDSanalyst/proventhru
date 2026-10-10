# Protocol: does a model help proof search, at matched effort?

Pre-registered. This file is committed before any model call, its sha256 is
in every episode run under it (`episode.protocol`), and `proventhru run`
refuses a model policy without it (`protocol.py`). The machine-checked part
is the `json frozen` block at the end. Everything else is the reasoning
behind it. A change is an amendment: a new commit, logged at the bottom with
its reason, so it has a new hash, and the records show which version each
run was under.

Stage: **v5, frozen.** The prompt, the model, its serving and its settings
are registered (v2 added the limitations, the M1-first sequence and the
Colab install rule; v3 moved M1 to 7B on an A100; v4 froze; v5 replaced
v4's prompt before any held-out model run, see Amendments). Held-out runs of
M1 may now start. Nothing in this protocol changes again before they are
reported, except by an amendment that says why and repeats the runs it
affects.

## Questions

- **Q1 (generation).** Does a model choosing tactics beat the fixed tactic
  list at the same number of tactics tried? Condition C against A.
- **Q2 (on top of retrieval).** With retrieval held constant, does the model
  add anything? Condition D against B.
- **Q3 (memorisation).** Does the model's proof rate drop when only bound
  variable names change? C on `test` against C on `test_renamed`.

Q1 and Q2 are the primary questions. Q3 is a control on how to read them.
Condition E (the model shown retrieved lemmas, choosing among them) asks a
different question and runs only after C and D, under its own amendment.

## Sets

| set | file | size | role |
|---|---|---|---|
| `dev` | `examples/eval_open.txt` | 29 | Prompt tuning and debugging. **Not held out**: retrieval and the gate were developed on it |
| `test` | `examples/eval_test.txt` | 120 | Held out. Generated (below); no model output on it is looked at before the prompt is frozen |
| `test_renamed` | `examples/eval_test_renamed.txt` | 120 | Held out. `test` with bound variables renamed (`l1 -> xs`, `l2 -> ys`, `n -> k`, `m -> j`), line for line |

`test` was made by `tools/make_eval.py --n 600 --seed 1 --max-term 5
--min-size 5 --max-size 9` (true-on-2,000-
random-inputs equations and inequalities over stdlib `nat` and `list nat`
functions, QuickSpec-style enumeration, see the script's docstring) and
`tools/gate_eval.py --keep 120 --backend coqtop`: the first 120, in the
generator's seeded order, that the gate leaves `open` (276 of the 600 were
open, 324 trivial). Nothing was removed by hand, and nothing
was removed because a baseline proved it. Selecting statements on a
baseline's results would bias the comparison against that baseline.
Difficulty is set by the generator's parameters. If the difficulty check
below fails, the whole set is regenerated with new parameters, as an
amendment.

A statement that holds on 2,000 random inputs may still be false. A false
statement stays unproved under every condition, so it costs power but not
bias.

The registered hash of a set covers its preamble and its statements in
order (`proventhru protocol set FILE`). Comments don't count.

**Difficulty check (before freezing).** If condition A proves more than 30%
of `test` at the low budget, the set measures lookup more than search, and
it is regenerated harder. **Result: A proves 22 of 120 (18.3%) at 600
steps.** Passed; the set is registered as generated.

**Rename check.** The fixed policy and retrieval do not read variable names
except to name hypotheses they act on, so A on `test_renamed` must prove the
same statements as A on `test`, item for item. If it doesn't, the rename is
not neutral and Q3 can't be read. **Result: the same 22 items, 0 discordant.**
The check is on outcomes, not trajectories: those differ slightly (32,317
against 32,320 errors in 62,661 steps), because the names Coq generates
depend on the names in scope (destructing a list with `n` in scope names
the head `n0`, with `k` in scope `n`). So the renamed state a model sees
differs from the original by more than the bound names, in exactly this
way.

A constant-renamed copy (`app -> my_app`, with definitions) also changes
what `Search` finds. That makes it a harder test of retrieval generalisation,
not of memorisation, so it is not part of this protocol.

## Environment

Every condition runs on the same prover: **coqtop, Coq 8.18.0**, with the
preamble given in each set's file (`Require Import Arith Lia List. Import
ListNotations.`). `check()` refuses a run on any other prover, and the report
flags a comparison across provers. Coq 8.18 has no `omega`; `lia` replaces
it, and neither vocabulary includes `omega`.

The Colab run (the primary model) must install exactly Coq 8.18.0, and the
fixed baselines are compared with model runs on that same prover version.
The record's `environment.prover` is the evidence for this.

**Everything runs in Colab**, the baseline reruns included, so every
condition shares one machine image and one Coq build.

**Colab install.** Colab's apt Coq is older than 8.18, so Coq 8.18.0 is
installed with opam (about 15 to 20 minutes), and the opam switch is cached
on Google Drive so later sessions reuse it. Using apt's Coq and noting the
deviation is not allowed: `lia` and `auto` change between versions, so a
baseline on one version doesn't measure the same thing as a model run on
another. **Fallback, only if opam cannot install 8.18.0 on Colab:** an
amendment moves the whole experiment, baselines included, to the Coq that
Colab can run. All conditions are rerun there, and the deviation is stated
with the results. That gives a worse result, but a real one.

## Definitions

- **Step**: one tactic submitted to the session, whatever its outcome: ok,
  error, refused by the guard, or timeout. A policy's own queries (retrieval's
  `Search`) are not steps. A retrieved lemma tried as a tactic is a step.
- **Invocation**: one policy call, that is, one expanded node. The fixed
  policy offers about 20 tactics per invocation, a model at k=5 at most 5.
- **Budget**: the search stops at the step budget, mid-node if need be, so
  conditions compared at one step budget tried exactly as many tactics.
  Expansions are unbounded (`budget: null`). Invocations are reported, not
  matched. If a model needs four times the decisions to match the fixed
  list, that is a finding.

## Conditions

| | policy id | what it is |
|---|---|---|
| A | `fixed-tactics/v1` | the fixed tactic list |
| B | `retrieval/v1+fixed-tactics/v1` | A plus the top 6 retrieved lemmas as `rewrite`/`rewrite <-`/`apply` |
| C | `openai-compat/v1` | the model alone: the goal state (`view.state`) and the vocabulary, k=5, temperature 0, seed 0 |
| D | `retrieval/v1+openai-compat/v1` | C plus the same retrieved lemmas as B, appended after the model's candidates |

C and D use the same prompt, the frozen `prompt_sha256`. The prompt
template, the schema, the vocabulary and the code that renders the state
are all inside that hash. JSON output is constrained to the schema where the
server supports it (`json_schema`: vLLM), and requested as JSON mode
otherwise (`json_object`: the HF router). Either way the answer is checked,
and what fails the checks is counted (below).

## Models

**M1 first; M2 only if M1 shows an effect.** M2 is a robustness check of an
effect M1 found. If M1 doesn't beat the fixed bars, the finding is that this
model adds no reasoning over fixed tactics at matched effort, and a second
family would not change what that means. So M2 is set up, registered and
run only if at least one of M1's primary comparisons is significant (below).
Running M2 then costs no extra Colab and vLLM setup until there is something
for it to check.

- **M1: `Qwen/Qwen2.5-7B-Instruct`, pinned by revision hash, served by vLLM
  in Colab on an A100, bf16, temperature 0.** M1 is the model that is
  fine-tuned afterwards (DPO, then GRPO), so it is chosen as the model those
  can run on with the hardware the whole line uses: a Colab A100 (bf16).
  7B serves there in bf16 without quantisation, and trains with LoRA in bf16.
  The weights are pinned by the Hugging Face revision (commit) hash, not by
  name. The baseline, the DPO model and the GRPO model are the same weights
  at that revision, plus each stage's adapter, served the same way: same
  dtype, same vLLM version, same GPU class. The freezing amendment records
  the revision hash, the vLLM version and the GPU, and `models` registers
  the served name `Qwen/Qwen2.5-7B-Instruct@<revision>`.
  **The A100 is part of the setup, not a convenience.** If a later stage
  can't get an A100, it waits. It doesn't move to a smaller GPU or a
  quantised copy, because that would make it a different model from the
  baseline.
- **M2 (if run): a second open-weight family, in Colab the same way (A100,
  bf16).** At up
  to about 12,000 calls (about 14M tokens) per low-budget run on `test`, the
  HF router's free allowance can't carry a held-out run. The router is used
  for prompt tuning on `dev` only.

Each model is named in the frozen block's `models` by the amendment that
freezes the prompt. Until then, `check()` refuses it on held-out sets.

## Runs

Step budgets: **600** (low, primary) and **2000** (high, secondary). On the
dev set the fixed policy spends 19.4 steps per expansion (coqtop, Coq
8.18.0), so 600 steps is about the 30 expansions the dev baselines were
first measured at. At k=5, 600 steps is up to 120 model calls per statement.

- Low budget, M1 (and M2 if it runs): C and D on `test`, C on
  `test_renamed`.
- High budget, M1 only: C and D on `test`. At up to 400 calls per
  statement, the high budget is affordable only on local weights.
- Fixed policies, both budgets: A and B on `test`. Low budget: A on
  `test_renamed` (the rename check).

**Baselines are rerun under the version the model runs use.** A
comparison is between records citing one protocol version, so A and B are
rerun on `test` under the freezing amendment (they're cheap). The v1
baselines (`results/v1-baselines.md`) remain the record of the difficulty
and rename checks, and the reruns must reproduce their counts. If they
don't, that is reported and investigated before any model result is read.

A run counts only when every statement in it finished. A model API that
stays down stops the run, which is resumed by rerunning it. Responses are
cached by request hash, so a resumed or repeated run makes no new calls for
requests already made. A run with any statement left `incomplete` is not a
result, and the report marks it.

## Analysis

**Primary**: M1's two comparisons at the low step budget, each on the 120
`test` statements, paired by statement, with an exact two-sided McNemar
test on the discordant pairs:

1. M1: C vs A (bar: A's 22 of 120 in v1)
2. M1: D vs B (bar: B's 22 of 120 in v1)

Holm-adjusted over these two at α = 0.05. "Beats the bar" means significant
here, not a higher raw count. The effect is reported as the difference in
statements proved, with the discordant counts. About 6 discordant pairs all
one way are needed for p < 0.05 on one comparison.

**Replication (only if a primary comparison is significant)**: M2's same
comparison(s), each at α = 0.05, as a check that the effect isn't one
model's.

**Secondary** (reported, not tested for significance unless stated):

- **retrieval-solved vs retrieval-unsolved.** A `test` statement is
  retrieval-solved if B proves it at the same step budget in the rerun under
  this version. C and D are reported within each half, with A and B, so it
  shows whether the model adds anything where lemma lookup already works and
  where it doesn't.
- **budget used.** For each condition: steps used out of steps allowed, and
  how many searches ended at the step budget, by running out of candidates
  (frontier), or by a proof. On dev, M1 without retrieval used about 12% of
  its budget and ended by frontier in 21 of 21 unproved searches
  (`results/dev-conditions-600steps.md`). A comparison where one side
  cannot use the effort it is matched on is reported as that, not as a
  plain loss.
- M1's two comparisons at the high step budget
- Q3: C on `test` vs C on `test_renamed`, by item, McNemar, per model run
- invocations per proof and per statement
- failures, split three ways: **api** (calls that failed: timeouts, 429,
  5xx, and retries), **invalid** (responses that were unusable, candidates
  dropped by the checks, tactics the guard refused), **unproductive** (valid
  tactics that Coq refused, that timed out, or that returned to a seen
  state). Only the last is about the model's reasoning.
- the tactic distribution of what was proposed, what ran and what is in the
  proofs: top-3 share and normalised entropy, as the degenerate-policy check
- the statements only one condition proved, listed
- kernel rejections of session-finished proofs
- tokens, calls and wall time

**Not done**: no tuning of anything (prompt, k, vocabulary, retrieval,
budgets) after looking at held-out results. Any such change is a new
amendment, and the held-out runs are repeated under it. Results under the
earlier version are still reported.

## The frozen policy (v5)

Tuned on `dev` only, over five rounds recorded in
`results/dev-conditions-600steps.md` (sha256 `0a75506889a4afff6c0b121b0667e94949235349274840344be9350f1ab9e5e3`).
Final dev numbers at 600 steps: A 10, B 15, C 7, D 12 of 29. The fifth
round was the last, as agreed before it ran, and the prompt was frozen
without regard to its numbers.

- Prompt `e26d4a7732dc48875af2cd566141a41ae7a939bb66ffd0bb0d794caba54f1ee4`,
  the code of commit `3c60b52` (`policy_openai.PROMPT`, `schema_for` with
  arity per tactic, `view.state`, the vocabulary and the arity rules).
- Model `Qwen/Qwen2.5-7B-Instruct` at revision
  `a09a35458c702b33eeacc393d103063234e8bc28`, served by vLLM 0.31.0 in
  bf16 on an NVIDIA A100-SXM4-40GB, under the served name in `models`.
- Settings, checked on every held-out run (`model_settings`): k = 5, up to
  3 re-asks per state shown what was tried there, `json_schema` output,
  temperature 0, seed 0, at most 400 output tokens.
- Search: best-first with re-asking for policies that set `reexpand`
  (`search.best_first`). The fixed policies don't re-ask, and their search
  is unchanged from v1: the dev baseline reproduces exactly.

**C and D replace the fixed list; they don't add to it.** D is retrieval
around the model, as B is retrieval around the fixed tactics. Whether the
model adds anything to the fixed list (fixed + retrieval + model) is a
different question. It is asked after these runs are reported, by its own
amendment.

## Limitations

**The study is powered for large effects only.** At 120 statements, a
comparison needs a lopsided split of discordant pairs to reach
significance. A non-significant result means that any effect is smaller than
this study can detect, not that there is none. An example from v1: B against
A at 2000 steps, 32 against 26 with 12 and 6 discordant, p = 0.24. That
does not show retrieval failing to help at 2000 steps. It shows that an
effect of that size can't be told from chance here.

**A null with a symmetric split is a different thing.** B against A at 600
steps: 22 and 22, with 9 discordant pairs each way, p = 1. That is not
"too few data". Many statements changed hands, in equal numbers both ways.
Retrieval changes which statements get proved at that budget (it gains list
laws that need a lemma and loses arithmetic ones whose steps it spent on
lemmas), not how many. It is a finding about retrieval at matched effort,
and it is why D's bar of 22 is a real bar, not noise.

**The earlier dev-set retrieval gain was confounded.** At matched
expansions, retrieval went from 10 to 15 on `dev` at budget 30, partly
because it tries more tactics per expansion. Every comparison here is at
matched steps.

**Other limits.** The statements are generated, and hold on 2,000 random
inputs, not by proof. They come from one signature (stdlib `nat` and `list
nat` functions) and one generator, so results say nothing yet about other
domains. The rename control changes Coq's generated names too (see Sets).
One prover, coqtop 8.18.0.

## Frozen

Filled by `proventhru protocol set FILE` and `proventhru protocol prompt`.
Checked by `protocol.check()` on every run.

```json frozen
{
 "sets": {
  "dev": "35f69ac94a07943357fe8e505088acf6e24a4035671a8f21e115f80b8cc47c5d",
  "test": "f6583b6dfec3f2b1104dcb6823edcf67af0edfaffd36d50769a5f83af628a587",
  "test_renamed": "eae151eefc178d7eb856be059553d39de64e6fa802aadf474511b0aad6df2efe"
 },
 "held_out": [
  "test",
  "test_renamed"
 ],
 "environment": {
  "backend": "coqtop",
  "prover": "coq-8.18.0"
 },
 "searches": [
  {
   "budget": null,
   "step_budget": 600
  },
  {
   "budget": null,
   "step_budget": 2000
  }
 ],
 "policies": [
  "fixed-tactics/v1",
  "retrieval/v1+fixed-tactics/v1",
  "openai-compat/v1",
  "retrieval/v1+openai-compat/v1"
 ],
 "prompts": [
  "e26d4a7732dc48875af2cd566141a41ae7a939bb66ffd0bb0d794caba54f1ee4"
 ],
 "models": [
  "Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28"
 ],
 "k": 5,
 "retrieval_top": 6,
 "model_settings": {
  "reexpand": 3,
  "response_format": "json_schema",
  "temperature": 0.0,
  "seed": 0,
  "max_tokens": 400
 }
}
```

## Amendments

| version | commit | change | why |
|---|---|---|---|
| v1 | `1e6b8ef` | first registration: sets, environment, conditions, budgets, analysis. No prompt or model frozen | |
| v2 | `53fcdde` | Limitations section; M1 first, M2 only if M1's primary comparison is significant; M1 = Qwen2.5-3B-Instruct (revision pinned at the freeze); Colab installs Coq 8.18.0 by opam, with the fallback rule; baselines rerun under the version model runs use. Frozen block unchanged | The v1 baselines (A = B = 22 at 600 steps, 26 vs 32 at 2000) needed their reading fixed before any model result; M2 needs a reason to exist first; the fine-tuning target has to be chosen as the baseline |
| v3 | `b18a0ad` | M1 = Qwen2.5-7B-Instruct, bf16, on a Colab A100 (was 3B fp16 on a T4); the A100 is fixed for baseline, DPO and GRPO; everything, baselines included, runs in Colab. Frozen block unchanged | An A100 is available: 7B then serves and trains without quantisation, which was the only reason for 3B. Made before any M1 call, as v2 requires |
| v4 | `2140c7c` | **Freeze** (superseded by v5 before any held-out model run). Registers the prompt (`9d5a3e60…`), M1 at revision `a09a3545…` served by vLLM 0.31.0 bf16 on an A100-SXM4-40GB, and `model_settings` (reexpand 3, json_schema, temperature 0, seed 0, max 400 tokens); search re-asks for model policies; secondary analyses: retrieval-solved split, budget used. Cites `results/dev-conditions-600steps.md` | The stopping rule: one hygiene round after the re-asking change, then freeze whatever the dev numbers, so the test result cannot have been tuned toward |
| v5 | (this commit) | **Freeze, replacing v4's prompt** with `e26d4a77…`: hygiene round 2, arity in the output schema (an argument is `""` for lia, reflexivity, ...; non-empty for rewrite, destruct, induction, ...) plus filled right/wrong examples. Everything else as v4. Cites the dev file with round 5 | After v4 froze, round 4's drop list showed arity errors in ~30% of the model's output (1,276 empty arguments of 1,455 invalid), which would have mixed a formatting bug into a capability comparison. Checked before amending: no model run on `test` or `test_renamed` existed (Colab `runs/` listing). Agreed in advance as the last round; frozen whatever it showed (C 8 to 7, D 12 to 12, invalid 1,455 to 90) |
