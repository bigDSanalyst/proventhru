# Exploration run 3: 6 rounds × 80, before seeding

`proventhru explore`, coqtop, Coq 8.18.0, 600 steps per candidate (half fixed tactics,
half fixed + retrieval with the corpus offered as `pose proof (L x); lia`), jobs 4, the
held-out and dev sets excluded. The code is at `47f2a28`.

| round | open after gate | admitted | derived | closed by one corpus lemma at the gate | proofs citing the corpus |
|---|---|---|---|---|---|
| 0 | 61 / 80 | 8 | 5 (all after proof, same round) | 0 | 0 |
| 1 | 56 / 80 | 3 | 13 | 2 | 0 |
| 2 | 59 / 80 | 9 | 17 | 3 | 4, top |
| 3 | 63 / 80 | 3 | 13 | 0 | 2, top |
| 4 | 75 / 80 | 6 | 0 | 1 | 4, "inner" (see below) |
| 5 | 63 / 80 | 3 | 8 | 1 | 2, "inner" |

32 lemmas admitted, 56 derivations, 7 gate closures by one corpus lemma: 75 uses of the
corpus in all. Every corpus lemma is closed under the global context (`Print Assumptions`,
checked afterwards).

## The six "inner" citations are derivations the check missed

All six are `intros. induction n. apply pt_r0_0. lia.`. Induction on `n` makes the base
case `list_max X <= 0 + list_sum X`, and `apply pt_r0_0` closes that at the instance
`X = map S l1` (or `filter Nat.even l1`, or `removelast l1`). The position test classified
them as inner because an induction comes first. But the lemma is just `pt_r0_0` at an
instance, plus a weakening. The derivation check missed them because it filled a lemma's
variables with the goal's variables only, never with its subterms.

Since fixed (`explore.py`, after this run): the check also fills variables with the
goal's list and nat subterms. Rechecked under it, exactly these six become derivations,
e.g. `intros; pose proof (pt_r0_0 (map S l1)); lia.`, and the other 26 stay novel.

So **every citation in this run is top-level.** Under the stopping rule, that's branch
2: the loop closes, but doesn't deepen. It's also a caution about the metric: tactic
position can be gamed by an induction that does no work. An inner citation should count
only once the derivation check has failed on the statement.

## The generalization pressure was a retry problem

Round 2's four citing lemmas are instances of `forall l1 l2, list_max l1 <= list_sum (l1
++ l2)`. The generator proposed that statement in round 0, the gate passed it as open, and
the prover failed it: `pt_r0_0`, which the proof needs, was proved in that same round and
wasn't in the corpus yet. Nothing retried it later. Seeding (next run) re-proposes it by
anti-unifying the instances, and a statement left open earlier isn't blocked from being
proposed again.

## Novel lemmas worth a look

- `list_sum l <= length l * list_max l` (pt_r2_2)
- `list_sum (firstn 1 l) <= list_max l` (pt_r2_0)
- `list_max (repeat n (length l)) <= n` (pt_r0_5)
- `length l <= list_sum (map S l)` (pt_r0_1)

All are induction + `lia`. Novel means relative to the library and the corpus, as always.
