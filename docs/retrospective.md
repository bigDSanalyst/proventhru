# Retrospective: what we set out to do, what we did, where we drifted

Written 2026-10-10, after pilot gate 2. It covers the whole project to date, from the
README's three positions to the insertion-sort pilot.

## What we set out to do

The aim, as stated at the start: **an RL / RCI system with Coq as the environment, that
finds patterns, generates novel conjectures and proves novel theorems.**

It was in two layers:
- **The truth layer, non-reciprocal:** the kernel, the gate, the protocol, the held-out
  test set, the reward. Nothing in it learns or bends.
- **The seeking layer, reciprocal:** conjecture ↔ proof, policy ↔ retrieval, policy ↔
  phase. Its parts:
  - a model policy, trained by DPO and then GRPO on its own trajectories;
  - RCI: critique and revise conjectures;
  - oscillate: phase readings of the policy, used to prune and as a dense reward;
  - AetherShell: orchestration, with lessons, bandits and grounded critique;
  - a conjecture generator that extracts patterns from theorems (the "pattern lenses").

The implied question was recursive self-improvement: does the system get better at
conjecturing and proving from its own output?

## What happened, in phases

1. **Substrate** (PRs before #9). The three positions, the coqtop and Pétanque backends,
   the hash-chained run record, retrieval and the fixed baselines.
2. **The pre-registered model experiment** (PR #9).
   - `PROTOCOL.md` was frozen at v5; M1 (Qwen2.5-7B) was run on 120 held-out statements.
   - **Result: null.** C vs A: 17 vs 22. D vs B: 26 vs 22. Neither significant.
   - Along the way: the coqtop deprecation-warning bug, found by replay and measured.
   - M2 wasn't run, by the protocol's own rule.
3. **The conjecture loop** (PR #10, then stacked branches). `proventhru explore` over
   `nat` / `list nat`, runs 3 to 9:
   - generator: derivations, seeding by anti-unification, an exact congruence rule;
   - prover: structural tactics v1 and v2, the corpus index, saturation;
   - instruments: the classification ladder and subclassifier, `Print Assumptions`,
     certified drops.
   - Result: the corpus grew from 2 lemmas to 244, with chains to depth 3 and 70
     necessary compositions. **No inner citation in nine runs:** a fact about that
     signature.
4. **oscillate calibration.** A fixed formula, stated before the data was read:
   inconclusive. It recognizes progress (AUC 0.96, the reward 0.90); it can't forecast a
   search's outcome (0.44). The schema is kept.
5. **The insertion-sort pilot.**
   - Gate 1: 8 of 9 gold statements proposed.
   - Gate 2: 4 of 5 helpers and 1 of 3 main theorems proved, and **the first inner
     citation:** `sort_length` uses `insert_length` at a step case, matched by term
     overlap.

## Scorecard against the original parts

| part | status | evidence |
|---|---|---|
| Truth layer: kernel, gate, records, protocol | **built, validated, used throughout** | every result above; it caught two silent failures (the deprecation warning, the congruence rule) and several biased checks |
| Pre-registered evaluation | **built and used once** | v5: a clean null |
| Model policy | **built, measured once, then idle** | M1 at v5; not in any run since. 97 A100 units unspent |
| Conjecture generator | **built, but of a different kind** | QuickSpec-style enumeration over a fixed signature, not pattern extraction from theorems |
| Conjecture ↔ proof loop | **built, and it compounds** | 244 lemmas, depth-3 chains. The operator is fixed and installed by us |
| Policy ↔ retrieval | **built, fixed policies only** | the library and corpus indexes, saturation |
| RCI (critique and revise) | **not started** | |
| RL (DPO, GRPO) | **not started** | the trajectories exist (tens of thousands of recorded steps, model ones included) |
| oscillate | **calibrated, inconclusive, out of the architecture** | `results/oscillate-calibration.md` |
| AetherShell orchestration | **not started** | patterns ported, never run as the orchestrator; `explore` is a bespoke loop |
| Reflection / grounded critique (README v2) | **not started** | |

## Where we drifted, and why

1. **From "does the model help" to substrate engineering.** After the v5 null, the model
   left the loop and didn't come back. Every later improvement was to fixed parts
   (generator, tactics, retrieval), made by us. The reasons were good each time: the
   model needs statements it could help with, and a signature with no inner use can't
   show it. But the effect is that the seeking layer's learning parts never ran.
2. **"Self-improvement" became "improved by us."** Nine runs found nine silent limits:
   the congruence rule, tactic shapes, test inputs, probe crowding, composition, match
   cases, `rev` invariance, the corpus interface, the hidden step case. We fixed each by
   hand. The loop compounds its corpus through operators we installed, and nothing in
   the system changes its own behaviour.
3. **The generator answered a narrower question than the one posed.** "Find patterns,
   generate novel conjectures" became enumerate a signature, test, gate. That's theory
   exploration (HipSpec's setting), re-implemented with a stronger truth layer. Its
   lemmas are novel relative to the corpus and the library, not to mathematics.
4. **The target metric moved several times:** from proved counts to citations, to
   citation position, to necessary composition, to inner citation. Each definition was
   committed before it was measured, which is the right discipline. But the sequence
   shows we were looking for evidence of depth that the setting didn't produce, and
   redefining what to look for.
5. **The pilot measures recall, not discovery.** It rediscovers the development's known
   helpers, with the development's types wired into the tactic set by us.
6. **Branch sprawl.** After PR #10, six branches are stacked unmerged: `subclassify`,
   `structural-v2`, `saturation`, `real-dev-scope`, `oscillate-calibration`,
   `isort-pilot`. So `main` doesn't hold runs 8–9, saturation, the calibration or the
   pilot.

## Paths named and not taken

- **DPO on the trajectories we have.** The records hold every model step from v5,
  successes and failures, with both verdicts. It's the original next step after M1, and
  it was deferred, first behind the conjecture loop and then behind the model question.
- **"Fixed + retrieval + model" on the test set:** the condition the v5 write-up itself
  named as the natural next one (the model's candidates added to B, not replacing it).
- **The model in the generator** (Lemmanaid-style shapes): scoped, not built.
- **Retrieval ranking.** The dev check showed library retrieval fails at ranking, and
  that lever was never pulled.
- **Goal selectors.** Matching corpus lemmas against every goal, not only the first,
  named after gate 2.
- **A real development.** The pilot is our own toy development. The standard library's
  `Sorting` and a red-black tree were scoped.
- **Smaller items:** M2 (by the protocol's rule); an external timestamp on the protocol
  hash (OpenTimestamps); the Pétanque backend's per-step signals, built and barely used.

## What holds

- **The truth layer works, and it pays for itself.** It found every silent failure
  before any money was spent on the wrong lever, twice saving an A100 run aimed at the
  wrong component.
- **The v5 null is a clean result:** at matched effort, a 7B model doesn't beat fixed
  tactics on these statements. It agrees with the Coq literature (models add most in
  combination).
- **Measured facts about the loop:**
  - composition compounds (depth-3 chains);
  - inner use doesn't arise over `nat` / `list nat`, and does arise once a development's
    own recursive functions are in the signature;
  - a new development costs one generic interface change plus a per-type tactic set.
- **Negative results with stated thresholds:** oscillate's forecasting, and the
  lemma-form check on dev.

## Three ways forward

They answer different questions; pick by which question matters.

| path | answers | cost | closeness to the original aim |
|---|---|---|---|
| **A. Finish the pilot, then a second development** | does the loop generalize, and at what cost per development | CPU, days per development | medium: recall, not discovery |
| **B. Return to the model: DPO on the existing trajectories, then the combined condition** | can the system improve its own policy from its own output, the original RSI question | A100: some of the 97 units; the protocol amendment first | **high**: the seeking layer's learning part, finally running |
| **C. Discovery mode on the pilot:** hold back the gold, start from the main theorems, propose helpers | can it find what a development needs, not what it already has | CPU, harder to score | high: the conjecturing aim |

**My recommendation:**
1. **Close the pilot first,** with gate 3 small, and one versioned 2b-iii for the goal
   selectors. That fixes the per-development cost, and it gives B a better test set than
   `nat` / `list nat`: the pilot's residue, `sort_perm` and `sorted_sort_id`, needs the
   prover to pick a lemma for what the goal becomes.
2. **Then path B,** pre-registered as before:
   - M1 (and the combined condition) on the pilot's residue;
   - DPO on the v5 and pilot trajectories, judged on held-out statements.

   That's the step this project was built for and has deferred the longest.
3. **Merge the stacked branches into `main`** before either, so the record of what was
   found is in one place.
