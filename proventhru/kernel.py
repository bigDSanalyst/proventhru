"""Position 3: the kernel check that admits a proof to the corpus.

A proof that reached "No more goals." step by step is not yet a proof: the
guard condition on fixpoints, universe constraints and the term built by
opaque tactics are only checked at Qed, and coqc accepts an Admitted proof
or an added axiom with exit 0. So the certificate is compiled from scratch
and every theorem must print "Closed under the global context".

The check is pq-verify's coq_check (pq_verify/core.py), adapted to write the
certificate itself.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

CLOSED = "Closed under the global context"


ACCEPTED, REJECTED, NOT_CHECKED = "accepted", "rejected", "not_checked"


@dataclass
class Certificate:
    """verdict is one of three, and the third is not a failure:
      accepted     the kernel checked the proof and it rests on nothing
      rejected     the kernel checked it and refused it (or it uses an axiom)
      not_checked  nothing was decided: the compiler is missing or timed out
    """
    verdict: str
    detail: str
    source: str

    @property
    def ok(self):
        return self.verdict == ACCEPTED

    @property
    def sha256(self):
        return hashlib.sha256(self.source.encode()).hexdigest()


def certificate_source(preamble, statement, tactics, name="pt_goal"):
    body = "\n".join(t.strip() for t in tactics)
    return (f"{preamble.strip()}\n\nTheorem {name} : {statement}.\nProof.\n"
            f"{body}\nQed.\nPrint Assumptions {name}.\n")


def certify(preamble, statement, tactics, name="pt_goal", timeout=300, compiler=None):
    """Compile the proof from scratch. accepted requires exit 0 and no axioms.
    compiler is the argv prefix that compiles a .v file (the session's own,
    so the proof is checked by the Rocq that found it); default coqc."""
    src = certificate_source(preamble, statement, tactics, name)
    if compiler is None:
        coqc = shutil.which("coqc")
        if coqc is None:
            return Certificate(NOT_CHECKED, "coqc not in PATH", src)
        compiler = [coqc]
    with tempfile.TemporaryDirectory(prefix="proventhru-") as work:
        path = os.path.join(work, "Cert.v")
        with open(path, "w") as fh:
            fh.write(src)
        try:
            proc = subprocess.run([*compiler, path], capture_output=True, text=True,
                                  timeout=timeout, cwd=work)
        except subprocess.TimeoutExpired:
            return Certificate(NOT_CHECKED, f"compiler timed out after {timeout}s", src)
        except OSError as e:
            return Certificate(NOT_CHECKED, f"compiler did not run: {e}", src)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return Certificate(REJECTED, out.strip()[-400:], src)
    if CLOSED not in out:
        return Certificate(REJECTED, "proof rests on an axiom or an Admitted proof:\n"
                           + out.strip()[-400:], src)
    return Certificate(ACCEPTED, "kernel accepted; closed under the global context", src)
