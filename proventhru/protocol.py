"""The pre-registered protocol, enforced.

PROTOCOL.md is prose for people plus one fenced block for this module:

    ```json frozen
    {"sets": {"dev": "<sha256>", "test": "<sha256>", ...},
     "held_out": ["test", "test_renamed"],
     "environment": {"backend": "coqtop", "prover": "coq-8.18.0"},
     "searches": [{"budget": null, "step_budget": 250}, ...],
     "policies": ["fixed-tactics/v1", ...],
     "prompts": ["<sha256>", ...],
     "models": ["Qwen/...", ...],
     "k": 5, "retrieval_top": 6,
     "model_settings": {"reexpand": 3, "temperature": 0.0, ...}}
    ```

load() refuses a protocol file that is not committed, or that differs from
the committed version, and returns its sha256 and the commit that holds it.
check() refuses a run that the frozen block does not cover:

- the statements (with their preamble) must be one of the registered sets;
- the environment's backend and prover must be the registered ones;
- on a held-out set, the search budgets, the policy id, and for a model
  policy its prompt template hash, model and k must all be registered. A
  model policy cannot touch a held-out set until a prompt is frozen.

Dev sets are open to any prompt or model: that is where the prompt is tuned.
Every episode then carries {sha256, commit, path, set}, so a result names
the exact protocol it was run under, and an amended protocol (a new commit,
a new hash) is visible in the records it governs.
"""
import hashlib
import json
import os
import re
import subprocess

from .record import canon


class ProtocolError(RuntimeError):
    pass


def statements_sha256(preamble, statements):
    """What a set's registered hash covers: the preamble and the statements
    in order. Comments in the file do not count."""
    return hashlib.sha256(canon({"preamble": preamble, "statements": list(statements)})
                          .encode()).hexdigest()


def frozen_block(text):
    m = re.search(r"```json frozen\n(.*?)\n```", text, re.S)
    if not m:
        raise ProtocolError("no ```json frozen block in the protocol")
    try:
        return json.loads(m.group(1))
    except ValueError as e:
        raise ProtocolError(f"the frozen block is not JSON: {e}")


def _git(d, *args):
    return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True)


def load(path, require_committed=True):
    path = os.path.abspath(path)
    with open(path, "rb") as fh:
        raw = fh.read()
    d, name = os.path.split(path)
    commit = None
    if require_committed:
        if _git(d, "ls-files", "--error-unmatch", name).returncode != 0:
            raise ProtocolError(f"{name} is not committed: commit it before any run under it")
        if _git(d, "diff", "--quiet", "HEAD", "--", name).returncode != 0:
            raise ProtocolError(f"{name} differs from its committed version: commit the change "
                                "(an amendment) before running under it")
        commit = _git(d, "log", "-1", "--format=%H", "--", name).stdout.strip() or None
    return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "commit": commit,
            "frozen": frozen_block(raw.decode())}


def is_model_policy(identity):
    return bool((identity or {}).get("prompt_sha256"))


def check(protocol, preamble, statements, policy, environment, search):
    """The episode field for this run, or ProtocolError naming what is not
    registered. search is {"budget", "step_budget"}."""
    f = protocol["frozen"]
    digest = statements_sha256(preamble, statements)
    names = [n for n, h in (f.get("sets") or {}).items() if h == digest]
    if not names:
        raise ProtocolError(f"these statements (sha256 {digest[:12]}...) are not a registered set")
    name = names[0]
    want = f.get("environment") or {}
    for k, v in want.items():
        if (environment or {}).get(k) != v:
            raise ProtocolError(f"environment {k} is {(environment or {}).get(k)!r}; "
                                f"the protocol registers {v!r}")
    if name in (f.get("held_out") or []):
        s = {"budget": search.get("budget"), "step_budget": search.get("step_budget")}
        if s not in (f.get("searches") or []):
            raise ProtocolError(f"search {s} is not registered for held-out sets")
        pid = (policy or {}).get("id")
        if pid not in (f.get("policies") or []):
            raise ProtocolError(f"policy {pid!r} is not a registered condition")
        if is_model_policy(policy):
            if not f.get("prompts"):
                raise ProtocolError("no prompt is frozen yet: model policies run on dev sets only")
            if policy["prompt_sha256"] not in f["prompts"]:
                raise ProtocolError(f"prompt {policy['prompt_sha256'][:12]}... is not the frozen one")
            if policy.get("model") not in (f.get("models") or []):
                raise ProtocolError(f"model {policy.get('model')!r} is not registered")
            if f.get("k") is not None and policy.get("k") != f["k"]:
                raise ProtocolError(f"k={policy.get('k')}; the protocol registers k={f['k']}")
            for key, want in (f.get("model_settings") or {}).items():
                if policy.get(key) != want:
                    raise ProtocolError(f"{key}={policy.get(key)!r}; the protocol registers "
                                        f"{want!r}")
        top = (policy or {}).get("retrieval", {}).get("top")
        if top is not None and f.get("retrieval_top") is not None and top != f["retrieval_top"]:
            raise ProtocolError(f"retrieval top={top}; the protocol registers {f['retrieval_top']}")
    return {"sha256": protocol["sha256"], "commit": protocol["commit"],
            "path": protocol["path"], "set": name}
