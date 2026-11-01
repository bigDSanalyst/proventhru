# Pattern extractor, run 2: specification

Written: 2026-11-01, before the run, after run 1's results (`results/pattern-run-1.md`).
Status: in force from the commit that removed its draft line. Its hash is in
`docs/frozen.md`, with the governed code's `code:pattern-run-2` row, and
`tools/pattern_run.py --run 2` refuses to run unless both match.

Run 1 had signal by the metrics doc's rule, though it was thin. The doc's answer to signal is
"expand the signature, not the model", and the owner chose that on 2026-11-01. This run
widens the signature and changes nothing else that it doesn't name below. Everything not
named here is as `docs/pattern-run-1.md` fixes it: testing, the falsifier space, proving,
the metrics (a)–(c), gold overlap, nulls and registration.

Seeking-layer work. The gate, the kernel, the records and the frozen sets are unchanged.

## What changes

**The proposer is `pattern/analogy-v2`** (`proventhru/pattern.py`). It adds two sources to
run 1's:
- **The `Sorted` module** (Coq 8.18.0's `Coq.Sorting.Sorted`).
  - A binary relation variable on the element type is set to `le`, the development's order.
    This is the only order this run uses.
  - A predicate applied to `le`, such as `Sorted le` or `HdRel le`, then counts as one symbol.
    So `Sorted le` (of shape `list nat -> Prop`) can be replaced by `sorted`, as `NoDup` was in
    run 1.
- **Constructor equations.** For every first-order function over `list nat` in `Datatypes`
  and `List`, at each list argument, its application to `nil` and to `cons a t` is simplified
  by Coq's `cbn`.
  - Where `cbn` makes progress, the result is a source theorem: `f (...) = what cbn gave`, or
    `<->` for a predicate. For example, `length (cons a t) = S (length t)`.
  - Where it leaves a `match` or a `fix`, or makes no progress, there's no equation.
  - These are definitional, so a candidate equal to one would be trivial at the gate. They
    serve as patterns, as the library's theorems do.

**Sources, all from one Coq session:** `Search _ inside List`, `Permutation` and `Sorted`,
printed without notations, plus the constructor equations. The harvest, with the equations,
is written to the run directory and its sha256 recorded.

**The prover's preamble** is the development's definitions plus `Require Import Sorted.`, so
that candidates mentioning `Sorted`'s predicates elaborate. The test harness loads it too.
Library retrieval therefore also sees `Sorted`'s lemmas. That's part of the widening, and the
prover's tactics and settings are run 1's.

**Criterion (d) is stricter.**
- In run 1, a weakening of another proved conjecture could meet (d): `~ In n l1 -> sorted l1
  -> sorted (insert n l1)` did, beside `insert_sorted`.
- In run 2, a conjecture C whose (d) pairs are new still doesn't meet (d) if some other proved
  conjecture of the run, or some gold statement other than C, closes C in one step (the
  one-step tactics of (a)). C is then a weakening, and it connects nothing new.
- This is a change made after seeing run 1. It only removes cases from (d), and it applies to
  this run only. Run 1's scores stay as frozen.

**One more count is reported:** significant conjectures that aren't gold overlap.

## What doesn't change

These are as in run 1:
- **Testing:** `ISortDec.v`, with no new decision procedures. A candidate with `Sorted`'s
  predicates, `Forall` or `exists` is untested, and goes to the prover.
- **The falsifier space and certification.**
- **Proving:** the 2b-ii settings, 4 rounds, 600 steps, jobs 3.
- **The metrics doc:** v1, unamended.
- **Significance (a), (b) and (c),** including the bug-rule fix of `code:pattern-run-1` v2:
  a conjecture is loaded with the lemmas its proof cites.

The run starts from an empty corpus. Its candidates include run 1's, since run 1's sources are
a subset of these. The results say which candidates are new to this run.

## The stopping rule

This is run 2 of the analogy proposer. Run 1 counted 2 significant novel conjectures by the
metrics doc's letter, so the doc's stopping rule isn't in play. If this run counts none, by
this file's stricter (d), the next run of this proposer has to count at least one, or this
proposer stops and its null is published.

## What was seen before freezing

- **The proposal step was run while it was built.** It gives 279 distinct candidates against
  run 1's 212, from 29 constructor equations and the `Sorted` module. Among them are
  `insert_length` (from `length`'s equation on `cons`) and `insert_In` (from `In`'s equation,
  with its `=` the other way round).
- **One smoke run of the whole tool,** at 60 steps and one round, on the first 12 candidates
  sent to the loop.
  - It proved nothing.
  - It ran the test step on all 279 candidates, but its counts weren't read. Its outputs stay
    out of the results.
  - It found a bug that would have broken the run. `Coq.Sorting.Sorted` defines the notation
    `sort := Sorted`, so importing it after the development covered the development's
    `sort`. `Sorted` is now imported before the development, in the harness and the prover's
    preamble alike, and a test pins this.
- **The stricter (d) was checked on run 1's corpus:**
  - `~ In n l1 -> sorted l1 -> sorted (insert n l1)` follows in one step from `insert_sorted`,
    both the run's own and the gold one;
  - the reverse step doesn't hold.
- **Nothing was proved at 600 steps** on run 2's candidates before freezing.

## Deviations

Any deviation from this file is listed in the results with its reason.
