# Scoping: the loop on a real Coq development

Written 2026-10-10, after run 9 (`results/explore-run9.md`). This is a design document,
not a protocol: nothing is run from it until its open decisions are settled and the
experiment is frozen.

## The question

Pointed at another development's functions, does the loop find the helper lemmas that
development's own proofs use? And does any of its proofs cite a discovered lemma inside
an induction?

The first part is what Hipster, HipSpec and Lemmanaid measure (recall of gold lemmas). The
second is this project's metric. Run 9 showed it can't occur in the `nat` / `list nat`
signature: there, every proof is a fixed shape or a top-level chain.

## Why the signature has to change

A lemma is needed inside an induction when the step case's goal is about the
development's own function. In insertion sort, for example, the step case of
`sorted (sort l)` is `sorted (insert a (sort t))`, and the proof needs
`insert_sorted : sorted l -> sorted (insert a l)` exactly there, at an inner goal the
statement doesn't show. Developments built from recursive functions over inductive
types have this shape everywhere. The current signature doesn't: its functions are
library functions, whose interactions are monotonicity chains.

## What the loop needs that it doesn't have

1. **Propositions, not just equations and inequalities.** Real helper lemmas are
   implications between predicates: `sorted l -> sorted (insert a l)`,
   `Permutation l (sort l)`, `In x l -> In x (insert a l)`. The generator now builds
   only `t1 = t2` and `t1 <= t2` over `nat` and `list nat`. It needs:
   - predicate atoms (`sorted l`, `In x l`, `Permutation l1 l2`);
   - conditional laws (`P -> Q`), tested by evaluating P and keeping the test only
     when P holds (QuickSpec's conditional equations).
2. **The development's functions, executable for testing.** Today each function has a
   Python mirror in `conjecture.OPS`. For another development, either:
   - **(a)** hand-written Python mirrors, checked against Coq's `Compute` on sample
     inputs before use, so a wrong mirror is caught;
   - **(b)** testing in Coq itself: QuickChick, or `Compute` over enumerated inputs.
     Slower, but there is no mirror to get wrong.
3. **Type-generic enumeration,** at least for the development's own data types (for
   example, binary trees for a BST development).
4. **Structural tactics for the new types.** Induction on trees has two recursive
   cases, and `Permutation` proofs use its constructors. The structural shapes are
   written per type, and kept as a separate tactic set so the earlier results stay
   comparable.
5. **The evaluation:**
   - hold out the development's own helper lemmas;
   - let the loop explore its function signature;
   - measure recall (the share of held-out helpers the corpus contains, up to
     variable renaming or as derivations), as Lemmanaid does;
   - then try to prove the development's main theorems with the corpus as the
     preamble, and count inner citations in those proofs.

## Candidate developments

| candidate | why | caveat |
|---|---|---|
| Insertion sort and sortedness (`insert`, `sort`, `sorted`, `Permutation`) | Small. The textbook case where a helper lemma is needed in the step case. Main theorems: `sort_sorted`, `sort_perm` | The best-known source is VFA (Software Foundations vol. 3). Its licence must be checked before vendoring; otherwise write a minimal independent one, which stops being "someone else's development" |
| The Coq standard library's `Sorting` (`Sorted`, `Permutation`, `Mergesort`) | A real, independently written development, LGPL, already installed, with its own helper lemmas as gold | Larger, and its proofs lean on general list lemmas, so the held-out set needs choosing with care |
| Binary search trees (`insert`, `lookup`, `elements`, `BST`) | Trees exercise type-generic enumeration and two-case induction. Inner helper use is common | More generator work: a second inductive type |

Suggested order: a pilot on insertion sort (the smallest real case, to build items 1, 2
and 5), then the standard library's `Sorting` as the real test.

## Decisions needed before building

1. **Which development first.** The pilot on insertion sort, with the VFA licence
   checked, or straight to the standard library.
2. **Testing:** Python mirrors checked against `Compute` (fast, one mirror per function),
   or testing in Coq (slower, nothing to mirror).
3. **What counts as "the development uses it":** the held-out helper itself, or also an
   equivalent statement (up to renaming, argument order, or a derivation of it).
4. **Whether the model experiment rides on this:** `docs/model-experiment-spec.md`
   stays registered. Re-pointing it at this signature (its statement set R, and V as
   the new structural set plus saturation) is an amendment made after the pilot shows
   the loop meets statements that need an inner use, and before any model call.

## Effort, roughly

Items 1 to 3 are the bulk: generator support for predicates and conditional laws, and
a second type. They're a week or more of work, not a run. Items 4 and 5 are smaller.
Everything stays on CPU until the model experiment, if it's triggered.
