# Conjecture loop metrics: definitions

Written 2026-10-10, before saturation or any composition step exists in the prover. The
commit that adds this file is its timestamp. A later change to a definition is a new
dated section below, not an edit, so a result can always be read against the
definitions in force when it was produced.

Each definition says what has to fail before a stronger claim is allowed: the simpler
explanation is tried first, and the claim stands only if it fails.

## Novel lemma

A kernel-certified statement, axiom-free (`Print Assumptions`), that none of these
close:
- one tactic (the gate's trivial set);
- one library lemma (`exact`, `apply`, `intros; apply`);
- one corpus lemma plus arithmetic (`intros; pose proof (L a ..); lia`, with the lemma's
  variables filled from the goal's variables and subterms).

It's novel relative to the library and the corpus, not to mathematics. Statements in the
held-out and dev sets are never proposed.

## Derivation

A statement that the one-corpus-lemma check closes. It's recorded with the lemma it
cites, and never admitted as novel. The check runs before the gate, against the earlier
corpus, and after proof, against everything admitted before it, the same round included.

## Composed proof

A proof that cites two or more distinct corpus lemmas.

## Necessary composition

A composed proof of statement S counts as necessary composition only if all of these
hold:
1. S is not a derivation: no single corpus lemma plus arithmetic closes it.
2. The prover without any corpus lemma fails on S at the same step budget. That prover
   is the same tactic set (`structural-tactics/v1`, or whichever produced the composed
   proof) and the library retrieval index, with no corpus index.
3. The composed proof is kernel-certified and axiom-free, like any corpus lemma.

A composed proof that fails 1 is a derivation. One that fails 2 shows only that the
corpus offered a longer path to a statement the prover reaches without it.

## Inner citation

A citation of a corpus lemma inside a proof, after an induction or case split, at a goal
the statement does not show. It counts only for a statement that passed the derivation
check: an induction that does no work (`intros. induction n. apply L. lia.` at an
instance of `L`) must not make a top-level use look structural (see
`results/explore-run3.md`).

## Open statement classes

`tools/classify_opens.py`, as documented there and in `results/explore-runs-5-7.md`.
Class 3 means "not closed by the probes", not "needs a new capability". Each class-3
wave so far has turned out to be a missing pattern once examined.
