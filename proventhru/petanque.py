"""The Petanque backend: coq-lsp's machine-to-machine protocol, via Pytanque.

Petanque keeps every proof state it returns, so a handle is the state itself:
running from any earlier node costs one request, with no rewind and no
replay. It also reports the hypotheses of every goal (coqtop prints only the
first goal's).

Sessions do not own a process: each is bound to a worker of a shared pool of
`pet` processes (pool.py), and starts with `Goal <statement>.` from the
worker's already loaded preamble state: ~1 ms, against ~550 ms to launch pet
and load the preamble. The kernel check still compiles a fresh file
(kernel.py), so nothing a session does in the shared process can reach it.

Rocq's Timeout bounds each tactic; behind it the worker is killed at the hard
deadline. A killed or restarted
worker loses its states, so handles also carry their tactic path and the
worker generation they were made in: a stale handle is rebuilt by replaying
its path, which is the only time this backend replays anything.
"""
import os
import shutil
from dataclasses import dataclass, field

from .goals import Goal, Observation
from .pool import default_pool
from .session import CoqNotFound, TacticError

@dataclass(frozen=True)
class Handle:
    path: tuple
    state: object = field(compare=False, repr=False)
    gen: int = 0


def observation(goals_response, finished):
    """Petanque's goals response -> Observation, in the same shapes the coqtop
    parser produces, so a policy sees one format whichever backend ran."""
    if finished:
        return Observation(finished=True)
    if goals_response is None:
        return Observation()
    goals = []
    for g in goals_response.goals:
        hyps = []
        for h in g.hyps:
            names = ", ".join(h.names)
            body = f" := {' '.join(h.def_.split())}" if h.def_ else ""
            hyps.append(f"{names}{body} : {' '.join(h.ty.split())}")
        evar = (g.info or {}).get("evar") or [None, 0]
        goals.append(Goal(int(evar[-1] or 0), " ".join(g.ty.split()), tuple(hyps)))
    return Observation(tuple(goals), len(goals_response.shelf or []), False)


def _message(err):
    msg = err.message
    return msg[len("Coq: "):] if msg.startswith("Coq: ") else msg


class PetanqueSession:
    name = "petanque"

    def __init__(self, preamble, statement, deadline=30.0, pool=None):
        if shutil.which("pet") is None:
            raise CoqNotFound("pet (coq-lsp) not in PATH")
        from pytanque import PetanqueError
        self._PetanqueError = PetanqueError
        self.preamble, self.statement, self.deadline = preamble, statement, deadline
        bindir = os.path.dirname(shutil.which("pet"))
        rocq = os.path.join(bindir, "rocq")
        self.compiler = [rocq, "compile"] if os.path.exists(rocq) else ["coqc"]
        self.worker = (pool or default_pool()).acquire()
        self._root()

    def _call(self, method, *args, **kw):
        return self.worker.call(self.deadline, method, *args, **kw)

    def _root(self):
        for attempt in (0, 1):
            try:
                base, gen = self.worker.base(self.deadline, self.preamble)
            except self._PetanqueError as e:
                raise ValueError(f"preamble does not load: {_message(e)}") from None
            try:
                st, gen = self._call("run", base, f"Goal {self.statement}.")
                break
            except self._PetanqueError as e:
                # The worker restarted between loading the preamble and this
                # request: the base state was gone, which says nothing about
                # the statement.
                if attempt == 0 and self.worker.gen != gen:
                    continue
                raise ValueError(f"statement does not elaborate: {_message(e)}") from None
        self.root = Handle((), st, gen)
        self.root_obs = self._observe(st)

    def _observe(self, st):
        if st.proof_finished:
            return Observation(finished=True)
        goals, _ = self._call("complete_goals", st)
        return observation(goals, False)

    def _live(self, handle):
        """The handle's state in the worker's current process, replaying its
        path only if the process that made it is gone. Returns (state, gen)."""
        if handle.gen == self.worker.gen and self.worker.client is not None:
            return handle.state, handle.gen
        if self.root.gen != self.worker.gen or self.worker.client is None:
            self._root()
        st, gen = self.root.state, self.root.gen
        for tac in handle.path:
            st, gen = self._call("run", st, tac)
        return st, gen

    def _run(self, handle, cmd, **kw):
        """Run cmd from handle. If the worker restarted under us (another
        session on it hit its deadline), the state we sent was already gone:
        that is not Coq's verdict, so rebuild and try once more."""
        for attempt in (0, 1):
            st, gen = self._live(handle)
            try:
                return self._call("run", st, cmd, **kw)
            except self._PetanqueError as e:
                if attempt == 0 and self.worker.gen != gen:
                    continue
                raise TacticError(_message(e)) from None

    def run(self, handle, tactic, timeout=None):
        try:
            new, gen = self._run(handle, tactic, timeout=int(timeout) if timeout else None)
        except TacticError as e:
            lines = str(e).strip().splitlines()
            raise TacticError(lines[-1] if lines else "error") from None
        return Handle(handle.path + (tactic,), new, gen), self._observe(new)

    def query(self, handle, command):
        out, _ = self._run(handle, command)
        return "\n".join(msg for _, msg in (out.feedback or []))

    def close(self):
        """Release the session; the worker and its preamble state stay up for
        the next one."""
