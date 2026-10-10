# proventhru

Coq is the environment, not a check run at the end. The agent proposes one
tactic, Coq returns the new proof state, and the agent chooses again. Coq
appears at three points in the loop:

| Position | Module | What Coq does | Output |
|---|---|---|---|
| 1. Conjecture gate | `proventhru.gate` | Checks the statement elaborates as a `Prop`, then tries bounded attempts at a disproof, contradictory hypotheses, and a one-tactic proof | `ill_formed`, `refuted`, `vacuous`, `trivial` or `open` |
| 2. Environment | `proventhru.env.CoqEnv` | Runs one tactic per step against a live `coqtop`, from any earlier node | New proof state or error, plus reward signals |
| 3. Kernel | `proventhru.kernel` | Compiles the full proof from scratch and requires `Closed under the global context` | `accepted`, `rejected`, or `not_checked` (a timeout or missing compiler: not a failure) |

```
conjectures ─▶ gate ─▶ open ─▶ best_first(CoqEnv, Policy) ─▶ kernel
                 │                    │ every proposal and step      │
                 ▼                    ▼                              ▼
              records.jsonl: one hash-chained run record (SCHEMA.md)
                 │
                 ├─▶ corpus      proved / refuted / open / rejected, annotations applied
                 └─▶ trajectories  every step, with its session and kernel verdicts
```

## The run record

Everything is written to one append-only, hash-chained file, `records.jsonl`.
Its schema is fixed in [SCHEMA.md](SCHEMA.md); the corpus and the
trajectories are views of it, not files of their own. Each step records:
- the full tactic path, so it replays from the statement alone;
- the session's verdict on the step (`ok`, `error`, `refused`, `timeout`)
  and, separately, the kernel's verdict on the proof (`accepted`, `rejected`,
  `not_checked`);
- the prover and version, the preamble, the policy's model and cost, and
  null placeholders for oscillate's phase reading.

A correction is an annotation, a new entry naming an older one by hash, never
an edit:

```sh
proventhru verify   out/records.jsonl          # chain intact, every entry well formed
proventhru corpus   out/records.jsonl          # standings, annotations applied
proventhru annotate out/records.jsonl 42 --label unsound --reason "kernel bug in rocq-9.1.0"
```

The chain is the pattern of Dharmapala's run records (`runs.py`).

## Quick start

```sh
sudo apt-get install coq          # coqtop backend: Coq 8.18, coqtop and coqc on PATH
pip install -e .                  # add '.[petanque]' for the Petanque backend (below)
proventhru gate  "forall n m : nat, n + m = n"      # refuted, disproof kernel-checked
proventhru prove "forall n : nat, n * n >= n" --trace
proventhru run examples/conjectures.txt --out out
proventhru --backend petanque prove "forall n : nat, n * n >= n"
python -m unittest discover -s tests          # runs per installed backend
```

## Backends

`session.py` defines what a backend provides: `root`, `run(handle, tactic)`,
`query(handle, command)` and `compiler`. A handle is opaque to the
environment. Pick a backend with `--backend`, with `$PROVENTHRU_BACKEND`, or
leave the default `auto`, which uses petanque when it is installed.

| | coqtop | petanque |
|---|---|---|
| Prover | any Coq with `coqtop` (CI: 8.18) | Rocq 9.1 + coq-lsp's `pet` |
| Handle | tactic path; rewinds with `BackTo` and replays | Petanque's own state; no replay |
| Hypotheses | focused goal only | every goal |
| Process | one per session | a shared pool (`pool.py`) |
| Session start | 343 ms | 1.7 ms (first one: ~690 ms to launch `pet` and load the preamble) |
| Step from the same node | 0.5 ms | 1.4 ms |
| Step alternating between two depth-15 branches | 9.5 ms, grows with depth | 1.5 ms, flat |
| Gate on 8 statements | 10.6 s | 0.39 s |
| Kernel check | `coqc` beside `coqtop` | `rocq compile` beside `pet` |

Both backends pass the same tests. On the 13 statements in
`examples/conjectures.txt` they give identical gate verdicts and proof
results; `tools/compare_backends.py` checks this and exits 1 on any
disagreement. End to end, Petanque takes 6.4 s and coqtop 23.7 s. Most of
what remains on proved statements is the kernel check, which compiles a
fresh file on purpose. Search step counts differ slightly because Petanque's
richer observations change the order of the frontier.

**The pet pool.** Loading the preamble (`Require Import Arith Lia List.`)
is the expensive part: about 550 ms with the process launch, and about 200 ms
even for a second document in the same process. Running
`Goal <statement>.` from an already-loaded preamble state takes about 1 ms.
So each worker loads a preamble once and every session starts from that
state. States are immutable values, so nothing one session does is visible
to the next; a test checks this.

A session stays on one worker, because its states exist only in that
process. A worker serves one request at a time; concurrent requests on one
stdio process hang, which is measured and why this is a pool and not one
process. A new session goes to an idle running worker first.

When a tactic ignores Rocq's `Timeout`, the worker is killed at the hard
deadline. The other sessions on that worker then rebuild their handles once
from their tactic paths. Workers also restart after 200 sessions, to bound
`pet`'s memory. `PROVENTHRU_PET_WORKERS` sets the size (default
`min(4, cpus)`).

Installing the Petanque backend: with opam,
`opam install rocq-core.9.1.1 rocq-stdlib coq-lsp.0.2.5+9.1` and then
`pip install -e '.[petanque]'`. Without opam (opam's server was unreachable
where this was built), `tools/install_rocq_from_source.sh` builds the same
stack from apt and git. The PyPI package called `pytanque` is unrelated; the
`[petanque]` extra pins LLM4Rocq's client by commit.

On the 13 statements in `examples/conjectures.txt` the baseline gives:
2 proved, 1 refuted, 9 rejected and 1 left open. The 9 rejected are
5 trivial, 2 already in the library (`rev (rev l) = l` is `rev_involutive`),
1 vacuous and 1 ill-formed.

## The environment interface

```python
from proventhru.env import CoqEnv
with CoqEnv("forall n : nat, n + 0 = n") as env:
    root = env.reset()                      # Node: path=(), obs = goals
    a = env.step(root, "intros n.")         # Step: node | error, signals, reward, done
    b = env.step(a.node, "induction n.")
    c = env.step(a.node, "destruct n.")     # branch from a again: backtracking is free
```

- **Observation** (`goals.Observation`): every goal's conclusion, the focused
  goal's hypotheses, and the shelved count. `key` is a hash of the state, used
  to detect loops.
- **Statement**: one term. `open_session` refuses a statement that contains
  a sentence break, so `True. Axiom cheat : False` cannot run commands of its
  own in the session or in the kernel's certificate.
- **Action**: one tactic sentence, never a command. `env.guard` admits a
  sentence only if its first token (after an optional goal selector like
  `all:` or `2:`) is lowercase: in Rocq every vernacular command starts with
  a capital letter and every tactic with a lowercase one. A blocklist inside
  the tactic still refuses `admit`, `give_up`, `Admitted`, `Axiom`,
  `Require` and the like, and more than one sentence per action is refused.
  Each tactic runs under Coq's `Timeout`, with a hard process deadline
  behind it. (The earlier blocklist-only guard let `Cd`, `Register` and
  `Optimize Heap` run mid-proof; none could write a file, but `Cd` moved the
  working directory of a shared `pet` worker.)
- **Transition**: `session.run(handle, tactic)`. Every handle the session has
  returned can be run from again, so search branches and backtracks freely
  (see Backends). A session killed at the hard deadline is rebuilt from the
  handle's tactic path.
- **Reward**: every step reports raw signals: `error`, `goals_before/after`,
  `size_before/after`, `revisit`, `finished` and `kernel`. `RewardWeights`
  turns them into a scalar. The defaults only shape the search: a step cost,
  penalties for errors and revisits, and +1 on kernel acceptance. Goal count
  is weighted 0 because `induction` and `split` raise it while making progress.
  A trainer can reweight these signals without re-running Coq.

## Why Position 3 is not a formality

`tests/test_proventhru.py::TestKernel` proves `forall n, n = S n` inside the
session with `fix IH 1. exact IH.` The session reports `No more goals`. The
kernel rejects the proof at `Qed` because the recursion is ill-formed, and that
step's reward is negative. The guard condition, universe constraints and axioms
are only checked there.

## The v1 model policy

`proventhru.policy_claude.ClaudePolicy` asks Claude (default `claude-opus-5-5`)
for the next tactic. It makes one API call per expanded node.

- **What the model sees** (`proventhru/view.py`, fixed once): every goal with
  its hypotheses split into name and type, the goal count, the shelved count,
  `given_up`, the tactic path so far, and the last failed attempt with Coq's
  exact error string.
- **What it may answer:** up to `k` ranked candidates. Each is a tactic name
  from a fixed vocabulary of 24 standard-library tactics plus an argument.
  Structured outputs restrict the name to the vocabulary. The argument is
  checked (no `;`, `||`, `try` or second sentence), and `env.guard` checks the
  result again. `omega` is not in the vocabulary: it was removed in Coq 8.17
  and is absent from Rocq 9, and `lia` replaces it.
- **No reflection step, no lemma retrieval, and no combinators in v1.**
  They wait for a baseline to measure them against.
- **Every call is recorded** with its model, token counts and latency.
  Dropped candidates are recorded with why, and a refusal is recorded as a
  call with no candidates. Server-side refusal fallbacks are on.

Evaluate against the baseline on the same statements, at equal expansions
(the baseline tries about 19 tactics per expansion, the model at most `k`):

```sh
export ANTHROPIC_API_KEY=...                 # or: ant auth login
proventhru run examples/eval_open.txt --out out/fixed  --budget 30
proventhru run examples/eval_open.txt --out out/claude --budget 30 \
           --policy claude --effort medium --max-calls 800
proventhru report out/fixed/records.jsonl out/claude/records.jsonl
```

`examples/eval_open.txt` holds 29 statements the gate leaves open, filtered
from 50 candidates. The 13 in `examples/conjectures.txt` are too few, because
the gate settles 12 of them before any search. The fixed-tactic baseline
proves 10 of the 29 at budget 30 and 11 at budget 200. With premise retrieval
(below) it proves 15 and 18.

`report` also shows how the tactics are distributed: across everything
proposed, across the steps that ran, and across finished proofs, with each
distribution's top-3 share and normalised entropy. A policy that has collapsed
to `lia`, `auto` and `congruence` on every step shows a top-3 share near 1.

## Premise retrieval

The fixed tactics never name a lemma, so a goal like `length (rev (l ++ l)) =
2 * length l`, which needs `length_rev` and `length_app`, is out of reach
however long the search runs. `proventhru.retrieval` asks Coq's own `Search`
which lemmas mention what the first goal mentions (its constants and
operators, without bound variables or common type names). It ranks them by
how many of the goal's terms they cover, equations first, and offers the top N
as `rewrite L`, `rewrite <- L` and `apply L`. Searches are cached per term set.

```sh
proventhru run examples/eval_open.txt --out out/retrieval --budget 30 --retrieval 6
```

`RetrievalPolicy` wraps any policy, the Claude one included, so a model gets
the same lemmas. On the 29-statement evaluation set (Pétanque, Rocq 9.1.1):

| | no retrieval | retrieval, 6 lemmas |
|---|---|---|
| budget 30 | 10 / 29 | 15 / 29 |
| budget 200 | 11 / 29 | 18 / 29 |

At budget 200, retrieval gained 7 statements and lost none. At budget 30 it
lost one (`3 ^ n >= 1`), because the extra candidates use part of a small
budget. The proofs chain lemmas, for example `rewrite rev_app_distr. f_equal.
apply rev_involutive. apply rev_involutive.` Total `Search` time was 10.6 s
over the 29 searches, and wall time fell (232 s to 198 s) because proofs come
sooner.

**The gate rejects library lemmas.** A statement that one library lemma
closes (`exact L`, `apply L`, or `intros; apply L` when the binders come in
another order) is `trivial`, with the lemma in the script:
`rev (rev l) = l` is `rev_involutive`, not a discovery. Without this check,
12 of the first 24 evaluation statements were "proved" by citing themselves.

## The experiment: does a model help, at matched effort?

`PROTOCOL.md` pre-registers it: the sets (by hash), the prover, the four
conditions (A fixed, B fixed + retrieval, C model alone, D model + retrieval),
the step budgets, and the analysis (paired, exact McNemar, Holm over four
primary comparisons). It is enforced, not just written down:
`proventhru run` refuses a model policy without `--protocol`, refuses a
protocol file that is uncommitted or edited, and `protocol.check()` refuses
any run the frozen block does not cover. Every episode carries the protocol's
sha256 and commit.

- **Steps, not expansions.** `--step-budget N` caps tactics submitted, failed
  ones included, so a policy offering 20 candidates per call and one offering
  5 try exactly as many. `--budget 0` lifts the expansion cap. Invocations
  (policy calls) are reported beside steps.
- **The held-out set** (`examples/eval_test.txt`, 120 statements) is
  generated by `tools/make_eval.py` and filtered only by the gate
  (`tools/gate_eval.py`). The fixed baseline proves 22 of 120 at 600 steps.
  `examples/eval_test_renamed.txt` is the same set with bound variables
  renamed, the memorisation control.
- **Any OpenAI-compatible endpoint** (`--policy openai --base-url URL --model
  NAME --key-env VAR`): the HF router, vLLM, Gemini's compat endpoint,
  OpenRouter. Keys come from the environment, never from arguments.
  `--cache FILE` keeps every response, keyed by the request hash, so reruns
  are free and identical. A model that stays down stops the run, and
  rerunning the same command resumes it.
- **Failures in three kinds** in `proventhru report`: api (the call failed),
  invalid (the answer or a candidate was unusable), unproductive (a valid
  tactic that failed, timed out or looped). Only the last is about reasoning.

- **Parallel statements**: `--jobs N` attempts N statements at once, each
  with its own policy instance and Coq session, so a vLLM server batches
  their calls. Outcomes don't depend on N.
- **M1 in Colab**: `notebooks/m1_colab.ipynb` installs Coq 8.18.0 with opam
  (cached on Drive), pins the model revision, serves it with vLLM in fp16,
  and runs the dev set. Held-out runs stay refused until the freeze.

```sh
proventhru protocol check PROTOCOL.md
proventhru run examples/eval_test.txt --out out/A600 --budget 0 --step-budget 600 \
           --protocol PROTOCOL.md
proventhru run examples/eval_open.txt --out out/dev-C --budget 0 --step-budget 600 \
           --policy openai --base-url https://router.huggingface.co/v1 \
           --model ORG/MODEL:PROVIDER --cache out/cache.jsonl --protocol PROTOCOL.md
proventhru report out/A600/records.jsonl out/C600/records.jsonl
```

## The conjecture loop: proving what nobody asked for

`proventhru explore` is the discovery half. In each round it:

1. **generates** candidates over the stdlib `nat` / `list nat` signature
   (`proventhru/conjecture.py`, the same QuickSpec-style enumerator that built
   the held-out set), smallest first;
2. **tests** each one on 2,000 random inputs, and drops instances of laws
   over `nat` alone: `0 * list_sum l = 0` is `0 * a = 0`, which is true of any
   number, so it says nothing about lists;
3. records **derivations**: a candidate that `pose proof (L l1); lia` closes
   with one lemma `L` found earlier is kept as a derivation citing `L`, not as
   a new lemma;
4. **gates** the rest. Trivial now also means closed by one discovered lemma;
5. **proves** what is open with half the step budget on fixed tactics, then
   half on fixed tactics + retrieval for what is left. Discovered lemmas are
   in the preamble, so Coq's `Search` retrieves them like library lemmas, and
   each one retrieved is also offered as `pose proof (L x); lia`;
6. **keeps** kernel-certified proofs smallest first. One that follows from a
   lemma admitted before it, from the same round included, is a derivation.
   The rest become `Lemma pt_rN_k` in the corpus, in the preamble of every
   later round.

The whole corpus is recompiled from scratch after every round. The held-out
and dev statements are excluded (`--exclude`), so the corpus can't leak into
an evaluation. "Novel" means not closed by one tactic, one library lemma, or
one discovered lemma plus arithmetic. It is novelty relative to the library
and the corpus, not to mathematics.

```sh
proventhru explore --out out/explore --rounds 4 --per-round 80 --step-budget 600 --jobs 4 \
    --exclude examples/eval_test.txt --exclude examples/eval_test_renamed.txt \
    --exclude examples/eval_open.txt
```

Outputs:
- `corpus.v` compiles on its own;
- `corpus.jsonl` lists each lemma's proof, prover, round, and the discovered lemmas it cites;
- `round-N/derived.jsonl` lists the derivations, each with the lemmas it cites;
- `rounds.jsonl` holds per-round counts (gate, derived, proved, citing, and
  `uses_of_corpus`, every place a discovered lemma did work) and the record heads;
- `round-N/` holds the run records.

It runs on CPU and needs no model.

## What is not built yet

- **Reflection (grounded critique).** v2, once v1 has a measured baseline;
  the exact error string it needs is already in the policy's view.
- **oscillate-.** `CoqEnv(observers=[fn])` calls `fn(step)` on every step;
  that is where a phase reader attaches. It is not implemented here.
- **Training (DPO, then GRPO).** The run record holds every step, failed
  steps included, with both verdicts and the reward; `record.steps()` reads them.

## Taken from pq-verify

The kernel check (`kernel.certify`) is pq-verify's `coq_check`. It requires
`coqc` to exit 0 and every theorem to print `Closed under the global context`,
because `coqc` alone accepts `Admitted` proofs and added axioms.
