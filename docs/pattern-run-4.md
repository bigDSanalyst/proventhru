# Pattern extractor, runs 4 and 5: the M1 proposer

Written: 2026-11-01, before any model call, after run 3's null (`results/pattern-run-3.md`).
Status: in force from the commit that removed its draft line. Its hash is in
`docs/frozen.md`, with two code rows:
- `code:pattern-m1`: the proposer, `tools/pattern_m1.py`, which runs in Colab;
- `code:pattern-run-4`: the scoring, `tools/pattern_run.py --run 4` and `--run 5`, which runs
  here on CPU.

Both tools refuse to run unless the spec and their row match.

Run 3 ended `pattern/analogy-v2` with a null: on insertion sort, carrying library patterns
over finds the development's own lemmas and nothing new that's significant. On 2026-11-01
the owner chose the M1 proposer next.

The metrics doc makes a change of model a new version, with its own runs. So this is a new
proposer, `pattern/model-m1-v1`, on the same development, scored exactly as run 3 was. The
comparison with run 3 is direct: same development, same novelty, same prover, a different
source of conjectures.

Seeking-layer work. The gate, the kernel, the records and the frozen sets are unchanged.

## The proposer

- **The model is M1:** `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`,
  as `PROTOCOL.md` v5 pins it. It's served by the notebook's vLLM, in bf16 on an A100. The tool
  refuses any other served name.
- **What the model is shown:** `pilots/isort/ISort.v` with its comments removed, and nothing
  else from the pilot. The held-out `ISortGold.v` is never in a prompt, and a test checks that
  no gold lemma's name appears there.
- **What it's asked:**
  - for each of the metrics doc's six pattern kinds (symmetry, invariance, duality, general
    form, composition, boundary), and each seed, K = 8 conjectures of that kind about
    `insert`, `sort` and `sorted`;
  - each as one closed Coq proposition, with a one-sentence reason;
  - as JSON under a schema (vLLM's `json_schema`).
- **Sampling:** temperature 0.8, top-p 0.95, at most 2,000 tokens, the seed per request.
- **Two batches, two runs:**
  - batch A is seeds 0–3, and it's run 4;
  - batch B is seeds 4–7, and it's run 5;
  - so 48 calls in all, up to 384 statements.
- **The prompt's identity:** prompt sha256
  `716fa2c2797158d1a0553fe2d6bf988df6417bdbf557cb9a33519802e7aca3a3`. It covers the template,
  the kinds, K, the schema, the sampling, the batches, the development's text and the code that
  builds a request. A change to any of them is a new version.
- **Caching:** responses are cached by request hash (Drive `cache/pattern-m1.jsonl`), so a
  rerun makes no calls.
- **The A100 budget:** a cap of 5 units, outside target 2's U. That's one session: the
  notebook's setup cells, vLLM's start, and 48 calls.

## Scoring, on CPU here

- **Input:** Colab writes the proposals to Drive (`runs/pattern-m1/proposals.jsonl`). The
  file's sha256 is recorded in each run's harvest.
- **Normalizing each statement:**
  - Coq elaborates it with notations off, in the same session setup as run 3 (`Sorted`
    imported first).
  - If it isn't a Prop, it's proposed but not formalizable.
  - If it's outside the first-order fragment, such as one with a function variable, it's kept
    but untested.
  - Otherwise it's read as a library theorem is.
- **Everything else is exactly run 3's** (`docs/pattern-run-3.md`):
  - testing, the falsifier space and its certified refutations;
  - the prover's 2b-ii settings, 4 rounds, 600 steps, jobs 3, from an empty corpus;
  - the closed novelty: the development's held-out lemmas and one constructor step are present
    in the development;
  - significance (a)–(d), with the strict (d).
- **Also reported:** how many of each run's candidates `pattern/analogy-v2` proposed too
  (run 3), and which proved novel conjectures run 3 didn't prove.

## The stopping rule, read now

- **Runs 4 and 5 are this proposer's two consecutive runs.**
- If both count zero significant novel conjectures, and run 5's residue has no new (kind,
  test, gate) bucket against run 4's, then `pattern/model-m1-v1` stops and the null is
  published.
- If either counts one or more, the proposer has signal. The report says which conjectures,
  and the next step is the metrics doc's: expand the signature, not the model.

## What was seen before freezing

- **No model call was made.**
- **One smoke run of the scoring,** on 12 statements written by hand in a made-up proposals
  file, at 60 steps and one round. It checked that the model path reads, tests, proves and
  reports. Its outputs stay out of the results.

## Deviations

Any deviation from this file is listed in the results with its reason.
