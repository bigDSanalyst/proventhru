"""Position 2: Coq as the environment.

    obs   = env.reset()                    # root node: the statement's goal
    res   = env.step(node, "intros n.")    # one tactic, one Coq response

A node is a tactic path from the root plus the backend's handle for it. Any
node can be stepped from again, so search can branch and backtrack; how the
backend gets back there (coqtop replays, Petanque keeps the state) does not
show here. See session.py.

Every step returns the raw signals (error, goals before and after, size
before and after, revisit, finished, kernel) and a scalar reward made from
them by RewardWeights. The defaults only shape: a step cost, a penalty for
errors and for revisiting a state, and the terminal reward on kernel
acceptance. Goal count is reported but weighted 0 by default, because
induction and split raise it while making progress.
"""
import re
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
    goals_delta: float = 0.0      # per goal removed (before - after)
    size_delta: float = 0.0       # per 100 characters of conclusion removed
    kernel: float = 1.0           # terminal: proof certified


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

    def record(self):
        return {"tactic": self.tactic, "depth": len(self.parent),
                "error": self.error, "signals": self.signals, "reward": self.reward,
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
            st.error = "refused: " + why
        else:
            try:
                handle, obs = self.session.run(node.handle, tactic, self.tactic_timeout)
                st.node = Node(node.path + (tactic,), obs, handle)
            except TacticError as e:
                st.error = str(e)
            except CoqTimeout:
                st.error = "timeout"
        st.signals = self._signals(before, st)
        st.reward = self._reward(st.signals)
        for fn in self.observers:
            fn(st)
        return st

    def _signals(self, before, st):
        s = {"error": st.error is not None,
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
                st.certificate = certify(self.preamble, self.statement, st.node.path,
                                         compiler=self.session.compiler)
                s["kernel"] = st.certificate.ok
        return s

    def _reward(self, s):
        w = self.weights
        r = w.step
        if s["error"]:
            return r + w.error
        if s["revisit"]:
            r += w.revisit
        r += w.goals_delta * (s["goals_before"] - s.get("goals_after", s["goals_before"]))
        r += w.size_delta * (s["size_before"] - s.get("size_after", s["size_before"])) / 100
        if s["kernel"]:
            r += w.kernel
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
