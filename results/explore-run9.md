# Exploration run 9: the loop with saturation

6 rounds × 80, 600 steps, `--prover structural2 --saturate`, the held-out and dev sets
excluded, at `a047f16`. Same generator and seed as run 8, so the two runs see the same
round-0 candidates.

| round | proved, run 8 | proved, run 9 | run 9 proofs citing the corpus |
|---|---|---|---|
| 0 | 51 | 51 | 0 |
| 1 | 17 | 31 | 14 |
| 2 | 15 | 35 | 20 |
| 3 | 39 | 50 | 11 |
| 4 | 28 | 47 | 21 |
| 5 | 30 | 30 | 2 |

| | run 8 | run 9 |
|---|---|---|
| lemmas admitted | 180 | **244** |
| open statements left | 88 | **19** |
| proofs citing the corpus | 0 | **68** |
| of which cite two or more lemmas | 0 | 67 |
| citations inside an induction or case split | 0 | **0** |
| corpus compile at the end | 4.1 s | 5.3 s |

Every corpus lemma is axiom-free. No round proves fewer than the same round of run 8:
saturation doesn't crowd at the loop level either.

## The corpus now compounds, but only at the top

**Citation depth.** A lemma's depth is 1 if its proof cites no corpus lemma, and one more
than the deepest lemma it cites otherwise:
- 176 lemmas at depth 1;
- 63 at depth 2;
- **5 at depth 3.** These cite a lemma that itself was proved by composing others, e.g.
  `list_sum (removelast (removelast (rev l))) <= list_sum l` cites `pt_r1_10`, a composed
  lemma from round 1.

So composed lemmas go back into the corpus and get composed again: the first chain of
discoveries building on discoveries in this project.

**Every citation is at the top.** All 146 citations sit in one saturation step before
`lia`. None comes after an induction or case split, and no proof cites lemmas at
different points. The chains are mechanical: monotonicity facts stacked by `lia`.

## The residue

19 statements stay open: class 2 (1), 2s (3) and 3 (15). **The 15 in class 3 are
exactly run 8's 15**, by statement: unknown 9 (`filter` commuting with `rev` or
`removelast`, `removelast` after `filter (map S …)`, two `skipn (list_max l) l`
statements), combined 4, library 1, rev 1. Saturation removed what was composition and
left the rest untouched, as the subclassification predicted.

## What the null is about

Nine runs, 244 lemmas, 146 citations, none inside an induction. That's information
about this signature (`nat` and `list nat` with these functions), not about the loop
or about a model:
- Every statement proved here closes by a fixed proof shape, or by a chain of corpus
  lemmas at the top.
- None of the 19 left open needs a corpus lemma inside an induction: the interior probe
  found none, with a lemma-free control.

Two limits on that claim:
- It covers what the generator proposed and the provers tried. It doesn't show that no
  statement over this signature needs an inner use.
- A proof found top-level doesn't rule out an inner one existing. Search takes the
  first proof it finds.

But a loop that never meets such a statement can't measure whether a model helps with
one. So the next experiment changes the signature, not the prover.

## Against the stopping rule and the model spec

- **Inner citations: 0,** at 244 lemmas, with composition working.
- The residue is 15 statements, unchanged from run 8, and none of them is interior.
- This is the case the second branch named: fixed-tactic composition is mechanical, and
  run 9 is about its ceiling. Candidate generation without a policy now proves nearly
  everything it can reach, and the loop never uses a lemma inside an induction.

`docs/model-experiment-spec.md` chose R from run 8, and its trigger didn't fire there. It
isn't amended or run: on this signature it can't produce the signal it exists to
detect. It stays registered for the next signature.
