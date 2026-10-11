# Pattern Extractor Metrics

Version: v1
Committed: 2026-10-10
Status: frozen before any pattern-extractor run

## Purpose

The pattern extractor takes a theorem or a development's function
signatures and proposes conjectures. It is the seeking layer.

This document defines what counts as success. It is committed
before the module runs, in the same spirit as PROTOCOL.md for the
registered experiment. Amendments are dated and appended; existing
records cite the version they were written under.

## What this module is not

Not a template generator. Templates enumerate forms over a signature
and saturate. Nine runs of the current generator demonstrated this:
yield falls as the boundary is reached, and every "unexplained"
residue resolves into a missing template shape.

Not scored by recall against a gold file. The insertion-sort pilot
scored the loop on how well it rediscovered the development's
existing helper lemmas. That measures agreement with a hand-authored
answer key, not discovery.

## Definitions

**Pattern.** A structural property of a statement: symmetry,
invariance under a transformation, duality, a general form of which
the statement is an instance, a composition with a known operation,
a boundary or limiting case.

**Conjecture.** A formal statement proposed by the extractor.
Rendered in Rocq syntax, elaborated by the gate before any further
processing.

**Novel.** Not present in:
- the corpus
- the Coq standard library
- the development the extractor is pointed at (if one is given)
- the literature, where the domain permits checking

"Novel" means novel *relative to these sources*. It does not mean
novel to mathematics. Write-ups must say so.

**Provable.** Closable by the current prover at the registered step
budget, or shown reachable by a bounded search. Not provable is not
a failure of the conjecture; it may be deep, or the prover may lack
the shape.

**Significant.** One of:
- implies a statement the development already has, or
- simplifies a proof the development already contains, or
- is used in a later proof (measured at corpus-growth time), or
- connects two functions or predicates the development treats
  separately

Significance is the hardest measure and the one that separates a
discovery engine from a very good prover.

## Metrics

All metrics are computed per run and reported per conjecture,
aggregated per round.

| metric | definition | primary? |
|---|---|---|
| **formalizability rate** | conjectures that elaborate / conjectures proposed | yes |
| **novelty rate** | novel conjectures / formalizable conjectures | yes |
| **provability rate** | proved conjectures / novel conjectures | yes |
| **significance rate** | significant conjectures / proved conjectures | yes |
| **gold overlap** | novel conjectures that match a development's helpers exactly | no, lower bound only |
| **gold overlap up to derivation** | as above, allowing equivalence | no, supplement |
| **inner use rate** | conjectures cited inside a later proof's induction or case split | yes, secondary |
| **necessary novelty** | novel conjectures no existing library lemma closes at the gate | yes, secondary |

The primary question: **how many novel significant conjectures did
the extractor produce?** Everything else is context.

## Pre-registration rules

- A run is registered by hashing this document's frozen block and
  the prompt template, and recording both in every episode.
- The extractor's prompt is part of the metric. A change to the
  prompt is a new version, not a revision.
- The model is pinned by revision. A change to the model is a new
  version.
- No run is scored against a gold file the extractor was shown.
- Significance is scored after the run, but the *rule* for
  significance is committed before.

## The evaluator rule

Every check that filters conjectures must enumerate inputs that
could falsify the claim, not inputs that are easy to construct.

Prior failures of this rule:
- test values 0..5 missed counterexamples with many zeros
- permutation cases missed reversed and rotated permutations
- the congruence filter dropped monotonicity laws as "instances"
  when no smaller law related the two sides

Each was a check that agreed with a wrong statement by construction.
The rule is: for every filter, state the falsifier space explicitly
and enumerate it exhaustively where feasible.

## Nulls

A null is a finding. Report as:
- **which metric failed** (formalizability, novelty, provability, significance)
- **the mechanism** (gate rejection, novelty match, prover miss, significance rule)
- **the residue** subclassified, not aggregated

Do not rename a null as progress. Do not amend this document after
seeing a run's numbers. Amendments are dated and start a new version;
earlier records cite the version they were written under.

## Stopping rule

If two consecutive runs produce zero significant novel conjectures,
and the residue subclassification shows no new bucket, the pattern
extractor is not working as a discovery mechanism. That is the
finding. Publish it. Do not add a third run to "see if it works."

If at least one significant novel conjecture appears, the extractor
has signal. Expand the signature, not the model.

## What carries forward from the proving pipeline

The gate, the kernel, the records, the protocol, the pool. Nothing
in this document changes PROTOCOL.md or any frozen tactic set.
