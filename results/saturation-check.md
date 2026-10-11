# Saturation on run 8's open statements

`tools/saturation_check.py` on exploration run 8: its final corpus (180 lemmas) as the
preamble, its 88 open statements, 600 steps each, three policies paired:

| policy | what it is | proved |
|---|---|---|
| P | run 8's own second-pass policy: structural-tactics/v2, library retrieval, the corpus index (one lemma per candidate) | 1 |
| PS | P plus saturation | **73** |
| V0 | the necessary-composition control: structural-tactics/v2 and library retrieval, no corpus index | 1 |

PS proves everything P does, plus 72 more. For each of the 72, the proof's saturation step
was minimized (each stated lemma dropped if the proof closes without it):

| | count |
|---|---|
| cite two corpus lemmas | 59 |
| cite three | 11 |
| cite one, used as a rewrite with a library lemma (not a derivation: `pose proof; lia` doesn't close them) | 2 |
| derivations (one corpus lemma plus arithmetic) | 0 |
| also proved by V0 | 0 |
| **necessary compositions** (cite at least two, not a derivation, V0 fails) | **70** |
| **inner citations** | **0** |

A typical proof:

    intros. pose proof (pt_r0_22 (firstn n l1)); pose proof (pt_r0_29 l1 n). lia.

**Crowding: none found.** Each round's retrieval pass of run 8 was replayed with the
corpus that round saw and that pass's 300 steps:
- round 3: P proves 1 of 14, PS proves 11;
- round 5: P proves 1 of 6, PS proves 5.

PS lost nothing P proved. Saturation is offered only in the retrieval pass, after the
cheap closers and the one-lemma forms, so the structural pass is unchanged. The replayed
passes are small, because the structural pass proves most candidates first. The
loop-level check of crowding is run 9's per-round proof rate.

(The tool's first crowding check reran the run's already-proved statements under the
final corpus. The gate closes those as trivial before any prover sees them, so that
check measured nothing. It's replaced by the replay above.)

## Reading it against docs/conjecture-metrics.md

- **Necessary composition: 70**, judged against the strongest prover at the time
  (structural-tactics/v2, no corpus). It's the first time the loop's corpus is
  necessary to a proof: without it, the same prover at the same budget proves 1 of 88.
- **Inner citations: 0.** Every composition is at the top: state two or three lemmas at
  subterms of the goal, then `lia`. The corpus now enables proofs, but only as a
  chain of monotonicity facts, not inside an induction.

Saturation is a fixed operator we installed. These 70 proofs are compositions the
operator makes possible, not something the system learned. The corpus compounds through
it: more lemmas give more chains. The operator itself doesn't change.
