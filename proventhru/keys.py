"""When two statements are the same statement, for held-out exclusions.

key: equal up to bound variable names. twin_key: also up to a permutation
of the variables and the commutativity of add, mul, max and min, so
list_sum l1 + list_sum l2 = list_sum (l2 ++ l1) and its mirror are one."""
import re
from itertools import permutations

from .conjecture import VARS, parse_statement

BINDER = re.compile(r"\(([^():]+):\s*([^()]+)\)")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
COMMUTATIVE = {"add", "mul", "max", "min"}


def _binders(statement):
    """(types of the bound variables, body), or (None, statement)."""
    s = " ".join(statement.split())
    types = {}
    m = re.match(r"forall\s+((?:\([^()]*\)\s*)+),\s*(.*)$", s)
    if m:
        for names, ty in BINDER.findall(m.group(1)):
            for v in names.split():
                types[v] = " ".join(ty.split())
        return types, m.group(2)
    m = re.match(r"forall\s+([^,:()]+?)\s*:\s*([^,()]+?)\s*,\s*(.*)$", s)
    if not m:
        return None, s
    for v in m.group(1).split():
        types[v] = m.group(2)
    return types, m.group(3)


def _rename(body, types, names_for):
    """Bound variables renamed by type, in order of first use in body."""
    count, ren = {}, {}
    for tok in IDENT.findall(body):
        if tok in types and tok not in ren:
            ty = types[tok]
            k = count.get(ty, 0)
            count[ty] = k + 1
            ren[tok] = names_for(ty, k)
    return IDENT.sub(lambda t: ren.get(t.group(0), t.group(0)), body)


def key(statement):
    """The statement up to bound variable names."""
    types, body = _binders(statement)
    if types is None:
        return body
    return _rename(body, types, lambda ty, k: f"<{ty}#{k + 1}>")


def _canon(t, ren):
    if t.op in VARS:
        return ren.get(t.op, t.op)
    args = [_canon(a, ren) for a in t.args]
    if t.op in COMMUTATIVE:
        args.sort()
    return f"{t.op}({','.join(args)})"


CANONICAL = {"list nat": ["l1", "l2"], "nat": ["n", "m"]}


def twin_key(statement):
    """The statement up to bound names, variable permutation and the
    commutativity of add, mul, max and min; '?' + key() when it is not a
    statement of the generator's signature."""
    types, body = _binders(statement)
    try:
        if types is None or any(ty not in CANONICAL for ty in types.values()):
            raise ValueError
        body = _rename(body, types, lambda ty, k: CANONICAL[ty][k])
        lhs, rhs, rel = parse_statement("forall x, " + body)
    except Exception:
        return "?" + key(statement)
    lists = [v for v in sorted(VARS) if VARS[v] == "list nat"]
    nats = [v for v in sorted(VARS) if VARS[v] == "nat"]
    best = None
    for pl in permutations(lists):
        for pn in permutations(nats):
            ren = dict(zip(lists, pl)) | dict(zip(nats, pn))
            k = f"{_canon(lhs, ren)} {rel.strip()} {_canon(rhs, ren)}"
            best = k if best is None or k < best else best
    return best
