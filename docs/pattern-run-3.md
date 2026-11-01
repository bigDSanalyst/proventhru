# Pattern extractor, run 3: specification

Written: 2026-11-01, before the run, after run 2's results (`results/pattern-run-2.md`).
Status: in force from the commit that removed its draft line. Its hash is in
`docs/frozen.md`, with the governed code's `code:pattern-run-3` row, and
`tools/pattern_run.py --run 3` refuses to run unless both match.

Run 2's notes found a gap in how novelty was measured. A conjecture counted as novel when it
was:
- one of the development's held-out lemmas, rediscovered;
- or the development's own constructor `sorted_cons` with its premises swapped.

Read plainly, neither run 1 nor run 2 found a significant conjecture that's new relative to
the development. On 2026-11-01 the owner chose to close the gap and run once more.

This run closes the gap and changes nothing else. Everything not named here is as
`docs/pattern-run-2.md` fixes it:
- the proposer (`pattern/analogy-v2`) and its sources;
- the preamble with `Sorted` imported first;
- testing, the falsifier space and proving;
- significance (a)–(d), with run 2's stricter (d);
- registration.

Seeking-layer work. The gate, the kernel, the records and the frozen sets are unchanged.

## What changes: novelty

The development is its definitions, its inductives' constructors, and its own lemmas. The
lemmas are held out from the extractor, and the scorer reads them as before.

A formalizable candidate is **not novel** if any of these holds:
- **As in runs 1 and 2:**
  - it's closed at the gate by one tactic or one library lemma;
  - it's derived from a corpus lemma by arithmetic;
  - it's vacuous.
- **New in this run:**
  - it's one of the development's held-out lemmas (`ISortGold.v`), up to names, binder order
    and the sides of =, iff or Permutation. That's a rediscovery. It's still reported, as gold
    overlap, and it no longer counts toward novelty or significance;
  - it's closed by one constructor step (`intros; constructor.` or `intros; constructor;
    assumption.`, 2 s each), so it's present in the development or in the library, whose
    inductives' constructors are theirs. Refuted candidates aren't checked: no step closes
    them.

The definitional equations of the development's functions (`sort (a :: t) = insert a (sort
t)`) were already closed at the gate by `reflexivity`, so nothing changes for them.

Since the novel set changes, the rates (novelty, provability, significance) are over this
definition. The report shows how many candidates are present in the development and which
held-out lemmas were proved.

## The stopping rule, read now

The metrics doc says: "If two consecutive runs produce zero significant novel conjectures,
and the residue subclassification shows no new bucket, the pattern extractor is not working
as a discovery mechanism. That is the finding. Publish it."

For this proposer, it's read as follows, fixed before the run:
- **Run 2 is recounted under this run's novelty.** The report computes that count from
  `results/pattern-run-2-candidates.jsonl`: run 2's significant conjectures, less the held-out
  lemmas and the statements one constructor step closes. Run 2's own frozen counts stand. The
  recount only puts the two runs on one definition.
- **A residue bucket** is a (pattern kind, test outcome, gate status) triple of the novel,
  unrefuted, unproved candidates. A new bucket is one that run 3's residue has and run 2's
  doesn't.
- **The rule:** if run 2 recounted and run 3 both count zero significant novel conjectures, and
  there's no new bucket, then `pattern/analogy-v2` stops. The null is published as the
  finding: on this development, carrying library patterns over finds the development's own
  lemmas and nothing new that's significant. No run 4 of this proposer is added to "see if it
  works".
- **Otherwise,** the proposer goes on, and the report says why.

Run 3 uses run 2's proposer on the same development, so the same candidates are expected. The
prover's results can still differ, through timing (Timeout 5 and the 30 s deadline).

## What was seen before freezing

- **The constructor check was tested on run 2's case:** `sorted (n :: l1) -> m <= n -> sorted
  (m :: n :: l1)` closes by `intros; constructor; assumption.`, and `insert_sorted` doesn't.
- **One smoke run of the whole tool,** at 60 steps and one round, on the first 12 candidates
  sent to the loop, to exercise the new novelty and stopping code.
  - It proved nothing.
  - Its recount of run 2 under this definition is 0 of run 2's 3. That follows from run 2's
    public results: two held-out lemmas and one constructor.
  - Its outputs stay out of the results.
- **Nothing was proved at 600 steps** on run 3 before freezing.
- Run 2's results are public. Their plain reading (no significant conjecture new relative to
  the development) is what this run tests under a fixed definition.

## Deviations

Any deviation from this file is listed in the results with its reason.
