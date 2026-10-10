# Related work for the conjecture loop

The work this repository builds on or measures itself against, mapped to the
part of proventhru it bears on. Collected October 2026. Each entry says what
we take from the work, or where we differ. The figures are as the papers
report them; papers with more than one version are noted.

## At a glance: what we take

| work | what we take | status here |
|---|---|---|
| QuickSpec / HipSpec / Hipster | test-then-prove theory exploration; proved lemmas feed later proofs | the loop's design |
| QuickSpec's pruning | skip terms a known lemma rewrites, before testing | not yet; we prune after proof, by derivation |
| LEGO-Prover's evolver | generalize discovered lemmas and re-gate them | built: seeding by anti-unification and subterm generalization |
| Lemmanaid | the model proposes lemma shapes, symbolic search fills them | the first model-in-the-generator step, when we get there |
| STP / Minimo / UseFor | reward conjectures just within reach, or useful to later proofs | measurable from the records (`uses_of_corpus`), not yet used as reward |
| LeanConjecturer | self-play collapses onto few topics | measure generator coverage before a model generates |
| Rango | retrieve similar proofs, not just lemma names | a candidate B variant; needs an amendment for test |
| Lean skill files | a result counts only with no `sorry` and no axioms | built: `Print Assumptions` on every corpus lemma |

## Theory exploration: the ancestor of `proventhru explore`

- **QuickSpec, HipSpec, Hipster, TheSy.**
  [Overview: *Conjectures, Tests and Proofs: An Overview of Theory Exploration*](https://arxiv.org/pdf/2109.03721);
  [HipSpec (CADE)](https://www.cse.chalmers.se/~jomoa/papers/hipspec-cade.pdf);
  [Hipster (ITP 2017)](https://www.cse.chalmers.se/~jomoa/papers/HipsterITP17.pdf);
  [TheSy (CAV 2021)](https://link.springer.com/chapter/10.1007/978-3-030-81688-9_6).
  - QuickSpec enumerates terms by size and tests them. It skips terms that
    lemmas already found can reduce.
  - HipSpec sends QuickSpec's conjectures to a prover, and the proved ones
    become lemmas for later proofs.
  - Hipster does the same in Isabelle.
  - TheSy filters symbolically instead of by testing, and argues that testing
    stops scaling for larger types.
  - **Us:** `conjecture.py` is QuickSpec-style, and `explore.py` is the HipSpec
    loop with Coq's kernel as the prover's judge. What we add:
    - the gate's novelty test against the library;
    - derivations recorded rather than discarded;
    - number-only drops certified by `lia`/`nia` rather than only tested;
    - the evaluation sets excluded by construction.
  - **Still to take:** QuickSpec's pruning, which skips a term that a known
    lemma rewrites to a smaller one, cuts the stream before testing. We prune
    only after proof, by derivation.

## Conjecturing and proving together

- **STP: Self-play LLM theorem provers** (Dong & Ma, ICML 2025).
  [Paper](https://proceedings.mlr.press/v267/dong25h.html);
  [arXiv v2](https://arxiv.org/html/2502.00212v2).
  - One model both conjectures and proves. The conjecturer is rewarded for
    statements just within the prover's reach.
  - Reported: 28.5% on LeanWorkbook (ICML version; arXiv v2 says 26.3%);
    65.0% on miniF2F-test at pass@3200.
  - **Us:** "just within reach" is the curriculum signal our records can
    already compute (proved at a budget, not by the gate). It's the obvious
    reward for a conjecturer once a model generates.
- **LeanConjecturer** (2025). [arXiv 2506.22005](https://arxiv.org/html/2506.22005v1).
  - Reports STP's failure modes: mode collapse onto a few topics, and
    instability as the data distribution moves.
  - **Us:** a reason to keep the generator's space explicit and measured
    (fingerprint classes, per-round gate counts) before a model generates.
- **Minimo: Learning formal mathematics from intrinsic motivation** (Poesia,
  Broman, Haber & Goodman, NeurIPS 2024).
  [arXiv 2407.00695](https://arxiv.org/abs/2407.00695v2).
  - An agent learns to pose and to prove from axioms alone, with
    type-directed conjecture synthesis. Domains: propositional logic,
    arithmetic, groups.
  - Follow-up: [*Usefulness-Driven Learning of Formal Mathematics*
    (NeurIPS 2025)](https://neurips.cc/virtual/2025/131119) rewards
    conjectures for being useful to later proofs.
  - **Us:** usefulness is what `uses_of_corpus` and the citation sites measure.

## A library that grows during proving

- **LEGO-Prover: neural theorem proving with growing libraries** (ICLR 2024).
  [arXiv 2310.00656](https://arxiv.org/pdf/2310.00656).
  - A prover retrieves verified lemmas from a skill library and adds new
    ones. An evolver generalizes lemmas.
  - Reported: 22,532 skills; miniF2F-valid up from 48.0% to 57.0%. The
    ablation credits the added skills with +4.9%.
  - **Us:** the evolver is the "seed the generator from a discovered lemma"
    mode the loop still lacks. Run 3, round 2 shows why it's needed: four
    admitted lemmas are instances of one missing general lemma,
    `list_max l1 <= list_sum (l1 ++ X)`.

## Neuro-symbolic lemma conjecturing

- **Lemmanaid** (Alhessi et al., ICML 2025).
  [arXiv v5](https://arxiv.org/html/2504.04942v5);
  [ICML page](https://icml.cc/virtual/2025/52423).
  - An LLM proposes lemma *templates*, the shape of a lemma, and symbolic
    search fills them in.
  - Reported: about 50% of gold lemmas on Isabelle's HOL library and 28% on
    the AFP (v5; v3 reports lower). On an Octonions case study, 79% against
    62% for neural-only and 23% for QuickSpec.
  - **Us:** the cleanest route to a model in the generator that keeps our
    truth layer. The model proposes shapes, and enumeration, testing, the
    gate and the kernel do the rest. Unlike a free-form model conjecturer,
    it can't invent undefined symbols.

## Coq/Rocq provers with retrieval: our B, and the tactic-form question

- **Rango** (ICSE 2025). [arXiv 2412.14063](https://arxiv.org/html/2412.14063v2).
  - Retrieves premises *and similar proofs* at each step. Its CoqStoq
    dataset has 196,929 theorems.
  - Reported: 32.0% proved, 29% more than Tactician. The ablation credits
    +47% to retrieved proofs in context.
  - **Us:** our retrieval offers lemma names only. Retrieving proofs, for
    example the corpus lemma's own proof script, is a natural B variant.
- **RocqStar** ([arXiv 2505.22846](https://arxiv.org/pdf/2505.22846)),
  **Planning to Hammer** ([arXiv 2606.17981](https://arxiv.org/pdf/2606.17981)),
  and AutoRocq: recent Rocq agents and benchmarks to compare against if a
  model condition is added.

## Surveys and reading lists

- **DL4TP**, the paper list for *A Survey on Deep Learning for Theorem
  Proving* (COLM 2024), more than 180 papers: [github.com/zhaoyu-li/DL4TP](https://github.com/zhaoyu-li/DL4TP);
  survey: [arXiv 2404.09939](https://arxiv.org/html/2404.09939v3).
- **ai4math-papers** (j991222), a curated list:
  [ecosyste.ms entry](https://awesome.ecosyste.ms/api/v1/projects/github.com%2Fj991222%2Fai4math-papers).

## Agent instruction files (SKILL.md / AGENTS.md)

All the maintained ones found are for Lean 4. None was found for Rocq.

- **cameronfreer/lean4-skills**: a prove / review / golf workflow, mathlib
  search, and axiom checking. [Listing](https://www.claudepluginhub.com/marketplaces/cameronfreer-lean4-skills).
- **epfl-lara/LeanProbe**: an AGENTS.md tool contract, moved into an
  installable SKILL.md. [Releases](https://github.com/epfl-lara/LeanProbe/releases).
- **smithery lean4-theorem-proving**: a result counts only when the build
  passes, with zero `sorry` and zero custom axioms.
  [Listing](https://www.skills.sh/site/smithery.ai/lean4-theorem-proving).
  - **Us:** adopted. `explore` runs `Print Assumptions` on every corpus
    lemma each round and stops if any rests on an axiom.
