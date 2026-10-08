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
| `policy` | `{id, model, provider}` of the policy that searched, or null. A model policy adds `prompt_sha256` and its settings (`k`, `temperature`, `seed`, ...) |
| `search` | `{algorithm, budget, step_budget?}`, or null if the gate settled it. `budget` caps expansions and may be null; `step_budget` (optional) caps steps |
| `weights` | the `RewardWeights` that computed every step's `reward` |
| `protocol` | optional: `{sha256, commit, path, set}` of the pre-registered protocol the run was checked against (`protocol.py`), and which registered set the statement belongs to. Absent for runs under no protocol |
| `item` | optional: the statement's position in its set, from 0. Pairs a statement with its renamed copy |

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
A proposal is one **policy invocation**: one per expanded node.

The OpenAI-compatible policy (`policy_openai.py`) adds to `cost`:
`served_model` and `served_provider` (what actually answered), `request_id`,
`stop_reason`, `cache` (`hit`, `miss`, or null) and `cache_key`, `retries`
and `api_errors` (each failed attempt's status and message), `dropped`
(candidates refused before running, with why), and `failure`: null, or
`{kind: api | invalid, ...}`. `api` means the call itself failed; `invalid`
means the model answered unusably (not JSON, no candidates list, cut off, no
valid candidate). A call that failed with `api` is followed by the episode's
outcome with `stats.incomplete`. Retrieval (`retrieval.py`) adds `lemmas`,
`retrieval_ms`, and `added`: the candidates it appended to the base
policy's, so a model's own choices can be told from retrieval's.

### `step`

One tactic submitted to the session: one **step**, whatever came of it. A
tactic Coq ran (`ok`), refused (`error`), that the guard refused before Coq
saw it (`refused`), and one that timed out (`timeout`) are each one step. A
policy's own queries are not steps (retrieval's `Search` is premise
selection, not a tactic attempt), but a lemma retrieval proposes is a step
once it is tried as a tactic. `search.step_budget` counts exactly these
entries. The two verdicts are separate fields because
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
| `session.hyps_before`, `hyps_after` | hypothesis lines across the goals (`n, m : nat` is one). Backend-dependent: coqtop prints only the focused goal's hypotheses, Petanque every goal's |
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
| `stats` | `{expansions, invocations, steps, stopped, seconds}`. `stopped` says what ended an unproved search: `frontier`, `budget` or `step_budget`. If the attempt was cut short (standing `open`): `error`, and `incomplete`, either `crashed` or `policy_unavailable` |

An episode with `stats.incomplete` is not a result: views count a statement
by its latest episode that was not cut short, and a run is resumed by
rerunning it.

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

## The reward vector: what is recorded, what is pending

The scalar `reward` is one weighting of signals the record keeps separately,
so any other weighting, or a multi-objective reward, can be computed from the
records later, without re-running anything and without a schema change.

| component | where | status |
|---|---|---|
| session verdict | `step.session.outcome`, `step.session.finished` | recorded |
| kernel verdict | `step.kernel.verdict`; `outcome.kernel` | recorded |
| goal-count delta | `step.session.goals_before - goals_after` | recorded |
| hypothesis delta | `step.session.hyps_before - hyps_after` | recorded; compare within one backend only |
| conclusion-size delta | `step.session.size_before - size_after` | recorded |
| state revisit (loop) | `step.session.revisit` | recorded |
| prover time | `step.cost.prover_ms`, `step.cost.kernel_ms` | recorded |
| model cost | `proposal.cost`: tokens, `model_ms`, retries | recorded (model policies) |
| invalid action | `step.session.outcome = refused`; `proposal.cost.dropped`, `failure` | recorded |
| proof length | `len(outcome.proof)` | recorded |
| search effort | `outcome.stats`: steps, invocations | recorded |
| known in the library | `episode.gate.status = trivial`, detail "already in the library" | recorded, at the gate only |
| phase (oscillate) | `step.phase`: `regime`, `distance`, `signature`, `digest` | placeholder: null until the phasor mapping is written down |
| novelty | an `annotation` (label `note`) on the outcome, with `assessment.novelty` | pending: needs the corpus check and a literature check |
| significance | the same annotation, `assessment.significance` | pending: needs a definition first |

Novelty and significance are judgments made after a proof exists, by a check
that can be wrong and redone, so they are annotations, not outcome fields: an
`annotation` with label `note` and an optional `assessment` object,
`{novelty, significance, method, by}`. That uses the existing kinds and
labels, so it needs no new format.

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
