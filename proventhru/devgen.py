"""Conjectures about a Coq development, tested in Coq.

The generator of conjecture.py evaluates its terms in Python. For a
development's own functions that would mean a Python copy of each, which can
drift from the Coq definition silently. Here every term and every candidate is
evaluated by Coq (vm_compute), against the development's own definitions, and
predicates go through boolean versions proved equivalent to them (the
development's test harness: sortedb_spec, inb_spec, permb_spec).

Candidates, QuickSpec style, over a signature of the development's functions
plus a few list functions:
  equations     t1 = t2, two members of one class of terms
  facts         P(t), a predicate true on every test input
  conditionals  P(vars) -> Q(...), where P holds on some inputs, the
                conclusion holds wherever P does, and does not hold everywhere
                (a conditional law, as QuickSpec's conditional equations)
Only candidates that mention one of the development's own symbols are kept:
laws about rev and ++ alone are the library's, not the development's.

A standing rule for every evaluator here: the inputs must cover what could
falsify a candidate, not what is easy to construct. The first version made l2
a permutation of l1 only in its sorted form, so `Permutation l1 l2 ->
sorted l2` passed every test. A premise that holds only on inputs of one
shape tests nothing beyond that shape.
"""
import itertools
import os
import random
import re
import shutil
import subprocess
import tempfile

N, L = "nat", "list nat"
VARS = {"l1": L, "l2": L, "n": N, "m": N}

# name: (argument types, result type, Coq rendering)
OPS = {
    "0": ((), N, lambda: "0"),
    "S": ((N,), N, lambda a: f"S {a}"),
    "length": ((L,), N, lambda a: f"length {a}"),
    "nil": ((), L, lambda: "[]"),
    "cons": ((N, L), L, lambda a, b: f"{a} :: {b}"),
    "app": ((L, L), L, lambda a, b: f"{a} ++ {b}"),
    "rev": ((L,), L, lambda a: f"rev {a}"),
    "insert": ((N, L), L, lambda a, b: f"insert {a} {b}"),
    "sort": ((L,), L, lambda a: f"sort {a}"),
}
# name: (argument types, Prop rendering, bool rendering in the test harness)
PREDS = {
    "sorted": ((L,), lambda a: f"sorted {a}", lambda a: f"sortedb {a}"),
    "In": ((N, L), lambda a, b: f"In {a} {b}", lambda a, b: f"inb {a} {b}"),
    "Permutation": ((L, L), lambda a, b: f"Permutation {a} {b}", lambda a, b: f"permb {a} {b}"),
}
OWN = {"insert", "sort", "sorted"}
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pilots", "isort")


class Term:
    __slots__ = ("op", "args", "type", "size")

    def __init__(self, op, args=()):
        self.op, self.args = op, tuple(args)
        self.type = VARS[op] if op in VARS else OPS[op][1]
        self.size = 1 + sum(a.size for a in self.args)

    def coq(self):
        if self.op in VARS:
            return self.op
        parts = [a.coq() if not a.args else f"({a.coq()})" for a in self.args]
        return OPS[self.op][2](*parts)

    def vars(self):
        if self.op in VARS:
            return {self.op}
        return set().union(*(a.vars() for a in self.args)) if self.args else set()

    def ops(self):
        return {self.op}.union(*(a.ops() for a in self.args)) if self.args else {self.op}


class Atom:
    """A predicate applied to terms."""

    def __init__(self, pred, args):
        self.pred, self.args = pred, tuple(args)

    def _parts(self):
        return [a.coq() if not a.args else f"({a.coq()})" for a in self.args]

    def coq(self):
        return PREDS[self.pred][1](*self._parts())

    def bool(self):
        return PREDS[self.pred][2](*self._parts())

    def vars(self):
        return set().union(*(a.vars() for a in self.args))

    def ops(self):
        return {self.pred}.union(*(a.ops() for a in self.args))


# ---------------------------------------------------------------- Coq evaluation

def _envs_coq(envs):
    def lst(xs):
        return "[" + "; ".join(map(str, xs)) + "]"
    return "[" + "; ".join(f"({lst(e['l1'])}, {lst(e['l2'])}, {e['n']}, {e['m']})"
                           for e in envs) + "]"


def _prelude():
    return ("Require Import Arith Lia List Permutation. Import ListNotations.\n"
            "From ISortPilot Require Import ISort ISortTest.\n"
            "Set Printing Width 1000000.\n")


def _build_pilot():
    for f in ("ISort", "ISortTest"):
        if not os.path.exists(os.path.join(HERE, f + ".vo")):
            subprocess.run([shutil.which("coqc") or "coqc", "-Q", HERE, "ISortPilot",
                            os.path.join(HERE, f + ".v")], check=True, capture_output=True)


TOKEN = re.compile(r"\[|\]|;|true|false|\d+")


def _parse(text):
    """Coq's printed value: nested lists of numbers and booleans."""
    toks = TOKEN.findall(text)
    pos = [0]

    def val():
        t = toks[pos[0]]
        pos[0] += 1
        if t == "[":
            out = []
            while toks[pos[0]] != "]":
                out.append(val())
                if toks[pos[0]] == ";":
                    pos[0] += 1
            pos[0] += 1
            return tuple(out)
        if t in ("true", "false"):
            return t == "true"
        return int(t)
    return val()


def coq_eval(exprs, envs, timeout=600):
    """[[value per env] per expression], each expression evaluated by Coq at
    each env (its variables l1 l2 n m bound from the env)."""
    if not exprs:
        return []
    _build_pilot()
    body = [_prelude(), f"Definition envs : list (list nat * list nat * nat * nat) := "
                        f"{_envs_coq(envs)}.\n"]
    for e in exprs:
        body.append(f"Eval vm_compute in map (fun '(l1, l2, n, m) => ({e})) envs.\n")
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, "eval.v")
        with open(path, "w") as fh:
            fh.write("".join(body))
        p = subprocess.run([shutil.which("coqc") or "coqc", "-Q", HERE, "ISortPilot", path],
                           cwd=d, capture_output=True, text=True, timeout=timeout)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if p.returncode != 0:
        raise RuntimeError("Coq evaluation failed: " + (p.stdout + p.stderr)[-800:])
    # each Eval prints "     = VALUE\n     : TYPE"
    values = re.findall(r"^\s*= (.*?)\n\s*: ", p.stdout, re.M | re.S)
    if len(values) != len(exprs):
        raise RuntimeError(f"{len(values)} values for {len(exprs)} expressions")
    return [list(_parse(v)) for v in values]


def coq_all_envs(bool_exprs, envs, timeout=600):
    """Like coq_all but over the given envs (the definition of envs is the
    check set itself)."""
    if not bool_exprs:
        return []
    _build_pilot()
    body = [_prelude(), f"Definition envs : list (list nat * list nat * nat * nat) := "
                        f"{_envs_coq(envs)}.\n"]
    for b in bool_exprs:
        body.append(f"Eval vm_compute in forallb (fun '(l1, l2, n, m) => {b}) envs.\n")
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, "check.v")
        with open(path, "w") as fh:
            fh.write("".join(body))
        p = subprocess.run([shutil.which("coqc") or "coqc", "-Q", HERE, "ISortPilot", path],
                           cwd=d, capture_output=True, text=True, timeout=timeout)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if p.returncode != 0:
        raise RuntimeError("Coq check failed: " + (p.stdout + p.stderr)[-800:])
    values = re.findall(r"^\s*= (true|false)\s*\n\s*: bool", p.stdout, re.M)
    if len(values) != len(bool_exprs):
        raise RuntimeError(f"{len(values)} answers for {len(bool_exprs)} checks")
    return [v == "true" for v in values]


# ---------------------------------------------------------------- inputs

def fingerprint_envs(seed=3, count=36):
    """Inputs for telling terms apart: random lists, and as many sorted ones,
    so a premise like sorted l1 holds on enough of them to test under."""
    rng = random.Random(seed)
    out = [{"l1": (), "l2": (), "n": 0, "m": 0}, {"l1": (1,), "l2": (0,), "n": 1, "m": 0},
           {"l1": (0, 2), "l2": (3, 1), "n": 1, "m": 2}, {"l1": (2, 2), "l2": (2,), "n": 2, "m": 2}]
    while len(out) < count:
        lst = lambda: tuple(rng.randint(0, 4) for _ in range(rng.randint(0, 5)))  # noqa: E731
        a, b = lst(), lst()
        if len(out) % 2:
            a = tuple(sorted(a))
        if len(out) % 3 == 0:
            # l2 a permutation of l1 that is not sorted, so a premise
            # Permutation l1 l2 is tested against unsorted l2 too
            b = a[1:] + a[:1] if len(a) > 1 else a[::-1]
            if b == tuple(sorted(b)):
                b = b[::-1]
        out.append({"l1": a, "l2": b, "n": rng.randint(0, 4), "m": rng.randint(0, 4)})
    return out


def check_envs(length=4, alphabet=(0, 1, 2)):
    """Every list of length up to 4 over {0, 1, 2} as l1, against a few l2,
    n and m: the small cases random inputs miss."""
    out = []
    for k in range(length + 1):
        for lst in itertools.product(alphabet, repeat=k):
            # l2: empty, a singleton, and three permutations of l1 (sorted,
            # reversed, rotated), so Permutation l1 l2 holds on unsorted l2
            for l2 in ((), (1,), tuple(sorted(lst)), lst[::-1], lst[1:] + lst[:1]):
                for n, m in ((0, 1), (1, 1), (2, 0), (3, 2)):
                    out.append({"l1": lst, "l2": l2, "n": n, "m": m})
    return out


# ---------------------------------------------------------------- enumeration

def _splits(total, k):
    if k == 1:
        if total >= 1:
            yield (total,)
        return
    for first in range(1, total):
        for rest in _splits(total - first, k - 1):
            yield (first,) + rest


def enumerate_terms(max_size, envs, log=lambda *_: None):
    """{(type, values): [terms]}, and reps[type][size], built size by size, each
    size's new terms evaluated by Coq in one batch."""
    classes, reps = {}, {L: {}, N: {}}

    def admit(terms, values):
        for t, v in zip(terms, values):
            key = (t.type, tuple(v))
            if key in classes:
                classes[key].append(t)
            else:
                classes[key] = [t]
                reps[t.type].setdefault(t.size, []).append(t)

    base = [Term(v) for v in VARS] + [Term("0"), Term("nil")]
    admit(base, coq_eval([t.coq() for t in base], envs))
    for size in range(2, max_size + 1):
        new = []
        for op, (args, _, _) in OPS.items():
            if not args:
                continue
            for split in _splits(size - 1, len(args)):
                pools = [reps[ty].get(s, []) for ty, s in zip(args, split)]
                for combo in itertools.product(*pools):
                    new.append(Term(op, combo))
        log(f"size {size}: {len(new)} terms to evaluate")
        admit(new, coq_eval([t.coq() for t in new], envs))
    return classes, reps


def constant_list(t):
    if t.type == L and not t.vars():
        return True
    return any(constant_list(a) for a in t.args)


def own(x):
    return bool(x.ops() & OWN)


def binders(names):
    ls = [v for v in ("l1", "l2") if v in names]
    ns = [v for v in ("n", "m") if v in names]
    out = []
    if ls:
        out.append(f"({' '.join(ls)} : list nat)")
    if ns:
        out.append(f"({' '.join(ns)} : nat)")
    return " ".join(out)


def render(vars_, body):
    return f"forall {binders(vars_)}, {body}" if vars_ else body


def candidates(max_size=4, atom_size=3, cond_size=3, seed=3, log=print):
    """[(statement, kind, check_expr)] for the pilot's signature, before the
    final check. check_expr is the boolean Coq checks on every input."""
    envs = fingerprint_envs(seed)
    classes, reps = enumerate_terms(max_size, envs, log)
    out = []

    def keep(stmt, kind, check, vars_, mentions_own):
        if mentions_own and any(VARS[v] == L for v in vars_):
            out.append((stmt, kind, check))

    # equations
    for (ty, _), members in classes.items():
        rep = members[0]
        for other in members[1:]:
            if other.vars() and not constant_list(other) and not constant_list(rep) \
                    and other.args and (own(other) or own(rep)):
                lhs, rhs = other.coq(), rep.coq()
                eq = (f"if list_eq_dec Nat.eq_dec ({lhs}) ({rhs}) then true else false"
                      if ty == L else f"({lhs}) =? ({rhs})")
                v = other.vars() | rep.vars()
                keep(render(v, f"{lhs} = {rhs}"), "equation", eq, v, True)

    # atoms over small class representatives
    small = {ty: [t for s, ts in reps[ty].items() if s <= atom_size for t in ts
                  if not constant_list(t)] for ty in (N, L)}
    atoms = []
    for pred, (args, _, _) in PREDS.items():
        for combo in itertools.product(*[small[ty] for ty in args]):
            if len(args) == 2 and combo[0].coq() == combo[1].coq():
                continue
            atoms.append(Atom(pred, combo))
    log(f"{len(atoms)} atoms to evaluate")
    truth = coq_eval([a.bool() for a in atoms], envs)
    for a, vals in zip(atoms, truth):
        if all(vals) and a.vars():
            keep(render(a.vars(), a.coq()), "fact", a.bool(), a.vars(), own(a))

    # conditionals: premise over variables only, conclusion an atom or equation
    premises = [(a, vals) for a, vals in zip(atoms, truth)
                if all(t.op in VARS for t in a.args) and 0 < sum(vals) < len(vals)]
    concl_atoms = [(a, vals) for a, vals in zip(atoms, truth)
                   if not all(vals) and sum(t.size for t in a.args) <= cond_size + 1]
    for p, pv in premises:
        for c, cv in concl_atoms:
            if c.coq() == p.coq() or not (c.vars() & p.vars()):
                continue
            if all(cvi for pvi, cvi in zip(pv, cv) if pvi) and own(c) | own(p):
                v = p.vars() | c.vars()
                keep(render(v, f"{p.coq()} -> {c.coq()}"), "conditional",
                     f"implb ({p.bool()}) ({c.bool()})", v, True)
        # conditional equations between small terms that differ without P
        for ty in (N, L):
            terms = [t for t in small[ty] if t.vars() & p.vars()]
            vals = {t.coq(): v for (tty, v), ms in classes.items() if tty == ty for t in ms[:1]}
            for a, b in itertools.combinations(terms, 2):
                va, vb = vals.get(a.coq()), vals.get(b.coq())
                if va is None or vb is None or va == vb:
                    continue
                if all(x == y for x, y, ok in zip(va, vb, pv) if ok) and (own(a) or own(b)):
                    big, sm = (a, b) if a.size >= b.size else (b, a)
                    lhs, rhs = big.coq(), sm.coq()
                    eq = (f"if list_eq_dec Nat.eq_dec ({lhs}) ({rhs}) then true else false"
                          if ty == L else f"({lhs}) =? ({rhs})")
                    v = p.vars() | a.vars() | b.vars()
                    keep(render(v, f"{p.coq()} -> {lhs} = {rhs}"), "conditional",
                         f"implb ({p.bool()}) ({eq})", v, True)
    seen, uniq = set(), []
    for c in out:
        if c[0] not in seen:
            seen.add(c[0])
            uniq.append(c)
    return uniq


def canonical(stmt):
    """Variables renamed in order of first use in the body (lists l1 l2,
    numbers n m), so candidates that differ only in names are one."""
    head, _, body = stmt.partition(", ") if stmt.startswith("forall") else ("", "", stmt)
    order = []
    for v in re.findall(r"\b(l1|l2|n|m)\b", body):
        if v not in order:
            order.append(v)
    names, count = {}, {L: 0, N: 0}
    for v in order:
        ty = VARS[v]
        names[v] = (["l1", "l2"] if ty == L else ["n", "m"])[count[ty]]
        count[ty] += 1
    body = re.sub(r"\b(l1|l2|n|m)\b", lambda mo: "_" + names[mo.group(1)], body).replace("_", "")
    return render(set(names.values()), body)


def generate(max_size=4, seed=3, log=print):
    """Candidates that pass the check on every small input, in Coq."""
    cands, seen = [], set()
    for stmt, kind, check in candidates(max_size, seed=seed, log=log):
        c = canonical(stmt)
        if c not in seen:
            seen.add(c)
            cands.append((c, kind, check))
    log(f"{len(cands)} candidates; checking each on {len(check_envs())} inputs in Coq")
    ok = coq_all_envs([c[2] for c in cands], check_envs())
    return [c for c, good in zip(cands, ok) if good], [c for c, good in zip(cands, ok) if not good]


def preamble():
    """The prover's preamble: the development's definitions, inline (the loop
    sees ISort.v and nothing else from the pilot)."""
    with open(os.path.join(HERE, "ISort.v")) as fh:
        text = fh.read()
    text = re.sub(r"\(\*.*?\*\)", "", text, flags=re.S)
    text = re.sub(r"Require Import[^\n]*\n", "", text)
    return ("Require Import Arith Lia List Permutation. Import ListNotations. "
            + " ".join(text.split()))


# ---------------------------------------------------------------- the pilot's tactics

def isort_tactics():
    """structural-tactics/isort/v1: structural-tactics/v2 plus what the pilot's
    types need (results/isort-gate2.md, 2a's failures):
      induction on a sorted hypothesis    insert_sorted, sorted_sort_id
      a case on <=?, turned into <= / >   so lia can use it
      Permutation's constructors          insert_perm
    Kept apart from v2 so the nat / list nat runs stay comparable."""
    from .explore import CASES_EQ, CLOSE, StructuralTacticsV2

    LEB = ("repeat match goal with H : (_ <=? _) = true |- _ => apply Nat.leb_le in H "
           "| H : (_ <=? _) = false |- _ => apply Nat.leb_gt in H end")
    CLOSE_S = ("first [lia | reflexivity | assumption | (repeat constructor; first [lia | "
               "assumption | eassumption]) | (constructor; [lia | assumption])]")
    PERM = ("first [reflexivity | (apply perm_skip; assumption) | (eapply perm_trans; "
            "[apply perm_swap | apply perm_skip; assumption])]")
    SORTED = re.compile(r"^(\w+) : sorted ")

    class ISortTactics(StructuralTacticsV2):
        identity = {"id": "structural-tactics/isort/v1", "model": None, "provider": None}

        def propose(self, obs, path, last_failure=None, tried=None):
            out = super().propose(obs, path, last_failure, tried)
            if not obs.goals:
                return out
            g = obs.goals[0]
            extra = []
            for h in g.hypotheses:
                m = SORTED.match(h)
                if m:
                    H = m.group(1)
                    extra += [
                        (f"induction {H} as [|x|x y t Hxy Ht IH]; simpl in *; {CASES_EQ}; "
                         f"{LEB}; simpl in *; {CASES_EQ}; {LEB}; {CLOSE_S}.", 0.9),
                        (f"induction {H} as [|x|x y t Hxy Ht IH]; simpl in *.", 0.45)]
            if "<=?" in g.conclusion or "if " in g.conclusion or "match" in g.conclusion:
                extra += [(f"{CASES_EQ}; {LEB}; simpl in *; {CLOSE_S}.", 0.85),
                          (f"{CASES_EQ}; {LEB}; simpl in *.", 0.5)]
            if any("<=?" in h for h in g.hypotheses):
                extra.append((f"{LEB}.", 0.6))
            if g.conclusion.startswith("Permutation"):
                extra += [(f"{PERM}.", 0.85),
                          (f"{CASES_EQ}; simpl in *; {PERM}.", 0.8)]
            extra.append((f"{CLOSE_S}.", 0.7))
            have = {t for t, _ in out}
            return out + [(t, sc) for t, sc in extra if t not in have]

    _ = CLOSE
    return ISortTactics
