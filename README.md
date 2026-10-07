# proventhru

Coq is the environment, not a check run at the end. The agent proposes one
tactic, Coq returns the new proof state, and the agent chooses again. Coq
appears at three points in the loop:

| Position | Module | What Coq does | Output |
|---|---|---|---|
| 1. Conjecture gate | `proventhru.gate` | Checks the statement elaborates as a `Prop`, then tries bounded attempts at a disproof, contradictory hypotheses, and a one-tactic proof | `ill_formed`, `refuted`, `vacuous`, `trivial` or `open` |
| 2. Environment | `proventhru.env.CoqEnv` | Runs one tactic per step against a live `coqtop`, from any earlier node | New proof state or error, plus reward signals |
| 3. Kernel | `proventhru.kernel` | Compiles the full proof from scratch with `coqc` and requires `Closed under the global context` | Admitted into the corpus, or rejected |

```
conjectures ─▶ gate ─▶ open ─▶ best_first(CoqEnv, Policy) ─▶ kernel ─▶ corpus.jsonl
                 │                    │ every step                  trajectories.jsonl
                 └ refuted / rejected └▶ observers (phase readers)
```

## Quick start

```sh
sudo apt-get install coq          # Coq 8.18; coqtop and coqc must be on PATH
pip install -e .
proventhru gate  "forall n m : nat, n + m = n"      # refuted, disproof kernel-checked
proventhru prove "forall n : nat, n * n >= n" --trace
proventhru run examples/conjectures.txt --out out
python -m unittest discover -s tests
```

On `examples/conjectures.txt` the baseline gives: 2 proved, 1 refuted,
4 rejected (2 trivial, 1 vacuous, 1 ill-formed) and 2 left open. The open ones
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
- **Action**: one tactic sentence. `env.guard` refuses anything that ends the
  proof on the agent's terms or changes the session: `admit`, `Admitted`,
  `Axiom`, `Require`, `BackTo`, `Qed`, bullets, and more than one sentence per
  action. Each tactic runs under Coq's `Timeout`, with a hard process deadline
  behind it.
- **Transition**: `coqtop -emacs` state ids form a stack. `ProofSession`
  turns them into a tree: it rewinds with `BackTo` to the longest shared
  prefix and replays the rest. A killed session is rebuilt from the path.
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
- **Training (DPO, then GRPO).** `trajectories.jsonl` holds every step, failed
  steps included, with signals and rewards.
- **A Pétanque (coq-lsp) backend.** It would give real state handles instead of
  replay. `ProofSession` is the only class that would change.

## Taken from pq-verify

The kernel check (`kernel.certify`) is pq-verify's `coq_check`. It requires
`coqc` to exit 0 and every theorem to print `Closed under the global context`,
because `coqc` alone accepts `Admitted` proofs and added axioms.
