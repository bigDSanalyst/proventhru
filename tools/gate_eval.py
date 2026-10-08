"""Gate a generated candidate file; keep the first N open statements in file order.

    python tools/gate_eval.py CANDIDATES --keep 120 --out examples/eval_test.txt \
        [--rename RENAMED --rename-out examples/eval_test_renamed.txt] --backend coqtop

The candidate file's order is the generator's seeded random order, so taking
the first N open ones selects on the gate alone. The renamed copy keeps the
same lines. Every candidate's gate status is written to --log (TSV) so the
selection can be audited.
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru.cli import _statements  # noqa: E402
from proventhru.gate import classify  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--keep", type=int, default=120)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rename", default=None)
    ap.add_argument("--rename-out", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--backend", default="coqtop")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)

    preamble, stmts = _statements(a.candidates)
    renamed = _statements(a.rename)[1] if a.rename else None
    with open(a.candidates) as fh:
        header = [ln for ln in fh if ln.startswith("#")]

    def gate(s):
        try:
            return classify(s, preamble, backend=a.backend).status
        except Exception as e:
            return f"crashed:{type(e).__name__}"

    with ThreadPoolExecutor(a.jobs) as ex:
        statuses = list(ex.map(gate, stmts))
    kept = [i for i, st in enumerate(statuses) if st == "open"][: a.keep]
    counts = {}
    for st in statuses:
        counts[st] = counts.get(st, 0) + 1
    note = (f"# Gated by tools/gate_eval.py (backend {a.backend}): {counts} of "
            f"{len(stmts)}; the first {len(kept)} open in file order are kept.\n")
    with open(a.out, "w") as fh:
        fh.write("".join(header) + note + "".join(stmts[i] + "\n" for i in kept))
    if renamed and a.rename_out:
        with open(a.rename) as fh:
            rheader = [ln for ln in fh if ln.startswith("#")]
        with open(a.rename_out, "w") as fh:
            fh.write("".join(rheader) + note + "".join(renamed[i] + "\n" for i in kept))
    if a.log:
        with open(a.log, "w") as fh:
            fh.write("".join(f"{st}\t{s}\n" for st, s in zip(statuses, stmts)))
    print(counts, f"kept {len(kept)}")


if __name__ == "__main__":
    main()
