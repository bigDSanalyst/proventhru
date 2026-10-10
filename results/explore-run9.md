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

## Against the stopping rule and the model spec

- **Inner citations: 0,** at 244 lemmas, with composition working.
- The residue is 15 statements, unchanged from run 8, and none of them is interior.
- This is the case the second branch named: fixed-tactic composition is mechanical, and
  run 9 is about its ceiling. Candidate generation without a policy now proves nearly
  everything it can reach, and the loop never uses a lemma inside an induction.

`docs/model-experiment-spec.md` chose R from run 8. Running it on run 9 instead needs an
amendment first. Run 9's R would be the 19 open statements minus false and gap, which
is under 20, so by the spec the primary outcome would be descriptive only.
