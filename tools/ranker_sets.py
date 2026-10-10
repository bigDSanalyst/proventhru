"""Build RSI target 1's statement sets (docs/rsi-target1-ranker.md).

    python tools/make_eval.py --n 3000 --seed 7 --max-term 5 --min-size 5 \
        --max-size 9 --out CANDS
    python tools/ranker_sets.py CANDS --records RUN_DIR... --log GATE_LOG

1. Exclude, up to bound variable names, and twins of them (step 3): every
   statement of the v5 sets (test, test_renamed, dev) and every statement
   any given run record searched (the ranker's training records: a
   held-out statement must not have been searched in them).
2. Gate the rest (coqtop, v5's preamble) and keep the open ones, in file
   order.
3. Group the open ones into twins: statements equal up to bound variable
   names, a permutation of the variables and the commutativity of +, *,
   Nat.max and Nat.min. Shuffle the groups (random.Random(7).shuffle, in
   generator order of each group's first member) and deal them whole: H
   (300), T1 (300), T2 (300), and the rest, reserved for target 2 and never
   read by target 1. A group that would overfill a set goes to the next.

The sets are written to examples/ranker_{H,T1,T2,rest}.txt with the
candidates' own preamble line (v5's), and their hashes (`proventhru
protocol set FILE`) printed. --reuse-log takes gate statuses from an earlier
log instead of gating again."""
import argparse
import glob
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru.cli import _statements  # noqa: E402
from proventhru.keys import key, twin_key  # noqa: E402,F401
from proventhru.gate import classify  # noqa: E402
from proventhru.protocol import statements_sha256  # noqa: E402

HERE = os.path.join(os.path.dirname(__file__), "..")
V5_SETS = ["examples/eval_test.txt", "examples/eval_test_renamed.txt", "examples/eval_open.txt"]
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


def write(path, header, preamble, stmts):
    with open(path, "w") as fh:
        fh.write(header + f"# preamble: {preamble}\n" + "".join(s + "\n" for s in stmts))


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
    ap.add_argument("--reuse-log", default=None, help="gate statuses from an earlier --log")
    a = ap.parse_args(argv)

    preamble, cands = _statements(a.candidates)
    if not preamble:
        raise SystemExit("the candidates file has no '# preamble:' line")
    v5 = set()
    for p in V5_SETS:
        v5 |= set(_statements(os.path.join(HERE, p))[1])
    from_records = record_statements(a.records)
    excluded = {key(s) for s in v5 | from_records}
    excluded_twins = {twin_key(s) for s in v5 | from_records}
    n_v5 = len({key(s) for s in v5})

    status = {}
    todo = []
    for s in cands:
        if key(s) in excluded or twin_key(s) in excluded_twins:
            status[s] = "excluded"
        else:
            todo.append(s)

    def gate(s):
        try:
            return classify(s, preamble, backend="coqtop").status
        except Exception as e:
            return f"crashed:{type(e).__name__}"

    reused = {}
    if a.reuse_log:
        with open(a.reuse_log) as fh:
            for ln in fh:
                st, s = ln.rstrip("\n").split("\t", 1)
                if st != "excluded":
                    reused[s] = st
    fresh = [s for s in todo if s not in reused]
    for s in todo:
        if s in reused:
            status[s] = reused[s]
    with ThreadPoolExecutor(a.jobs) as ex:
        for s, st in zip(fresh, ex.map(gate, fresh)):
            status[s] = st
    with open(a.log, "w") as fh:
        fh.write("".join(f"{status[s]}\t{s}\n" for s in cands))
    opens = [s for s in cands if status[s] == "open"]
    groups = {}
    for s in opens:
        groups.setdefault(twin_key(s), []).append(s)
    order = list(groups.values())
    random.Random(a.seed).shuffle(order)
    sizes = [("H", a.h), ("T1", a.t), ("T2", a.t)]
    dealt = {name: [] for name, _ in sizes}
    dealt["rest"] = []
    for g in order:
        for name, cap in sizes:
            if len(dealt[name]) + len(g) <= cap:
                dealt[name] += g
                break
        else:
            dealt["rest"] += g
    h, t1, t2, reserve = dealt["H"], dealt["T1"], dealt["T2"], dealt["rest"]
    twins = sum(len(g) for g in groups.values() if len(g) > 1)

    counts = {}
    for st in status.values():
        counts[st] = counts.get(st, 0) + 1
    header = (f"# RSI target 1 (docs/rsi-target1-ranker.md). From {os.path.basename(a.candidates)}"
              f" ({len(cands)} candidates): {counts}.\n"
              f"# Excluded up to bound variable names, with their twins: the v5 sets ({n_v5} statements) and "
              f"{len(from_records)} statements searched in the records under "
              f"{', '.join(sorted(os.path.basename(p.rstrip('/')) for p in a.records))}.\n"
              f"# {len(opens)} open statements in {len(groups)} twin groups ({twins} statements "
              f"in groups of 2 or more), shuffled with seed {a.seed} and dealt whole: H {len(h)}, "
              f"T1 {len(t1)}, T2 {len(t2)}, rest {len(reserve)}.\n")
    out = {}
    for name, stmts in [("H", h), ("T1", t1), ("T2", t2), ("rest", reserve)]:
        path = os.path.join(a.out_dir, f"ranker_{name}.txt")
        write(path, header + f"# This file: {name}.\n", preamble, stmts)
        out[name] = {"path": os.path.relpath(path, HERE), "n": len(stmts),
                     "sha256": statements_sha256(preamble, stmts)}
    print(json.dumps({"counts": counts, "sets": out}, indent=2))


if __name__ == "__main__":
    main()
