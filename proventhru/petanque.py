"""The Petanque backend: coq-lsp's machine-to-machine protocol, via Pytanque.

Petanque keeps every proof state it returns, so a handle is the state itself:
running from any earlier node costs one request, with no rewind and no replay.
It also reports the hypotheses of every goal (coqtop prints only the first
goal's).

`pet` runs over stdio, one process per session. Rocq's Timeout bounds each
tactic; behind it a watchdog kills the process at the hard deadline. A killed
process loses its states, so handles also carry their tactic path and the
process generation: a stale handle is rebuilt by replaying its path, which is
the only time this backend replays anything.
"""
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field

from .goals import Goal, Observation
from .session import CoqNotFound, CoqTimeout, TacticError

THEOREM = "pt_goal"


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
    shelved = len(goals_response.shelf or [])
    return Observation(tuple(goals), shelved, False)


class PetanqueSession:
    name = "petanque"

    def __init__(self, preamble, statement, deadline=30.0):
        if shutil.which("pet") is None:
            raise CoqNotFound("pet (coq-lsp) not in PATH")
        from pytanque import Pytanque, PytanqueMode, PetanqueError
        self._Pytanque, self._mode, self._PetanqueError = Pytanque, PytanqueMode, PetanqueError
        self.preamble, self.statement, self.deadline = preamble, statement, deadline
        bindir = os.path.dirname(shutil.which("pet"))
        rocq = os.path.join(bindir, "rocq")
        self.compiler = [rocq, "compile"] if os.path.exists(rocq) else ["coqc"]
        self.dir = tempfile.mkdtemp(prefix="proventhru-pet-")
        self.file = os.path.join(self.dir, "Goal.v")
        with open(self.file, "w") as fh:
            fh.write(f"{preamble.strip()}\n\nTheorem {THEOREM} : {statement}.\nProof.\nAdmitted.\n")
        self.gen = 0
        self.client = None
        self._start()

    def _call(self, fn, *args, **kw):
        """One request under the hard deadline."""
        fired = []

        def kill():
            fired.append(True)
            if self.client and self.client.process:
                self.client.process.kill()
        timer = threading.Timer(self.deadline, kill)
        timer.start()
        try:
            return fn(*args, **kw)
        except self._PetanqueError as e:
            if fired:
                self._dead()
                raise CoqTimeout(f"no response after {self.deadline}s")
            if self.client.process.poll() is not None:
                self._dead()
                raise RuntimeError(f"pet exited: {e}")
            raise
        finally:
            timer.cancel()

    def _dead(self):
        try:
            self.client.close()
        except Exception:
            pass
        self.client = None

    def _start(self):
        self.client = self._Pytanque(mode=self._mode.STDIO)
        self.client.connect()
        self.gen += 1
        try:
            st = self._call(self.client.start, self.file, THEOREM)
        except self._PetanqueError as e:
            self.close()
            raise ValueError(f"statement does not elaborate: {e.message}") from None
        self.root = Handle((), st, self.gen)
        self.root_obs = self._observe(st)

    def _observe(self, st):
        if st.proof_finished:
            return Observation(finished=True)
        return observation(self._call(self.client.complete_goals, st), False)

    def _live(self, handle):
        """The handle's state in the running process, replaying only if the
        process that made it is gone."""
        if self.client is None:
            self._start()
        if handle.gen == self.gen:
            return handle.state
        st = self.root.state
        for tac in handle.path:
            st = self._call(self.client.run, st, tac)
        return st

    def run(self, handle, tactic, timeout=None):
        st = self._live(handle)
        try:
            new = self._call(self.client.run, st, tactic,
                             timeout=int(timeout) if timeout else None)
        except self._PetanqueError as e:
            msg = e.message[len("Coq: "):] if e.message.startswith("Coq: ") else e.message
            lines = msg.strip().splitlines()
            raise TacticError(lines[-1] if lines else "error") from None
        return Handle(handle.path + (tactic,), new, self.gen), self._observe(new)

    def query(self, handle, command):
        st = self._live(handle)
        try:
            out = self._call(self.client.run, st, command)
        except self._PetanqueError as e:
            raise TacticError(e.message) from None
        return "\n".join(msg for _, msg in (out.feedback or []))

    def close(self):
        if self.client:
            self._dead()
        shutil.rmtree(self.dir, ignore_errors=True)
