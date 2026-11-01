# Frozen documents

Each entry is a document that governs runs, with the sha256 of the file and the commit
that froze it. A run cites the hash it ran under. A changed hash means a new version,
added as a new row, never an edit of an old one.

| document | version | sha256 | frozen at commit | date |
|---|---|---|---|---|
| `docs/pattern-metrics.md` | v1 | `533e08285a91c8c85a0f914d9ed6c964c48439bd96c098b28fe9f65621fe7fe1` | `b1a8d8a` | 2026-10-10 |
| `docs/rsi-target1-ranker.md` | v1 | `5597d49fe9b44e59c50bc71fd0b276d5ba27fc4d25fbb54af7c3b0de0b24c172` | `448b7ff` | 2026-10-11 |
| `code:target-1` | v1 | `b0e1bbf1544d91b6bb580bb8dbcfe387abf461c2a6e492f59ec244f2ea3d6494` | `448b7ff` | 2026-10-11 |
| `results/ranker/D0.jsonl` | v1 | `d60bad63099373e52ce9bef5ca20fd58722d8fea333c4db3d0163396f40982e6` | `448b7ff` | 2026-10-11 |
| `examples/ranker_H.txt` | v1 | `cfad6f5b7446ea306f1bde0313ecbbad0cca2ce0e1e43a2a80fb9c2c8596174b` | `448b7ff` | 2026-10-11 |
| `examples/ranker_T1.txt` | v1 | `9138bd60bae3f1a312828c0e904783abcc2071223de354607ccf83af3f72d1fd` | `448b7ff` | 2026-10-11 |
| `examples/ranker_T2.txt` | v1 | `7be63370876e7804230bc2473e79e42b2a831ea7624f5ca3b7073f76cbc93935` | `448b7ff` | 2026-10-11 |
| `examples/ranker_rest.txt` | v1 | `268df8ab537885cbbcba1b301cd6776098c86dc866b60634ed675475e1cd99d3` | `448b7ff` | 2026-10-11 |

`PROTOCOL.md` keeps its own history table and hash check (`proventhru protocol check`).

A `code:` row is a hash over the files its owner lists, not a file: `code:target-1` is
`tools/ranker_schedule.code_hash` over `GOVERNED`. A fix to that code is a new row
(bug rule, `docs/rsi-target1-ranker.md`). The set files' statement hashes, as
`proventhru protocol set FILE` prints them: H `52b5025c…db47`, T1 `2cc78944…edac`, T2
`db2a7748…faa5`, rest `dfbe55b7…9627`. `tools/doctor.py` checks every row.
| `docs/pattern-run-1.md` | v1 | `e8b31596d574963140773827f377ba0c238ce05db6f5d0500724c41b333256da` | `9192904` | 2026-10-11 |
| `code:pattern-run-1` | v1 | `c31a3eee4e7967cbe2210d4b1e274a9969af0b1304d9f6984bd681ff3062e3ed` | `9192904` | 2026-10-11 |
| `code:pattern-run-1` | v2 | `d69317c6039673f620a3b19941b886bb82781cc6b6e7ec4d1a9fecdf20071b8c` | `3e84939` | 2026-11-01 |
| `docs/rsi-target2-prover-dpo.md` | v1 | `0218d1ab8d4aa486111bf7efa50dca26d5f7f1da6da360333c0489c3e60f4d89` | `c5f7e8e` | 2026-11-01 |
| `code:target-2-pairs` | v1 | `75769d9224e45220c2a39283b7f50badc902e68d7cffe78aa1a6f6eb3fbe94d5` | `c5f7e8e` | 2026-11-01 |
| `code:target-2-pairs` | v2 | `5fa9de698bc901b2fdf22c9e2ae55fad88200572e5f2aaaf181db8e5d734288e` | `5c9a941` | 2026-11-01 |
| `code:pattern-run-1` | closed | `d69317c6039673f620a3b19941b886bb82781cc6b6e7ec4d1a9fecdf20071b8c` | `3e84939` | 2026-11-01 |
| `docs/pattern-run-2.md` | v1 | `e1657026f646446193aae41fab826f8656bc0e03c94156438ddb594cf03558d9` | `70a0809` | 2026-11-01 |
| `code:pattern-run-2` | v1 | `26aa1ef72639ee51523bdf8ff59592d3fbf24acbad6aa63d82d74ce624ccf3af` | `70a0809` | 2026-11-01 |
| `code:pattern-run-2` | closed | `26aa1ef72639ee51523bdf8ff59592d3fbf24acbad6aa63d82d74ce624ccf3af` | `70a0809` | 2026-11-01 |
| `docs/pattern-run-3.md` | v1 | `ac0319c402f68f7e8f3119b522c010c6025ec7a8ee5445fdfe6c8972451568b6` | `f899cd2` | 2026-11-01 |
| `code:pattern-run-3` | v1 | `f90d36b5ff6f3710de624f69a6d63d63025cf84f010ffbd21d9d41ad3f325944` | `f899cd2` | 2026-11-01 |
| `code:pattern-run-3` | closed | `f90d36b5ff6f3710de624f69a6d63d63025cf84f010ffbd21d9d41ad3f325944` | `f899cd2` | 2026-11-01 |
| `docs/pattern-run-4.md` | v1 | `1486df51fbe5855b5297c363ae6638597cb3e8cea947479cbbf1f65a774ad6e0` | `92fae1c` | 2026-11-01 |
| `code:pattern-m1` | v1 | `95877dd1768c5ed1c91697e049031b7a8649f72ea8692f4edf21621ee6cde509` | `92fae1c` | 2026-11-01 |
| `code:pattern-run-4` | v1 | `ee082dae5b1a01d6498a08b256efc2fdfc791cc3a71e3f9941ab404d2f325518` | `92fae1c` | 2026-11-01 |
| `code:pattern-m1` | closed | `95877dd1768c5ed1c91697e049031b7a8649f72ea8692f4edf21621ee6cde509` | `92fae1c` | 2026-11-01 |
| `code:pattern-run-4` | closed | `ee082dae5b1a01d6498a08b256efc2fdfc791cc3a71e3f9941ab404d2f325518` | `92fae1c` | 2026-11-01 |
