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
