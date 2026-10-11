"""Conjecture generation over stdlib nat and list nat functions.

The enumerator behind tools/make_eval.py (the held-out set) and the
exploration loop (explore.py): terms over a fixed signature are enumerated
by size, QuickSpec style. Each term is evaluated on a fixed vector of random
inputs, terms with the same values form a class, and only each class's
smallest member is used to build bigger terms. Two members of a class give a
candidate equation; two classes ordered on every input give a candidate
inequality. holds() re-tests a candidate on fresh inputs.

A candidate that holds on every test is plausible, not true: the gate's
bounded refutation and, for a proof, the kernel are the checks that count.
"""
import itertools
import re
from collections import defaultdict

L, N = "list nat", "nat"
VARS = {"l1": L, "l2": L, "n": N, "m": N}
RENAME = {"l1": "xs", "l2": "ys", "n": "k", "m": "j"}


def sub(a, b):
    return max(0, a - b)


# name: (argument types, result type, Python meaning, Coq rendering)
OPS = {
    "0": ((), N, lambda: 0, lambda: "0"),
    "nil": ((), L, lambda: (), lambda: "[]"),
    "S": ((N,), N, lambda a: a + 1, lambda a: f"S {a}"),
    "add": ((N, N), N, lambda a, b: a + b, lambda a, b: f"{a} + {b}"),
    "mul": ((N, N), N, lambda a, b: a * b, lambda a, b: f"{a} * {b}"),
    "sub": ((N, N), N, sub, lambda a, b: f"{a} - {b}"),
    "max": ((N, N), N, max, lambda a, b: f"Nat.max {a} {b}"),
    "min": ((N, N), N, min, lambda a, b: f"Nat.min {a} {b}"),
    "length": ((L,), N, len, lambda a: f"length {a}"),
    "sum": ((L,), N, sum, lambda a: f"list_sum {a}"),
    "lmax": ((L,), N, lambda a: max(a, default=0), lambda a: f"list_max {a}"),
    "app": ((L, L), L, lambda a, b: a + b, lambda a, b: f"{a} ++ {b}"),
    "cons": ((N, L), L, lambda a, b: (a,) + b, lambda a, b: f"{a} :: {b}"),
    "rev": ((L,), L, lambda a: a[::-1], lambda a: f"rev {a}"),
    "mapS": ((L,), L, lambda a: tuple(x + 1 for x in a), lambda a: f"map S {a}"),
    "even": ((L,), L, lambda a: tuple(x for x in a if x % 2 == 0),
             lambda a: f"filter Nat.even {a}"),
    "firstn": ((N, L), L, lambda n, a: a[:n], lambda n, a: f"firstn {n} {a}"),
    "skipn": ((N, L), L, lambda n, a: a[n:], lambda n, a: f"skipn {n} {a}"),
    "repeat": ((N, N), L, lambda x, n: (x,) * n, lambda x, n: f"repeat {x} {n}"),
    "seq": ((N, N), L, lambda s, n: tuple(range(s, s + n)), lambda s, n: f"seq {s} {n}"),
    "removelast": ((L,), L, lambda a: a[:-1], lambda a: f"removelast {a}"),
}
# The wider signature, for exploration only: the held-out and dev sets were
# generated from OPS alone, and enumerate_classes() uses OPS unless told
# otherwise, so tools/make_eval.py's output does not change. count_occ stands
# in for In: membership as a number (count_occ l x > 0), since the generator
# builds equations and inequalities between nat and list terms, not Props.
WIDE = {
    "nth": ((N, L), N, lambda n, a: a[n] if n < len(a) else 0, lambda n, a: f"nth {n} {a} 0"),
    "last": ((L,), N, lambda a: a[-1] if a else 0, lambda a: f"last {a} 0"),
    "count": ((L, N), N, lambda a, x: a.count(x),
              lambda a, x: f"count_occ Nat.eq_dec {a} {x}"),
}
ALL_OPS = {**OPS, **WIDE}
INFIX = {"add", "mul", "sub", "app", "cons"}
CAP = 60  # values above this are not compared (repeat/seq/mul blow up)


class Term:
    __slots__ = ("op", "args", "type", "size")

    def __init__(self, op, args=(), type_=None):
        self.op, self.args = op, tuple(args)
        self.type = VARS[op] if op in VARS else ALL_OPS[op][1]
        self.size = 1 + sum(a.size for a in self.args)

    def eval(self, env):
        if self.op in VARS:
            return env[self.op]
        vals = [a.eval(env) for a in self.args]
        if any(v is None for v in vals):
            return None
        out = ALL_OPS[self.op][2](*vals)
        if (isinstance(out, int) and out > CAP) or (isinstance(out, tuple) and len(out) > CAP):
            return None
        return out

    def coq(self, names=None, top=True):
        if self.op in VARS:
            return (names or {}).get(self.op, self.op)
        parts = [a.coq(names, top=False) for a in self.args]
        parts = [p if not a.args else f"({p})" for a, p in zip(self.args, parts)]
        return ALL_OPS[self.op][3](*parts)

    def vars(self):
        if self.op in VARS:
            return {self.op}
        return set().union(*(a.vars() for a in self.args)) if self.args else set()

    def head(self):
        return self.op


def random_env(rng):
    lst = lambda: tuple(rng.randint(0, 5) for _ in range(rng.randint(0, 6)))
    return {"l1": lst(), "l2": lst(), "n": rng.randint(0, 6), "m": rng.randint(0, 6)}


def wide_env(rng):
    """Wider inputs than random_env (values to 100, lists to 12): small
    values let a false bound through (list_max (filter Nat.even l) <=
    S (S (S (S n))) holds while every element is at most 5). For
    exploration; the eval sets were generated with random_env alone."""
    lst = lambda: tuple(rng.randint(0, 100) for _ in range(rng.randint(0, 12)))  # noqa: E731
    return {"l1": lst(), "l2": lst(), "n": rng.randint(0, 100), "m": rng.randint(0, 100)}


EDGE = [{"l1": (), "l2": (), "n": 0, "m": 0}, {"l1": (0,), "l2": (), "n": 1, "m": 0},
        {"l1": (), "l2": (3, 1), "n": 0, "m": 2}, {"l1": (2, 2), "l2": (2,), "n": 2, "m": 2}]


def fingerprint(t, envs):
    vals = tuple(t.eval(e) for e in envs)
    return None if any(v is None for v in vals) else vals


def enumerate_classes(max_size, envs, ops=None):
    """{fingerprint: [terms in size order]}; reps[type][size] = class reps.
    ops: the signature, OPS (the eval sets') unless given."""
    ops = OPS if ops is None else ops
    classes = {}
    reps = {L: defaultdict(list), N: defaultdict(list)}

    def add(t):
        fp = fingerprint(t, envs)
        if fp is None:
            return
        key = (t.type, fp)
        if key in classes:
            classes[key].append(t)
        else:
            classes[key] = [t]
            reps[t.type][t.size].append(t)

    for v in VARS:
        add(Term(v))
    for size in range(1, max_size + 1):
        for op, (args, _, _, _) in ops.items():
            if not args:
                if size == 1:
                    add(Term(op))
                continue
            for split in _splits(size - 1, len(args)):
                pools = [reps[ty][s] for ty, s in zip(args, split)]
                for combo in itertools.product(*pools):
                    add(Term(op, combo))
    return classes


def _splits(total, k):
    if k == 1:
        if total >= 1:
            yield (total,)
        return
    for first in range(1, total):
        for rest in _splits(total - first, k - 1):
            yield (first,) + rest


def holds(lhs, rhs, rel, envs):
    for e in envs:
        a, b = lhs.eval(e), rhs.eval(e)
        if a is None or b is None:
            continue
        if rel == "=" and a != b:
            return False
        if rel == "<=" and not a <= b:
            return False
    return True


def counterexample(lhs, rhs, rel, envs):
    """The first env where the candidate fails, or None."""
    for e in envs:
        a, b = lhs.eval(e), rhs.eval(e)
        if a is None or b is None:
            continue
        if (rel == "=" and a != b) or (rel == "<=" and not a <= b):
            return e
    return None


def small_envs(length=5, alphabet=(0, 1, 2)):
    """Every list of length at most `length` over `alphabet` as l1, against a
    few fixed values of l2, n and m: complete coverage of small lists, where
    random inputs rarely put four zeros in one list."""
    out = []
    for k in range(length + 1):
        for lst in itertools.product(alphabet, repeat=k):
            for l2 in ((), (1, 0), lst[::-1]):
                for n, m in ((0, 0), (2, 1), (1, 3)):
                    out.append({"l1": lst, "l2": l2, "n": n, "m": m})
    return out


def canonical_names(lhs, rhs):
    """Variables renamed in order of first use, so l2 ++ [] = l2 and
    l1 ++ [] = l1 are one candidate."""
    order = [v for v in re.findall(r"\b(l1|l2|n|m)\b", lhs.coq() + " " + rhs.coq())]
    names, count = {}, {L: 0, N: 0}
    for v in order:
        if v not in names:
            names[v] = (["l1", "l2"] if VARS[v] == L else ["n", "m"])[count[VARS[v]]]
            count[VARS[v]] += 1
    return names


def statement(lhs, rhs, rel, names=None):
    order = list(VARS) + list(RENAME.values())
    named = sorted(((names or {}).get(v, v), VARS[v]) for v in lhs.vars() | rhs.vars())
    named.sort(key=lambda p: order.index(p[0]) if p[0] in order else len(order))
    ls = [n for n, ty in named if ty == L]
    ns = [n for n, ty in named if ty == N]
    binders = []
    if ls:
        binders.append(f"({' '.join(ls)} : list nat)")
    if ns:
        binders.append(f"({' '.join(ns)} : nat)")
    return f"forall {' '.join(binders)}, {lhs.coq(names)} {rel} {rhs.coq(names)}"


def constant_list(t):
    """A list subterm with no variable in it ([], rev []): Coq cannot infer
    its element type when nothing else fixes it (skipn n [] = []), and such
    laws are about the constant, not the functions."""
    if t.type == L and not t.vars():
        return True
    return any(constant_list(a) for a in t.args)


def same_context(lhs, rhs):
    """f(a, x) vs f(a, y): an instance of the smaller law about x and y."""
    if lhs.op != rhs.op or not lhs.args:
        return False
    if len(lhs.args) == 1:   # S x <= S y, length x = length y: about x and y
        return True
    return bool({a.coq() for a in lhs.args} & {b.coq() for b in rhs.args})


def candidates(classes, min_size, max_size, congruence="eval"):
    """Candidate (lhs, rhs, rel) from the fingerprints alone; holds() is run
    later, only on what is sampled.

    congruence: how f(x) against f(y) is treated. "eval" (the held-out and
    dev sets were made this way) drops every such pair as an instance of a
    smaller law about x and y. "exact" (exploration) drops it only when x and
    y are in one class, so the pair really follows by congruence: for lists
    there is often no smaller law (removelast l against l), and "eval" drops
    every monotonicity lemma, list_max (removelast l) <= list_max l."""
    out = []
    fp = {}
    for (ty, f), members in classes.items():
        for m in members:
            fp[m.coq()] = (ty, f)

    def congruent(lhs, rhs):
        if congruence == "eval":
            return same_context(lhs, rhs)
        if lhs.op != rhs.op or not lhs.args:
            return False
        diff = [(a, b) for a, b in zip(lhs.args, rhs.args) if a.coq() != b.coq()]
        return len(diff) == 1 and fp.get(diff[0][0].coq()) is not None \
            and fp.get(diff[0][0].coq()) == fp.get(diff[0][1].coq())

    def ok_shape(lhs, rhs):
        both = lhs.vars() | rhs.vars()
        return (any(VARS[v] == L for v in both) and min_size <= lhs.size + rhs.size <= max_size
                and lhs.args and lhs.vars() and not congruent(lhs, rhs)
                and not constant_list(lhs) and not constant_list(rhs))

    for (ty, _), members in classes.items():
        rep = members[0]
        for other in members[1:]:
            if ok_shape(other, rep):  # the bigger side on the left, the simpler on the right
                out.append((other, rep, "="))
    nat = [(m[0], fp) for (ty, fp), m in classes.items() if ty == N and m[0].vars()]
    for a, fa in nat:
        for b, fb in nat:
            if a is b or not min_size <= a.size + b.size <= max_size:
                continue
            # Tight: equal on some input and ordered on all, so neither side
            # is slack by a constant (length l <= S (S (length l))).
            if fa != fb and all(x <= y for x, y in zip(fa, fb)) \
                    and any(x == y for x, y in zip(fa, fb)) and ok_shape(a, b):
                out.append((a, b, "<="))
    return out


def _atoms(t, out):
    """The nat subterms computed from a list (length l, list_sum (rev l)):
    a nat-typed term whose head takes a list, outermost first, keyed by
    rendering so equal subterms share one atom. Nat operations above them
    (Nat.min n (length l)) stay, since they are the law over nat."""
    if t.type == N and t.op not in VARS and L in ALL_OPS[t.op][0]:
        out.setdefault(t.coq(), len(out))
        return
    for a in t.args:
        _atoms(a, out)


def _eval_abstract(t, atoms, env):
    if t.type == N and t.coq() in atoms:
        return env[("atom", atoms[t.coq()])]
    if t.op in VARS:
        return env[t.op]
    return ALL_OPS[t.op][2](*(_eval_abstract(a, atoms, env) for a in t.args))


def nat_instance(lhs, rhs, rel, rng, tests=500):
    """True if the candidate is an instance of a law over nat alone: with
    every list-derived nat subterm replaced by a free nat, it still holds on
    random inputs. 0 * (list_sum l) = 0 is 0 * a = 0, and
    list_max l - n <= list_max l is a - n <= a: true of any number, so they
    say nothing about lists. A side that is list-typed is never abstracted."""
    if lhs.type != N:
        return False
    atoms = {}
    _atoms(lhs, atoms)
    _atoms(rhs, atoms)
    for _ in range(tests):
        env = {"n": rng.randint(0, 12), "m": rng.randint(0, 12)}
        env.update({("atom", i): rng.randint(0, 12) for i in range(len(atoms))})
        a, b = _eval_abstract(lhs, atoms, env), _eval_abstract(rhs, atoms, env)
        if (rel == "=" and a != b) or (rel == "<=" and not a <= b):
            return False
    return True


def nat_abstraction(lhs, rhs, rel):
    """The law over nat that nat_instance() found the candidate to be an
    instance of, as a Coq statement: each list-derived subterm becomes a0, a1 ..
    So the drop can be certified (first [lia | nia] proves it), not just tested."""
    atoms = {}
    _atoms(lhs, atoms)
    _atoms(rhs, atoms)

    def go(t):
        if t.type == N and t.coq() in atoms:
            return f"a{atoms[t.coq()]}", True
        if t.op in VARS:
            return t.op, True
        parts = []
        for a in t.args:
            p, atom = go(a)
            parts.append(p if atom else f"({p})")
        return ALL_OPS[t.op][3](*parts), not t.args
    vs = [f"a{i}" for i in range(len(atoms))] + sorted(
        v for v in lhs.vars() | rhs.vars() if VARS[v] == N)
    body = f"{go(lhs)[0]} {rel} {go(rhs)[0]}"
    return f"forall ({' '.join(vs)} : nat), {body}" if vs else body


# Reading a rendered statement back, so a discovered lemma can seed new
# candidates. The grammar is the one Term.coq() writes: every non-atomic
# argument is parenthesized, so an expression is one prefix application or
# one infix operation over atoms.
HEADS = {"S": "S", "length": "length", "list_sum": "sum", "list_max": "lmax", "rev": "rev",
         "map S": "mapS", "filter Nat.even": "even", "firstn": "firstn", "skipn": "skipn",
         "repeat": "repeat", "seq": "seq", "removelast": "removelast", "Nat.max": "max",
         "Nat.min": "min", "nth": "nth", "last": "last", "count_occ Nat.eq_dec": "count"}
SUFFIX = {"nth": "0", "last": "0"}     # the default argument the rendering fixes
INFIX_OPS = {"+": "add", "*": "mul", "-": "sub", "++": "app", "::": "cons"}
TOKEN = re.compile(r"count_occ Nat\.eq_dec|map S|filter Nat\.even|Nat\.max|Nat\.min|\+\+|::|\[\]|[()+*-]|[\w.]+")


def _split_top(text, seps):
    depth = 0
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0:
            for sep in seps:
                if text.startswith(sep, i):
                    return text[:i], sep.strip(), text[i + len(sep):]
    return None


def parse_term(text):
    toks = TOKEN.findall(text)
    pos = [0]

    def atom():
        t = toks[pos[0]]
        pos[0] += 1
        if t == "(":
            e = expr()
            assert toks[pos[0]] == ")", text
            pos[0] += 1
            return e
        if t in VARS:
            return Term(t)
        if t == "0":
            return Term("0")
        if t == "[]":
            return Term("nil")
        if t in HEADS:
            op = HEADS[t]
            term = Term(op, [atom() for _ in ALL_OPS[op][0]])
            if op in SUFFIX:
                assert toks[pos[0]] == SUFFIX[op], text
                pos[0] += 1
            return term
        raise ValueError(f"cannot read {t!r} in {text!r}")

    def expr():
        a = atom()
        if pos[0] < len(toks) and toks[pos[0]] in INFIX_OPS:
            op = INFIX_OPS[toks[pos[0]]]
            pos[0] += 1
            return Term(op, [a, atom()])
        return a

    e = expr()
    if pos[0] != len(toks):
        raise ValueError(f"trailing input in {text!r}")
    return e


def parse_statement(stmt):
    """'forall (l1 : list nat), A <= B' -> (lhs, rhs, rel)."""
    body = stmt.split(", ", 1)[1] if stmt.startswith("forall") else stmt
    lhs, rel, rhs = _split_top(body, [" <= ", " = "])
    return parse_term(lhs), parse_term(rhs), rel


def ops_used(t):
    return {t.op} | set().union(*(ops_used(a) for a in t.args)) if t.args else {t.op}


def _subterms(t):
    yield t
    for a in t.args:
        yield from _subterms(a)


def _replace(t, target, var):
    if t.coq() == target:
        return Term(var)
    if not t.args:
        return t
    return Term(t.op, [_replace(a, target, var) for a in t.args])


def _fresh(ty, used):
    for v in (["l1", "l2"] if ty == L else ["n", "m"]):
        if v not in used:
            return v
    return None


def anti_unify(a, b):
    """The least general (lhs, rhs, rel) that a and b are both instances of,
    with each pair of differing subterms replaced by one fresh variable; None
    if they differ in shape, in relation, or need more variables than the
    signature has. a, b: (lhs, rhs, rel)."""
    if a[2] != b[2]:
        return None
    used = set().union(*(t.vars() for t in a[:2] + b[:2]))
    names = {}

    def go(x, y):
        if x.coq() == y.coq():
            return x
        if x.op == y.op and len(x.args) == len(y.args) and x.args:
            return Term(x.op, [go(p, q) for p, q in zip(x.args, y.args)])
        if x.type != y.type:
            raise ValueError
        key = (x.coq(), y.coq())
        if key not in names:
            v = _fresh(x.type, used)
            if v is None:
                raise ValueError
            used.add(v)
            names[key] = v
        return Term(names[key])
    try:
        lhs, rhs = go(a[0], b[0]), go(a[1], b[1])
    except ValueError:
        return None
    return (lhs, rhs, a[2]) if names else None


def generalize(c):
    """Each non-variable subterm of c, every occurrence at once, replaced by
    a fresh variable of its type: list_sum (l1 ++ rev l1) gives
    list_sum (l1 ++ l2)."""
    lhs, rhs, rel = c
    used = lhs.vars() | rhs.vars()
    seen = set()
    for t in list(_subterms(lhs)) + list(_subterms(rhs)):
        key = t.coq()
        if t.op in VARS or key in seen or (t.type == L and not t.vars()):
            continue
        seen.add(key)
        v = _fresh(t.type, used)
        if v is not None:
            yield (_replace(lhs, key, v), _replace(rhs, key, v), rel)
