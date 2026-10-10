"""Build RSI target 1's statement sets (docs/rsi-target1-ranker.md).

    python tools/make_eval.py --n 3000 --seed 7 --max-term 5 --min-size 5 \
        --max-size 9 --out CANDS
    python tools/ranker_sets.py CANDS --records RUN_DIR... --log GATE_LOG

1. Exclude, up to bound variable names: every statement of the v5 sets
   (test, test_renamed, dev) and every statement any given run record
   searched (the ranker's training records: a held-out statement must not
   have been searched in them).
2. Gate the rest (coqtop, v5's preamble) and keep the open ones, in file
   order.
3. Shuffle them with seed 7 and split: H (300), T1 (300), T2 (300), and the
   rest, reserved for target 2 and never read by target 1. With fewer than
   900 open, H keeps 300 and T1 and T2 split the rest equally.

The sets are written to examples/ranker_{H,T1,T2,rest}.txt with v5's
preamble line, and their hashes (`proventhru protocol set FILE`) printed."""
import argparse
import glob
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru.cli import _statements  # noqa: E402
from proventhru.env import DEFAULT_PREAMBLE  # noqa: E402
from proventhru.gate import classify  # noqa: E402
from proventhru.protocol import statements_sha256  # noqa: E402

HERE = os.path.join(os.path.dirname(__file__), "..")
V5_SETS = ["examples/eval_test.txt", "examples/eval_test_renamed.txt", "examples/eval_open.txt"]
BINDER = re.compile(r"\(([^():]+):\s*([^()]+)\)")


def key(statement):
    """The statement up to bound variable names: binders read off the
    forall, variables renamed by type in order of first use in the body."""
    s = " ".join(statement.split())
    types = {}
    m = re.match(r"forall\s+((?:\([^()]*\)\s*)+),\s*(.*)$", s)
    if m:
        for names, ty in BINDER.findall(m.group(1)):
            for v in names.split():
                types[v] = " ".join(ty.split())
    else:
        m = re.match(r"forall\s+([^,:()]+?)\s*:\s*([^,()]+?)\s*,\s*(.*)$", s)
        if not m:
            return s
        for v in m.group(1).split():
            types[v] = m.group(2)
    body, count, ren = m.groups()[-1], {}, {}
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_']*", body):
        if tok in types and tok not in ren:
            ty = types[tok]
            count[ty] = count.get(ty, 0) + 1
            ren[tok] = f"<{ty}#{count[ty]}>"
    body = re.sub(r"[A-Za-z_][A-Za-z0-9_']*", lambda t: ren.get(t.group(0), t.group(0)), body)
    return body


def record_statements(paths):
    out = set()
    for p in paths:
        files = [p] if os.path.isfile(p) else glob.glob(os.path.join(p, "**", "records.jsonl"),
                                                       recursive=True)
        for f in files:
            with open(f) as fh:
                for ln in fh:
                    if '"kind":"episode"' not in ln and '"kind": "episode"' not in ln:
                        continue
                    d = json.loads(ln)["data"]
                    s = d.get("statement") or d.get("item_statement")
                    if s:
                        out.add(s)
    return out


def write(path, header, stmts):
    with open(path, "w") as fh:
        fh.write(header + f"# preamble: {DEFAULT_PREAMBLE}\n" + "".join(s + "\n" for s in stmts))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--records", nargs="*", default=[],
                    help="run directories or records.jsonl files whose statements are excluded")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "examples"))
    ap.add_argument("--log", required=True, help="TSV: every candidate's exclusion or gate status")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--h", type=int, default=300)
    ap.add_argument("--t", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)

    preamble, cands = _statements(a.candidates)
    preamble = preamble or DEFAULT_PREAMBLE
    excluded = set()
    for p in V5_SETS:
        excluded |= {key(s) for s in _statements(os.path.join(HERE, p))[1]}
    n_v5 = len(excluded)
    from_records = record_statements(a.records)
    excluded |= {key(s) for s in from_records}

    status = {}
    todo = []
    for s in cands:
        if key(s) in excluded:
            status[s] = "excluded"
        else:
            todo.append(s)

    def gate(s):
        try:
            return classify(s, preamble, backend="coqtop").status
        except Exception as e:
            return f"crashed:{type(e).__name__}"

    with ThreadPoolExecutor(a.jobs) as ex:
        for s, st in zip(todo, ex.map(gate, todo)):
            status[s] = st
    with open(a.log, "w") as fh:
        fh.write("".join(f"{status[s]}\t{s}\n" for s in cands))
    opens = [s for s in cands if status[s] == "open"]
    random.Random(a.seed).shuffle(opens)
    h = opens[: a.h]
    rest = opens[a.h:]
    t = a.t if len(rest) >= 2 * a.t else len(rest) // 2
    t1, t2, reserve = rest[:t], rest[t: 2 * t], rest[2 * t:]

    counts = {}
    for st in status.values():
        counts[st] = counts.get(st, 0) + 1
    header = (f"# RSI target 1 (docs/rsi-target1-ranker.md). From {os.path.basename(a.candidates)}"
              f" ({len(cands)} candidates): {counts}.\n"
              f"# Excluded up to bound variable names: the v5 sets ({n_v5} statements) and "
              f"{len(from_records)} statements searched in the training records.\n"
              f"# Open statements shuffled with seed {a.seed}, then split H {len(h)}, "
              f"T1 {len(t1)}, T2 {len(t2)}, rest {len(reserve)}.\n")
    out = {}
    for name, stmts in [("H", h), ("T1", t1), ("T2", t2), ("rest", reserve)]:
        path = os.path.join(a.out_dir, f"ranker_{name}.txt")
        write(path, header + f"# This file: {name}.\n", stmts)
        out[name] = {"path": os.path.relpath(path, HERE), "n": len(stmts),
                     "sha256": statements_sha256(DEFAULT_PREAMBLE, stmts)}
    print(json.dumps({"counts": counts, "sets": out}, indent=2))


if __name__ == "__main__":
    main()
