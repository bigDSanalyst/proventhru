# AGENTS.md

Operating manual for autonomous sessions in this repository.

## What this repository is

proventhru is a pre-registered, kernel-gated theorem proving and
conjecture generation system for Rocq (Coq). Its contribution is
methodological: a pipeline whose results are reproducible, whose
failures are diagnosable, and whose seeking layer cannot influence
its truth layer.

Read `README.md` first for what exists.
Read `docs/related-work.md` for what is new and what is re-implemented.
Read `PROTOCOL.md` before running anything that touches the registered
experiment.

## The invariant

**The truth layer is non-reciprocal.**

The kernel, the protocol, the frozen tactic sets, the test sets, and
the record schema cannot be shaped by the seeking layer. Nothing that
generates, proposes, searches, or trains may influence what counts as
a proof, what counts as a valid record, or what the frozen tests are.

If a proposed change would let a model or a search influence any of
those, stop. That is the failure mode this repository exists to
prevent.

## Rules

**Pre-register before measuring.** A metric, criterion, or stopping
rule is committed before the run it governs. Amendments are dated and
start a new version. Records cite the version they were written under.

**Certify your own filters.** Every filter that drops a candidate
proves its drops sound as a standing step. The certified number-only
filter is the model: the abstracted form of every dropped candidate
is proved in Coq each round. A filter that drops silently is a bug.

**Classify before you spend.** Cheap CPU classification before any
GPU or API spend. Every "unexplained" wave in this repository's
history has resolved into a missing pattern, not a capability gap.
Exhaust CPU classification before reaching for a model.

**The evaluator rule.** Every check must enumerate inputs that could
falsify the claim, not inputs that are easy to construct. Prior
failures: values 0..5, sorted-only permutations, the congruence
filter. State the falsifier space explicitly.

**Records are append-only.** Corrections are annotations, never edits.
A hash chain that can be rewritten is not a hash chain.

**Report nulls.** An inconclusive or negative result that was
pre-committed is a finding. Renaming a null as progress is the failure
mode this repository exists to catch.

**Verify external claims.** If a tool, paper, or repository is cited,
it has been checked to exist. `rocq-piler`, `stratify`, and
`close_admits` were once cited in this repository and were not real.
Check before citing.

**Report per-phase, not aggregate.** The gate-2 split (2a, 2b-i, 2b-ii)
exists because the aggregate hid which fix worked. Always report the
delta, not just the total.

## Layout

- `proventhru/` — the package (env, search, policies, records, explore)
- `tools/` — classifiers, gates, runners, one-off analysis
- `results/` — write-ups, one per run, dated
- `docs/` — protocol-adjacent docs (metrics, related work, specs)
- `pilots/` — development-specific work (isort, etc.)
- `SCHEMA.md` — the record schema and its invariants
- `PROTOCOL.md` — the registered experiment

## Commands

- `proventhru verify <records.jsonl>` — verify a record chain
- `proventhru report <records.jsonl>` — summarize a run
- `proventhru explore` — run a conjecture loop round
- `tools/classify_opens.py` — classify open statements by cause
- `tools/isort_pilot.py` — the pilot runner

## What not to do

- Do not amend `PROTOCOL.md` after seeing data from the experiment it
  governs.
- Do not import a component that touches the kernel, the protocol, or
  the records. Those are built here, on purpose.
- Do not rename a null as progress.
- Do not add tactic shapes without versioning them and re-running the
  control. A v2 shape invalidates every "necessary composition" claim
  measured against v1.
- Do not run a model on a residue before subclassifying it. The residue
  is almost always a missing shape.
- Do not cite a tool without checking it exists.

## The one-line summary

The truth layer is built and works. The seeking layer is the project.
Pre-register, certify, classify, verify, report.
