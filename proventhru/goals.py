"""Parse coqtop's goal display into an observation.

coqtop prints the first goal in full (hypotheses and conclusion) and every
other goal by its conclusion only:

    2 goals (ID 7)
      n : nat
      ============================
      0 + 0 = 0

    goal 2 (ID 10) is:
     S n + 0 = S n

So an observation carries the hypotheses of the focused goal and the
conclusions of all of them. Printing width is set to 1000 in Coqtop, so no
hypothesis or conclusion wraps.
"""
import hashlib
import re
from dataclasses import dataclass, field

HEAD = re.compile(r"^(\d+) (?:focused )?goals?(?: \(shelved: (\d+)\))?(?: \(ID (\d+)\))?", re.M)
OTHER = re.compile(r"^goal (\d+) \(ID (\d+)\) is:\n(.*?)(?=\n\s*\n|\ngoal \d+ |\Z)", re.M | re.S)
RULE = re.compile(r"^\s*=+\s*$", re.M)


@dataclass(frozen=True)
class Goal:
    id: int
    conclusion: str
    hypotheses: tuple = ()


@dataclass(frozen=True)
class Observation:
    goals: tuple = ()
    shelved: int = 0
    finished: bool = False
    raw: str = field(default="", compare=False)

    @property
    def key(self):
        """Hash of what the agent can see: equal keys are the same state, so a
        search treats a revisit as a loop."""
        body = repr([(g.hypotheses, g.conclusion) for g in self.goals]) + str(self.shelved)
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    @property
    def size(self):
        """Total characters across the conclusions: a crude complexity measure."""
        return sum(len(g.conclusion) for g in self.goals)

    def text(self):
        if self.finished:
            return "No more goals."
        out = []
        for i, g in enumerate(self.goals, 1):
            out.append(f"Goal {i}:")
            out += [f"  {h}" for h in g.hypotheses]
            out.append("  ----")
            out.append(f"  {g.conclusion}")
        if self.shelved:
            out.append(f"({self.shelved} shelved)")
        return "\n".join(out)


def parse(text):
    if "No more goals." in text:
        return Observation(finished=True, raw=text)
    goals = []
    shelved = 0
    head = HEAD.search(text)
    rule = RULE.search(text)
    if head and rule and rule.start() > head.end():
        shelved = int(head.group(2) or 0)
        hyps = [ln.strip() for ln in text[head.end():rule.start()].splitlines() if ln.strip()]
        rest = text[rule.end():]
        concl = rest.split("\n\n")[0].strip()
        goals.append(Goal(int(head.group(3) or 0), " ".join(concl.split()), tuple(hyps)))
    for m in OTHER.finditer(text):
        goals.append(Goal(int(m.group(2)), " ".join(m.group(3).split())))
    if not goals and "remaining goals are on the shelf" in text:
        shelved = max(shelved, 1)
    return Observation(tuple(goals), shelved, False, text)
