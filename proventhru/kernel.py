"""Position 3: the kernel check that admits a proof to the corpus.

A proof that reached "No more goals." step by step is not yet a proof: the
guard condition on fixpoints, universe constraints and the term built by
opaque tactics are only checked at Qed, and coqc accepts an Admitted proof
or an added axiom with exit 0. So the certificate is compiled from scratch
and every theorem must print "Closed under the global context".

The check is pq-verify's coq_check (pq_verify/core.py), adapted to write the
certificate itself.
"""
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

CLOSED = "Closed under the global context"


@dataclass
class Certificate:
    ok: bool
    detail: str
    source: str


def certificate_source(preamble, statement, tactics, name="pt_goal"):
    body = "\n".join(t.strip() for t in tactics)
    return (f"{preamble.strip()}\n\nTheorem {name} : {statement}.\nProof.\n"
            f"{body}\nQed.\nPrint Assumptions {name}.\n")


def certify(preamble, statement, tactics, name="pt_goal", timeout=300, compiler=None):
    """Compile the proof from scratch. ok requires exit 0 and no axioms.
    compiler is the argv prefix that compiles a .v file (the session's own,
    so the proof is checked by the Rocq that found it); default coqc."""
    if compiler is None:
        coqc = shutil.which("coqc")
        if coqc is None:
            raise FileNotFoundError("coqc not in PATH")
        compiler = [coqc]
    src = certificate_source(preamble, statement, tactics, name)
    with tempfile.TemporaryDirectory(prefix="proventhru-") as work:
        path = os.path.join(work, "Cert.v")
        with open(path, "w") as fh:
            fh.write(src)
        try:
            proc = subprocess.run([*compiler, path], capture_output=True, text=True,
                                  timeout=timeout, cwd=work)
        except subprocess.TimeoutExpired:
            return Certificate(False, f"coqc timed out after {timeout}s", src)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return Certificate(False, out.strip()[-400:], src)
    if CLOSED not in out:
        return Certificate(False, "proof rests on an axiom or an Admitted proof:\n"
                           + out.strip()[-400:], src)
    return Certificate(True, "kernel accepted; closed under the global context", src)
