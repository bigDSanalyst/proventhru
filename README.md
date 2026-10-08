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
disagreement. End to end, Petanque takes 10.5 s and coqtop 21.3 s. Most of
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
3 proved, 1 refuted, 7 rejected (5 trivial, 1 vacuous, 1 ill-formed) and
2 left open. The open ones
are `rev (rev l) = l` and the even/odd lemma; both need a lemma the
fixed-tactic baseline never tries.

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
- **Action**: one tactic sentence. `env.guard` refuses anything that ends the
  proof on the agent's terms or changes the session: `admit`, `Admitted`,
  `Axiom`, `Require`, `BackTo`, `Qed`, bullets, and more than one sentence per
  action. Each tactic runs under Coq's `Timeout`, with a hard process deadline
  behind it.
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

## What is not built yet

- **An LLM policy.** `search.Policy.propose(obs, path) -> [(tactic, score)]`
  is the interface. `FixedTactics` is a baseline with no learning in it, so
  the loop runs end to end today.
- **Premise retrieval.** Most open conjectures need a library lemma.
- **oscillate-.** `CoqEnv(observers=[fn])` calls `fn(step)` on every step;
  that is where a phase reader attaches. It is not implemented here.
- **Training (DPO, then GRPO).** The run record holds every step, failed
  steps included, with both verdicts and the reward; `record.steps()` reads them.

## Taken from pq-verify

The kernel check (`kernel.certify`) is pq-verify's `coq_check`. It requires
`coqc` to exit 0 and every theorem to print `Closed under the global context`,
because `coqc` alone accepts `Admitted` proofs and added axioms.
