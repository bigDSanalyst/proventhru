# Exploration run 4: 6 rounds × 80, with seeding

Same settings as run 3 (`results/explore-run3.md`), at `e6555a6`, with:
- seeding (anti-unification and subterm generalization of discovered lemmas);
- two retrieval indexes (library `Search` without the corpus; a corpus index);
- derivations that fill a lemma's variables with the goal's subterms;
- `Print Assumptions` on every corpus lemma.

| round | open after gate | admitted | derived | seeds in batch → proved | seeds proposed | proofs citing the corpus |
|---|---|---|---|---|---|---|
| 0 | 61 / 80 | 8 | 5 | – | 0 | 0 |
| 1 | 61 / 80 | 7 | 12 | – | 1 | 1 top |
| 2 | 59 / 80 | 16 | 20 | 1 → 0 | 4 | 11 top |
| 3 | 54 / 80 | 5 | 23 | 4 → 1 | 3 | 3 top |
| 4 | 67 / 80 | 2 | 8 | 3 → 0 | 0 | 0 |
| 5 | 64 / 80 | 1 | 8 | 0 | 0 | 0 |

Totals:
- 39 lemmas admitted;
- 76 derivations (91 uses of the corpus in all);
- 8 seeds proposed, 1 proved;
- 15 citations inside proofs, all top-level, 0 inner.

Every corpus lemma is closed under the global context. The corpus compile stays flat at
0.4 to 0.6 s up to 39 lemmas. The cap of 3 ways to fill a lemma's variables never bound:
no corpus lemma has more than one variable of a type.

## What seeding did

**Anti-unification found the missing generalization from the loop's own output.** Round
2 proved instances of `list_max l1 <= list_sum (l1 ++ X)` at `X = filter Nat.even l1`,
`map S l1`, `removelast l1`, and others. Two of them anti-unify to
`forall l1 l2, list_max l1 <= list_sum (l1 ++ l2)`. It was seeded into round 3 and proved
there as `pt_r3_0` (`rewrite list_sum_app`, then `pose proof (pt_r0_0 l1); lia`). In run 3
the same statement was proposed in round 0, failed, and was never retried.

**Subterm generalization proposed only weakenings.** Its seeds, such as
`Nat.min n (list_max l1) <= list_sum l1`, were all derivations of existing lemmas, so they
were recorded as derivations before the gate. The operator is cheap and harmless, but on
this signature anti-unification is the one that finds real generalizations.

**No later proof cites `pt_r3_0`.** No candidate after round 3 has its shape, so the
general lemma ends the cluster rather than starting a deeper one.

## Against the stopping rule

- Proofs cite the corpus: yes (15).
- Any citation structural (inner, after the derivation check fails): no (0).
- The generator, seeded by its own output, found the one generalization the
  corpus pointed to, and then ran dry: 0 seeds in rounds 4 and 5. Admissions fell from
  16 to 5, 2, 1.

So branch 2 holds even after the generalization step. Every discovered lemma is closed by
induction plus `lia`, or by a library rewrite plus one corpus lemma plus `lia`. With these
fixed tactics, the loop finds the lemmas that class of proof closes and generalizes
within it, but it doesn't deepen. That's the condition the stopping rule set for the
next step.

## Novel lemmas worth a look (both runs)

- `list_sum l <= length l * list_max l`
- `forall l1 l2, list_max l1 <= list_sum (l1 ++ l2)`, found by seeding
- `list_max (repeat n (length l)) <= n`
- `length l <= list_sum (map S l)`
