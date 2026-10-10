"""Run RSI target 1 end to end, as pre-registered (docs/rsi-target1-ranker.md).

    python tools/ranker_schedule.py --runs /tmp/claude-0/runs/ranker/runs [--jobs 3]

Every step is the fixed update rule; nothing between iterations is chosen
by hand. Steps are idempotent: a run resumes from its record, and a fit or
an extraction whose output exists is skipped. Each D and each fitted ranker
is committed before anything uses it, so the record's order is the git
history's.

  1. 0a, 0b: B' on H. 0b must equal 0a item for item, or the schedule stops.
  2. ref (A), v1 (B as registered) and P0 (placebo slots) on H.
  3. B' on T1 and on T2 (the controls' data, D1' and D2').
  4. R1 on D0; R1 on H (iteration 1) and on T1; D1 and D1' extracted.
  5. R2 on D0+D1 and R2' on D0+D1'; R2 on H (iteration 2), R2 on T2, R2' on H;
     D2 and D2' extracted.
  6. R3 on D0+D1+D2 and R3' on D0+D1'+D2'; R3 on H (iteration 3), R3' on H,
     and the interleaved run (B' and R3) on H.
  7. The report, results/rsi-target1.md."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RES = os.path.join(HERE, "results", "ranker")
H, T1, T2 = "examples/ranker_H.txt", "examples/ranker_T1.txt", "examples/ranker_T2.txt"


def sh(argv):
    print("$ " + " ".join(argv), flush=True)
    rc = subprocess.call(argv, cwd=HERE)
    if rc:
        raise SystemExit(f"step failed ({rc}): {' '.join(argv)}")


def commit(paths, message):
    sh(["git", "add"] + paths)
    if subprocess.call(["git", "diff", "--cached", "--quiet"], cwd=HERE):
        sh(["git", "commit", "-q", "-m", message])


DOC = "docs/rsi-target1-ranker.md"


def frozen_hash():
    """The doc's sha256, which must match its docs/frozen.md row: the
    schedule refuses to run under a pre-registration that changed."""
    with open(os.path.join(HERE, DOC), "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    with open(os.path.join(HERE, "docs", "frozen.md")) as fh:
        rows = [ln for ln in fh if ln.startswith(f"| `{DOC}`")]
    if not rows:
        raise SystemExit(f"{DOC} has no row in docs/frozen.md: it isn't frozen")
    m = re.search(r"`([0-9a-f]{64})`\s*\|\s*`([0-9a-f]+)`", rows[-1])
    if not m or m.group(1) != digest:
        raise SystemExit(f"{DOC} (sha256 {digest}) doesn't match its docs/frozen.md row")
    return digest, m.group(2)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args(argv)
    py = sys.executable
    it = [py, "tools/ranker_iterate.py"]
    d = lambda label: os.path.join(a.runs, label)       # noqa: E731
    r = lambda name: os.path.join(RES, name)             # noqa: E731

    def run(label, sset, *extra):
        sh(it + ["run", "--set", sset, "--out", d(label), "--jobs", str(a.jobs)] + list(extra))
        # every target-1 record cites the pre-registration it ran under
        from proventhru import record as rec
        book = rec.RecordLog(os.path.join(d(label), "records.jsonl"))
        cites = [e for e in book.entries if e.get("kind") == "annotation"
                 and digest in (e.get("data") or {}).get("reason", "")]
        if not cites:
            book.annotate(0, "note", f"RSI target 1 run {label}, under {DOC} sha256 {digest} "
                          f"(frozen at {commit_id})", by="tools/ranker_schedule.py")

    def fit(name, rows):
        if not os.path.exists(r(name)):
            sh(it + ["fit", "--rows"] + [r(x) for x in rows] + ["--out", r(name)])
            commit([r(name)], f"Target 1: fit {name} on {', '.join(rows)}")

    def extract(name, label):
        if not os.path.exists(r(name)):
            sh([py, "tools/ranker_data.py", d(label), "--out", r(name), "--jobs", str(a.jobs)])
            stats = os.path.splitext(r(name))[0] + ".stats.json"
            commit([r(name), stats], f"Target 1: extract {name} from run {label}")

    digest, commit_id = frozen_hash()
    os.makedirs(a.runs, exist_ok=True)
    if not os.path.exists(r("D0.jsonl")):
        raise SystemExit("results/ranker/D0.jsonl is missing: it is committed at the freezing commit")

    # 1
    run("0a", H)
    run("0b", H)
    sys.path.insert(0, os.path.join(HERE, "tools"))
    from ranker_iterate import Run
    ra, rb = Run(d("0a")), Run(d("0b"))
    diff = [s for s in ra.by_stmt if ra.by_stmt[s]["proof"] != rb.by_stmt.get(s, {}).get("proof")
            or ra.by_stmt[s]["proved"] != rb.by_stmt.get(s, {}).get("proved")]
    if diff or len(ra.by_stmt) != len(rb.by_stmt):
        raise SystemExit(f"0b differs from 0a on {len(diff)} statements: stop and find the cause")
    # 2
    run("ref", H, "--fixed-only")
    run("v1", H, "--retrieval-version", "1")
    run("P0", H, "--slots", "placebo")
    # 3
    run("T1-B", T1)
    run("T2-B", T2)
    # 4
    fit("R1.json", ["D0.jsonl"])
    run("1", H, "--ranker", r("R1.json"))
    run("T1-R1", T1, "--ranker", r("R1.json"))
    extract("D1.jsonl", "T1-R1")
    extract("D1p.jsonl", "T1-B")
    # 5
    fit("R2.json", ["D0.jsonl", "D1.jsonl"])
    fit("R2p.json", ["D0.jsonl", "D1p.jsonl"])
    run("2", H, "--ranker", r("R2.json"))
    run("T2-R2", T2, "--ranker", r("R2.json"))
    run("2p", H, "--ranker", r("R2p.json"))
    extract("D2.jsonl", "T2-R2")
    extract("D2p.jsonl", "T2-B")
    # 6
    fit("R3.json", ["D0.jsonl", "D1.jsonl", "D2.jsonl"])
    fit("R3p.json", ["D0.jsonl", "D1p.jsonl", "D2p.jsonl"])
    run("3", H, "--ranker", r("R3.json"))
    run("3p", H, "--ranker", r("R3p.json"))
    run("X", H, "--ranker", r("R3.json"), "--slots", "interleave")
    # 7
    labels = ["ref", "v1", "0a", "0b", "P0", "1", "2", "3", "2p", "3p", "X"]
    out = os.path.join(HERE, "results", "rsi-target1.md")
    sh(it + ["report", "--runs"] + [f"{k}={d(k)}" for k in labels] + ["--set", H,
             "--models", f"1={r('R1.json')}", f"2={r('R2.json')}", f"3={r('R3.json')}",
             f"2p={r('R2p.json')}", f"3p={r('R3p.json')}",
             "--training", T1, T2,
             "--rows", r("D0.jsonl"), r("D1.jsonl"), r("D2.jsonl"),
             "--stats"] + [r(f"{x}.stats.json") for x in ["D0", "D1", "D1p", "D2", "D2p"]]
       + ["--out", out])
    commit([out], "Target 1: results")
    print(json.dumps({"done": True, "report": out}))


if __name__ == "__main__":
    main()
