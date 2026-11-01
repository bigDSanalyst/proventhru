# RSI target 2: results

In progress. The spec is `docs/rsi-target2-prover-dpo.md` (frozen). Results are added here as
its steps run. Deviations are listed below as they happen, each with its reason.

## Step 2: the pair count on dev round 5

Pending: T2-a again, under `code:target-2-pairs` v2. The first count (v1) read condition C
twice, and it isn't used (deviation 1).

## Deviations

1. **The first pair count read dev C twice (2026-11-01).**
   - The Colab session that made M1's pattern proposals also ran the notebook's dev cells 6a,
     6b and 7. Cell 7 ran dev C at 600 steps again, into round 5's directory
     (`runs/dev-C600-pe26d4a77`).
   - All 1,580 of cell 7's model calls were cache hits, so it replayed round 5's responses and
     generated nothing new. But it appended 29 episodes to round 5's records.
   - T2-a ran next. Its v1 loader made a tree of every episode, so C counted 58 trees and 14
     proofs, against round 5's 29 and 7. D (29 trees, 12 proofs) wasn't touched.
   - **The doubled trees changed the pairs, not just the totals.**
     - The cap of 3 pairs per state applied per tree, so the replay could add a state's
       4th to 6th pairs.
     - Its repeated triples (77) were counted as "the same triple in another condition", though
       C is the first condition.
   - **What v1 printed, kept for the record and not used:**
     - 95 pairs, 3.654 per proved tree (over 26 proofs);
     - C: 13 pairs i < j, 49 i > j, 11 beyond 3 per state;
     - D: 10 pairs i < j, 23 i > j.
   - **The fix, under the bug rule:** `code:target-2-pairs` v2 (commit `5c9a941`).
     - It keeps one tree per statement, the first episode that ended, and reports the rest as
       set aside.
     - Its test reruns a search into the same directory: v1 gives 2 trees and 5 pairs at the
       root, v2 gives 1 tree and 3 pairs.
   - The notebook now says not to rerun cells 6a–7.
