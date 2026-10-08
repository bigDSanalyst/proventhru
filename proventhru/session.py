"""What every backend provides, and how to open one.

A session is proof mode on one statement:

    s = open_session(preamble, statement, backend="petanque")
    s.root, s.root_obs                     # handle and Observation at the start
    h, obs = s.run(s.root, "intros n.", timeout=5)
    s.query(h, "Check Nat.add_comm.")      # output text; the proof does not move
    s.compiler                             # argv prefix that compiles a .v file
    s.environment                          # {backend, prover, ...}: what every
                                           # verdict is relative to
    s.close()

Handles are opaque. Any handle the session returned can be run from again,
so search branches without the environment knowing how: coqtop replays a
tactic path, Petanque keeps the state itself.

`run` raises TacticError when Coq refuses the tactic and CoqTimeout when the
hard deadline passes; the session stays usable after either.
"""
import importlib.util
import os
import re
import shutil


_IDENTITY = {}
_VERSION = {}


def prover_identity(exe):
    """'coq-8.18.0' or 'rocq-9.1.1' for the binary at exe, from its own
    --version, or 'unknown' when it does not say. A verdict is only meaningful
    relative to the prover that gave it, so every record names this."""
    if exe in _IDENTITY:
        return _IDENTITY[exe]
    import subprocess
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    m = re.search(r"The (Coq Proof Assistant|Rocq Prover), version (\S+)", out)
    ident = (("rocq" if m.group(1).startswith("Rocq") else "coq") + "-" + m.group(2)
             if m else "unknown")
    _IDENTITY[exe] = ident
    return ident


def tool_version(exe):
    """First line of `exe --version` (coq-lsp's pet prints just '0.2.5')."""
    if exe in _VERSION:
        return _VERSION[exe]
    import subprocess
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=30).stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        out = []
    _VERSION[exe] = out[0] if out else "unknown"
    return _VERSION[exe]


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


def check_statement(statement):
    """A statement is one term. A sentence break would let it run commands of
    its own (`True. Axiom cheat : False`) in the session and in the kernel's
    certificate."""
    if re.search(r"\.(\s|$)", statement.strip()) or "(*" in statement:
        raise ValueError("a statement is one term: no sentence-ending '.' and no comments")


def open_session(preamble, statement, backend=None, deadline=30.0):
    check_statement(statement)
    backend = resolve(backend)
    if backend == "petanque":
        from .petanque import PetanqueSession
        return PetanqueSession(preamble, statement, deadline)
    from .coqtop import CoqtopSession
    return CoqtopSession(preamble, statement, deadline)
