"""A learned ranker for retrieval's lemma slots (docs/rsi-target1-ranker.md).

B offers the top 6 of Coq's Search list, ranked by how many of the goal's
terms a lemma mentions. Search tries every candidate of an expanded node,
so the order of a node's candidates hardly matters; which lemmas fill the
slots does. The ranker scores every lemma Search returns and the policy
offers the 6 best, with B's forms and B's scores, so nothing else changes.

The unit is a (node, lemma) pair at a node on a kernel-accepted proof. The
features are fixed by the pre-registration; the model is L2-regularized
logistic regression fitted by Newton's method, nothing else."""
import hashlib
import json
import math
import re

import numpy as np

from .retrieval import RetrievalPolicy, mentions, terms

VERSION = "lemma-ranker/v1"
FEATURES = ["cov_share", "cov_all", "back_share", "back_all", "is_eq", "rel_match",
            "premises", "log_len", "head_match", "log_rank", "nat_name", "prior"]
PRIOR_M = 5.0          # m-estimate weight: (pos + m g) / (n + m)
FOLDS = 5


def _split_top(text, sep):
    """Index of the first occurrence of sep at parenthesis depth 0, or -1."""
    depth, i = 0, 0
    while i < len(text):
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and text.startswith(sep, i):
            return i
        i += 1
    return -1


def conclusion(stmt):
    """A statement without its leading binders and premises."""
    s = " ".join(stmt.split())
    while s.startswith("forall "):
        k = _split_top(s, ", ")
        if k < 0:
            break
        s = s[k + 2:]
    while True:
        k = _split_top(s, " -> ")
        if k < 0:
            return s
        s = s[k + 4:]


def premises(stmt):
    s = " ".join(stmt.split())
    n = 0
    while True:
        while s.startswith("forall "):
            k = _split_top(s, ", ")
            if k < 0:
                return n
            s = s[k + 2:]
        k = _split_top(s, " -> ")
        if k < 0:
            return n
        n, s = n + 1, s[k + 4:]


RELATIONS = [(" <-> ", "iff"), (" = ", "eq"), (" <= ", "le"), (" < ", "lt"),
             (" >= ", "ge"), (" > ", "gt"), (" <> ", "ne")]
INFIX = ["++", "::", "+", "-", "*", "^"]      # lowest precedence first


def relation(concl):
    """(relation, left side, right side) of a conclusion, split at depth 0."""
    for sep, name in RELATIONS:
        k = _split_top(concl, sep)
        if k >= 0:
            return name, concl[:k], concl[k + len(sep):]
    return "other", concl, ""


def _wrapped(t):
    """Whether t is one parenthesized term: its first ( closes at the end."""
    if not t.startswith("("):
        return False
    depth = 0
    for i, c in enumerate(t):
        depth += c == "("
        depth -= c == ")"
        if depth == 0:
            return i == len(t) - 1
    return False


def head(side):
    """The head symbol of a term: its lowest-precedence infix operator at
    depth 0 if it has one, else the function it applies."""
    t = side.strip()
    while _wrapped(t):
        t = t[1:-1].strip()
    for op in INFIX:
        if _split_top(t, f" {op} ") >= 0:
            return op
    m = re.match(r"[A-Za-z_][A-Za-z0-9_'.]*", t)
    return m.group(0) if m else None


def heads(concl):
    _, lhs, rhs = relation(concl)
    return {h for h in (head(lhs), head(rhs) if rhs else None) if h}


def features(goal_concl, goal_hyps, name, stmt, position, prior):
    """The pre-registered features of lemma (name, stmt) at a goal; position
    is the lemma's index in B's order, prior its usage prior."""
    gt = terms(goal_concl, goal_hyps)
    covered = sum(mentions(stmt, t) for t in gt)
    lt = set(terms(stmt))
    back = len(lt & set(gt))
    lc = conclusion(stmt)
    lrel = relation(lc)[0]
    grel = relation(" ".join(goal_concl.split()))[0]
    return {
        "cov_share": covered / len(gt) if gt else 0.0,
        "cov_all": float(bool(gt) and covered == len(gt)),
        "back_share": back / len(lt) if lt else 0.0,
        "back_all": float(bool(lt) and back == len(lt)),
        "is_eq": float(lrel == "eq"),
        "rel_match": float(lrel == grel),
        "premises": float(min(premises(stmt), 3)),
        "log_len": math.log(max(len(stmt), 1)),
        "head_match": float(bool(heads(lc) & heads(" ".join(goal_concl.split())))),
        "log_rank": math.log(1 + position),
        "nat_name": float(name.startswith("Nat.")),
        "prior": prior,
    }


def fold_of(statement):
    return int(hashlib.sha256(statement.encode()).hexdigest(), 16) % FOLDS


def priors(rows):
    """{name: (positives, labelled)} and the global rate, over rows."""
    table, pos, n = {}, 0, 0
    for r in rows:
        p, k = table.get(r["lemma"], (0, 0))
        table[r["lemma"]] = (p + r["label"], k + 1)
        pos, n = pos + r["label"], n + 1
    return table, (pos / n if n else 0.0)


def prior_of(table, rate, name):
    p, k = table.get(name, (0, 0))
    return (p + PRIOR_M * rate) / (k + PRIOR_M)


def design(rows):
    """Feature matrix for training rows, with the usage prior out of fold:
    a row's prior comes from rows of the other folds (by statement)."""
    by_fold = {f: priors([r for r in rows if fold_of(r["statement"]) != f])
               for f in range(FOLDS)}
    X = []
    for r in rows:
        table, rate = by_fold[fold_of(r["statement"])]
        f = dict(r["features"], prior=prior_of(table, rate, r["lemma"]))
        X.append([f[k] for k in FEATURES])
    return np.array(X, dtype=float), np.array([r["label"] for r in rows], dtype=float)


def fit(X, y, max_iter=100, tol=1e-8):
    """L2-regularized logistic regression, penalty 1/2 |w|^2 on standardized
    features, the intercept unpenalized, by Newton's method."""
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    w = np.zeros(Z.shape[1])
    reg = np.ones(Z.shape[1])
    reg[0] = 0.0
    for it in range(max_iter):
        p = 1.0 / (1.0 + np.exp(-(Z @ w)))
        g = Z.T @ (p - y) + reg * w
        if np.linalg.norm(g) < tol:
            break
        H = (Z * (p * (1 - p))[:, None]).T @ Z + np.diag(reg)
        w = w - np.linalg.solve(H, g)
    return {"mean": mu.tolist(), "sd": sd.tolist(), "intercept": float(w[0]),
            "weights": w[1:].tolist(), "iterations": it + 1,
            "gradient_norm": float(np.linalg.norm(g))}


class Ranker:
    def __init__(self, model):
        self.model = model
        self.mu = np.array(model["mean"])
        self.sd = np.array(model["sd"])
        self.w = np.array(model["weights"])
        self.b = model["intercept"]
        self.table = {k: tuple(v) for k, v in model["prior_table"].items()}
        self.rate = model["prior_rate"]

    @classmethod
    def train(cls, rows, sources):
        X, y = design(rows)
        model = fit(X, y)
        table, rate = priors(rows)
        model.update(version=VERSION, features=FEATURES, prior_m=PRIOR_M,
                     prior_table={k: list(v) for k, v in sorted(table.items())},
                     prior_rate=rate, rows=len(rows), positives=int(y.sum()),
                     sources=sources)
        return cls(model)

    @classmethod
    def load(cls, path):
        with open(path) as fh:
            return cls(json.load(fh))

    def dump(self, path):
        with open(path, "w") as fh:
            fh.write(self.text())

    def text(self):
        return json.dumps(self.model, sort_keys=True, indent=1) + "\n"

    @property
    def sha256(self):
        return hashlib.sha256(self.text().encode()).hexdigest()

    def scores(self, goal, found):
        """Probability for each (name, stmt) of found, in found's order."""
        rows = []
        for i, (name, stmt) in enumerate(found):
            f = features(goal.conclusion, goal.hypotheses, name, stmt, i,
                         prior_of(self.table, self.rate, name))
            rows.append([f[k] for k in FEATURES])
        if not rows:
            return []
        z = ((np.array(rows) - self.mu) / self.sd) @ self.w + self.b
        return (1.0 / (1.0 + np.exp(-z))).tolist()

    def select(self, goal, found, top):
        """The top lemmas by score, ties in found's order, with their
        positions in found."""
        s = self.scores(goal, found)
        order = sorted(range(len(found)), key=lambda i: (-s[i], i))[:top]
        return [found[i] for i in order], order


class RankedRetrievalPolicy(RetrievalPolicy):
    """B with the ranker choosing which lemmas fill the slots."""

    def __init__(self, base, ranker, top=6, score=0.7):
        super().__init__(base, top, score)
        self.ranker = ranker
        rid = ranker.sha256
        self.identity = dict(base.identity, id=f"retrieval/v1+ranker/{rid[:16]}+{base.identity['id']}",
                             retrieval={"top": top, "method": "coq Search on goal terms",
                                        "ranker": {"version": VERSION, "sha256": rid}})

    def select(self, goal, found):
        picked, positions = self.ranker.select(goal, found, self.top)
        self.picked = {"pool": len(found), "positions": positions}
        return picked

    def propose(self, obs, path, last_failure=None, tried=None):
        self.picked = None
        out = super().propose(obs, path, last_failure, tried)
        if self.picked is not None:
            self.last_cost["ranker"] = self.picked
        return out
