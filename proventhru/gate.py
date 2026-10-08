"""Position 1: the formalizability gate on conjectures.

Elaboration only proves a statement is well typed, and `forall n, n = n`
elaborates. So the gate sorts a candidate into one of:

  ill_formed  does not elaborate as a Prop
  refuted     its negation falls to a bounded attempt (a kernel-checked disproof)
  vacuous     its hypotheses are contradictory, so it says nothing
  trivial     a one-line tactic proves it
  open        formal, and survives all of the above: worth attacking

Every attempt is bounded by Coq's Timeout, so `open` means "not settled by the
gate", never "hard". The disproof script for `refuted` is returned so it can
be certified like any proof.
"""
from dataclasses import dataclass

from .env import DEFAULT_PREAMBLE
from .kernel import certify
from .session import CoqTimeout, TacticError, check_statement, open_session

TRIVIAL = ("reflexivity.", "intros; reflexivity.", "auto.", "intros; lia.",
           "intros; congruence.", "intuition.", "tauto.", "intros; discriminate.")
CONTRADICTION = ("intros; exfalso; solve [lia | congruence | discriminate | auto | intuition].",)
COUNTER_CLOSERS = "solve [lia | discriminate | congruence | intuition | (simpl in H; lia) | (simpl in H; discriminate)]"


def counterexample_tactics(values=range(5)):
    """For ~P with P = forall (x y ... : nat), Q: instantiate every leading
    nat quantifier with the same small value and close the contradiction."""
    for k in values:
        yield ("intro H; repeat match type of H with forall _ : nat, _ => "
               f"specialize (H {k}) end; {COUNTER_CLOSERS}.")


@dataclass
class GateResult:
    status: str
    detail: str = ""
    script: tuple = ()        # the closing tactic(s) for trivial / refuted
    kernel: str = None        # refuted: accepted | rejected | not_checked

    def record(self):
        return {"status": self.status, "detail": self.detail,
                "script": list(self.script), "kernel": self.kernel}


def _first_closing(session, tactics, timeout):
    for tac in tactics:
        try:
            _, obs = session.run(session.root, tac, timeout)
        except (TacticError, CoqTimeout):
            continue
        if obs.finished:
            return tac
    return None


def elaborates(statement, preamble=DEFAULT_PREAMBLE, backend=None):
    try:
        check_statement(statement)
    except ValueError as e:
        return False, str(e)
    s = open_session(preamble, "True", backend)
    try:
        s.query(s.root, f"Check ({statement} : Prop).")
        return True, ""
    except TacticError as e:
        return False, str(e)
    finally:
        s.close()


def classify(statement, preamble=DEFAULT_PREAMBLE, timeout=2, certify_disproof=True,
             backend=None):
    ok, detail = elaborates(statement, preamble, backend)
    if not ok:
        return GateResult("ill_formed", detail)

    neg = open_session(preamble, f"~ ({statement})", backend)
    try:
        tac = _first_closing(neg, counterexample_tactics(), timeout)
        compiler = neg.compiler
    finally:
        neg.close()
    if tac:
        kern = None
        if certify_disproof:
            kern = certify(preamble, f"~ ({statement})", [tac], compiler=compiler).verdict
        return GateResult("refuted", "negation proved by a small instance", (tac,), kern)

    pos = open_session(preamble, statement, backend)
    try:
        tac = _first_closing(pos, CONTRADICTION, timeout)
        if tac:
            return GateResult("vacuous", "hypotheses are contradictory", (tac,))
        tac = _first_closing(pos, TRIVIAL, timeout)
        if tac:
            return GateResult("trivial", "closed by one tactic", (tac,))
    finally:
        pos.close()
    return GateResult("open", "formal; not settled by the gate")
