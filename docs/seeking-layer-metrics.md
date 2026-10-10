# The seeking layer: what counts as a result

**Status: draft, under review; not yet in force.** The rule against edits below takes effect at the commit that removes this line.

Written 2026-10-10, before `proventhru/pattern.py` or any part of the seeking layer exists.
The commit that adds this file is its timestamp. A change to anything here is a dated
amendment appended below, never an edit, and nothing here may be changed after a model
call on the evaluation development. Before the first model call, the parts that bind a run
(the development and its hash, the prompt hash, the budgets, the thresholds) are frozen
into `PROTOCOL.md` as an amendment, and the pipeline refuses model runs without it, as it
does today.

## What the seeking layer is for

**To propose conjectures that nobody wrote down, that formalize, are new, are provable,
and matter to the development they're about.** The measure is novel, significant
conjectures. Recovering a development's known helper lemmas is a floor: a check that the
system can find what's already known. It is not the target.

This document exists because the project drifted once (`docs/retrospective.md`). The
template generator, meant as a stand-in for this layer, became the project, and the
metric moved toward whatever that setting could produce. The rules below are written so
that can't happen again unnoticed.

## The system under test

    development (definitions + main theorem statements; no proofs, no helper lemmas)
      → pattern extractor (model): structured patterns
      → synthesizer (model): candidate conjectures, each tied to the pattern it came from
      → RCI loop: critique and revise, grounded only in Coq's verdicts
      → gate (Position 1) → novelty check → prover (Position 2) → kernel (Position 3)
      → significance tests
      → records (every step above, hash-chained)

**A pattern** is structured output, not free text:
- `type`: one of `symmetry`, `invariance`, `idempotence`, `monotonicity`,
  `preservation`, `inverse`, `composition`, `generalization`, `specialization`,
  `case-split`, or `other` with a name;
- `about`: the definitions and theorems it reads;
- `description`: one sentence.

Each conjecture names its pattern, so we can measure which pattern types produce
significant conjectures, and so RCI can critique a conjecture against the pattern it
claims to express.

**RCI**, bounded at 3 revisions per conjecture. Every critique is a Coq verdict, never the
model's own opinion:

| gate verdict | what happens |
|---|---|
| `ill_formed` | revise, given the elaboration error |
| `refuted` | revise, given the counterexample |
| `vacuous` | revise, given the contradiction |
| `trivial`, or known by the novelty check | drop, counted as not novel |
| `open` | goes to the prover |

## The development

The model must not be able to recall the answers.

- **Evaluation development: written for this project, never published before the run.**
  It's committed (and hashed into the protocol) before the prompt is frozen, with its
  gold file (helpers and main theorems, proved) committed alongside under a hash.
- **Renamed control:** the same development with every function, predicate, constructor
  and variable renamed to meaningless names (`f1`, `p1`, `c1`), run under the same
  frozen prompt. If the counts fall sharply on the renamed copy, the model is recalling
  from familiar names, not reading the definitions. This is the function-name version of
  v5's variable-rename control.
- **Dev development, where the prompt may be tuned:** a different one. The
  insertion-sort pilot (`pilots/isort/`), renamed, is the candidate. Tuning stops when
  the prompt is frozen, by the same rule as `PROTOCOL.md` v4/v5: one round after the
  last change, then frozen whatever it shows.
- **What the model sees:** the definitions, and the statements of the main theorems.
  Not their proofs, not the helper lemmas, not the gold file.

A public development (MathComp, a CoqStoq project, the standard library) can be a
secondary target, reported separately and labelled as possibly memorized. It can't be the
primary one.

## Counts

For each run, every conjecture the synthesizer emits is counted once, in the first row
that applies:

| count | what it is |
|---|---|
| `ill_formed`, `refuted`, `vacuous` after RCI | not a theorem candidate |
| `not novel` | the novelty check below finds it, or the gate calls it trivial |
| `unproved` | novel and open, but not proved at the budget |
| **G: gold recovered** | it's a gold statement exactly, up to the names of bound variables, confirmed in Coq by closing the gold statement with it |
| **S: novel and significant** | novel, proved, not gold, and passes a significance test |
| **N: novel, not significant** | novel, proved, not gold, passes no significance test |

**G is the floor. S is the result.** N is reported, because a system that only produces N
is a true-statement generator, not a discovery engine.

## Novelty, mechanically

A proved conjecture is novel if all of these are false:
1. The gate's trivial check closes it (one tactic, or one library lemma via `exact`,
   `apply` or `intros; apply`).
2. It's a derivation of the corpus or of the development's own lemmas: one of them plus
   arithmetic closes it (`docs/conjecture-metrics.md`), with the lemma's variables filled
   from the goal's variables and subterms.
3. It's equal, up to bound variable names or the orientation of a symmetric relation, to
   a statement in the corpus, the development, or an earlier conjecture of the same run.

**Not checked:** novelty against the published literature. There's no mechanical test for
it, and no claim of it is made. Novel always means novel relative to the library, the
development and the corpus.

## Significance, by use

A novel, proved conjecture C is significant if a test passes. Each result records which
test, with the control's record:

- **s1, enabling (primary):** a held-out target is unproved at budget B without C, and
  proved at budget B with C added to the preamble. Same prover, same budget, paired.
  - Targets are the development's main theorems and its gold helpers. None of these are
    shown to the model, and none of them is C itself.
  - If a target is a derivation of C alone (C plus arithmetic closes it), it counts as a
    restatement, not an enabling. Restatements are reported separately.
- **s3, reuse:** a later kernel-certified proof of a different statement that passed the
  derivation check cites C, and that statement isn't proved at budget B without C.
- **s2, shortening (reported, not counted in S):** the prover's search to a target's first
  proof takes at least 50% fewer steps with C than without. It's a weaker signal: it
  reports usefulness without showing necessity.

The prover for every test is the strongest available at the time of measurement, the rule
of `docs/conjecture-metrics.md` (amendment of 2026-10-10). That's recorded by identity.
The B used is the one frozen in the protocol, 600 steps unless the amendment says
otherwise.

Human judgement of "interesting" isn't part of S. If collected, it's reported beside S,
by raters who didn't see which source produced each conjecture.

## Baseline: the template generator

On the same development, the same prover, the same budget B, and the same cap on the
number of conjectures sent to the prover:
- **T:** `proventhru/devgen.py`, the QuickSpec-style enumerator, already built and
  measured on the pilot (8 of 9 gold statements proposed at gate 1).
- **M:** the model's pattern extractor and synthesizer, with RCI.
- **M ∪ T:** reported for information.

The model's contribution is what it adds over T. A result where M's S is matched by T's S
says the model adds nothing an enumerator doesn't.

## Success and failure, stated now

On the evaluation development, at the frozen budget:
- **Success:** S(M) > S(T), with S(M) ≥ 3, **and** on the renamed control S(M) stays at
  least half of its original value (the memorization check).
- **Failure:** S(M) ≤ S(T). It's reported as the finding: a model proposing conjectures
  doesn't beat an enumerator here. The rule that matters: **after a failure, the
  extractor's misses are not patched one by one to reach success.** Any change to the
  extractor after the evaluation run is a new, dated amendment, with a new evaluation
  development, so the result can't be fitted to one development.
- **Anything else** (S(M) > S(T) but S(M) < 3, or the renamed control halves) is
  inconclusive, and reported as such.

These counts are small. No significance test is claimed on one development, and the
results are descriptive. A claim beyond descriptive needs a second evaluation
development, run under the same frozen prompt.

## Records: a schema version, not an edit

The seeking layer writes `proventhru-record/v2`. It's v1 plus one entry kind,
`conjecture`, holding:
- the source (development hash, which definitions and theorems were shown);
- the patterns;
- the synthesizer's output;
- the RCI history (each verdict, the message given back, each revision);
- the gate verdict;
- the novelty result (which check, and against what);
- the proof outcome (a link to its episode);
- the significance tests (s1, s2, s3, each with the control episode's link).

v1 records stay valid, and `proventhru verify` accepts both. SCHEMA.md gets a v2 section;
v1's text is unchanged.

## Cost

- Model calls are on the A100 (M1 as served in v5, unless an amendment names another
  model). The ceiling is set after a 10-call smoke test on the dev development: tokens
  and latency per call, projected to the evaluation run. It's frozen in the protocol
  amendment, and the run stops if, after 10% of it, the projection exceeds the ceiling.
- The template baseline, the prover and the significance tests run on CPU.
- The A100 isn't avoided to save units if the measurement needs it. The cost is
  estimated and put to the project owner, who decides.

## What this document does not decide

- **The proof-assistant stack** (Rocq 9 + MathComp + CoqPyt + rocq-piler, or the current
  coqtop / Pétanque backends). It's decided in `AGENT.md`, and these metrics hold under
  any of them.
- **The model.** M1 is the default because it's frozen and measured. Another model is an
  amendment.
