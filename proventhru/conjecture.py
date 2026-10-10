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
INFIX = {"add", "mul", "sub", "app", "cons"}
CAP = 60  # values above this are not compared (repeat/seq/mul blow up)


class Term:
    __slots__ = ("op", "args", "type", "size")

    def __init__(self, op, args=(), type_=None):
        self.op, self.args = op, tuple(args)
        self.type = VARS[op] if op in VARS else OPS[op][1]
        self.size = 1 + sum(a.size for a in self.args)

    def eval(self, env):
        if self.op in VARS:
            return env[self.op]
        vals = [a.eval(env) for a in self.args]
        if any(v is None for v in vals):
            return None
        out = OPS[self.op][2](*vals)
        if (isinstance(out, int) and out > CAP) or (isinstance(out, tuple) and len(out) > CAP):
            return None
        return out

    def coq(self, names=None, top=True):
        if self.op in VARS:
            return (names or {}).get(self.op, self.op)
        parts = [a.coq(names, top=False) for a in self.args]
        parts = [p if not a.args else f"({p})" for a, p in zip(self.args, parts)]
        return OPS[self.op][3](*parts)

    def vars(self):
        if self.op in VARS:
            return {self.op}
        return set().union(*(a.vars() for a in self.args)) if self.args else set()

    def head(self):
        return self.op


def random_env(rng):
    lst = lambda: tuple(rng.randint(0, 5) for _ in range(rng.randint(0, 6)))
    return {"l1": lst(), "l2": lst(), "n": rng.randint(0, 6), "m": rng.randint(0, 6)}


EDGE = [{"l1": (), "l2": (), "n": 0, "m": 0}, {"l1": (0,), "l2": (), "n": 1, "m": 0},
        {"l1": (), "l2": (3, 1), "n": 0, "m": 2}, {"l1": (2, 2), "l2": (2,), "n": 2, "m": 2}]


def fingerprint(t, envs):
    vals = tuple(t.eval(e) for e in envs)
    return None if any(v is None for v in vals) else vals


def enumerate_classes(max_size, envs):
    """{fingerprint: [terms in size order]}; reps[type][size] = class reps."""
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
        for op, (args, _, _, _) in OPS.items():
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


def candidates(classes, min_size, max_size):
    """Candidate (lhs, rhs, rel) from the fingerprints alone; holds() is run
    later, only on what is sampled."""
    out = []

    def ok_shape(lhs, rhs):
        both = lhs.vars() | rhs.vars()
        return (any(VARS[v] == L for v in both) and min_size <= lhs.size + rhs.size <= max_size
                and lhs.args and lhs.vars() and not same_context(lhs, rhs)
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
    if t.type == N and t.op not in VARS and L in OPS[t.op][0]:
        out.setdefault(t.coq(), len(out))
        return
    for a in t.args:
        _atoms(a, out)


def _eval_abstract(t, atoms, env):
    if t.type == N and t.coq() in atoms:
        return env[("atom", atoms[t.coq()])]
    if t.op in VARS:
        return env[t.op]
    return OPS[t.op][2](*(_eval_abstract(a, atoms, env) for a in t.args))


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
