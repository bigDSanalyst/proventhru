# Frozen documents

Each entry is a document that governs runs, with the sha256 of the file and the commit
that froze it. A run cites the hash it ran under. A changed hash means a new version,
added as a new row, never an edit of an old one.

| document | version | sha256 | frozen at commit | date |
|---|---|---|---|---|
| `docs/pattern-metrics.md` | v1 | `533e08285a91c8c85a0f914d9ed6c964c48439bd96c098b28fe9f65621fe7fe1` | `b1a8d8a` | 2026-10-10 |

`PROTOCOL.md` keeps its own history table and hash check (`proventhru protocol check`).
