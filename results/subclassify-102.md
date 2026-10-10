# Run 7's 102 unexplained open statements, subclassified

`tools/subclassify_opens.py` splits class 3 of `tools/classify_opens.py` and leaves the
ladder and its other classes unchanged. Each statement goes to the first bucket that
explains it, and every bucket except gap and unknown comes with a closing script checked
by Coq.

| bucket | count | what it lacks |
|---|---|---|
| false | 4 | nothing: it's false, failing on a list of length at most 6 with elements 0..2 (`length (removelast (removelast (removelast l))) <= list_sum l` fails at `[0; 0; 0; 0]`) |
| combined | **54** | **a tactic shape, no lemma at all**: a case on a `match` that `simpl` leaves behind (27), the same keeping each case's equation (23), or a number reverted before induction plus a case (4) |
| gap | 3 | `filter` commuting with `rev` or `removelast`: nothing in the corpus mentions only their terms |
| rev | 29 | `list_max (rev l) = list_max l` and `list_sum (rev l) = list_sum l`: given those (proved inline), the corpus lemmas close it |
| library | 1 | a chain that needs library inequalities as well as corpus lemmas |
| base | 4 | `list_max l <= list_max (map S l)` and `list_max (map S l) <= S (list_max l)`: given those, the corpus lemmas close it |
| interior | **0** | a corpus lemma inside an induction, with the same script failing without it |
| unknown | 7 | `removelast` of a `filter` of `map S` (4), `length (removelast (rev l)) = length (removelast l)`, and two `skipn (list_max l) l` statements |

## One more vocabulary gap, not composition

The 54 in combined need no lemma. They need a case on a `match`:
- `simpl` turns `Nat.max (S a) x` into `match x with 0 => … | S m => … end`, which `lia`
  can't see through;
- `filter` leaves `if Nat.even a then … else …`, an `if` being a `match` on a bool;
- casing it again later needs the earlier case's equation, so the contradictory branch
  closes (`destruct x eqn:E`).

The structural tactics case on the tail and on an `if` at the top, but never on a `match`
that `simpl` produces mid-proof.

The rev (29) and base (4) buckets sit one level above that gap. The lemmas they need,
`list_max (rev l) = list_max l` and the `map S` bounds, were all generated and passed the
gate as open in run 7, and the prover failed them. They're in the combined bucket
themselves, or close with `simpl` again after a library rewrite. So 87 of the 102
(combined, rev, base) come down to two tactic shapes.

## For the model question

Interior is 0: no statement here needs a corpus lemma used inside an induction. Under the
rule set before this ran, nothing in run 7's residue justifies a model-as-prover run on
the A100. The 7 unknowns are too few to decide anything.

Saturation targets composition. Here composition is classes 2 and 2s of the ladder (70
statements), not this residue: this subclassification found none.

## Generator note

Four statements are false and passed random testing: their counterexamples need several
zeros in one list. Exhaustive testing on small lists (length at most 6, elements 0..2)
finds them. That's cheaper than more random samples, and the generator should do it.
