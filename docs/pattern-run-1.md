# Pattern extractor, run 1: specification

Written: 2026-10-11, before the run.
Status: in force from the commit that removed its draft line. Its hash is in
`docs/frozen.md`, with the governed code's `code:pattern-run-1` row, and `tools/pattern_run.py`
refuses to run unless both match.

This file fixes how `docs/pattern-metrics.md` v1 is measured for the first run of the
symbolic proposer. The metrics doc says significance is scored after the run but its rule is
committed before. This file is where that rule is committed, together with every other
choice the doc leaves open.

Seeking-layer work. The gate, the kernel, the records and the frozen sets are unchanged.

## What runs

- **The proposer:** `pattern/analogy-v1` (`proventhru/pattern.py`).
  - It's symbolic and runs on CPU only; no model is called.
  - The M1 proposer, run in Colab, is a separate version with its own run spec. The
    metrics doc makes a change of model a new version.
- **Pointed at:** the insertion-sort pilot, `pilots/isort/ISort.v`, with `insert`, `sort`
  and `sorted`. The extractor is shown its definitions only.
- **The held-out gold** is `pilots/isort/ISortGold.v`.
  - The proposer, the tester and the prover never read it.
  - The scorer reads it after the prover has finished.
- **The library the patterns come from:** every constant that `Search _ inside List` and
  `Search _ inside Permutation` list in Coq 8.18.0, printed without notations.
  - The harvest is written to the run directory, and its sha256 is recorded.

## How a candidate is made

**Which library theorems are used.** A theorem is used if, with its type variables set to
`nat`:
- every variable is a `nat` or a `list nat`;
- no hypothesis binds a name used later.

Every other entry is counted under its reason: outside the parser's grammar, higher-order,
other types, a definition rather than a theorem, or no symbol the development can stand for.

**The substitution rule.** A constant of the theorem (never a bound variable) may be replaced
by a development symbol of the same shape:

| library symbol's shape | replaced by |
|---|---|
| `list nat -> list nat` | `sort`, or `insert a` with a fresh number `a` |
| `nat -> list nat -> list nat` | `insert` |
| `list nat -> Prop` | `sorted` |

- One or two symbols are replaced at a time, each at every occurrence.
- Variables are then renamed by order of first use.
- Candidates equal up to variable names and binder order are one candidate. Every source of
  a duplicate is listed.

**Pattern kind.** Each candidate's kind is read from its source theorem's shape
(`pattern.kind`):
- symmetry;
- composition: the substituted symbol applied to itself, or over another operation;
- invariance: R relating X and T X, F (T X) against F X, or P X → P (T X);
- transfer: anything else.

The metrics doc's other kinds, duality and boundary cases, aren't produced by this rule. That
is stated in the results as a limit of this proposer, not counted as a miss.

## Testing

Testing is a filter, so its drops are certified.

**The test.** Each candidate is elaborated in Coq and then decided at every input of its
falsifier space. The decisions go through the procedures in `pilots/isort/ISortDec.v`:
- each procedure is a `sumbool` carrying a proof either way, so a wrong one doesn't
  typecheck;
- the development's predicates go through the test harness's reflection lemmas.

**The falsifier space.** It's exhaustive within these bounds:
- with one list variable: every list over {0, 1, 2} up to length 5 (364 lists), with every
  pair of numbers n, m in {0, …, 3};
- with two list variables: every pair of such lists up to length 3 (1,600 pairs), with every
  pair of numbers.

Because the space is exhaustive and not a sample, a premise like `Permutation l1 l2` or
`sorted l1` is tested on every input of that shape within range. This is the lesson of the
pilot's first evaluator, whose inputs made `Permutation l1 l2` hold only for sorted `l2`.

**What happens to each outcome:**
- **Refuted:** the candidate is false at some input. The refutation is certified: the
  disproof from the counterexample (`decide_false`) is compiled by coqc and checked
  axiom-free.
  - A refutation that doesn't certify isn't dropped. It goes to the prover, as an untested
    candidate would.
- **Untested:** the candidate has more than two list or two number variables, or a
  predicate with no decision procedure. It goes to the prover.
- **Tested vacuously:** the candidate's premises hold at no input of its space. It goes to
  the prover and is counted as tested vacuously.
- **Not formalizable:** the candidate doesn't elaborate. It stops here.

## Proving

The loop (`explore`) runs with the isort pilot's phase 2b-ii settings
(`results/isort-gate2.md`):
- the development's definitions as the preamble (`devgen.preamble`);
- `structural-tactics/isort/v1`, with saturation;
- corpus lemmas offered in all forms;
- open statements retried each round, for 4 rounds;
- 600 steps per candidate (300 with fixed tactics, 300 with retrieval);
- `--jobs 3`.

The gate classifies each candidate first: ill_formed, refuted, vacuous, trivial or open.
Statements the loop proposes itself, its seeds, are reported apart, because they aren't the
extractor's.

## The metrics, as measured here

These are reported per distinct candidate, then aggregated overall, by pattern kind and by
source module.

- **Proposed:** the distinct candidates.
- **Formalizable:** the candidate elaborates in Coq. Both the test harness and the gate
  elaborate it, and any disagreement between them is reported.
- **Novel:** formalizable, and not present in the corpus, the standard library or the
  development shown (ISort.v). Operationally, as in every run so far, a novel candidate is:
  - not closed at the gate by one tactic or one library lemma;
  - not derived from a corpus lemma by arithmetic (the loop's derivations);
  - not vacuous.

  How the definition applies here:
  - Every candidate mentions a development symbol, so none is in the standard library
    word for word.
  - The held-out gold isn't the development shown, so a candidate equal to it counts as
    gold overlap, not as a novelty failure.
  - The literature isn't checked, so "novel" means novel relative to these sources.
  - Refuted candidates are formalizable and novel by this definition. They're also reported
    apart, so the rates can be read either way.
- **Provable:** proved by the loop and admitted to its corpus.
- **Significant:** a proved novel candidate C is significant if any of the four criteria
  below holds. Each criterion is also reported on its own.
  - **(a) It implies a development statement.** Some gold statement G, other than C itself,
    closes in one step from C.
    - "Other than C" means different up to variable names and the sides of =, iff or
      Permutation.
    - "One step" is one tactic from a fixed list in `tools/pattern_run.py`: exact, apply or
      rewrite with C, or C at the goal's variables followed by lia. Each tactic gets a 2 s
      timeout.
  - **(b) It simplifies a development proof.** For some gold statement G other than C:
    - the prover, with the same settings and 600 steps, proves G with C as its only corpus
      lemma;
    - its proof cites C;
    - without C (the same prover on the development's definitions alone), G either isn't
      proved or is proved in more steps.
  - **(c) It's used in a later proof.** A later lemma of the run's corpus cites C, or a (b)
    proof does.
  - **(d) It connects two of the development's symbols that the development treats
    separately.**
    - C mentions two symbols of the development's vocabulary, and no statement of
      ISortGold.v mentions those two together.
    - At least one of the two is defined by the development.
    - The vocabulary is `insert`, `sort` and `sorted`, plus the non-logical library symbols
      of the development's statements: `length`, `S`, `cons`, `In` and `Permutation`.
- **Gold overlap:** novel candidates equal to a gold helper or main theorem, up to names and
  sides.
  - "Up to derivation" means each closes the other in one step, as in (a).
  - It's measured for proved candidates only, since the step from C needs C proved.
- **Inner use rate:** the proved novel candidates that a later proof (in the corpus or under
  (b)) cites inside an induction or case split, divided by the proved novel candidates.
- **Necessary novelty:** novel candidates that no library lemma closes at the gate. Under
  this run's definition of novel it's the same set as novel. It's reported anyway, for the
  metrics doc's table.

## Nulls and the stopping rule

- **A null is reported** by the metric that failed and by its mechanism, with the residue
  subclassified by kind, source and gate status. That is the doc's form.
- **This is run 1 of `pattern/analogy-v1`.** The doc's rule applies to that count: two
  consecutive runs with no significant novel conjecture, and no new residue bucket, end this
  proposer, and the null is published. The M1 proposer is a new version and keeps its own
  count.

## Registration

- **Annotations.** Every record of the run is annotated with the sha256 of:
  - `docs/pattern-metrics.md`;
  - this file;
  - the governed code (`code:pattern-run-1`);
  - the harvest.
- **Refusal.** `tools/pattern_run.py` refuses to run unless this file and the governed code
  match their `docs/frozen.md` rows.

## What was seen before freezing

- **The proposal and test steps were run while they were built, on all 212 distinct
  candidates.** They're deterministic, and their verdicts were seen: 114 refuted, 55 passed,
  42 untested (26 with no decision procedure, 16 with too many variables), and 1 not
  formalizable.
- **Two smoke runs of the whole tool, at 60 steps and one round,** on the first 3 and then the
  first 12 candidates sent to the loop. They proved nothing. Their outputs stay out of the
  results.
- **One check of the significance paths.** It used the held-out `insert_length` as the
  conjecture:
  - it doesn't close `sort_length` in one step;
  - with it, the prover proves `sort_length` citing it inside an induction;
  - without it, the prover doesn't prove `sort_length`.

  This was already reported, as `results/isort-gate2.md`'s phase 2b-i.
- **Nothing at 600 steps was run** on any candidate before freezing.

## Deviations

Any deviation from this file is listed in the results with its reason.
