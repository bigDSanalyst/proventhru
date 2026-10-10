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

## Gate 1 result, and gate 2's criteria (2026-10-10, before gate 2 runs)

**Gate 1 passed** (`results/isort-gate1.md`):
- 53 candidates about the development, all elaborate;
- 8 of the 9 gold statements were proposed exactly: 5 of the 6 helpers and 3 of the 3
  main theorems;
- the ninth, `insert_In`, is an iff, which the generator doesn't build: a limit of the
  generator, counted as not proposed.

**Gate 2 (proof), measured in this order:**
1. **Primary:** how many of the 5 proposed gold helpers the loop proves. "Exactly" means
   the proved corpus lemma is the gold statement up to the names of bound variables
   only: no swapped sides, no derivation. Each match is confirmed in Coq by closing
   the gold statement with `exact` and the corpus lemma.
2. **Secondary:** how many of the 3 main theorems it proves.
3. **Tertiary, within the pilot (not gate 3):** whether any proof cites a corpus lemma,
   and at what position (top or inner). With 53 candidates, inner citations aren't
   expected. If one appears, it's flagged at once.
4. **Supplement:** gold helpers proved in the other orientation, or present as
   derivations, each with the stated equivalence.

**Two phases:**
- **2a:** the existing prover, unchanged: `structural-tactics/v2` + library retrieval +
  corpus index + saturation, with open statements retried in the next round (the corpus
  may have the helper by then). This tests whether the loop generalizes to a new
  development without modification.
- **2b:** only if 2a leaves gold helpers unproved: a tactic set for the development's
  predicate (induction on a `sorted` hypothesis, a case on `<=?`), named
  `structural-tactics/isort/v1` and kept separate from v2. Reported against 2a: the
  difference is the finding.

**Budget:** 600 steps per candidate, as in the exploration runs.
