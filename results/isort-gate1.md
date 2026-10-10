# Insertion-sort pilot, gate 1 (proposal): passed

`tools/isort_pilot.py gate1`, as planned in `docs/isort-pilot.md`. The development
(`pilots/isort/ISort.v`) is our own `insert`, `sort` and inductive `sorted`. Its helper
lemmas and main theorems are proved in `ISortGold.v`, which the loop never loads. Every
term and candidate was evaluated by Coq (`vm_compute`), with predicates going through
boolean versions proved equivalent to them (`ISortTest.v`). Full numbers:
`results/isort-gate1.json`.

| | |
|---|---|
| candidates, after testing in Coq | **53** |
| mentioning `insert` / `sort` / `sorted` | 11 / 44 / 5 |
| kinds | 14 equations, 14 facts, 25 conditionals |
| elaborate in Coq | **53 of 53** |
| gate: open / trivial | 50 / 3 |

**Gold, at the proposal stage:**

| gold | role | proposed? | gate |
|---|---|---|---|
| `insert_length` | helper | exact | open |
| `sort_length` | helper | exact | open |
| `insert_sorted` | helper | exact | open |
| `insert_perm` | helper | exact | open |
| `sorted_sort_id` | helper | exact | open |
| `insert_In` | helper | not expressible: an iff, which the generator doesn't build | – |
| `sort_sorted` | main | exact | open |
| `sort_perm` | main | exact | open |
| `sort_idem` | main | exact | open |

**5 of 6 helpers and 3 of 3 main theorems are proposed exactly.** Exact means the same
statement up to variable renaming, or with the sides of `=` or `Permutation` swapped.

Gate 1 measures proposal only. Whether any of these can be proved is gate 2.

## An instrument failure, caught and fixed before this count

The first gate-1 run passed false conditionals such as
`Permutation l1 l2 -> sorted l2` and `Permutation l1 l2 -> sort l1 = l2`. Both the
inputs used to tell terms apart and the final check set took `l2` as a permutation of
`l1` only in its sorted form. So the premise `Permutation l1 l2` never held for an
unsorted `l2`. Both sets now include reversed and rotated permutations, and the false
conditionals are gone.

It's the same shape as the earlier silent failures: inputs that agree with a wrong
statement by construction. The 53 above are from the corrected run.

## Notes for gate 2

- Some candidates are the same law in two orientations (`sort l1 = sort l2` and
  `sort l2 = sort l1` under `Permutation l1 l2`). That's harmless for proposal, and
  the derivation check will handle it in the loop.
- The 3 trivial ones are library instances (`rev (rev x) = x`) or one-step unfoldings
  (`sort (n :: l) = insert n (sort l)`).
