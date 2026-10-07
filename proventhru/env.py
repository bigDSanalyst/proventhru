"""Position 2: Coq as the environment.

    obs   = env.reset()                    # root node: the statement's goal
    res   = env.step(node, "intros n.")    # one tactic, one Coq response

A node is a tactic path from the root. Any node can be stepped from again,
so search can branch and backtrack; ProofSession rewinds coqtop with BackTo
to the longest shared prefix and replays the rest.

Every step returns the raw signals (error, goals before and after, size
before and after, revisit, finished, kernel) and a scalar reward made from
them by RewardWeights. The defaults only shape: a step cost, a penalty for
errors and for revisiting a state, and the terminal reward on kernel
acceptance. Goal count is reported but weighted 0 by default, because
induction and split raise it while making progress.
"""
import os
import re
import tempfile
from dataclasses import dataclass, field, asdict

from . import goals as goalparse
from .coqtop import Coqtop, CoqTimeout
from .kernel import certify

DEFAULT_PREAMBLE = "Require Import Arith Lia List."

# Sentences that would end the proof on the agent's terms, add an
# assumption, or move the session out from under the environment.
BANNED = re.compile(
    r"\b(admit|give_up|Admitted|Abort|Axiom|Axioms|Parameter|Parameters|Hypothesis|"
    r"Hypotheses|Variable|Variables|Conjecture|Context|Back|BackTo|Undo|Restart|"
    r"Reset|Qed|Defined|Save|Require|Import|Export|Load|Declare|Set|Unset|Drop|Quit|"
    r"Unshelve|Focus|Unfocus|Proof|Timeout|Fail|Redirect|Time)\b")


def guard(tactic):
    """Return why a tactic is refused, or None if it may run."""
    t = tactic.strip()
    if not t.endswith("."):
        return "a tactic is one sentence ending in '.'"
    if re.search(r"\.\s", t[:-1]) or "(*" in t:
        return "one sentence per action, no comments"
    if re.match(r"^[-+*{}]", t):
        return "bullets and braces are not actions; the env works on the first goal"
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


class ProofSession:
    """A coqtop process in proof mode on one statement, positioned on a path."""

    def __init__(self, preamble, statement, deadline=30.0):
        self.preamble, self.statement, self.deadline = preamble, statement, deadline
        self._start()

    def _start(self):
        self.top = Coqtop(deadline=self.deadline)
        if self.preamble.strip():
            fd, pre = tempfile.mkstemp(suffix=".v", prefix="proventhru-pre-")
            with os.fdopen(fd, "w") as fh:
                fh.write(self.preamble)
            try:
                text, _, err = self.top.run(f'Load "{pre}".')
            finally:
                os.unlink(pre)
            if err:
                raise ValueError("preamble does not load: " + text.strip()[-300:])
        text, state, err = self.top.run(f"Goal {self.statement}.")
        if err:
            raise ValueError("statement does not elaborate: " + text.strip()[-300:])
        self.root_text = text
        self.path, self.states = [], [state]

    def goto(self, path):
        """Put the session at the end of path (which must have run before)."""
        if not self.top.alive:
            self._start()
        k = 0
        while k < min(len(path), len(self.path)) and path[k] == self.path[k]:
            k += 1
        if k < len(self.path):
            _, _, err = self.top.run(f"BackTo {self.states[k]}.")
            if err:
                self.top.close()
                self._start()
                k = 0
            del self.path[k:], self.states[k + 1:]
        for tac in path[k:]:
            text, err = self.apply(tac)
            if err:
                raise RuntimeError(f"replay of {tac!r} failed: {text.strip()[-200:]}")
        return self

    def apply(self, tactic, timeout=None):
        sentence = tactic if timeout is None else f"Timeout {int(timeout)} {tactic}"
        text, state, err = self.top.run(sentence)
        if not err:
            self.path.append(tactic)
            self.states.append(state)
            if not text.strip():
                # coqtop prints nothing when a tactic leaves the goals as they
                # were. Show is a query: the state recorded above stays valid.
                text, _, _ = self.top.run("Show.")
        return text, err

    def close(self):
        self.top.close()


class CoqEnv:
    def __init__(self, statement, preamble=DEFAULT_PREAMBLE, tactic_timeout=5,
                 deadline=30.0, weights=None, certify_on_finish=True, observers=()):
        self.statement, self.preamble = statement, preamble
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
        self.session = ProofSession(self.preamble, self.statement, self.deadline)
        root = Node((), goalparse.parse(self.session.root_text))
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
                self.session.goto(list(node.path))
                text, err = self.session.apply(tactic, self.tactic_timeout)
                if err:
                    st.error = text.strip().splitlines()[-1] if text.strip() else "error"
                else:
                    st.node = Node(node.path + (tactic,), goalparse.parse(text))
            except CoqTimeout:
                st.error = "timeout"
                self.session.close()
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
                st.certificate = certify(self.preamble, self.statement, st.node.path)
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
