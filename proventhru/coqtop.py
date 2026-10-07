"""A coqtop session driven sentence by sentence.

`coqtop -emacs` ends every response with a prompt naming the state the next
sentence runs in, e.g. `<prompt>t < 4 |t| 0 < </prompt>`. Running one sentence
and reading up to that prompt gives the response and the state id; `BackTo n`
returns the session to state n. State ids form a stack, not a tree: going
back to n discards every state after it. `ProofSession` turns that stack into
the tree a search needs by keeping the tactic path for every state.

Prompts and errors arrive on stderr and goals on stdout, so both share one
pipe. Each sentence has a hard deadline; past it the process is killed and
the caller rebuilds the session (see ProofSession.goto).
"""
import os
import re
import select
import shutil
import subprocess
import time

PROMPT = re.compile(r"<prompt>\S* < (\d+) \|[^<]*\| \d+ < </prompt>")
ERROR = re.compile(r"^(Error:|Toplevel input, characters)", re.M)


class CoqNotFound(RuntimeError):
    pass


class CoqTimeout(RuntimeError):
    pass


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
        err = bool(ERROR.search(text))
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
