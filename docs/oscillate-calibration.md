# oscillate: a calibration, stated before any data is looked at

Written 2026-10-10. Exploratory, not a validated prediction. It doesn't use the prediction
register, and its result can't anchor one. Its only job is to decide between keeping
oscillate for a later learning policy and dropping it.

## Why now, and what it can't show

Every step record carries an empty `phase` field (`digest`, `distance`, `regime`,
`signature`, all null), and has since record v1. oscillate was meant to read the phase
state of a learning policy, and there's no learning policy here: the provers are fixed
tactic lists with retrieval and saturation. So this calibration can't test oscillate as
designed.

What it can test is whether the per-step signals a phase reading would be built from
carry any information in this domain at all. If they don't predict anything here, where
search outcomes vary a lot between branches, there's little reason to expect them to be
useful later.

## Data

Two runs:
- **Run 8** (`structural-tactics/v2`) to explore. Any mapping from signals to a reading
  is chosen on run 8 only.
- **Run 9** (v2 + saturation) to test, once, with the mapping fixed beforehand.

Both runs' records exist. Run 9's are not looked at for this purpose before the mapping
is fixed.

## Signals, per step (from the record, or by replaying its path)

- the change in open goals;
- the change in hypotheses;
- the change in the conclusion's size;
- error, refusal and timeout;
- whether the resulting state was already seen in the episode (revisit);
- the depth of the path.

## Outcomes

1. **Step level, within proved episodes:** is the step on the final proof's path, or off
   it?
2. **Episode level:** from the readings of the first 50 steps, does the episode end
   proved?

## The readings, and the measure

The reading is a classifier from the signals to {ordered, edge, disordered}, fixed on
run 8. It's scored by AUC on run 9: the ordered-vs-other reading as a predictor of each
outcome. The decision:
- **AUC ≥ 0.70 on both outcomes:** keep oscillate, to be built for the policy once one
  exists.
- **AUC < 0.60 on both:** drop it (option A). The phase field leaves the record schema in
  a record v2, and the README stops naming it.
- **Anything else:** inconclusive. It stays out of the architecture until a learning
  policy exists, with the empty field kept until a schema change is needed for another
  reason.

Baselines, reported next to it: the same AUC from the existing reward alone, and from
path depth alone. A phase reading that only matches the reward adds nothing.

## Not done here

No pruning and no reward from the reading. No claim that a phase reading is a phase in
oscillate's sense.

## Amendment, 2026-10-10, before any record is read for this purpose

"Chosen on run 8" was ambiguous between a hand-written formula and a fitted model. It's
replaced by a formula, fixed here and not fitted on anything. Run 8 is used only to check
that the computation runs and the outcomes are well defined. Run 9 is the one test.

**Signals,** all in each step record's `session` field:
- `ok`: the outcome is `ok`;
- `dg`: goals closed, `goals_before - goals_after`;
- `ds`: the relative shrink of the conclusion, `(size_before - size_after) / size_before`;
- `revisit`;
- `depth`: the tactic path's length plus one.

`err20` and `rev20` are the shares of errors (any outcome but `ok`) and of revisits among
the episode's previous 20 steps (fewer at the start; 0 if there are none).

**The reading:**

    order = (ds + 0.5 * sign(dg) if ok else 0) - err20 - rev20

- ordered if `order > 0.1`;
- disordered if `order < -0.3`;
- edge otherwise.

Higher `order` is predicted to mean closer to a proof. The direction is fixed: an AUC
below 0.5 counts as below threshold, not as a flipped signal.

**Outcome 1, step level:** among `ok` steps of proved episodes, is the step on the final
proof (its path plus its tactic a prefix of the proof)? Error steps are excluded:
they're never on a proof, so including them would make any reading look good.

**Outcome 2, episode level:** among episodes with at least 50 steps (not proved within
them), does the episode end proved? The episode's reading is the mean of `order` over
its first 50 steps. Episodes that ended sooner are excluded, because a short episode is
mostly a quick proof, and length alone would predict the outcome.

**Measures:**
- **Primary:** AUC of the continuous `order` for each outcome.
- **Also reported:** AUC of the three-way regime (ordered 2, edge 1, disordered 0), and
  the two baselines: the step's recorded reward (episode level: the mean over the first
  50 steps), and depth (episode level: the mean over the first 50 steps).
- **Pooling:** both prover passes (`fixed/` and `retrieval/`) of every round.

**Decision**, on run 9, as stated above:
- primary AUC ≥ 0.70 on both outcomes: keep;
- below 0.60 on both: drop (record v2);
- otherwise inconclusive.

Either way, if the reading doesn't beat the reward baseline, it adds nothing the record
doesn't already carry, and that's reported as such.

**A null is a result.** If the reading fails the 0.60 threshold, the finding is that
phase-state observation of this form doesn't predict proof outcomes in this domain. It's
reported as a negative result, and it is what justifies the schema change.
