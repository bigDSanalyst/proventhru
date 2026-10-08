"""Position 2: Coq as the environment.

    obs   = env.reset()                    # root node: the statement's goal
    res   = env.step(node, "intros n.")    # one tactic, one Coq response

A node is a tactic path from the root plus the backend's handle for it. Any
node can be stepped from again, so search can branch and backtrack; how the
backend gets back there (coqtop replays, Petanque keeps the state) does not
show here. See session.py.

Every step returns two verdicts that are kept apart, because they train
different things and disagree in exactly the case worth catching (a `fix`
that closes every goal in the session and fails the guard condition at Qed):

  outcome  what the live session said about this one step:
           ok | error (Coq refused the tactic) | refused (the guard refused it,
           Coq never saw it) | timeout (nothing was decided)
  kernel   only on a step that finished the proof: what a from-scratch compile
           said about the whole proof: accepted | rejected | not_checked

plus the raw signals (goals and size before and after, revisit, finished) and
a scalar reward made from them by RewardWeights. The defaults only shape: a
step cost, a penalty for errors and for revisiting a state, and the terminal
reward on kernel acceptance. A timeout is not a failure and is weighted 0 by
default; so is a kernel that did not check. Goal count is reported but
weighted 0, because induction and split raise it while making progress.
"""
import re
import time
from dataclasses import dataclass, field, asdict

from . import goals as goalparse
from .kernel import certify
from .session import CoqTimeout, TacticError, open_session

DEFAULT_PREAMBLE = "Require Import Arith Lia List."

# Sentences that would end the proof on the agent's terms, add an
# assumption, or move the session out from under the environment.
BANNED = re.compile(
    r"\b(admit|give_up|Admitted|Abort|Axiom|Axioms|Parameter|Parameters|Hypothesis|"
    r"Hypotheses|Variable|Variables|Conjecture|Context|Back|BackTo|Undo|Restart|"
    r"Reset|Qed|Defined|Save|Require|Import|Export|Load|Declare|Set|Unset|Drop|Quit|"
    r"Unshelve|Focus|Unfocus|Proof|Timeout|Fail|Redirect|Time)\b")


# An action is a tactic, never a command. In Rocq every vernacular command
# begins with a capital letter (Cd, Register, Print, Search, Optimize, ...) and
# every tactic with a lowercase one, so the allowlist is on the first token,
# after an optional goal selector (all:, 2:, 1-3:, [n]:). Probing the earlier
# blocklist found Cd, Register and Optimize Heap running mid-proof; Cd moves
# the working directory of a pet worker shared by later sessions.
SELECTOR = r"(?:all|par|!|\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*|\[\s*\w+\s*\])\s*:\s*"
SELECTOR_RE = re.compile(rf"^{SELECTOR}")


def guard(tactic):
    """Return why a tactic is refused, or None if it may run."""
    t = tactic.strip()
    if not t.endswith("."):
        return "a tactic is one sentence ending in '.'"
    if re.search(r"\.\s", t[:-1]) or "(*" in t:
        return "one sentence per action, no comments"
    if re.match(r"^[-+*{}]", t):
        return "bullets and braces are not actions; the env works on the first goal"
    sel = SELECTOR_RE.match(t)
    body = t[sel.end():] if sel else t
    if not re.match(r"[a-z(]", body):
        return "an action is a tactic: it starts with a lowercase tactic name, not a command"
    m = BANNED.search(t)
    if m:
        return f"'{m.group(1)}' is not an action"
    return None


@dataclass
class RewardWeights:
    step: float = -0.01
    error: float = -0.1
    revisit: float = -0.2
    refused: float = -0.1         # the guard refused the action
    timeout: float = 0.0          # nothing was decided: not a failure
    goals_delta: float = 0.0      # per goal removed (before - after)
    size_delta: float = 0.0       # per 100 characters of conclusion removed
    kernel: float = 1.0           # terminal: proof certified (accepted)
    kernel_rejected: float = 0.0  # the session finished, the kernel refused


@dataclass
class Node:
    path: tuple
    obs: goalparse.Observation
    handle: object = field(default=None, repr=False, compare=False)

    @property
    def depth(self):
        return len(self.path)


@dataclass
class Step:
    tactic: str
    parent: tuple
    node: Node = None
    error: str = None
    signals: dict = field(default_factory=dict)
    reward: float = 0.0
    done: bool = False
    certificate: object = None
    outcome: str = "ok"          # ok | error | refused | timeout
    prover_ms: float = 0.0       # time in the session for this step
    kernel_ms: float = 0.0       # time in the from-scratch compile, if any

    @property
    def kernel(self):
        """accepted | rejected | not_checked, or None when the step did not
        finish the proof (or certification is off)."""
        return None if self.certificate is None else self.certificate.verdict

    def record(self):
        return {"tactic": self.tactic, "depth": len(self.parent),
                "outcome": self.outcome, "error": self.error,
                "kernel": self.kernel, "signals": self.signals, "reward": self.reward,
                "done": self.done,
                "obs": None if self.node is None else self.node.obs.text(),
                "obs_key": None if self.node is None else self.node.obs.key}


class CoqEnv:
    def __init__(self, statement, preamble=DEFAULT_PREAMBLE, tactic_timeout=5,
                 deadline=30.0, weights=None, certify_on_finish=True, observers=(),
                 backend=None):
        self.statement, self.preamble, self.backend = statement, preamble, backend
        self.tactic_timeout, self.deadline = tactic_timeout, deadline
        self.weights = weights or RewardWeights()
        self.certify_on_finish = certify_on_finish
        # Called with every Step: where a phase reader (oscillate-) attaches.
        self.observers = list(observers)
        self.session = None
        self.seen = set()

    def reset(self):
        if self.session:
            self.session.close()
        self.session = open_session(self.preamble, self.statement, self.backend,
                                    self.deadline)
        root = Node((), self.session.root_obs, self.session.root)
        self.seen = {root.obs.key}
        return root

    def step(self, node, tactic):
        tactic = tactic.strip()
        st = Step(tactic, node.path)
        before = node.obs
        why = guard(tactic)
        if why:
            st.error, st.outcome = "refused: " + why, "refused"
        else:
            t0 = time.perf_counter()
            try:
                handle, obs = self.session.run(node.handle, tactic, self.tactic_timeout)
                st.node = Node(node.path + (tactic,), obs, handle)
            except TacticError as e:
                st.error = str(e)
                # Rocq's own Timeout reports as an error message; it decided nothing.
                # coqtop says "Error: Timeout!", Petanque "Timeout!".
                st.outcome = "timeout" if re.search(r"(^|: )Timeout!?\s*$", st.error) else "error"
            except CoqTimeout:
                st.error, st.outcome = "timeout", "timeout"
            st.prover_ms = (time.perf_counter() - t0) * 1000
        st.signals = self._signals(before, st)
        st.reward = self._reward(st, st.signals)
        for fn in self.observers:
            fn(st)
        return st

    def _signals(self, before, st):
        s = {"error": st.outcome == "error",
             "goals_before": len(before.goals) + before.shelved,
             "size_before": before.size, "revisit": False, "finished": False,
             "kernel": None}
        if st.node is None:
            return s
        after = st.node.obs
        s.update(goals_after=len(after.goals) + after.shelved, size_after=after.size,
                 revisit=after.key in self.seen, finished=after.finished)
        self.seen.add(after.key)
        if after.finished:
            st.done = True
            if self.certify_on_finish:
                t0 = time.perf_counter()
                st.certificate = certify(self.preamble, self.statement, st.node.path,
                                         compiler=self.session.compiler)
                st.kernel_ms = (time.perf_counter() - t0) * 1000
                s["kernel"] = st.certificate.verdict
        return s

    def _reward(self, st, s):
        w = self.weights
        r = w.step
        if st.outcome != "ok":
            return r + {"error": w.error, "refused": w.refused, "timeout": w.timeout}[st.outcome]
        if s["revisit"]:
            r += w.revisit
        r += w.goals_delta * (s["goals_before"] - s.get("goals_after", s["goals_before"]))
        r += w.size_delta * (s["size_before"] - s.get("size_after", s["size_before"])) / 100
        if s["kernel"] == "accepted":
            r += w.kernel
        elif s["kernel"] == "rejected":
            r += w.kernel_rejected
        return r

    def close(self):
        if self.session:
            self.session.close()
            self.session = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def weights_dict(w):
    return asdict(w)
