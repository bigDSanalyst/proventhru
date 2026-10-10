"""The coqtop backend: a coqtop process driven sentence by sentence.

`coqtop -emacs` ends every response with a prompt naming the state the next
sentence runs in, e.g. `<prompt>t < 4 |t| 0 < </prompt>`. Running one sentence
and reading up to that prompt gives the response and the state id; `BackTo n`
returns the session to state n. State ids form a stack, not a tree: going
back to n discards every state after it. `CoqtopSession` turns that stack into
the tree a search needs: a handle is the tactic path from the root, and
reaching one rewinds to the longest shared prefix and replays the rest.

Prompts and errors arrive on stderr and goals on stdout, so both share one
pipe. Each sentence has a hard deadline; past it the process is killed and
the session is rebuilt from the path on the next run.
"""
import os
import re
import tempfile
import select
import shutil
import subprocess
import time

PROMPT = re.compile(r"<prompt>\S* < (\d+) \|[^<]*\| \d+ < </prompt>")
# An error is an "Error:" line. "Toplevel input, characters ..." is only the
# location header Coq prints before an error *or a warning*: a tactic that
# succeeds while naming a deprecated lemma prints that header, then a
# <warning> block, then the new goals. Treating the header as an error
# recorded such successes as failures while coqtop's state moved on.
ERROR = re.compile(r"^Error:", re.M)
WARNING = re.compile(r"(Toplevel input, characters[^\n]*\n(?:>[^\n]*\n)*)?<warning>.*?</warning>\n?",
                     re.S)


from . import goals as goalparse
from .session import CoqNotFound, CoqTimeout, TacticError, prover_identity


class Coqtop:
    """One coqtop process. run() sends one sentence and returns
    (text, state_id, is_error)."""

    def __init__(self, coqtop=None, args=(), deadline=30.0):
        exe = coqtop or shutil.which("coqtop")
        if exe is None:
            raise CoqNotFound("coqtop not in PATH")
        self.deadline = deadline
        self.proc = subprocess.Popen(
            [exe, "-q", "-emacs", *args], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        self.state = None
        _, self.state = self._read(self.deadline)
        self.run("Set Printing Width 1000.")

    def _read(self, deadline):
        fd = self.proc.stdout.fileno()
        buf = b""
        end = time.monotonic() + deadline
        while True:
            m = PROMPT.search(buf.decode("utf-8", "replace"))
            if m:
                text = buf.decode("utf-8", "replace")
                return text[:m.start()] + text[m.end():], int(m.group(1))
            left = end - time.monotonic()
            if left <= 0:
                self.close()
                raise CoqTimeout(f"no prompt after {deadline}s")
            ready, _, _ = select.select([fd], [], [], left)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    self.close()
                    raise RuntimeError("coqtop exited: " +
                                       buf.decode("utf-8", "replace")[-400:])
                buf += chunk

    def run(self, sentence, deadline=None):
        if "\n" in sentence.strip():
            raise ValueError("one sentence per call")
        self.proc.stdin.write(sentence.strip().encode() + b"\n")
        text, state = self._read(deadline or self.deadline)
        text = re.sub(r"</?infomsg>", "", text)
        err = bool(ERROR.search(WARNING.sub("", text)))
        if err and self.state is not None and state != self.state:
            # coqtop leaves its state where it was when a sentence fails. If
            # the state moved, the classification is wrong; stop rather than
            # let the session's path and coqtop's state drift apart.
            raise RuntimeError(f"coqtop reported an error but moved from state "
                               f"{self.state} to {state} on {sentence!r}")
        if not err:
            self.state = state
        return text, state, err

    @property
    def alive(self):
        return self.proc.poll() is None

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        for f in (self.proc.stdin, self.proc.stdout):
            if f and not f.closed:
                f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class CoqtopSession:
    """Proof mode on one statement. Handles are tactic paths."""

    name = "coqtop"

    def __init__(self, preamble, statement, deadline=30.0):
        self.preamble, self.statement, self.deadline = preamble, statement, deadline
        self.coqtop = shutil.which("coqtop")
        if self.coqtop is None:
            raise CoqNotFound("coqtop not in PATH")
        coqc = os.path.join(os.path.dirname(self.coqtop), "coqc")
        self.compiler = [coqc if os.path.exists(coqc) else "coqc"]
        self.environment = {"backend": self.name, "prover": prover_identity(self.coqtop),
                            "interface": f"coqtop -emacs ({self.coqtop})",
                            "compiler": self.compiler[0]}
        self._start()
        self.root = ()
        self.root_obs = goalparse.parse(self.root_text)

    def _start(self):
        self.top = Coqtop(self.coqtop, deadline=self.deadline)
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

    def _goto(self, path):
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
            text, err = self._apply(tac)
            if err:
                raise RuntimeError(f"replay of {tac!r} failed: {text.strip()[-200:]}")

    def _apply(self, tactic, timeout=None):
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

    def run(self, handle, tactic, timeout=None):
        """Run tactic at handle. Returns (new handle, Observation); raises
        TacticError when Coq refuses it and CoqTimeout past the deadline."""
        self._goto(list(handle))
        try:
            text, err = self._apply(tactic, timeout)
        except CoqTimeout:
            self.top.close()
            raise
        if err:
            lines = text.strip().splitlines()
            raise TacticError(lines[-1] if lines else "error")
        return handle + (tactic,), goalparse.parse(text)

    def query(self, handle, command):
        """Run a non-tactic command (Check, Search) at handle; returns its
        output and leaves the proof where it was."""
        self._goto(list(handle))
        text, _, err = self.top.run(command)
        if err:
            lines = text.strip().splitlines()
            raise TacticError(lines[-1] if lines else "error")
        return text

    def close(self):
        self.top.close()
