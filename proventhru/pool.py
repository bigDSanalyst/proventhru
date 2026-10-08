"""A small pool of `pet` processes shared by every Petanque session.

Measured on one process (Rocq 9.1.1, coq-lsp 0.2.5): launching pet and
loading `Require Import Arith Lia List.` costs ~550 ms, a second document with
the same Require still ~200 ms, but `Goal <statement>.` run from an already
loaded preamble state costs ~1 ms. So each worker loads a preamble once and
keeps that state; every session on the worker starts from it. States are
immutable values: what one session does from the preamble state is invisible
to the next. One stdio process serves one request at a time, so:

  * a session is bound to one worker for its life, because its states exist
    only in that process;
  * each worker has a lock, held for exactly one request;
  * sessions on different workers run in parallel;
  * a new session goes to an idle running worker first, so sequential use
    stays on one process and concurrent use spreads across the pool.

A worker is killed at a session's hard deadline, or by a crash. It then
restarts lazily with a new generation, and every handle made under the old
generation is rebuilt by its session from the tactic path. That is the cost
of sharing: one runaway tactic makes the other sessions on that worker replay
once. A worker also restarts after `recycle` sessions, to bound pet's memory.

The pool size is PROVENTHRU_PET_WORKERS, default min(4, cpu count).
"""
import atexit
import itertools
import os
import shutil
import tempfile
import threading

from .session import CoqTimeout


class Worker:
    def __init__(self, index, recycle=200):
        self.index = index
        self.recycle = recycle
        self.lock = threading.Lock()
        self.client = None
        self.gen = 0
        self.sessions = 0
        self.claimed = False    # some session has been assigned to it
        self.bases = {}         # preamble -> (state after it, generation)
        self.dir = tempfile.mkdtemp(prefix=f"proventhru-pet{index}-")

    def _ensure(self):
        if self.client is None:
            from pytanque import Pytanque, PytanqueMode
            self.client = Pytanque(mode=PytanqueMode.STDIO)
            self.client.connect()
            self.gen += 1
            self.sessions = 0

    def _kill(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def call(self, deadline, method, *args, **kw):
        """One request on this worker, under its lock and the hard deadline.
        Returns (result, generation the result belongs to)."""
        from pytanque import PetanqueError
        with self.lock:
            self._ensure()
            gen, client, fired = self.gen, self.client, []

            def kill():
                fired.append(True)
                if client.process:
                    client.process.kill()
            timer = threading.Timer(deadline, kill)
            timer.start()
            try:
                return getattr(client, method)(*args, **kw), gen
            except PetanqueError:
                if fired:
                    self._kill()
                    raise CoqTimeout(f"no response after {deadline}s") from None
                if client.process.poll() is not None:
                    self._kill()
                    raise RuntimeError("pet exited") from None
                raise
            finally:
                timer.cancel()

    def base(self, deadline, preamble):
        """The state just after `preamble` in this worker's process, loading
        it at most once per process. Returns (state, generation)."""
        cached = self.bases.get(preamble)
        if cached and cached[1] == self.gen and self.client is not None:
            return cached
        path = os.path.join(self.dir, f"Base{len(self.bases)}.v")
        with open(path, "w") as fh:
            fh.write(f"{preamble.strip()}\n\nTheorem pt_anchor : True.\nProof.\nAdmitted.\n")
        anchor, gen = self.call(deadline, "start", path, "pt_anchor")
        st, gen2 = self.call(deadline, "run", anchor, "Abort.")
        if gen2 != gen:
            raise RuntimeError("pet restarted while loading a preamble")
        self.bases[preamble] = (st, gen)
        return st, gen

    def opened(self):
        """Count a new session; restart the process (between requests) once
        it has served `recycle` of them."""
        with self.lock:
            self.sessions += 1
            if self.client is not None and self.sessions > self.recycle:
                self._kill()

    def kill(self):
        with self.lock:
            self._kill()

    def shutdown(self):
        self.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


class Pool:
    def __init__(self, size=None, recycle=200):
        size = size or int(os.environ.get("PROVENTHRU_PET_WORKERS") or min(4, os.cpu_count() or 1))
        self.workers = [Worker(i, recycle) for i in range(max(1, size))]
        self._next = itertools.cycle(self.workers)
        self._lock = threading.Lock()

    def acquire(self):
        """The worker for a new session: one that has launched and is idle
        right now, else one no session has been given yet, else round robin.

        A worker is claimed when a session is assigned to it, before its
        process starts (that happens on the session's first request). Until
        it has launched it counts as busy, so callers arriving together get
        different workers instead of all picking the first unstarted one,
        and a sequential caller still pays one launch, not one per worker."""
        with self._lock:
            w = self._choose()
            w.claimed = True
        w.opened()
        return w

    def _choose(self):
        idle = [w for w in self.workers
                if w.claimed and w.gen > 0 and not w.lock.locked()]
        fresh = [w for w in self.workers if not w.claimed]
        return idle[0] if idle else fresh[0] if fresh else next(self._next)

    def close(self):
        for w in self.workers:
            w.shutdown()


_default = None
_default_lock = threading.Lock()


def default_pool():
    global _default
    with _default_lock:
        if _default is None:
            _default = Pool()
            atexit.register(_default.close)
        return _default
