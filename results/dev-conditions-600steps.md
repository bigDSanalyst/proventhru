# Dev set: conditions A–D at 600 steps, by tuning round

**The dev set, not the registered finding.** These are the 29 statements of
`examples/eval_open.txt`, which the protocol keeps for tuning and does not
hold out. The prompt was tuned on them, so the model numbers here are
optimistic by construction. The registered comparison is on `test` under the
freezing amendment. This file is what that amendment cites as the state of
the policy when it was frozen.

Setup throughout: coqtop, Coq 8.18.0; `--budget 0 --step-budget 600`;
M1 = `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`,
served by vLLM 0.31.0 in bf16 on an NVIDIA A100-SXM4-40GB, temperature 0,
seed 0, k = 5, `json_schema` output. Runs cite protocol v3
(`a6b435200588…`).

## The final round (the frozen prompt)

Prompt `e26d4a7732dc48875af2cd566141a41ae7a939bb66ffd0bb0d794caba54f1ee4`
(commit `3c60b52`), re-asking up to 3 times per state, arity enforced by
the output schema.

| dev, 600 steps | without retrieval | with retrieval |
|---|---|---|
| fixed tactics | **A = 10** / 29 | **B = 15** / 29 |
| M1 | **C = 7** / 29 | **D = 12** / 29 |

| run | proved | ended: proved / step budget / frontier | steps | invocations | candidates per call | invalid candidates | record head |
|---|---|---|---|---|---|---|---|
| A | 10 | 10 / 16 / 3 | 11,406 | 618 | 18.99 | – | 12,082 `f5f5d6c9…31fb` |
| B | 15 | 15 / 12 / 2 | 10,925 | 374 | 30.82 | – | 11,357 `e07b1916…f354` |
| C | 7 | 7 / 4 / 18 | 4,315 | 1,580 | 4.94 | 90 | 5,953 `2b2517f1…0fc2e` |
| D | 12 | 12 / 10 / 7 | 9,944 | 974 | 17.58 | 60 | 10,976 `5cfffa3e…1dfb` |

A and B were run in this repository's container; C and D in Colab. Their
records are in the Drive folder `proventhru/runs/`.

## Earlier rounds

| round | prompt | change | C | D | C's searches ended by frontier | records |
|---|---|---|---|---|---|---|
| 1 | `c9ce1aa0…` | first prompt, "up to k" candidates | 0 / 29 | – | 29 of 29 (126 steps in all) | not kept |
| 2 | `63ca6854…` | exactly k, worked examples | 4 / 29 | – | 25 of 25 unproved (792 steps) | not kept |
| 3 | `2c274554…` | re-asking with `tried_here`; nullary arguments refused | 7 / 29 | 10 / 29 | 20 of 22 unproved (4,106 steps) | C 5,570 `a5ca750c…328f`, D 10,672 `ba3e25fd…d564` |
| 4 | `9d5a3e60…` | arity rules and a fourth example; empty arguments refused | 8 / 29 | 12 / 29 | 21 of 21 unproved (2,042 steps); 1,455 invalid candidates | C 3,064 `947da863…5197`, D 9,495 `8c1ae289…7137` |
| 5 | `e26d4a77…` | arity enforced by the output schema; filled right/wrong examples | 7 / 29 | 12 / 29 | 18 of 22 unproved (4,315 steps); 90 invalid | above |

## What the rounds show

**Formatting is not what limits the model.** Round 4 found arity errors in
about 30% of what the model emitted (1,455 of ~4,800 candidates; 1,276
were an argument-taking tactic with no argument). Round 5 put arity into the
output schema, so under constrained decoding the error cannot be emitted:
invalid candidates fell to 90. C did not improve (8 to 7), D stayed at 12.
About 85% of C's well-formed tactics still fail in Coq or return to a seen
state (3,687 of 4,315). Where an argument is required, the model often
supplies the nearest variable (`rewrite n`, `unfold n`, `discriminate n`):
well-formed, and wrong about what the tactic acts on.

**The model's search starves.** In every round, most of C's unproved searches
end by running out of candidates, not at the step budget: 18 of 22 in round
5, which used 4,315 of 17,400 steps (25%). Read a C result as the result of
a policy that cannot use its budget, not of one that used it and lost.

**D replaces the fixed list rather than adding to it.** D is retrieval
wrapped around the model; B is retrieval wrapped around the fixed tactics.
D therefore lacks B's cheap closers (`lia`, `auto`, `congruence`, `nia`,
...), and on dev that is where its gap to B lies. Whether the model adds
anything *to* the fixed list is a different condition (fixed + retrieval +
model, the model's candidates appended). It is not part of the frozen
protocol and comes after the test runs, by its own amendment.

**The DPO starting point.** C proves 7 of 29 on dev. That is worse than the
fixed list, but not zero, and preference optimisation needs a policy that
already finds some proofs.

**About 85–90% of the model's own tactics are unproductive** (an error, a
timeout, or a return to a state already seen) in every round with
re-asking, rounds 4 and 5 included.
