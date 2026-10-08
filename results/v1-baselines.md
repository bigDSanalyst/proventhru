# v1 baselines: the fixed policies on the held-out set

Run under `PROTOCOL.md` v1 (sha256 `56524589def952e2ab069bec795acff871ebc5797ff576d62cb463ca073b948e`,
commit `1e6b8ef`), coqtop, Coq 8.18.0. Every record verifies (`proventhru
verify`), and every episode in it cites the protocol. The records (530 MB in
all) are not in git. Each is named by its head, `(entries, hash of the last
entry)`, which commits to the whole file.

| run | set | step budget | proved | steps | invocations | record head |
|---|---|---|---|---|---|---|
| A | test | 600 | **22** / 120 | 62,661 | 3,626 | 66,527 `363a6acc…25e8` |
| A | test_renamed | 600 | **22** / 120 | 62,661 | 3,623 | 66,524 `d1b5e82b…4c23` |
| B | test | 600 | **22** / 120 | 61,876 | 1,922 | 64,038 `4efad592…2825` |
| A | test | 2000 | **26** / 120 | 195,781 | 10,606 | 206,627 `46cb814f…7577` |
| B | test | 2000 | **32** / 120 | 191,016 | 5,777 | 197,033 `fff87d8a…0ee4` |

Commands: `proventhru --backend coqtop run SET --out DIR --budget 0
--step-budget N --protocol PROTOCOL.md`, plus `--retrieval 6` for B.

## What they show

**Rename check (pre-registered): passed.** A proves the same 22 items on
`test` and `test_renamed`, with 0 discordant pairs.

**At matched steps, retrieval does not help at the low budget.** B against A
at 600 steps: 22 and 22, with 9 discordant pairs each way (McNemar p = 1).
Retrieval gains the list laws that need a lemma (`rev l1 ++ rev l2 =
rev (l2 ++ l1)`, `filter Nat.even` over `++`), and loses arithmetic ones
(`list_sum (repeat 0 _) = 0`, `Nat.max n (length l1) <= ...`). Its extra
candidates spend the step budget that the fixed tactics needed for those.
At 2000 steps the gain shows: 32 against 26, 12 against 6, p = 0.24.

This revises an earlier reading. On the dev set, at matched *expansions*,
retrieval went from 10 to 15 at budget 30. Part of that came from trying
more tactics per expansion. This is the budget confound the protocol's
step budgets exist to remove, and it is why steps are the primary axis.

**What the model conditions are compared against** (primary, 600 steps):
C against A's 22, and D against B's 22.

## The records

Kept outside git, as xz files, in the project's Drive folder
(`proventhru/records/v1/`). `xz -d`, then `proventhru verify`, must
report the head in the table above.

```
2d3805fb546ffa96bbc7b0c4b4717342a5785be8b56d5edab40af42d84a95abe  A2000.records.jsonl.xz
c919faf864d888542488b7716924f5323d4ab2246496fabec195554490b0c706  A600.records.jsonl.xz
8e92da47b26be3dcc35c89d284035caf14031afd4f3ae483390aeb669acd7e01  A600r.records.jsonl.xz
6962aec29a4bb54d5e117dda1ecb0506e39729958a2e94ed7a9ea39b5a9fde5a  B2000.records.jsonl.xz
00d3bd1d22a2146ec5af2e5e49e158ca56d6dab38e3bb6a0c2b751abe5f65052  B600.records.jsonl.xz
```
