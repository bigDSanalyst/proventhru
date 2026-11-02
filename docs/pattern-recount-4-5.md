# Pattern extractor: the necessary-premise (d), and runs 4 and 5 recounted

Written: 2026-11-02, after runs 4 and 5 (`results/pattern-run-4.md`, `results/pattern-run-5.md`),
on the owner's decision of 2026-11-02 to fix the measure before any more model runs.
Status: in force from the commit that registers its hash in `docs/frozen.md`, with the code row
`code:pattern-recount` (`tools/pattern_recount.py` and the code it runs).

Seeking-layer work. The gate, the kernel, the records and the frozen sets are unchanged.

## Why

- **(d), as frozen since run 2,** counts a proved novel conjecture that names two of the
  development's symbols that no development statement names together. One-step weakenings of
  another proved conjecture or a gold lemma are excluded.
- **In runs 4 and 5, all 4 conjectures it counted got there through premises their proofs
  don't use.** Without those premises, each is a standard library fact or `insert_sorted`
  applied twice. The runs' notes checked this in Coq.
- **A premise the proof doesn't need connects nothing.**

## The necessary-premise (d)

- **What it applies to:** a proved novel conjecture that (d) as frozen counts, after the
  weakening check.
- **The check, for each symbol of its pairs:**
  - A symbol in the conclusion is needed.
  - For a symbol only in premises, every premise that mentions it is replaced by `True`. Then
    the conjecture's own recorded proof is run on the result, in one file compiled from
    scratch by `coqc`, with the development's definitions and the corpus lemmas the proof
    cites. If it compiles, the symbol isn't needed.
- **How it counts:** a pair counts if both its symbols are needed, and the conjecture is
  significant by (d) if any pair counts.
- **Why it's sound:** replacing a premise by `True` keeps the name of every hypothesis the proof
  uses, so the proof runs as recorded. A compile is a kernel-checked proof of the statement
  without those premises.
- **The control:** the statement as recorded, rendered the same way, must compile with its
  proof. If it doesn't, the check doesn't apply, and the conjecture's pairs stand as frozen
  (and that's reported).
- **It works in one direction only.** A premise the recorded proof uses still counts as needed,
  even if another proof wouldn't need it. The check removes the padding a proof shows; it
  doesn't search for more.
- **Unchanged:** (a)–(c), novelty, testing and proving.

## Runs 4 and 5, recounted

- **Inputs:** the two runs' recorded directories, i.e. their scored rows and corpus. They're
  archived with the owner, and their heads are cited in `results/pattern-run-{4,5}-records.md`.
  Nothing is re-proved or re-tested.
- **The outcome was known before this was written.** The runs' notes ran this check by hand on
  all 4 conjectures, and every premise was unneeded. So the recount confirms that reading with
  registered code; it isn't a test of the proposer.
- **What follows:**
  - **If both runs recount to 0,** the signal runs 4 and 5 registered doesn't stand.
    - The metrics doc's stopping rule also needs the second run's residue to have no new
      (kind, test, gate) bucket.
    - Run 5's has one: (general form, untestable, open). So `pattern/model-m1-v1` doesn't stop
      either.
    - The next step is the owner's. One option is a third batch (run 6: seeds 8–11, 24 calls,
      one A100 session) scored under this (d), whose result reads the rule against run 5. The
      other is stopping the proposer by decision, reported as that.
  - **If either run recounts to 1 or more,** the signal stands, and the registered next step is
    unchanged: expand the signature.
- **From now on, every pattern run is scored with this (d),** registered with that run's code.

## Deviations

Any deviation from this file is listed in the results, with its reason.
