"""The run record: one append-only, hash-chained JSON-lines file.

Every trajectory and every corpus entry is a view of this file, so it is the
one thing that cannot change shape later: see SCHEMA.md for every field. The
chain is Dharmapala's run-record pattern (runs.py): canonical JSON, each
entry's hash covers every other field including the previous entry's hash, so
an edit, a deletion from the middle or a reordering breaks it.

Nothing is ever rewritten. A correction is a new `annotation` entry naming the
seq and hash of the entry it is about ("unsound: kernel bug in rocq-9.1.0",
"superseded by seq 812"). Views apply annotations; the entries stay as they
were, so the record of what was believed, and when, survives the correction.

Kinds, in the order an episode writes them:

  episode     opens one statement's attempt: environment, preamble, gate, policy
  proposal    a policy call: candidates for one node, with the model and its cost
  step        one tactic in the session: session outcome, kernel verdict, path
  outcome     closes the episode: standing, proof, kernel verdict
  annotation  a later statement about an earlier entry
"""
import hashlib
import json
import os
import threading
import time
import uuid

FORMAT = "proventhru-record/v1"
GENESIS = "0" * 64
KINDS = ("episode", "proposal", "step", "outcome", "annotation")
SESSION_OUTCOMES = ("ok", "error", "refused", "timeout")
KERNEL_VERDICTS = ("accepted", "rejected", "not_checked")
STANDINGS = ("proved", "refuted", "open", "rejected")
LABELS = ("unsound", "superseded", "retracted", "note")
PHASE_FIELDS = ("regime", "distance", "signature", "digest")


class RecordError(ValueError):
    pass


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def entry_hash(e):
    return sha256(canon({k: v for k, v in e.items() if k != "hash"}))


def _roundtrip(obj):
    # What is read back is what is hashed: tuples become lists.
    return json.loads(json.dumps(obj))


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load(path):
    entries = []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except ValueError as e:
                raise RecordError(f"{path}:{n}: not JSON ({e})") from None
    return entries


class RecordLog:
    """Appends entries to `path`, continuing the chain already there. Refuses
    to append to a file whose chain does not verify: adding to a broken record
    would bury the break under entries that look sound.

    One writer process per file. Threads in that process may share the log
    (appends are locked); two processes appending to one file would fork the
    chain, which verify() then reports. Parallel runs write separate files."""

    def __init__(self, path):
        self.path = path
        self.entries = load(path) if os.path.exists(path) else []
        self.index = Index()
        problems = verify(self.entries, self.index)
        if problems:
            raise RecordError(f"{path} does not verify; not appending to it: {problems[0]}")
        self._lock = threading.Lock()
        self.start = len(self.entries)

    def append(self, kind, data):
        if kind not in KINDS:
            raise RecordError(f"unknown kind {kind!r}")
        with self._lock:
            e = {"format": FORMAT, "seq": len(self.entries), "kind": kind, "at": _now(),
                 "data": _roundtrip(data),
                 "prev": self.entries[-1]["hash"] if self.entries else GENESIS}
            e["hash"] = entry_hash(e)
            problems = check_entry(e, self.index)
            if problems:
                raise RecordError(f"refusing to write a malformed {kind}: {problems[0]}")
            with open(self.path, "a") as fh:
                fh.write(canon(e) + "\n")
            self.entries.append(e)
            self.index.add(e)
            return e

    def episode(self, statement, preamble, environment, gate=None, policy=None,
                search=None, weights=None):
        return Episode(self, statement, preamble, environment, gate, policy, search, weights)

    def annotate(self, target_seq, label, reason, by="unknown"):
        """A later statement about entry target_seq. The entry is not touched."""
        if not 0 <= target_seq < len(self.entries):
            raise RecordError(f"no entry {target_seq} to annotate")
        t = self.entries[target_seq]
        return self.append("annotation", {"target": {"seq": t["seq"], "hash": t["hash"]},
                                          "label": label, "reason": reason, "by": by})


def observation(obs):
    """An Observation as data: every goal's hypotheses and conclusion."""
    if obs is None:
        return None
    return {"finished": obs.finished, "shelved": obs.shelved, "key": obs.key,
            "goals": [{"hypotheses": list(g.hypotheses), "conclusion": g.conclusion}
                      for g in obs.goals]}


def no_phase():
    """oscillate's reading, absent until it runs. The fields exist now so a
    later reading is a value in a known place, not a new schema."""
    return {k: None for k in PHASE_FIELDS}


class Episode:
    """One statement's attempt, written as it happens."""

    def __init__(self, log, statement, preamble, environment, gate, policy, search, weights):
        self.log = log
        self.id = uuid.uuid4().hex
        e = log.append("episode", {
            "episode": self.id, "statement": statement, "preamble": preamble,
            "preamble_sha256": sha256(preamble), "environment": environment,
            "gate": gate, "policy": policy, "search": search, "weights": weights})
        self.seq = e["seq"]

    def proposal(self, path, policy, candidates, cost=None):
        e = self.log.append("proposal", {
            "episode": self.id, "path": list(path), "policy": policy,
            "candidates": [[t, s] for t, s in candidates], "cost": cost})
        return e["seq"]

    def step(self, st, proposal=None, phase=None):
        """st is an env.Step. path is the full tactic path to the node it ran
        from, so any step replays from the statement alone."""
        cert = st.certificate
        e = self.log.append("step", {
            "episode": self.id, "proposal": proposal,
            "path": list(st.parent), "tactic": st.tactic,
            "session": {"outcome": st.outcome, "error": st.error,
                        "finished": bool(st.signals.get("finished")),
                        "goals_before": st.signals.get("goals_before"),
                        "goals_after": st.signals.get("goals_after"),
                        "size_before": st.signals.get("size_before"),
                        "size_after": st.signals.get("size_after"),
                        "hyps_before": st.signals.get("hyps_before"),
                        "hyps_after": st.signals.get("hyps_after"),
                        "revisit": bool(st.signals.get("revisit")),
                        "observation": observation(st.node.obs if st.node else None)},
            "kernel": None if cert is None else {
                "verdict": cert.verdict, "detail": cert.detail,
                "certificate_sha256": cert.sha256},
            "reward": st.reward,
            "cost": {"prover_ms": round(st.prover_ms, 3), "kernel_ms": round(st.kernel_ms, 3)},
            "phase": phase or no_phase()})
        return e["seq"]

    def outcome(self, standing, proof=(), kernel=None, certificate_sha256=None, stats=None):
        e = self.log.append("outcome", {
            "episode": self.id, "standing": standing, "proof": list(proof),
            "kernel": kernel, "certificate_sha256": certificate_sha256, "stats": stats or {}})
        return e["seq"]


# ---------------------------------------------------------------- verification

class Index:
    """What later entries are checked against, kept up to date one entry at
    a time so verifying a record is linear in its length."""

    def __init__(self):
        self.hashes = []          # seq -> hash
        self.kinds = []           # seq -> kind
        self.opened = set()       # episode ids
        self.closed = set()
        self.proposals = {}       # seq -> episode id

    def add(self, e):
        d = e.get("data") or {}
        self.hashes.append(e.get("hash"))
        self.kinds.append(e.get("kind"))
        if e.get("kind") == "episode":
            self.opened.add(d.get("episode"))
        elif e.get("kind") == "outcome":
            self.closed.add(d.get("episode"))
        elif e.get("kind") == "proposal":
            self.proposals[e.get("seq")] = d.get("episode")


def check_entry(e, ix):
    """Problems with entry e given the index of the entries before it; [] if it holds."""
    p = []
    d = e.get("data")
    if not isinstance(d, dict):
        return ["data is not an object"]
    kind = e.get("kind")
    if kind in ("proposal", "step", "outcome"):
        if d.get("episode") not in ix.opened:
            p.append(f"{kind} names episode {d.get('episode')!r}, which no earlier entry opened")
        if d.get("episode") in ix.closed:
            p.append(f"{kind} for episode {d.get('episode')!r} after its outcome")
    if kind == "episode":
        for k in ("episode", "statement", "preamble", "preamble_sha256", "environment"):
            if k not in d:
                p.append(f"episode lacks {k}")
        env = d.get("environment") or {}
        if not env.get("backend") or not env.get("prover"):
            p.append("episode environment must name backend and prover")
        if d.get("preamble_sha256") != sha256(d.get("preamble", "")):
            p.append("preamble_sha256 does not match the preamble")
        if d.get("episode") in ix.opened:
            p.append(f"episode id {d.get('episode')!r} opened twice")
    if kind == "step":
        s = d.get("session") or {}
        if s.get("outcome") not in SESSION_OUTCOMES:
            p.append(f"session outcome {s.get('outcome')!r} not one of {SESSION_OUTCOMES}")
        k = d.get("kernel")
        if k is not None:
            if k.get("verdict") not in KERNEL_VERDICTS:
                p.append(f"kernel verdict {k.get('verdict')!r} not one of {KERNEL_VERDICTS}")
            if not s.get("finished"):
                p.append("a kernel verdict on a step that did not finish the proof")
        if set(d.get("phase") or {}) != set(PHASE_FIELDS):
            p.append(f"phase must have exactly {PHASE_FIELDS}")
        if not isinstance(d.get("path"), list) or not isinstance(d.get("tactic"), str):
            p.append("step needs its full path and its tactic")
        prop = d.get("proposal")
        if prop is not None and ix.proposals.get(prop) != d.get("episode"):
            p.append(f"step names proposal {prop}, not an earlier proposal of its episode")
    if kind == "outcome":
        if d.get("standing") not in STANDINGS:
            p.append(f"standing {d.get('standing')!r} not one of {STANDINGS}")
        if d.get("kernel") not in KERNEL_VERDICTS + (None,):
            p.append(f"outcome kernel {d.get('kernel')!r} not one of {KERNEL_VERDICTS}")
        if d.get("standing") in ("proved", "refuted") and d.get("kernel") != "accepted":
            p.append(f"{d.get('standing')} requires the kernel to have accepted")
    if kind == "annotation":
        t = d.get("target") or {}
        seq = t.get("seq")
        if not (isinstance(seq, int) and 0 <= seq < len(ix.hashes)):
            p.append(f"annotation targets seq {seq}, which is not an earlier entry")
        elif ix.hashes[seq] != t.get("hash"):
            p.append(f"annotation targets seq {seq} with a hash that is not that entry's")
        if d.get("label") not in LABELS:
            p.append(f"annotation label {d.get('label')!r} not one of {LABELS}")
        if not d.get("reason"):
            p.append("annotation without a reason")
    return p


def verify(entries, index=None):
    """Problems found in the entries; [] means the record holds: the chain is
    intact (nothing edited, dropped from the middle or reordered) and every
    entry is well formed against the entries before it. Pass an Index to
    have it filled as a side effect."""
    problems, prev = [], GENESIS
    ix = index if index is not None else Index()
    for i, e in enumerate(entries):
        tag = f"entry {i}"
        if not isinstance(e, dict) or e.get("format") != FORMAT:
            problems.append(f"{tag}: not a {FORMAT} entry")
            ix.add({})
            continue
        if e.get("seq") != i:
            problems.append(f"{tag}: out of sequence (seq {e.get('seq')})")
        if e.get("prev") != prev:
            problems.append(f"{tag}: chain broken (does not follow the entry before it)")
        if e.get("hash") != entry_hash(e):
            problems.append(f"{tag}: edited (its hash does not match it)")
        if e.get("kind") not in KINDS:
            problems.append(f"{tag}: unknown kind {e.get('kind')!r}")
        else:
            problems += [f"{tag}: {m}" for m in check_entry(e, ix)]
        ix.add(e)
        prev = e.get("hash")
    return problems


def head(entries):
    """(size, hash of the last entry): what to timestamp or sign to commit to
    the whole record as it stands."""
    return len(entries), entries[-1]["hash"] if entries else GENESIS


# ----------------------------------------------------------------------- views

def annotations(entries):
    """{seq: [annotation data, ...]} for every annotated entry."""
    out = {}
    for e in entries:
        if e.get("kind") == "annotation":
            out.setdefault(e["data"]["target"]["seq"], []).append(dict(e["data"], seq=e["seq"]))
    return out


def corpus(entries):
    """One row per episode with its standing as of now: an outcome annotated
    unsound or retracted no longer counts as proved or refuted, and says why.
    The annotated entry itself is unchanged."""
    notes = annotations(entries)
    eps = {}
    for e in entries:
        d = e["data"]
        if e["kind"] == "episode":
            eps[d["episode"]] = {"episode": d["episode"], "statement": d["statement"],
                                 "preamble_sha256": d["preamble_sha256"],
                                 "environment": d["environment"],
                                 "gate": (d.get("gate") or {}).get("status"),
                                 "standing": None, "proof": [], "kernel": None,
                                 "opened": e["seq"], "closed": None, "annotations": []}
        elif e["kind"] == "outcome":
            row = eps[d["episode"]]
            row.update(standing=d["standing"], proof=d["proof"], kernel=d["kernel"],
                       closed=e["seq"])
            for a in notes.get(e["seq"], []) + notes.get(row["opened"], []):
                row["annotations"].append({k: a[k] for k in ("seq", "label", "reason", "by")})
                if a["label"] in ("unsound", "retracted") and row["standing"] in ("proved", "refuted"):
                    row["standing"] = "withdrawn"
    return list(eps.values())


def steps(entries, episode=None):
    """The step entries' data, in order, optionally for one episode."""
    return [e["data"] for e in entries
            if e["kind"] == "step" and (episode is None or e["data"]["episode"] == episode)]
