# Insertion-sort pilot, gate 2 (proof)

Criteria and phases fixed before any of this ran (`docs/isort-pilot.md`, gate 2 section).
Gate 1's 53 candidates go through the loop:
- the development's definitions as the preamble;
- 600 steps per candidate;
- open statements retried in the next round;
- 3 rounds for 2a, 4 for 2b. 2a proved nothing after round 0, so the extra round couldn't
  have changed it.

Gold is matched exactly, up to the names of bound variables only, and every match is
confirmed in Coq by closing the gold statement with the corpus lemma. Full numbers are in
`results/isort-gate2a.json`, `-2b-i.json` and `-2b-ii.json`.

| | 2a: existing prover | 2b-i: + corpus interface | 2b-ii: + isort tactics |
|---|---|---|---|
| lemmas admitted | 3 | 6 | 11 |
| **gold helpers proved exactly (of 5)** | **1** | **2** | **4** |
| **main theorems proved exactly (of 3)** | **0** | **0** | **1** |
| proofs citing the corpus | 0 | 2 | 3 |
| **inner citations** | **0** | **1** | **1** |
| axiom-free | yes | yes | yes |

Gold, by phase:

| gold | 2a | 2b-i | 2b-ii |
|---|---|---|---|
| `insert_length` (helper) | proved | proved | proved |
| `sort_length` (helper) | – | **proved, citing `insert_length` inside an induction** | **same** |
| `insert_sorted` (helper) | – | – | proved |
| `insert_perm` (helper) | – | – | proved |
| `sorted_sort_id` (helper) | – | – | – |
| `insert_In` (helper) | not expressible (an iff) | | |
| `sort_sorted` (main) | – | – | proved, with the helper's argument inline (below) |
| `sort_perm` (main) | – | – | – |
| `sort_idem` (main) | – | – | – |

## The phases

- **2a, the existing prover unchanged** (structural-tactics/v2, library retrieval, corpus
  index, saturation): 1 of 5 helpers. The loop doesn't carry over to a new development as
  it is.
- **2b-i, a generic change to how corpus lemmas are offered,** not specific to this
  development:
  - corpus lemmas are also offered as `rewrite` / `apply`, which find the instance by
    unification, including `rewrite`-then-close in one step;
  - an induction that closes the trivial cases, so the step case is the first goal.

  The corpus index reads only the first goal, and after `induction` that's the base case,
  so the step case, where a discovered lemma is used, was hidden. This adds `sort_length`.
- **2b-ii, `structural-tactics/isort/v1`:** induction on a `sorted` hypothesis, `<=?`
  cases turned into `<=` / `>` for `lia`, and `Permutation`'s constructors. This adds
  `insert_sorted`, `insert_perm` and `sort_sorted`.

So the development needed both kinds of change. The generic one (2b-i) should carry over
to any development. The type-specific one (2b-ii) is per development, which is the
scope doc's per-development cost, now measured.

## The inner citation, read precisely

    sort_length:  intros. induction l1 as [|a t IH]; simpl in *; try solve [lia | reflexivity | constructor].
                  rewrite pt_r0_7; first [lia | reflexivity | congruence | assumption].

`pt_r0_7` is `insert_length`, proved in round 0. `sort_length` was retried in round 1 and
proved using it at the step case `length (insert a (sort t)) = S (length t)`, a goal the
statement doesn't show. It passes the derivation check (one lemma plus `lia` doesn't close
it), and neither 2a nor the first 2b-i run proved it. It's the first inner citation in the
project, from the loop itself, not only the hand-run test.

**What it is, mechanically:** the corpus index offered `insert_length` because the step
goal mentions `insert` and `length`. That's the same term-overlap rule as at the top,
applied once the interface stopped hiding the step case. The prover didn't choose the
lemma for what the goal became; it tried what was offered, and it worked.

## `sort_sorted`: the helper's argument, inline

`sort_sorted` was proved in round 0, before `insert_sorted` was in the corpus. Its proof
inducts on `l1`, then inducts again on the induction hypothesis `sorted (sort t)`. That
re-proves `insert_sorted`'s content inside the step case instead of citing it. Two
consequences:
- **Citation counts are a lower bound on what the corpus is worth.** When a structural
  shape can rebuild a helper inline, the proof doesn't need to cite it, and it won't.
- **Retrying open statements is what turns this into corpus growth.** Without it,
  `sort_sorted`'s neighbours never see `insert_sorted`.

## Left unproved, and what each needs (for gate 3)

- **`sort_perm`:** at the step case, `Permutation (a :: t) (insert a (sort t))`, which
  chains `perm_skip` of the induction hypothesis with the corpus lemma `insert_perm`
  through `perm_trans`. The lemma is used as one side of a transitivity step, not by
  rewriting or applying it to the goal. Term overlap retrieves it; no offered form uses
  it that way.
- **`sorted_sort_id`:** induction on the `sorted` hypothesis, then rewriting with the
  induction hypothesis under `insert`, and a `<=?` case.
- **`sort_idem`:** from `sorted_sort_id` applied to `sort_sorted`, so it waits on
  `sorted_sort_id`.
- One proved lemma is `insert_perm` in the other orientation (`pt_r1_1`, via a rewrite
  with `insert_perm`). It isn't counted as a gold match.

## A note on the interface

Each step's observation holds every open goal, but the policy reads only the first, and
tactics apply to the first. So matching corpus lemmas to a later goal, the deeper fix you
named, is possible at the policy layer, with goal selectors (`2: rewrite L`) so the
candidate acts on the goal it was matched to. "Close trivial cases first" works around
the same limit by reordering.
