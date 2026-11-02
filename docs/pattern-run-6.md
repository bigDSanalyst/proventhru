# Pattern extractor, run 6: M1's third batch, under the necessary-premise (d)

Written: 2026-11-02, after the recount of runs 4 and 5 (`results/pattern-recount-4-5.md`), on the
owner's decision of 2026-11-02 to run one more batch of M1 in the Colab session of target 2's
smoke test.
Status: in force from the commit that registers its hash in `docs/frozen.md`, with two code rows:
- `code:pattern-m1` v2: the proposer, `tools/pattern_m1.py` with batch C added, which runs in
  Colab;
- `code:pattern-run-6`: the scoring, `tools/pattern_run.py --run 6`, which runs here on CPU.

Seeking-layer work. The gate, the kernel, the records and the frozen sets are unchanged.

## Why a third batch

- Under the necessary-premise (d), runs 4 and 5 count 0 significant novel conjectures.
- The metrics doc's stopping rule also needs the second run's residue to have no new (kind,
  test, gate) bucket. Run 5's has one: (general form, untestable, open).
- So the rule doesn't stop `pattern/model-m1-v1` on runs 4 and 5. Run 6 is its next run, and the
  rule reads it against run 5.

## The proposer: unchanged except for the seeds

- **Batch C** is seeds 8–11: 24 calls (six kinds × four seeds), up to 192 statements.
- **Everything else is runs 4 and 5's:** the model and its served name, the development it's
  shown, the prompt template, the kinds, K, the schema and the sampling.
  - Every request body of batches A and B is byte-identical to v1's, so their cache keys are
    too (checked against v1's code).
  - The prompt identity hash covers the batches, so it changes, from `716fa2c2…` to
    `cffb853091e5c8201734a8fd3fad4dae079a781470a64c08f4a5d70be1436a8f`. Only batch C's requests
    are new.
  - So run 6 is a run of the same proposer, `pattern/model-m1-v1`, for the stopping rule.
- **The calls:**
  - In Colab, cell P-2 runs `tools/pattern_m1.py --batch C` in the session of target 2's smoke
    test, while vLLM serves M1 and before the smoke test trains.
  - Its output goes to Drive `runs/pattern-m1-c/proposals.jsonl`. The cache is runs 4 and 5's
    (`cache/pattern-m1.jsonl`).
- **A100 time:**
  - The session's setup is counted in the smoke test, which needs it anyway.
  - P-2's own minutes are reported from the cell's elapsed time. They count against the
    pattern extractor's 5-unit cap (as run 4's did), not against target 2's U or U_smoke.

## Scoring, here on CPU

- **Exactly run 5's** (`docs/pattern-run-4.md`), except (d).
- **(d) is the necessary-premise (d)** (`docs/pattern-recount-4-5.md`), applied after the weakening
  check. For each proved conjecture, the report lists the symbols that come only from
  premises its proof doesn't need.
- **Unchanged:** the prover's settings, the closed novelty, testing and the significance
  searches are run 5's.

## The stopping rule, read now

Run 5 counts 0 under this (d) (its recount). Run 6 is read against it:
- **If run 6 counts 0, and its residue has no bucket that run 5's lacks:** by the metrics doc's
  rule, `pattern/model-m1-v1` stops, and the null is published.
- **If run 6 counts 1 or more:** the proposer has signal.
  - Each such conjecture is reported, and read by hand as runs 4 and 5's were.
  - The registered next step is the metrics doc's: expand the signature, not the model.
- **If run 6 counts 0 but its residue has a new bucket:** the rule doesn't fire.
  - Run 6 is the last batch registered for this proposer, so it stops by the cap set here.
  - That's reported as "stopped by the cap, with its residue still moving", not as a null by
    the rule.

## What was seen before freezing

- **No model call for batch C was made.**
- **A smoke run of run 6's scoring,** on 8 statements written by hand in a made-up batch C file
  (60 steps, one round). Three of them were also run at 600 steps (one round) to watch the
  check act on proofs:
  - the two with a `sorted` premise their proofs don't use lost their pairs;
  - `length l1 = 0 -> sorted l1` kept its pair.

  These outputs stay out of the results.
- **The recount of runs 4 and 5 is known** (`results/pattern-recount-4-5.md`).

## Deviations

Any deviation from this file is listed in the results, with its reason.
