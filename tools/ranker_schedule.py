"""Run RSI target 1 end to end, as pre-registered (docs/rsi-target1-ranker.md).

    python tools/ranker_schedule.py --runs RUNS_DIR [--tag TAG]

Every step is the fixed update rule; nothing between iterations is chosen
by hand. Steps are idempotent: a run resumes from its record, and a fit or
an extraction whose output exists is skipped. Each D and each fitted ranker
is committed before anything uses it, so the record's order is the git
history's.

Before anything runs, it refuses unless:
  - the doc's sha256 matches its docs/frozen.md row;
  - the governed code (GOVERNED) hashes to the latest `code:target-1` row;
  - every frozen file (D0, the sets) matches its row (doctor's check_frozen).
After every run it stops if an episode's preamble isn't v5's, relaunches a
run whose searches crashed (at most twice more), and annotates the record
with the doc hash, the code hash and the commit it ran under. It refuses to
resume a record started under a different doc or code hash: a rerun under the
bug rule takes a --tag, which namespaces the run directories, the D and R
files and the report.

  1. 0a, 0b: B' on H. 0b must equal 0a item for item (fingerprint: gate
     status, standing, proof, steps, expansions, stop reason, step trail).
  2. ref (A), v1 (B as registered) and P0 (placebo slots) on H.
  3. B' on T1 and on T2 (the controls' data, D1' and D2').
  4. R1 on D0; R1 on H (iteration 1) and on T1; D1 and D1' extracted.
  5. R2 on D0+D1 and R2' on D0+D1'; R2 on H (iteration 2), R2 on T2, R2' on H;
     D2 and D2' extracted.
  6. R3 on D0+D1+D2 and R3' on D0+D1'+D2'; R3 on H (iteration 3), R3' on H,
     and the interleaved run (B' and R3) on H.
  7. The report, results/rsi-target1.md (results/rsi-target1-TAG.md)."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

DOC = "docs/rsi-target1-ranker.md"
CODE_ROW = "code:target-1"
JOBS = 3                     # registered: outcomes can depend on load (Timeout 5, 30 s deadline)
H, T1, T2 = "examples/ranker_H.txt", "examples/ranker_T1.txt", "examples/ranker_T2.txt"
# The code whose behaviour the pre-registration fixes. A change to any of these
# after freezing is a bug fix under the bug rule, registered as a new row.
GOVERNED = [
    "proventhru/cli.py", "proventhru/coqtop.py", "proventhru/env.py", "proventhru/explore.py",
    "proventhru/gate.py", "proventhru/goals.py", "proventhru/keys.py", "proventhru/kernel.py",
    "proventhru/pipeline.py", "proventhru/ranker.py", "proventhru/record.py",
    "proventhru/retrieval.py", "proventhru/search.py", "proventhru/session.py",
    "tools/ranker_data.py", "tools/ranker_iterate.py", "tools/ranker_schedule.py",
    "tools/ranker_sets.py",
]


def code_hash(repo, paths=GOVERNED):
    """sha256 over the governed files' paths and contents, in order."""
    h = hashlib.sha256()
    for p in paths:
        with open(os.path.join(repo, p), "rb") as fh:
            h.update(f"{p} {hashlib.sha256(fh.read()).hexdigest()}\n".encode())
    return h.hexdigest()


def sh(argv):
    print("$ " + " ".join(argv), flush=True)
    rc = subprocess.call(argv, cwd=HERE)
    if rc:
        raise SystemExit(f"step failed ({rc}): {' '.join(argv)}")


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=HERE, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def commit(paths, message):
    sh(["git", "add"] + paths)
    if subprocess.call(["git", "diff", "--cached", "--quiet"], cwd=HERE):
        sh(["git", "commit", "-q", "-m", message])


def frozen_rows():
    with open(os.path.join(HERE, "docs", "frozen.md")) as fh:
        text = fh.read()
    return re.findall(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([0-9a-f]{64})`\s*\|\s*`([0-9a-f]+)`\s*\|",
                      text, re.M)


def preflight():
    """(doc sha256, code hash, freezing commit) or SystemExit."""
    rows = frozen_rows()
    with open(os.path.join(HERE, DOC), "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    docs = [r for r in rows if r[0] == DOC]
    if not docs:
        raise SystemExit(f"{DOC} has no row in docs/frozen.md: it isn't frozen")
    if docs[-1][2] != digest:
        raise SystemExit(f"{DOC} (sha256 {digest}) doesn't match its docs/frozen.md row")
    codes = [r for r in rows if r[0] == CODE_ROW]
    if not codes:
        raise SystemExit(f"no `{CODE_ROW}` row in docs/frozen.md")
    current = code_hash(HERE)
    if codes[-1][2] != current:
        raise SystemExit(f"the governed code hashes to {current[:16]}, not the registered "
                         f"{codes[-1][2][:16]} ({codes[-1][1]}): a change to it is a bug fix, "
                         "registered as a new row before anything runs under it")
    import doctor
    from pathlib import Path
    for c in doctor.check_frozen(Path(HERE)):
        if c.status == doctor.BLOCK:
            raise SystemExit(f"doctor: {c.headline}: {c.detail}")
    return digest, current, docs[-1][3]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--tag", default="", help="a rerun under the bug rule: namespaces runs, D, R and the report")
    a = ap.parse_args(argv)
    py = sys.executable
    it = [py, "tools/ranker_iterate.py"]
    runs_dir = os.path.join(a.runs, a.tag) if a.tag else a.runs
    res = os.path.join(HERE, "results", "ranker", a.tag) if a.tag else os.path.join(HERE, "results", "ranker")
    d = lambda label: os.path.join(runs_dir, label)                       # noqa: E731
    r = lambda name: os.path.join(HERE, "results", "ranker", name) if name == "D0.jsonl" \
        else os.path.join(res, name)                                       # noqa: E731

    digest, chash, frozen_at = preflight()
    head = git("rev-parse", "HEAD")
    from proventhru import record as rec
    from ranker_iterate import V5_PREAMBLE_SHA256, Run, fingerprint_diff

    def cites(book):
        return [e for e in book.entries if e.get("kind") == "annotation"
                and (e.get("data") or {}).get("by") == "tools/ranker_schedule.py"]

    def run(label, sset, *extra):
        path = os.path.join(d(label), "records.jsonl")
        if os.path.exists(path):
            notes = cites(rec.RecordLog(path))
            if notes and not any(digest in n["data"]["reason"] and chash in n["data"]["reason"]
                                 for n in notes):
                raise SystemExit(f"{path} was started under another doc or code hash: a rerun "
                                 "under the bug rule takes --tag")
        argv = it + ["run", "--set", sset, "--out", d(label), "--jobs", str(JOBS)] + list(extra)
        for attempt in range(3):
            sh(argv)
            crashed = [s for s, o in Run(d(label)).by_stmt.items() if o["crashed"]]
            if not crashed:
                break
            print(f"{label}: {len(crashed)} search(es) crashed; relaunching (pipeline resumes them)",
                  flush=True)
        book = rec.RecordLog(path)
        bad = [e["data"]["statement"] for e in book.entries if e.get("kind") == "episode"
               and e["data"].get("preamble_sha256") != V5_PREAMBLE_SHA256]
        if bad:
            raise SystemExit(f"{label}: {len(bad)} episode(s) ran under another preamble: invalid")
        if not any(digest in n["data"]["reason"] and chash in n["data"]["reason"] for n in cites(book)):
            dirty = git("status", "--porcelain", "--untracked-files=no")
            book.annotate(0, "note", f"RSI target 1 run {label}{' (' + a.tag + ')' if a.tag else ''}: "
                          f"{DOC} sha256 {digest} (frozen at {frozen_at}); governed code sha256 "
                          f"{chash}; commit {head}{' with uncommitted changes' if dirty else ''}",
                          by="tools/ranker_schedule.py")

    def fit(name, rows):
        if not os.path.exists(r(name)):
            os.makedirs(os.path.dirname(r(name)), exist_ok=True)
            sh(it + ["fit", "--rows"] + [r(x) for x in rows] + ["--out", r(name)])
        commit([r(name)], f"Target 1{' (' + a.tag + ')' if a.tag else ''}: fit {name} on {', '.join(rows)}")

    def extract(name, label):
        stats = os.path.splitext(r(name))[0] + ".stats.json"
        if not os.path.exists(r(name)):
            os.makedirs(os.path.dirname(r(name)), exist_ok=True)
            sh([py, "tools/ranker_data.py", d(label), "--out", r(name), "--jobs", str(JOBS)])
        commit([r(name), stats], f"Target 1{' (' + a.tag + ')' if a.tag else ''}: extract {name} "
               f"from run {label}")

    os.makedirs(runs_dir, exist_ok=True)
    if not os.path.exists(r("D0.jsonl")):
        raise SystemExit("results/ranker/D0.jsonl is missing: it is committed at the freezing commit")

    # 1
    run("0a", H)
    run("0b", H)
    diff = fingerprint_diff(d("0a"), d("0b"))
    if diff:
        raise SystemExit(f"0b differs from 0a on {len(diff)} statement(s), e.g. {diff[0]!r}: "
                         "stop and find the cause before iteration 1")
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
    out = os.path.join(HERE, "results", f"rsi-target1{'-' + a.tag if a.tag else ''}.md")
    sh(it + ["report", "--runs"] + [f"{k}={d(k)}" for k in labels] + ["--set", H,
             "--models", f"1={r('R1.json')}", f"2={r('R2.json')}", f"3={r('R3.json')}",
             f"2p={r('R2p.json')}", f"3p={r('R3p.json')}",
             "--training", T1, T2,
             "--rows", r("D0.jsonl"), r("D1.jsonl"), r("D2.jsonl"),
             "--stats"] + [os.path.splitext(r(f"{x}.jsonl"))[0] + ".stats.json"
                           for x in ["D0", "D1", "D1p", "D2", "D2p"]]
       + ["--out", out])
    commit([out], f"Target 1{' (' + a.tag + ')' if a.tag else ''}: results")
    print(json.dumps({"done": True, "report": out}))


if __name__ == "__main__":
    main()
