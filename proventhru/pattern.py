"""The pattern extractor's symbolic proposer, pattern/analogy-v1
(docs/pattern-metrics.md v1; the run is fixed by docs/pattern-run-1.md).

A pattern is a library theorem with one or two of its symbols abstracted.
rev_length, `forall l, length (rev l) = length l`, read with rev abstracted,
says "length is invariant under F". The extractor carries the pattern over to a
development by putting one of the development's functions where the library's
was, when the types agree: rev_length proposes `forall l, length (sort l) =
length l`. NoDup_rev (`NoDup l -> NoDup (rev l)`), with NoDup and rev both
abstracted, proposes `sorted l -> sorted (insert a l)`.

The shapes are the library's theorems, read from Coq (`Search _ inside M`,
printed without notations), not written here. What's written here is the
substitution rule (SHAPES): which of the development's symbols may stand for a
library symbol, decided by type once the element type is nat. A symbol is
replaced at every occurrence, so the statement keeps the pattern's structure.

Every candidate is then tested in Coq against its own Prop, through the
decision procedures of pilots/isort/ISortDec.v, at every input of a fixed
exhaustive space, and a failing input becomes a kernel-checked disproof. What
the parser, the substitution rule or the tester doesn't cover is counted under
a named reason; tools/pattern_run.py says what the run does with each.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile

from .coqtop import Coqtop

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pilots", "isort")
SOURCES = ("List", "Permutation")        # the library modules patterns are read from
HARNESS = ("Require Import Arith Lia List Permutation.", "Import ListNotations.",
           "From ISortPilot Require Import ISort ISortTest ISortDec.")
PROPOSER = "pattern/analogy-v1"
NAT, LIST, PROP = "nat", "list nat", "Prop"
# The development's symbols, by the shape they can stand for: (argument types,
# result type) once the element type is nat. "insert a" is insert with a fresh
# number as its first argument, which gives it sort's shape.
SHAPES = {
    ((LIST,), LIST): ("sort", "insert a"),
    ((NAT, LIST), LIST): ("insert",),
    ((LIST,), PROP): ("sorted",),
}
OWN = ("insert", "sort", "sorted")
KEYWORDS = {"match", "let", "if", "fix", "cofix", "return", "with", "end", "in", "as", "then",
            "else", "exists", "forall", "fun"}
SPACES = {"one_list": "every list over {0, 1, 2} up to length 5, every n, m up to 3",
          "two_lists": "every pair of lists over {0, 1, 2} up to length 3, every n, m up to 3"}


class ParseError(ValueError):
    pass


# ---------------------------------------------------------------- terms
# ("id", name) | ("num", text) | ("app", head, args) | ("forall", binders, body)
# | ("fun", binders, body), a binder being (names, type, implicit).

TOKEN = re.compile(r"\s*(?:(=>)|(:=)|([()\[\],:])|([A-Za-z_][\w'.]*)|(\d+))")
WORD = re.compile(r"[A-Za-z_][\w'.]*|\d+")


def tokens(text):
    out, pos, text = [], 0, text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ParseError(f"unexpected text at {pos}: {text[pos:pos + 20]!r}")
        out.append(next(g for g in m.groups() if g is not None))
        pos = m.end()
    return out


def parse(text):
    """A term as Coq prints it under Unset Printing Notations: prefix
    applications, forall and fun binders. Anything else raises ParseError."""
    toks, pos = tokens(text), [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def eat(expected=None):
        t = peek()
        if t is None or (expected is not None and t != expected):
            raise ParseError(f"expected {expected!r}, got {t!r}")
        pos[0] += 1
        return t

    def name_next():
        t = peek()
        return t is not None and WORD.fullmatch(t) is not None and t not in KEYWORDS

    def binders(stop):
        out = []
        if peek() in ("(", "["):
            while peek() in ("(", "["):
                close = ")" if eat() == "(" else "]"
                names = []
                while name_next():
                    names.append(eat())
                eat(":")
                ty = term()
                eat(close)
                out.append((tuple(names), ty, close == "]"))
        else:
            names = []
            while name_next():
                names.append(eat())
            eat(":")
            out.append((tuple(names), term(), False))
        if not all(b[0] for b in out):
            raise ParseError("a binder without a name")
        eat(stop)
        return tuple(out)

    def term():
        if peek() in ("forall", "fun"):
            k = eat()
            bs = binders("," if k == "forall" else "=>")
            return (k, bs, term())
        head, args = atom(), []
        while peek() == "(" or name_next():
            args.append(atom())
        return apply(head, args)

    def atom():
        if peek() == "(":
            eat()
            x = term()
            eat(")")
            return x
        if not name_next():
            raise ParseError(f"not an atom: {peek()!r}")
        t = eat()
        return ("num", t) if t.isdigit() else ("id", t)

    out = term()
    if peek() is not None:
        raise ParseError(f"trailing {peek()!r}")
    return out


def apply(head, args):
    if not args:
        return head
    if head[0] == "app":
        return ("app", head[1], head[2] + tuple(args))
    return ("app", head, tuple(args))


def render(t):
    """Coq text that parses back to t, with notations on or off."""
    k = t[0]
    if k in ("id", "num"):
        return t[1]
    if k == "app":
        return " ".join(_wrap(x) for x in (t[1],) + t[2])
    bs = " ".join(f"({' '.join(ns)} : {render(ty)})" for ns, ty, _ in t[1])
    return f"forall {bs}, {render(t[2])}" if k == "forall" else f"fun {bs} => {render(t[2])}"


def _wrap(t):
    return render(t) if t[0] in ("id", "num") else f"({render(t)})"


def subst(t, env):
    """Replace free identifiers by terms (env: name -> term)."""
    k = t[0]
    if k == "id":
        return env.get(t[1], t)
    if k == "num":
        return t
    if k == "app":
        return apply(subst(t[1], env), [subst(a, env) for a in t[2]])
    inner, bs = dict(env), []
    for names, ty, imp in t[1]:
        bs.append((names, subst(ty, inner), imp))
        for n in names:
            inner.pop(n, None)
    return (k, tuple(bs), subst(t[2], inner))


def free(t, bound=frozenset()):
    """Free identifiers, in order of first occurrence."""
    k, out = t[0], []
    if k == "id":
        return [] if t[1] in bound else [t[1]]
    if k == "num":
        return []
    parts = [(x, bound) for x in (t[1],) + t[2]] if k == "app" else []
    if k in ("forall", "fun"):
        inner = set(bound)
        for names, ty, _ in t[1]:
            parts.append((ty, frozenset(inner)))
            inner |= set(names)
        parts.append((t[2], frozenset(inner)))
    for x, b in parts:
        out += [n for n in free(x, b) if n not in out]
    return out


def head(t):
    return t[1][1] if t[0] == "app" and t[1][0] == "id" else None


# ---------------------------------------------------------------- statements

def flatten(t):
    """(binders, body): the leading foralls, one (name, type) per name."""
    out = []
    while t[0] == "forall":
        for names, ty, _ in t[1]:
            out += [(n, ty) for n in names]
        t = t[2]
    return out, t


def is_sort(ty):
    return ty in (("id", "Type"), ("id", "Set"))


def specialize(t):
    """(data binders, hypotheses, conclusion) with every type variable set to
    nat; ParseError when the statement is outside the first-order nat /
    list nat fragment (the message says how)."""
    binders, body = flatten(t)
    env, data, hyps = {}, [], []
    for i, (name, ty) in enumerate(binders):
        if is_sort(ty):
            env[name] = ("id", NAT)
            continue
        ty = subst(ty, env)
        r = render(ty)
        if r in (NAT, LIST):
            data.append((name, r))
            continue
        if ty[0] in ("forall", "fun"):
            raise ParseError(f"higher-order binder {name}")
        if r.split()[0] in ("list", "prod", "option", "bool", "nat", "sumbool", "Type", "Set"):
            raise ParseError(f"binder {name} : {r} is outside nat and list nat")
        later = [b for _, b in binders[i + 1:]] + [body]
        if name != "_" and any(name in free(x) for x in later):
            raise ParseError(f"dependent hypothesis {name}")
        hyps.append(ty)
    return data, hyps, subst(body, env)


def statement(data, hyps, concl):
    """forall (data...), h1 -> ... -> concl, in prefix form."""
    body = concl
    for h in reversed(hyps):
        body = ("forall", ((("_",), h, False),), body)
    if not data:
        return body
    return ("forall", tuple(((n,), parse(ty), False) for n, ty in data), body)


def rename(data, hyps, concl):
    """Data variables renamed by type in order of first use (lists l1 l2 ...,
    numbers n m k ...), unused ones dropped: one text per meaning."""
    used = free(statement([], hyps, concl))
    order = sorted(((n, ty) for n, ty in data if n in used), key=lambda b: used.index(b[0]))
    fresh = {LIST: ["l1", "l2", "l3", "l4", "l5"], NAT: ["n", "m", "k", "j", "i", "p"]}
    tmp, back, out = {}, {}, []
    for n, ty in order:
        new = fresh[ty].pop(0)
        tmp[n], back["_r_" + new] = ("id", "_r_" + new), ("id", new)
        out.append((new, ty))
    return (out, [subst(subst(h, tmp), back) for h in hyps], subst(subst(concl, tmp), back))


def key(data, hyps, concl):
    """Equal for two statements that differ only in variable names and the
    order of their binders."""
    d, h, c = rename(data, hyps, concl)
    return render(statement(sorted(d), h, c))


def swapped_key(data, hyps, concl):
    """The key with the two sides of a final =, iff or Permutation swapped."""
    if head(concl) in ("eq", "iff", "Permutation") and len(concl[2]) == 2:
        return key(data, hyps, ("app", concl[1], concl[2][::-1]))
    return None


def kind(source, symbols):
    """The pattern kind of a source statement, read from its shape around the
    abstracted symbols (docs/pattern-metrics.md's names where one fits):
      symmetry     s x y = s y x, s abstracted
      composition  s applied to s, or s over another operation (s (op X Y)
                   against op (s X) (s Y)), s abstracted
      invariance   R relating X and T X; F (T X) on one side and F X on the
                   other; or P X -> P (T X), for any function T
      transfer     anything else: the statement carried over as a whole."""
    _, hyps, concl = source
    names = set(symbols)

    def applied(t, among=None):
        return t[0] == "app" and (among is None or head(t) in among)

    def step(x, y):
        """x is some function applied to y, as its last argument."""
        return applied(x) and x[2][-1] == y

    def one_step(x, y):
        """x and y differ in one argument, which is a function of y's."""
        if not (applied(x) and applied(y) and head(x) == head(y) and len(x[2]) == len(y[2])):
            return False
        diff = [(p, q) for p, q in zip(x[2], y[2]) if p != q]
        return len(diff) == 1 and step(*diff[0])

    if applied(concl) and len(concl[2]) == 2:
        a, b = concl[2]
        if applied(a, names) and applied(b, names) and head(a) == head(b) \
                and len(a[2]) == 2 and a[2] == b[2][::-1]:
            return "symmetry"
        for x in (a, b):
            if applied(x, names) and any(applied(y, {head(x)}) for y in x[2]):
                return "composition"
        if any(applied(x, names) and any(applied(y) and head(y) not in names for y in x[2])
               for x in (a, b)) and any(s in free(y) for s in names for y in (a, b)) \
                and all(any(s in free(y) for s in names) for y in (a, b)):
            return "composition"
        if step(a, b) or step(b, a) or one_step(a, b) or one_step(b, a):
            return "invariance"
    if any(one_step(concl, h) for h in hyps):
        return "invariance"
    return "transfer"


# ---------------------------------------------------------------- Coq

def build_harness():
    for f in ("ISort", "ISortTest", "ISortDec"):
        src, vo = os.path.join(HERE, f + ".v"), os.path.join(HERE, f + ".vo")
        if not os.path.exists(vo) or os.path.getmtime(vo) < os.path.getmtime(src):
            subprocess.run([shutil.which("coqc") or "coqc", "-Q", HERE, "ISortPilot", src],
                           check=True, capture_output=True)


class Coq:
    """One coqtop with the harness loaded. Without notations, it prints
    terms the way parse() reads them; with them, the way the prover sees."""

    def __init__(self, notations, deadline=300.0):
        build_harness()
        self.top = Coqtop(args=("-Q", HERE, "ISortPilot"), deadline=deadline)
        for c in HARNESS:
            self.must(c)
        if not notations:
            self.must("Unset Printing Notations.")

    def run(self, cmd):
        text, _, err = self.top.run(cmd)
        return text, err

    def must(self, cmd):
        text, err = self.run(cmd)
        if err:
            raise RuntimeError(f"{cmd}: {text.strip()[-300:]}")
        return text

    def term(self, stmt):
        """Coq's printing of a statement, or None if it doesn't elaborate."""
        text, err = self.run(f"Check ({stmt}).")
        return None if err else text.split("\n     : ", 1)[0].strip()

    def close(self):
        self.top.close()


ENTRY = re.compile(r"^([A-Za-z_][\w'.]*): (.*)$")
ABOUT = re.compile(r'^\(use "About" for full details on the implicit arguments of ')


def harvest(coq, modules=SOURCES):
    """[(name, type text)] of every constant Search lists inside the modules,
    in Coq's order, printed without notations."""
    out = []
    for m in modules:
        for line in coq.must(f"Search _ inside {m}.").splitlines():
            mo = ENTRY.match(line)
            if mo:
                out.append((mo.group(1), mo.group(2).strip()))
            elif line.strip() and not ABOUT.match(line):
                raise RuntimeError(f"unexpected Search line: {line[:120]!r}")
    return out


def shape_of(coq, name, cache):
    """(argument types, result type) of a constant with its type variables set
    to nat, or None when it isn't a first-order function or predicate."""
    if name not in cache:
        text, err = coq.run(f"Check @{name}.")
        shape = None
        if not err:
            try:
                binders, res = flatten(parse(text.split("\n     : ", 1)[-1].strip()))
                env, args = {}, []
                for n, b in binders:
                    if is_sort(b):
                        env[n] = ("id", NAT)
                    elif n == "_" or n not in free(res):
                        args.append(render(subst(b, env)))
                    else:
                        raise ParseError("dependent")
                shape = (tuple(args), render(subst(res, env)))
            except ParseError:
                shape = None
        cache[name] = shape
    return cache[name]


def theorems(coq, entries, count):
    """[(name, data, hyps, concl)]: the entries that are first-order theorems
    over nat and list nat once their element type is nat."""
    out = []
    for name, text in entries:
        try:
            data, hyps, concl = specialize(parse(text))
        except ParseError as e:
            count("outside the parser's grammar" if "expected" in str(e) or "atom" in str(e)
                  or "unexpected" in str(e) or "trailing" in str(e)
                  else "outside first-order nat and list nat")
            continue
        _, err = coq.run(f"Check ({render(statement(data, hyps, concl))} : Prop).")
        if err:
            count("not a theorem (a definition, or not a Prop)")
            continue
        out.append((name, data, hyps, concl))
    return out


def proposals(coq, entries, log=lambda *_: None):
    """(candidates, counts): every substitution of the development's symbols
    for library symbols of the same shape, in every library theorem, one or
    two symbols at a time, each at every occurrence of its symbol."""
    counts, cache, out = {}, {}, []

    def count(reason):
        counts[reason] = counts.get(reason, 0) + 1

    lemmas = theorems(coq, entries, count)
    log(f"{len(entries)} library entries, {len(lemmas)} first-order theorems; {counts}")
    for name, data, hyps, concl in lemmas:
        bound = {n for n, _ in data}
        syms = [s for s in free(statement([], hyps, concl)) if s not in bound]
        options = [(s, t) for s in syms for t in SHAPES.get(shape_of(coq, s, cache), ())]
        if not options:
            count("no symbol the development can stand for")
            continue
        picks = [(o,) for o in options] + [(o1, o2) for i, o1 in enumerate(options)
                                           for o2 in options[i + 1:] if o1[0] != o2[0]]
        for pick in picks:
            env, extra = {}, []
            for s, target in pick:
                if target == "insert a":
                    a = f"_ins{len(extra)}"
                    extra.append((a, NAT))
                    env[s] = ("app", ("id", "insert"), (("id", a),))
                else:
                    env[s] = ("id", target)
            d, h, c = rename(extra + data, [subst(x, env) for x in hyps], subst(concl, env))
            out.append({"source": name, "substitution": dict(pick),
                        "kind": kind((data, hyps, concl), [s for s, _ in pick]),
                        "data": d, "hyps": [render(x) for x in h], "concl": render(c),
                        "prefix": render(statement(d, h, c)), "key": key(d, h, c)})
    return out, counts


# ---------------------------------------------------------------- testing

def conj(hs):
    out = hs[-1]
    for h in reversed(hs[:-1]):
        out = ("app", ("id", "and"), (h, out))
    return out


def test_terms(c):
    """(body, premises, space) of the candidate's test, its variables bound
    as the space binds them (l1 l2 n m), or None when it has more variables
    than the space covers."""
    lists = [n for n, ty in c["data"] if ty == LIST]
    nats = [n for n, ty in c["data"] if ty == NAT]
    if len(lists) > 2 or len(nats) > 2:
        return None
    hyps = [parse(h) for h in c["hyps"]]
    body = render(statement([], hyps, parse(c["concl"])))
    return body, (render(conj(hyps)) if hyps else None), \
        ("two_lists" if "l2" in lists else "one_list")


VALUE = re.compile(r"\[|\]|;|\d+")


def values(text):
    """Coq's printing of Some (l1, l2, n, m), as Python values."""
    toks, pos, out = VALUE.findall(text), [0], []

    def one():
        t = toks[pos[0]]
        pos[0] += 1
        if t != "[":
            return int(t)
        lst = []
        while toks[pos[0]] != "]":
            if toks[pos[0]] == ";":
                pos[0] += 1
            else:
                lst.append(one())
        pos[0] += 1
        return lst
    while pos[0] < len(toks):
        out.append(one())
    return out


LAM = "fun pat : list nat * list nat * nat * nat => match pat with (l1, l2, n, m) => {} end"


def test(coq, c):
    """{status: passed | refuted | untestable, ...}: the candidate's Prop
    decided at every input of its space (ISortDec.v), the first failing input
    kept as a counterexample, and whether its premises held anywhere. coq
    must print with notations (the counterexample is read from Coq's output)."""
    t = test_terms(c)
    if t is None:
        return {"status": "untestable", "reason": "more variables than the test space binds"}
    body, prem, space = t
    # Check leaves an instance it can't find as a hole (?d) instead of failing,
    # and evaluating around the hole takes minutes: look for one first.
    text, err = coq.run(f"Check ({LAM.format(f'decide ({body})')}).")
    if err or "\nwhere\n" in text:
        lines = text.strip().splitlines()
        return {"status": "untestable",
                "reason": "no decision procedure for part of it" if not err
                else (lines[-1] if lines else "error")[:200]}
    text, err = coq.run(f"Eval vm_compute in find ({LAM.format(f'negb (decide ({body}))')}) "
                        f"{space}.")
    if err:
        lines = text.strip().splitlines()
        return {"status": "untestable", "reason": (lines[-1] if lines else "error")[:200]}
    value = text.split("=", 1)[1].split("\n     :")[0].strip()
    if value == "None":
        out = {"status": "passed", "space": space}
        if prem:
            t2, e2 = coq.run(f"Eval vm_compute in existsb ({LAM.format(f'decide ({prem})')}) "
                             f"{space}.")
            out["premises_held"] = not e2 and "true" in t2.split("\n     :")[0]
        return out
    env = dict(zip(("l1", "l2", "n", "m"), values(value)))
    return {"status": "refuted", "space": space, "counterexample": env,
            "args": [env[n] for n, _ in c["data"]]}


def coq_value(v):
    return "[" + "; ".join(map(str, v)) + "]" if isinstance(v, list) else str(v)


def disproof(c, result):
    """(statement, tactic): the disproof a counterexample gives, for the kernel."""
    args = " ".join(f"({coq_value(v)})" for v in result["args"])
    return (f"~ ({c['prefix']})",
            f"intro H; refine (decide_false _ _ (H {args})); vm_compute; reflexivity.")


def certify_disproofs(items, timeout=1800):
    """[accepted | rejected] per (statement, tactic): compiled against the
    harness, many to a file, each checked axiom-free by Print Assumptions. A
    file that doesn't compile is split until each failure is on its own."""
    if not items:
        return []
    build_harness()
    lines = list(HARNESS)
    for i, (stmt, tac) in enumerate(items):
        lines += [f"Lemma refuted_{i} : {stmt}.", f"Proof. {tac} Qed.",
                  f"Print Assumptions refuted_{i}."]
    with tempfile.TemporaryDirectory(prefix="proventhru-") as d:
        path = os.path.join(d, "Refuted.v")
        with open(path, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        p = subprocess.run([shutil.which("coqc") or "coqc", "-Q", HERE, "ISortPilot", path],
                           cwd=d, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        if len(items) == 1:
            return ["rejected"]
        half = len(items) // 2
        return certify_disproofs(items[:half], timeout) + certify_disproofs(items[half:], timeout)
    verdicts = re.findall(r"Closed under the global context|Axioms:", p.stdout)
    if len(verdicts) != len(items):
        raise RuntimeError(f"{len(verdicts)} assumption reports for {len(items)} disproofs")
    return ["accepted" if v.startswith("Closed") else "rejected" for v in verdicts]


def file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()
