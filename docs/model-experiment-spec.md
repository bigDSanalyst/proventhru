# Model experiment: specification, written before its statement set is known

Written 2026-10-10, while exploration run 8 (`structural-tactics/v2`, 6 × 80) was still
running and before any of its open statements were classified. The commit that adds this
file is its timestamp. The experiment runs only if the stopping rule in
`docs/conjecture-metrics.md` (amendment of 2026-10-10) fires.

Before any model call, the experiment is frozen into `PROTOCOL.md` as a v6 amendment:
the statement set's hash, the conditions, the budget and the analysis below. The
pipeline refuses model policies without a protocol, so this is enforced, not just
written down. Anything this file leaves open is decided in that amendment, before the
set is run, and recorded as a deviation from this file.

## The question

Does a model, offered as one more candidate source next to the strongest fixed prover,
prove open statements that the fixed prover cannot, at the same step budget? And are
those proofs structural, citing a corpus lemma at an inner goal, or only mechanical?

## The statement set R

Chosen mechanically from run 8, by rules fixed here:
- **If run 8 has any inner citation**, or `tools/subclassify_opens.py` puts any
  statement in the interior bucket: R is the interior bucket.
- **Otherwise:** R is every open statement of run 8 in class 2, 2s or 3 of
  `tools/classify_opens.py --prover structural2`, minus the buckets false and gap of
  `tools/subclassify_opens.py`. False ones aren't theorems. Gap ones have no corpus
  lemma to cite, so a citation can't be the outcome.

R is written to a file in the order the classifier lists it, and its sha256 goes in the
v6 amendment. Statements of the held-out and dev sets can't be in R: exploration
excludes them.

The preamble is the full corpus of run 8, recompiled, and `Print Assumptions`-clean.

## Conditions, paired on R

- **V (control):** `structural-tactics/v2`, plus library retrieval, plus the corpus
  index (`CorpusRetrievalPolicy(StructuralTacticsV2(), corpus)`), as in run 8's second
  pass.
- **MV (model added):** the same policy, with the model's candidates added to it, not
  substituted for it. That's the "fixed + retrieval + model" condition the v5 results
  named as the natural next one.

Both run at 600 steps per statement, the same budget per candidate that run 8 gave
(300 fixed + 300 with retrieval), with the step definition of `PROTOCOL.md`.

## The model

M1, exactly as frozen in `PROTOCOL.md` v5:
- `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`;
- vLLM 0.31.0, bf16, on an A100;
- temperature 0, seed 0, max 400 tokens, k = 5, re-asking up to 3 times, JSON schema
  with arity;
- prompt `e26d4a77…`.

Only the policy it's added to changes. The prompt isn't re-tuned: tuning on R would
contaminate it.

## Outcomes

- **Primary:** on R, the statements MV proves and V doesn't, against the reverse, by
  an exact two-sided McNemar test at α = 0.05.
  - If R has fewer than 20 statements, no test is run: the counts are reported
    descriptively and called underpowered.
- **Key secondary (the one the loop was built for):** among MV's proofs of statements V
  leaves open:
  - the number with an inner citation (`docs/conjecture-metrics.md`, counted only for a
    statement that passed the derivation check);
  - the number that are necessary compositions, judged against the strongest prover at
    the time (V itself, with the corpus index removed, at 600 steps).
- **Reported, not tested:**
  - invocations, steps, tokens and failure classes (api / invalid / unproductive), as in
    the v5 results;
  - each MV-only proof, with its kernel certificate.

**Success** means the key secondary is at least one inner citation or one necessary
composition, the reason to run this at all. A significant primary result without either
would mean the model adds proofs of the same mechanical kind.

## Cost ceiling

- **30 Colab A100 compute units**, of the 97 left.
- After the first 10 statements of MV, units used are extrapolated to all of R. If the
  projection is over 30, the run stops there. It's then reported as incomplete on the
  statements run, and is not extended without a new amendment.
- V runs on CPU (this container or Colab CPU) and costs no units.
- If R has fewer than 10 statements, it runs whole, with the ceiling still applying.

## What would change this file

Only an amendment, dated and committed before R is run. Each amendment says what
changed and why, as `PROTOCOL.md`'s history table does.
