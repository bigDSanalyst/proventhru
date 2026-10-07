"""What every backend provides, and how to open one.

A session is proof mode on one statement:

    s = open_session(preamble, statement, backend="petanque")
    s.root, s.root_obs                     # handle and Observation at the start
    h, obs = s.run(s.root, "intros n.", timeout=5)
    s.query(h, "Check Nat.add_comm.")      # output text; the proof does not move
    s.compiler                             # argv prefix that compiles a .v file
    s.close()

Handles are opaque. Any handle the session returned can be run from again,
so search branches without the environment knowing how: coqtop replays a
tactic path, Petanque keeps the state itself.

`run` raises TacticError when Coq refuses the tactic and CoqTimeout when the
hard deadline passes; the session stays usable after either.
"""
import importlib.util
import os
import shutil


class CoqNotFound(RuntimeError):
    pass


class CoqTimeout(RuntimeError):
    pass


class TacticError(RuntimeError):
    pass


BACKENDS = ("coqtop", "petanque")


def petanque_available():
    if shutil.which("pet") is None:
        return False
    return importlib.util.find_spec("pytanque") is not None


def resolve(backend=None):
    backend = backend or os.environ.get("PROVENTHRU_BACKEND") or "auto"
    if backend == "auto":
        return "petanque" if petanque_available() else "coqtop"
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}; one of {BACKENDS} or 'auto'")
    return backend


def open_session(preamble, statement, backend=None, deadline=30.0):
    backend = resolve(backend)
    if backend == "petanque":
        from .petanque import PetanqueSession
        return PetanqueSession(preamble, statement, deadline)
    from .coqtop import CoqtopSession
    return CoqtopSession(preamble, statement, deadline)
