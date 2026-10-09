"""Premise retrieval: library lemmas as candidate actions.

The fixed tactics never name a lemma, so a goal like rev (rev l) = l, which
needs rev_app_distr, is out of reach however long the search runs. Retrieval
asks Coq itself which lemmas mention what the goal mentions and offers them as
`rewrite L`, `rewrite <- L` and `apply L`:

  1. terms: the constants and operators in the first goal's conclusion
     (rev, app, "++", Nat.even, "+" ...), minus bound variables, hypothesis
     names and type names too common to discriminate (nat, list, bool).
  2. Search: `Search t1 t2 ...` with all of them; if that finds nothing,
     each term on its own. Coq's own Search, through the session's query, so
     what is found is exactly what the preamble loaded.
  3. rank: by how many of the goal's terms the lemma's statement mentions,
     equations first (they can be rewritten with), shorter statements first.

Searches are cached per term set: Search reads the global environment, which
does not change during a proof.
"""
import re
import time

from .search import Policy

OPERATORS = ["++", "::", "<=", ">=", "<>", "+", "*", "-", "^", "<", ">"]
NOT_TERMS = {"forall", "exists", "fun", "match", "with", "end", "let", "in", "if",
             "then", "else", "Type", "Prop", "Set", "nat", "list", "bool", "option",
             "True", "False", "as", "return"}
# Generated eliminators, and names a library marks as internal
# (Nat.PrivateImplementsBitwiseSpec.*), are not lemmas to cite.
GENERATED = re.compile(r"_(ind|rec|rect|sind|ind_dep|rec_dep|rect_dep)$")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_'.]*")


def bound_names(text):
    """Names bound by forall / exists / fun binders in text."""
    out = set()
    for m in re.finditer(r"\b(?:forall|exists|fun)\b(.*?)(?:,|=>)", text):
        for g in re.finditer(r"\(([^():]*):", m.group(1)):
            out.update(g.group(1).split())
        head = m.group(1).split(":")[0] if "(" not in m.group(1) else ""
        out.update(head.split())
    return out


def terms(conclusion, hypotheses=()):
    """The constants and operators of a goal, in order of appearance."""
    skip = set(NOT_TERMS) | bound_names(conclusion)
    for h in hypotheses:
        skip.update(n.strip() for n in h.split(" : ")[0].split(","))
    found = []
    for t in IDENT.findall(conclusion):
        t = t.rstrip(".")
        if t in skip or len(t) == 1 or t.isdigit() or t in found:
            continue
        found.append(t)
    spaced = f" {conclusion} "
    for op in OPERATORS:
        if f" {op} " in spaced and f'"{op}"' not in found:
            found.append(f'"{op}"')
            spaced = spaced.replace(f" {op} ", " ")
    return found


def parse(output):
    """Search output -> [(name, statement)]. An entry starts at column 0 with
    'name:'; Petanque wraps long statements onto indented lines."""
    entries, cur = [], None
    for line in output.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_'.]*):\s*(.*)$", line)
        if m:
            cur = [m.group(1), m.group(2)]
            entries.append(cur)
        elif cur is not None and line.startswith(" "):
            cur[1] += " " + line.strip()
    return [(n, " ".join(s.split())) for n, s in entries
            if not GENERATED.search(n) and ".Private" not in n]


def mentions(statement, term):
    if term.startswith('"'):
        return f" {term.strip(chr(34))} " in f" {statement} "
    return re.search(rf"(?<![\w.']){re.escape(term)}(?![\w'])", statement) is not None


def rank(found, goal_terms):
    def key(entry):
        name, stmt = entry
        covered = sum(mentions(stmt, t) for t in goal_terms)
        return (-covered, " = " not in stmt, len(stmt), name)
    return sorted(found, key=key)


class Retriever:
    """Searches through a session's query, caching per term set."""

    def __init__(self):
        self.cache = {}
        self.ms = 0.0

    def lemmas(self, session, goal_terms):
        key = tuple(goal_terms)
        if key in self.cache:
            return self.cache[key]
        t0 = time.perf_counter()
        found = []
        if goal_terms:
            found = self._search(session, goal_terms)
            if not found:
                seen = set()
                for t in goal_terms:
                    for e in self._search(session, [t]):
                        if e[0] not in seen:
                            seen.add(e[0])
                            found.append(e)
        self.ms += (time.perf_counter() - t0) * 1000
        self.cache[key] = rank(found, goal_terms)
        return self.cache[key]

    @staticmethod
    def _search(session, ts):
        try:
            return parse(session.query(session.root, "Search " + " ".join(ts) + "."))
        except Exception:
            return []


class RetrievalPolicy(Policy):
    """A base policy's candidates, then up to `top` library lemmas for the
    first goal, each as rewrite / rewrite <- (equations) and apply."""

    def __init__(self, base, top=6, score=0.7):
        self.base, self.top, self.score = base, top, score
        self.retriever = Retriever()
        self.env = None
        self.identity = dict(base.identity, id=f"retrieval/v1+{base.identity['id']}",
                             retrieval={"top": top, "method": "coq Search on goal terms"})
        self.last_cost = None

    def bind(self, env):
        """Called by search with the environment it runs in."""
        self.env = env
        if hasattr(self.base, "bind"):
            self.base.bind(env)

    @property
    def reexpand(self):
        return getattr(self.base, "reexpand", 0)

    def propose(self, obs, path, last_failure=None, tried=None):
        out = list(self.base.propose(obs, path, last_failure, tried=tried) if tried is not None
                   else self.base.propose(obs, path, last_failure))
        ms0 = self.retriever.ms
        lemmas = []
        if obs.goals and self.env is not None and self.env.session is not None:
            g = obs.goals[0]
            lemmas = self.retriever.lemmas(self.env.session,
                                           terms(g.conclusion, g.hypotheses))[: self.top]
        have = {t for t, _ in out}
        added = []
        for i, (name, stmt) in enumerate(lemmas):
            s = self.score - 0.01 * i
            forms = ([f"rewrite {name}.", f"rewrite <- {name}."] if " = " in stmt else [])
            forms.append(f"apply {name}.")
            for t in forms:
                if t not in have:
                    have.add(t)
                    out.append((t, s))
                    added.append(t)
        cost = dict(self.base.last_cost or {})
        # added: the candidates retrieval contributed, so a report can tell the
        # base policy's choices (a model's) from the lemmas appended to them.
        cost.update(retrieval_ms=round(self.retriever.ms - ms0, 1),
                    lemmas=[n for n, _ in lemmas], added=added)
        self.last_cost = cost
        return out


def library_closers(session, conclusion, hypotheses=(), top=8, per_term=4):
    """Candidates that close a goal with one library lemma: what the gate tries
    before calling a statement open. `intros; apply L` covers a lemma that
    quantifies in another order (firstn_skipn is stated forall n l).

    The lemmas are the best `top` that mention all the goal's terms, then the
    best `per_term` for each term alone: an instance of a library lemma
    (rev (rev (filter f l)) = filter f l is rev_involutive) mentions terms the
    lemma does not, so the joint search misses it."""
    r = Retriever()
    ts = terms(conclusion, hypotheses)
    names = [n for n, _ in r.lemmas(session, ts)[:top]]
    for t in ts:
        for n, _ in r.lemmas(session, [t])[:per_term]:
            if n not in names:
                names.append(n)
    return [f"{form} {name}." for name in names
            for form in ("exact", "apply", "intros; apply")]
