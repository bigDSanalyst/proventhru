# oscillate calibration: inconclusive by the rule stated in advance

`tools/oscillate_calibration.py`, with the fixed reading of `docs/oscillate-calibration.md`
(amendment committed at `bf5d530`, before any record was read for this purpose). Nothing
was fitted. Run 8 was used only to check that the computation runs; nothing was changed
after seeing it. Run 9 is the test.

| | run 9, step level | run 9, episode level |
|---|---|---|
| what is predicted | an `ok` step of a proved episode is on the final proof | an episode still open at step 50 ends proved |
| n (positives) | 4,984 (594) | 199 (90) |
| **reading (`order`), AUC** | **0.961** | **0.443** |
| three-way regime, AUC | 0.711 | 0.296 |
| baseline: recorded reward | 0.904 | 0.583 |
| baseline: depth | 0.408 | 0.126 |

Run 8, the sanity check: step 0.948 (reward 0.924), episode 0.460 (reward 0.400).

**Decision, by the stated rule: inconclusive.** 0.96 at the step level is above 0.70; 0.44 at
the episode level is below 0.60. So neither keep nor drop.

## What the two numbers mean

- **Step level:** high, and only a little above the reward (0.96 against 0.90). Among
  steps that succeeded, the ones on the final proof are mostly the ones that made
  progress (closed a goal, shrank the conclusion), and that's what `order` and the reward
  both measure. It's close to definitional: a local progress signal recognizes local
  progress. It adds little that the record doesn't already carry.
- **Episode level:** no predictive value (0.44, below chance in the stated direction), and
  worse than the reward (0.58). A reading of the search's first 50 steps doesn't forecast
  whether it will end in a proof. This is the use oscillate was meant for: steering a
  search early.
- **Depth, a baseline:** strongly predictive in reverse (0.13). Episodes whose early steps
  go deep tend to fail. That's a property of best-first search on a fixed policy, not a
  phase reading. It's noted here and not acted on.

## What follows, as stated in advance

Inconclusive means oscillate stays out of the architecture until a learning policy
exists. The empty `phase` field stays in the record schema, with no record v2 now. It
leaves only when the schema has to change for another reason, or when a calibration on
a learning policy decides it.

In the form tested, the reading doesn't do the job it was meant for (early forecasting of
search outcome) in this domain. As a local progress signal it recognizes progress about
as well as the reward does, and the reward already exists.
