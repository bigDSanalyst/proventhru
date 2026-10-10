"""v1 model policy: Claude proposes tactics from a fixed vocabulary.

One API call per expanded node. The model sees view.state() (goals with their
hypotheses, the path so far, and the last failure with Coq's exact message)
and returns up to k ranked candidates, each a tactic name from VOCABULARY plus
an argument. Structured outputs constrain the name to the vocabulary; the
argument is checked here (one tactic, no tacticals, no second sentence) and
again by env.guard before anything runs.

What v1 deliberately does not do: no reflection pass, no lemma retrieval, no
combinators (`;`, `||`, `try`), no MathComp. Those wait until there is a
baseline to measure them against.

Every call's model, token counts and latency become the proposal's `cost` in
the run record; candidates the checks dropped are recorded beside it, so a
policy that keeps proposing invalid actions shows up in the data.
"""
import hashlib
import inspect
import json
import re
import time

from . import view
from .record import canon
from .search import Policy

DEFAULT_MODEL = "claude-opus-5-5"

# Standard-library tactics only. omega is not here: it was removed from Coq in
# 8.17 and is absent from Rocq 9; lia replaces it.
VOCABULARY = (
    "intros", "intro", "simpl", "reflexivity", "assumption", "exact", "apply",
    "rewrite", "induction", "destruct", "split", "left", "right", "exists",
    "lia", "nia", "auto", "congruence", "discriminate", "injection", "unfold",
    "f_equal", "symmetry", "trivial",
)

SYSTEM = """You choose the next tactic in an interactive Coq (Rocq) proof.

You are given the current proof state as JSON: every open goal with its
hypotheses, the tactic path taken so far, and, when the last attempt failed,
that tactic and Coq's exact error message. The first goal is the one the next
tactic acts on.

Propose up to {k} candidate tactics for the next step, best first. Each
candidate is one tactic name from the allowed list, plus its argument:

- the argument is whatever follows the name, without the final period:
  hypothesis or variable names from the state ("n", "H as [x Hx]"), a term
  ("(S n)"), or a standard-library lemma name ("Nat.add_comm", "<- IHn",
  "app_nil_r"); use "" when the tactic takes none.
- one tactic per candidate: no ";", no "||", no "try", no second sentence.
- candidates must differ from each other. Prefer a step that makes progress
  on the first goal over one that only restates it.
- if the last failure is shown, do not repeat that tactic at the same path;
  read Coq's message for why it failed.

Allowed tactic names: {vocab}.

The libraries loaded are given by the preamble: {preamble}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tactic": {"type": "string", "enum": list(VOCABULARY)},
                    "argument": {"type": "string"},
                },
                "required": ["tactic", "argument"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

# Tactics that take no argument here: an argument is a sure Coq error, so it
# is refused before it costs a step ("lia n", "reflexivity H").
NULLARY = {"lia", "nia", "reflexivity", "assumption", "trivial", "congruence", "split",
           "f_equal", "left", "right"}

# Tactics that act on something named: without an argument they are a sure
# error here (`rewrite.`, `apply.`), refused before they cost a step.
NEEDS_ARGUMENT = {"rewrite", "apply", "exact", "unfold", "induction", "destruct", "exists"}

# What an argument may not contain: a tactical, a comment, or a second sentence.
BAD_ARGUMENT = re.compile(r";|\|\||\(\*|\.\s|\.$|\n|\btry\b|\brepeat\b|\bdo\b")


def prompt_sha256():
    """The template, schema, vocabulary and state rendering this policy shows."""
    return hashlib.sha256(canon({
        "template": SYSTEM, "user": "view.state as json.dumps(sort_keys=True)",
        "schema": SCHEMA, "vocabulary": list(VOCABULARY), "view": inspect.getsource(view),
    }).encode()).hexdigest()


def assemble(tactic, argument):
    """(name, argument) -> one tactic sentence, or None with the reason."""
    if tactic not in VOCABULARY:
        return None, f"{tactic!r} is not in the vocabulary"
    arg = (argument or "").strip()
    if arg and tactic in NULLARY:
        return None, f"{tactic} takes no argument (got {arg!r})"
    if not arg and tactic in NEEDS_ARGUMENT:
        return None, f"{tactic} needs an argument"
    if BAD_ARGUMENT.search(arg):
        return None, f"argument {arg!r} is more than one tactic's argument"
    return (f"{tactic} {arg}".strip() + "."), None


class ClaudePolicy(Policy):
    """client is an anthropic.Anthropic (or anything with the same
    beta.messages.create); tests pass a stand-in."""

    def __init__(self, preamble, model=DEFAULT_MODEL, effort="medium", k=5,
                 client=None, max_calls=None, fallbacks=True):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client, self.model, self.effort, self.k = client, model, effort, k
        self.max_calls, self.calls = max_calls, 0
        self.fallbacks = fallbacks
        self.system = SYSTEM.format(k=k, vocab=", ".join(VOCABULARY),
                                    preamble=preamble.strip() or "(none)")
        self.identity = {"id": "claude-fixed-vocab/v1", "model": model,
                         "provider": "anthropic", "effort": effort, "k": k,
                         "prompt_sha256": prompt_sha256(), "vocabulary": list(VOCABULARY)}
        self.last_cost = None

    def _request(self, state):
        kw = dict(
            model=self.model, max_tokens=16000,
            system=[{"type": "text", "text": self.system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": json.dumps(state, sort_keys=True)}],
            output_config={"effort": self.effort,
                           "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        if self.fallbacks:
            # On a policy decline the API re-runs the request on a fallback
            # model inside the same call; the served model is in the cost.
            kw.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        return self.client.beta.messages.create(**kw)

    def propose(self, obs, path, last_failure=None, tried=None):
        if self.max_calls is not None and self.calls >= self.max_calls:
            self.last_cost = {"model": self.model, "skipped": "max_calls reached"}
            return []
        self.calls += 1
        state = view.state(obs, path, last_failure, tried)
        t0 = time.perf_counter()
        resp = self._request(state)
        ms = (time.perf_counter() - t0) * 1000
        u = resp.usage
        cost = {"model": getattr(resp, "model", self.model),
                "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "model_ms": round(ms, 1), "stop_reason": resp.stop_reason,
                "request_id": getattr(resp, "_request_id", None), "dropped": []}
        self.last_cost = cost
        if resp.stop_reason != "end_turn":
            # refusal, max_tokens: no candidates; the record says why.
            return []
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            raw = json.loads(text).get("candidates", [])
        except ValueError:
            cost["dropped"].append({"raw": text[:200], "why": "not JSON"})
            return []
        out, seen = [], set()
        for i, c in enumerate(raw[: self.k]):
            tac, why = assemble(c.get("tactic"), c.get("argument"))
            if tac is None:
                cost["dropped"].append({"candidate": c, "why": why})
            elif tac in seen:
                cost["dropped"].append({"candidate": c, "why": "duplicate"})
            else:
                seen.add(tac)
                out.append((tac, 1.0 - i / max(self.k, 1)))
        return out
