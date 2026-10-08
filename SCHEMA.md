# The run record: `proventhru-record/v1`

Every trajectory, reward and corpus entry is a view of one file,
`records.jsonl`. This file defines its schema. Changing an existing field
means re-recording or carrying two formats, so the rules for change are at the
end and are strict.

`proventhru verify records.jsonl` checks a record. `proventhru corpus
records.jsonl` prints the corpus derived from it. `proventhru annotate
records.jsonl SEQ --label unsound --reason "..."` appends a correction.

## The chain

One JSON object per line, in canonical form (sorted keys, no whitespace,
UTF-8). Every entry has the same envelope:

| field | meaning |
|---|---|
| `format` | always `proventhru-record/v1` |
| `seq` | position in the file, from 0, no gaps |
| `kind` | `episode`, `proposal`, `step`, `outcome` or `annotation` |
| `at` | UTC time written, `YYYY-MM-DDTHH:MM:SSZ` |
| `data` | the kind's fields, below |
| `prev` | `hash` of the entry before; 64 zeros for the first |
| `hash` | sha256 of the canonical entry without `hash` |

Because `hash` covers `prev`, editing, deleting or reordering any entry breaks
every hash after it. The format is Dharmapala's run records (`runs.py`).
`record.head()` gives `(size, last hash)`: committing to that, by signing it
or timestamping it, commits to the whole record.

**Nothing is rewritten.** A writer refuses to append to a file that doesn't
verify, and refuses to write an entry that fails the checks below. A
correction is a new `annotation`.

## Kinds

An episode is one statement's attempt. Its entries appear in this order:
`episode`, then any number of `proposal` and `step` entries, then exactly one
`outcome`. Nothing for that episode may follow its outcome. Episodes may
interleave in the file, for example when several run concurrently.

### `episode`

| field | meaning |
|---|---|
| `episode` | id, 32 hex characters, unique in the file |
| `statement` | the conjecture, one term (no sentence break) |
| `preamble` | the exact library sentences loaded before it |
| `preamble_sha256` | sha256 of `preamble`; checked |
| `environment.backend` | `coqtop` or `petanque` (later `lean`, ...) |
| `environment.prover` | prover and version, e.g. `coq-8.18.0`, `rocq-9.1.1` |
| `environment.interface` | how the session was driven, e.g. `coq-lsp pet 0.2.5 (...)` |
| `environment.compiler` | what compiled the kernel certificate |
| `gate` | Position 1's result: `status` (`ill_formed`, `refuted`, `vacuous`, `trivial`, `open`), `detail`, `script`, `kernel` |
| `policy` | `{id, model, provider}` of the policy that searched, or null |
| `search` | `{algorithm, budget}`, or null if the gate settled it |
| `weights` | the `RewardWeights` that computed every step's `reward` |

A verdict is only meaningful relative to `environment` and `preamble`. A proof
recorded under `rocq-9.1.1` with `Require Import Arith Lia List.` is a claim
about exactly that pair.

### `proposal`

One policy call: the candidates it offered at one node.

| field | meaning |
|---|---|
| `episode` | the episode id |
| `path` | full tactic path from the statement to the node |
| `policy` | `{id, model, provider}` |
| `candidates` | `[[tactic, score], ...]` in the order offered |
| `cost` | `{model, input_tokens, output_tokens, model_ms}`, or null for a policy that calls no model |

Cost is recorded once per call, not per step, so summing it never double counts.

### `step`

One tactic sent to the session. The two verdicts are separate fields because
they train different things and disagree in exactly the case worth catching.
For example, `fix IH 1. exact IH.` closes every goal in the session
(`outcome: ok, finished: true`), and the kernel rejects it at Qed
(`kernel.verdict: rejected`).

| field | meaning |
|---|---|
| `episode` | the episode id |
| `proposal` | seq of the proposal it came from, or null |
| `path` | full tactic path from the statement to the node it ran from |
| `tactic` | the action |
| `session.outcome` | `ok`: the session ran it. `error`: Coq refused it. `refused`: the guard refused it and Coq never saw it. `timeout`: nothing was decided |
| `session.error` | the message, or null |
| `session.finished` | the session reports no goals left |
| `session.goals_before`, `goals_after` | goal counts, shelved goals included |
| `session.size_before`, `size_after` | characters across the conclusions |
| `session.revisit` | the resulting state was already seen in this episode |
| `session.observation` | `{finished, shelved, key, goals: [{hypotheses, conclusion}]}`, or null |
| `kernel` | null unless the step finished the proof, else `{verdict, detail, certificate_sha256}` |
| `kernel.verdict` | `accepted`, `rejected`, or `not_checked` (the compiler was missing or timed out: not a failure) |
| `reward` | the scalar from `weights`. A timeout costs only the step weight; `not_checked` earns nothing and costs nothing |
| `cost.prover_ms`, `cost.kernel_ms` | wall time in the session, and in the from-scratch compile |
| `phase` | oscillate's reading: `{regime, distance, signature, digest}`, all null until it runs |

**Replay.** `path + [tactic]` from `statement` under `preamble` in
`environment` reproduces the step. A test replays a recorded step in a fresh
session and checks it reaches the recorded `observation.key`.

**Phase.** The fields exist now so a later reading is a value in a known
place, not a new schema. Before any non-null value is written, the mapping
from search signals to oscillate's phasor must be written down, in its own
document: which of the fields above compose the phasor, and why. A regime
label is only as meaningful as that mapping.

### `outcome`

| field | meaning |
|---|---|
| `episode` | the episode id |
| `standing` | `proved`, `refuted`, `open` or `rejected` |
| `proof` | the tactic path of the proof (or the gate's disproof) |
| `kernel` | the verdict on that proof, or null |
| `certificate_sha256` | sha256 of the certificate the kernel compiled |
| `stats` | `{expansions, steps, seconds}`; `error` if the attempt crashed (standing `open`) |

`proved` and `refuted` require `kernel: accepted`, and the writer refuses
anything else.

### `annotation`

A later statement about an earlier entry: a proof found unsound (a kernel bug,
a library change, a wrong lemma), superseded, retracted, or just noted.

| field | meaning |
|---|---|
| `target` | `{seq, hash}` of the entry it is about; the hash must match |
| `label` | `unsound`, `superseded`, `retracted` or `note` |
| `reason` | required |
| `by` | who says so |

The annotated entry stays as written, so the record keeps both what was
believed and when it stopped being believed. Views apply annotations:
`corpus()` reports an episode whose outcome (or opening) is annotated
`unsound` or `retracted` as `withdrawn`, with the annotations listed.

## What `verify` checks

- Every entry has the envelope, `seq` runs 0..n−1, every `prev` names the
  entry before, and every `hash` matches.
- `kind` and every enumerated field hold a value listed above.
- `proposal`, `step` and `outcome` name an episode opened earlier and not
  yet closed. A step's `proposal` is an earlier proposal of the same episode.
- An episode names a backend and a prover, its `preamble_sha256` matches,
  and its id is new.
- A `kernel` verdict appears only on a step that finished the proof.
- `phase` has exactly its four fields.
- `proved` and `refuted` carry `kernel: accepted`.
- An annotation targets an earlier entry by its exact hash, with a label
  and a reason.

Verification is linear in the record's length: 3,600 entries in 0.04 s.

## Changing the schema

- **Adding** an optional field to `data` is allowed. Readers must ignore
  fields they don't know, and old entries simply lack the new field.
- **Renaming, removing, or changing the meaning or allowed values** of a field
  is a new format, `proventhru-record/v2`, with its own reader. v1 files stay
  readable as they are and are never converted in place.
- The envelope and the hash rule never change within a format.
