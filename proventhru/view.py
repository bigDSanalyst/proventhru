"""The policy's view of a proof state: everything a model is shown, in one format.

This is the whole of a model-backed policy's world, so it is fixed here, once:

    {
      "goal_count": 2,
      "shelved": 0,
      "given_up": false,
      "goals": [
        {"type": "0 + 0 = 0", "hypotheses": []},
        {"type": "S n + 0 = S n",
         "hypotheses": [{"name": "n", "type": "nat"},
                        {"name": "IHn", "type": "n + 0 = n"}]}
      ],
      "path": ["intros n.", "induction n."],
      "last_failure": {"path": [...], "tactic": "lia.", "outcome": "error",
                       "error": "<the exact string Coq returned>"}
    }

- goals: every goal with its own hypotheses. The coqtop backend prints only the
  focused goal's hypotheses, so its other goals arrive with an empty list; the
  Petanque backend fills them all.
- hypotheses: "n, m : nat" becomes two entries; "x := 3 : nat" keeps its body
  in the type ("3 : nat" -> {"name": "x", "type": "nat", "value": "3"}).
- given_up: always false, because the guard refuses give_up and admit; the
  field is here so the format does not change if that rule ever does.
- last_failure: the most recent attempt in this episode that Coq or the guard
  refused, or that timed out, with Coq's message verbatim, never summarised.
  null until something fails.
"""


def hypotheses(h):
    """'n, m : nat' -> [{'name': 'n', 'type': 'nat'}, {'name': 'm', ...}]."""
    head, sep, ty = h.partition(" : ")
    if not sep:
        return [{"name": h.strip(), "type": ""}]
    value = None
    if " := " in head:
        head, _, value = head.partition(" := ")
    out = []
    for name in head.split(","):
        entry = {"name": name.strip(), "type": ty.strip()}
        if value is not None:
            entry["value"] = value.strip()
        out.append(entry)
    return out


def state(obs, path, last_failure=None):
    """The view of one node: obs is a goals.Observation, path its tactic path."""
    return {
        "goal_count": len(obs.goals),
        "shelved": obs.shelved,
        "given_up": False,
        "goals": [{"type": g.conclusion,
                   "hypotheses": [x for h in g.hypotheses for x in hypotheses(h)]}
                  for g in obs.goals],
        "path": list(path),
        "last_failure": last_failure,
    }
