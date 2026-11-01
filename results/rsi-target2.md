# RSI target 2: results

In progress. The spec is `docs/rsi-target2-prover-dpo.md` (frozen). Results are added here as
its steps run. Deviations are listed below as they happen, each with its reason.

## Step 2: the pair count on dev round 5

T2-a, under `code:target-2-pairs` v2, run in Colab on 2026-11-01 from main at `34ddc94`. The
first count (v1) read condition C twice, and it isn't used (deviation 1).

- **82 pairs from 19 proved trees: 4.316 per proved tree.**
  - C (M1 alone): 29 trees (the rerun's 29 set aside), 7 proved, 4 on the frontier. 48 pairs:
    9 i < j, 39 i > j.
  - D (with retrieval): 29 trees, 12 proved, 11 on the frontier. 34 pairs: 10 i < j, 24 i > j.
  - The 82 pairs come from 9 of the 29 dev statements.
- **The files.**
  - Stats: `results/rsi-target2-pairs-dev5.stats.json` (sha256 `cdb40249fce300b5…`), as Colab
    wrote it to Drive (`runs/t2-pairs-dev5.stats.json`).
  - Pairs: Drive `runs/t2-pairs-dev5.jsonl`, 627,985 bytes, sha256
    `53eada391ce8f1a7c1d1be9b36c848084c5ccea7bde724cbf961f59d6d3f21bd`.
- **N_min = 500 is reachable, so the target runs in this form.**
  - P is the 29 dev statements plus the first N statements of `examples/ranker_rest.txt`
    (200 ≤ N ≤ 625).
  - M1's proof rate on the new statements isn't measured until iteration 0 searches P. At
    dev's rate (19 proofs in 58 searches), 4.316 per proved tree projects to 82/29 = 2.83
    pairs per statement of P: 648 pairs at N = 200, and 1,849 at N = 625. So N_lo = 200.
  - Dev was the tuning set, so its rate may run high. 500 pairs need about 116 proofs: 25% of
    P's searches at N = 200, or 9% at N = 625 (dev: 33%).
  - What happens if iteration 0's real count falls short of N_min is for the amendment (step
    4) to state.
- **Next in the order:** step 3, the smoke test on the 29 dev statements, capped at U_smoke =
  15 A100 units.

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
