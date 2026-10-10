# Insertion-sort pilot: plan and gates

Written 2026-10-10, before any pilot code exists. Scoped in `docs/real-development-scope.md`.
Decided:
- the pilot is a small development in our own code (`pilots/isort/`), not copied from VFA;
- candidates are tested in Coq, not in Python mirrors;
- the headline count is exact matches of the development's own helper lemmas, with an
  up-to-derivation count as a supplement;
- `docs/model-experiment-spec.md` is not amended.

## The development

- `insert : nat -> list nat -> list nat`
- `sort : list nat -> list nat`
- an inductive `sorted : list nat -> Prop`

Its helper lemmas and main theorems are written and proved in a separate file
(`ISortGold.v`), which the loop never loads. They're the held-out gold. The loop sees only
the definitions.

## Testing in Coq

Candidates are evaluated by Coq's own `vm_compute` on enumerated inputs. Predicates are
evaluated through boolean versions written in Coq (`sortedb`, membership, a
permutation check). Each boolean version is tied to its predicate by a reflection lemma,
proved and compiled before any test runs, so a wrong boolean version can't pass silently.

## Gates, measured and reported in this order

A later gate is undefined if an earlier one fails.

1. **Proposal.** Does the loop propose candidates that mention the development's
   functions (`insert`, `sort`, `sorted`) and that formalize, i.e. elaborate in Coq?
   Reported:
   - the number of candidates mentioning each function, after testing;
   - how the gate classifies them;
   - how many gold helpers appear among the candidates, exactly (up to variable
     renaming).

   Fails if no candidate mentions the development's functions, or none elaborates.
2. **Proof.** Can the loop prove any of them? Reported: proved, by function; gold helpers
   proved (the exact count is the headline). Fails if none of the development's
   candidates is proved.
3. **Depth.** Does any proof cite a corpus lemma inside an induction or case split
   (`docs/conjecture-metrics.md`)? Then, with the corpus as the preamble, can the prover
   prove the development's main theorems, and with inner citations?

Each gate is reported before the next is built or run.
