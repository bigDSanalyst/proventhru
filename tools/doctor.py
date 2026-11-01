#!/usr/bin/env python3
"""Is this proventhru tree fit to be a pull request, and what is the next command?

    python tools/doctor.py [--repo .] [--records RUN_DIR ...] [--tests] [--json]

Modelled on two doctors: syndicate-genesis's tools/doctor.py (the repository's
state, computed, never narrated) and Dharmapala's doctor.py (a ledger's
integrity: chains, unchecked certificates, refusals, keys read from the file
itself). Its contract is theirs:

  It reads and writes nothing. It computes; it does not advise. Every line is
  derived from the tree, the git history and the records, and the rules come
  from the modules that own them (record.verify, protocol.load, keys.twin_key,
  ranker_iterate.FORBIDDEN, AGENTS.md's list of tools that were not real), so a
  rule is never stated twice. A green check must never lie: what it did not
  compute, it says it did not compute.

STATUSES
  ok        nothing owed
  LOOK      worth reading; not a fault
  DECIDE    a decision not made yet (a pre-registration still in draft)
  WARN      works, but something is off or unfinished
  DEGRADED  holds, but on weaker ground than claimed (a proof the kernel didn't check)
  BLOCK     wrong now: a frozen document changed, a held-out set leaked, a record
            doesn't verify, a cited tool doesn't exist

EXIT
  0  nothing BLOCK or DEGRADED
  1  at least one BLOCK or DEGRADED

Offline: it never calls the network, so it doesn't check CI. A pull request's
checks are read on the pull request."""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

OK, LOOK, DECIDE, WARN, DEGRADED, BLOCK = "ok", "LOOK", "DECIDE", "WARN", "DEGRADED", "BLOCK"
FAILING = (BLOCK, DEGRADED)


class Check:
    """One computed finding. `fix` is a command or an act, never an opinion."""

    def __init__(self, key, status, headline, detail="", fix=""):
        self.key, self.status, self.headline, self.detail, self.fix = key, status, headline, detail, fix

    def as_dict(self):
        return {"check": self.key, "status": self.status, "headline": self.headline,
                "detail": self.detail, "fix": self.fix}


def git(repo, *args):
    """Stdout, or None. Never raises: doctor runs in trees that are mid-mess."""
    try:
        r = subprocess.run(("git",) + args, cwd=str(repo), text=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def tracked(repo):
    out = git(repo, "ls-files", "-z")
    return [p for p in (out or "").split("\0") if p]


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ─────────────────────────────── the tree ────────────────────────────────

def check_tree(repo):
    dirty = git(repo, "status", "--porcelain", "--untracked-files=no")
    untracked = git(repo, "status", "--porcelain", "--untracked-files=normal")
    out = []
    if dirty is None:
        return [Check("tree", BLOCK, "not a git repository", fix="run doctor from a proventhru clone")]
    if dirty:
        n = len(dirty.splitlines())
        out.append(Check("tree", WARN, f"{n} tracked file(s) differ from HEAD",
                         "Doctor checks the working tree, so its findings are about these "
                         "uncommitted changes, not about any commit a pull request carries.",
                         "commit or stash, then run doctor again"))
    else:
        out.append(Check("tree", OK, "the working tree matches HEAD"))
    extra = [ln for ln in (untracked or "").splitlines() if ln.startswith("??")]
    if extra:
        out.append(Check("untracked", LOOK, f"{len(extra)} untracked path(s)",
                         ", ".join(ln[3:] for ln in extra[:8]) + (" …" if len(extra) > 8 else "")))
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = git(repo, "rev-parse", "--abbrev-ref", "@{u}")
    if not upstream:
        out.append(Check("pushed", WARN, f"{branch} has no upstream",
                         fix=f"git push -u origin {branch}"))
    else:
        ahead = git(repo, "rev-list", "--count", "@{u}..HEAD")
        if ahead and ahead != "0":
            out.append(Check("pushed", WARN, f"{ahead} commit(s) on {branch} not on {upstream}",
                             "As of the last fetch; doctor does not call the network.",
                             f"git push origin {branch}"))
        else:
            out.append(Check("pushed", OK, f"{branch} is on {upstream} (as of the last fetch)"))
    return out


# ─────────────────────────── the truth layer ─────────────────────────────

def sets_table(text):
    """{set name: file} from PROTOCOL.md's Sets table."""
    return dict(re.findall(r"^\|\s*`(\w+)`\s*\|\s*`([^`]+)`\s*\|", text, re.M))


def check_protocol(repo):
    from proventhru import protocol as proto
    from proventhru.cli import _statements
    path = repo / "PROTOCOL.md"
    if not path.exists():
        return [Check("protocol", BLOCK, "no PROTOCOL.md")]
    cwd = os.getcwd()
    try:
        p = proto.load(str(path))
    except proto.ProtocolError as e:
        return [Check("protocol", BLOCK, "PROTOCOL.md doesn't hold", str(e),
                      "commit the change as a dated amendment, or restore the file")]
    finally:
        os.chdir(cwd)
    out = [Check("protocol", OK, f"PROTOCOL.md holds: sha256 {p['sha256'][:16]}, commit {str(p['commit'])[:12]}")]
    files = sets_table(path.read_text(encoding="utf-8"))
    bad, seen = [], []
    for name, want in (p["frozen"].get("sets") or {}).items():
        f = files.get(name)
        if not f or not (repo / f).exists():
            bad.append(f"{name}: no file for it in the Sets table")
            continue
        pre, stmts = _statements(str(repo / f))
        got = proto.statements_sha256(pre, stmts)
        seen.append(name)
        if got != want:
            bad.append(f"{name} ({f}): {got[:16]} against the frozen {want[:16]}")
    if bad:
        out.append(Check("protocol.sets", BLOCK, f"{len(bad)} registered set(s) don't match PROTOCOL.md",
                         "; ".join(bad), "restore the set, or register the change as an amendment"))
    else:
        out.append(Check("protocol.sets", OK, f"the registered sets match their frozen hashes: {', '.join(seen)}"))
    return out


def frozen_rows(text):
    """[(document, version, sha256, commit)] from docs/frozen.md's table."""
    return re.findall(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([0-9a-f]{64})`\s*\|\s*`([0-9a-f]+)`\s*\|",
                      text, re.M)


def _target1_code(repo):
    from ranker_schedule import code_hash
    return code_hash(str(repo))


def _pattern_run1_code(repo):
    from pattern_run import code_hash
    return code_hash(str(repo))


# Code rows in docs/frozen.md, and the module that owns each one's file list.
CODE_ROWS = {"code:target-1": _target1_code, "code:pattern-run-1": _pattern_run1_code}


def check_frozen(repo):
    path = repo / "docs" / "frozen.md"
    if not path.exists():
        return [Check("frozen", LOOK, "no docs/frozen.md registry")]
    latest = {}
    for doc, version, digest, commit in frozen_rows(path.read_text(encoding="utf-8")):
        latest[doc] = (version, digest, commit)
    bad, good, unseen = [], [], []
    shallow = git(repo, "rev-parse", "--is-shallow-repository") == "true"
    for doc, (version, digest, commit) in sorted(latest.items()):
        if doc.startswith("code:"):
            # frozen code: a hash over the files its owner governs
            owner = CODE_ROWS.get(doc)
            if owner is None:
                bad.append(f"{doc} {version}: no rule for this code row")
                continue
            got = owner(repo)
            if got != digest:
                bad.append(f"{doc} {version}: the governed code hashes to {got[:16]}, registered {digest[:16]}")
                continue
        else:
            f = repo / doc
            if not f.exists():
                bad.append(f"{doc} {version}: the file is gone")
                continue
            if sha256_file(f) != digest:
                bad.append(f"{doc} {version}: sha256 {sha256_file(f)[:16]}, registered {digest[:16]}")
                continue
        if git(repo, "cat-file", "-e", commit + "^{commit}") is None:
            if shallow:
                unseen.append(f"{doc} {version} ({commit})")
            else:
                bad.append(f"{doc} {version}: the freezing commit {commit} isn't in this history")
                continue
        good.append(f"{doc} {version}")
    out = []
    if bad:
        out.append(Check("frozen", BLOCK, f"{len(bad)} frozen document(s) changed since freezing",
                         "; ".join(bad),
                         "restore the frozen text; a change is a new version, added as a new row "
                         "with its own hash and commit"))
    else:
        out.append(Check("frozen", OK, f"{len(good)} frozen document(s) match their registered hashes: "
                         + ", ".join(good)))
    if unseen:
        out.append(Check("frozen.commits", LOOK, f"shallow clone: {len(unseen)} freezing commit(s) not checked",
                         "; ".join(unseen), "git fetch --unshallow, then run doctor again"))
    return out


def check_drafts(repo):
    drafts = []
    for f in sorted(glob.glob(str(repo / "docs" / "*.md"))):
        head = Path(f).read_text(encoding="utf-8").splitlines()[:12]
        if any(re.match(r"^Status:\s*\**draft", ln, re.I) for ln in head):
            drafts.append(os.path.relpath(f, repo))
    if not drafts:
        return [Check("drafts", OK, "no document in docs/ is marked draft")]
    return [Check("drafts", DECIDE, f"{len(drafts)} document(s) still marked draft: " + ", ".join(drafts),
                  "A draft governs nothing yet. Any run under it must wait until it is frozen "
                  "(its draft line removed, its hash in docs/frozen.md).",
                  "freeze it, or leave it out of anything that runs")]


def fabricated_names(repo):
    """The tools AGENTS.md records as cited here once and not real."""
    path = repo / "AGENTS.md"
    if not path.exists():
        return []
    text = " ".join(path.read_text(encoding="utf-8").split())
    m = re.search(r"([^.]*?)were once cited in this repository and were not real", text)
    return re.findall(r"`([^`]+)`", m.group(1)) if m else []


def check_claims(repo):
    names = fabricated_names(repo)
    if not names:
        return [Check("claims", LOOK, "AGENTS.md lists no tools known not to exist",
                      "doctor reads that list from AGENTS.md; with none there is nothing to check")]
    hits = []
    for rel in tracked(repo):
        if rel == "AGENTS.md":
            continue
        p = repo / rel
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n in names:
            if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text):
                hits.append(f"{rel}: {n}")
    if hits:
        return [Check("claims", BLOCK, f"{len(hits)} citation(s) of a tool that doesn't exist",
                      "; ".join(hits[:12]),
                      "remove the citation: AGENTS.md records these as cited once and not real")]
    return [Check("claims", OK, f"none of the tools AGENTS.md records as not real is cited: {', '.join(names)}")]


# ───────────────────────────── held-out sets ─────────────────────────────

def check_heldout(repo):
    from proventhru.cli import _statements
    from proventhru.keys import twin_key
    sets = {}
    for f in sorted(glob.glob(str(repo / "examples" / "ranker_*.txt"))):
        sets[Path(f).stem.replace("ranker_", "")] = f
    if not sets:
        return [Check("heldout", OK, "no target-1 sets in examples/")]
    v5 = {n: str(repo / "examples" / f) for n, f in
          (("test", "eval_test.txt"), ("test_renamed", "eval_test_renamed.txt"), ("dev", "eval_open.txt"))}
    pre_ref = _statements(v5["test"])[0]
    keys, bad = {}, []
    for name, f in {**sets, **v5}.items():
        pre, stmts = _statements(f)
        keys[name] = {twin_key(s) for s in stmts}
        if name in sets and pre != pre_ref:
            bad.append(f"{name}: preamble {pre!r} is not v5's {pre_ref!r}")
    names = sorted(sets)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            n = len(keys[a] & keys[b])
            if n:
                bad.append(f"{a} and {b} share {n} twin group(s)")
        for b in v5:
            n = len(keys[a] & keys[b])
            if n:
                bad.append(f"{a} holds {n} twin(s) of {b}")
    # training rows against what may not be trained on (ranker_iterate.FORBIDDEN)
    try:
        from ranker_iterate import FORBIDDEN
    except ImportError as e:        # the ranker extra (numpy) isn't installed
        return [Check("heldout", WARN, "couldn't load the training-row rule (tools/ranker_iterate.FORBIDDEN)",
                      str(e), "pip install -e '.[ranker]'")]
    forbidden = set()
    for p in FORBIDDEN:
        if (repo / p).exists():
            forbidden |= {twin_key(s) for s in _statements(str(repo / p))[1]}
    rows_checked = 0
    for f in sorted(glob.glob(str(repo / "results" / "ranker" / "D*.jsonl"))):
        with open(f) as fh:
            stmts = {json.loads(ln)["statement"] for ln in fh if ln.strip()}
        rows_checked += 1
        leak = [s for s in stmts if twin_key(s) in forbidden]
        if leak:
            bad.append(f"{os.path.relpath(f, repo)}: {len(leak)} statement(s) are twins of a held-out set")
    if bad:
        return [Check("heldout", BLOCK, f"{len(bad)} held-out problem(s)", "; ".join(bad),
                      "rebuild the sets with tools/ranker_sets.py, or drop the leaked rows; "
                      "nothing from a held-out set may be trained on")]
    return [Check("heldout", OK, f"target-1 sets ({', '.join(names)}) are pairwise twin-disjoint, hold no "
                  f"twin of test, test_renamed or dev, and carry v5's preamble; {rows_checked} training "
                  "file(s) hold no twin of a held-out set")]


# ─────────────────────────────── results ─────────────────────────────────

def check_results(repo):
    bad, n = [], 0
    for f in sorted(glob.glob(str(repo / "results" / "ranker" / "D*.jsonl"))):
        st = Path(f[: -len(".jsonl")] + ".stats.json")
        if not st.exists():
            bad.append(f"{os.path.relpath(f, repo)} has no stats file")
            continue
        stats = json.loads(st.read_text())
        with open(f) as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
        n += 1
        if len(rows) != stats.get("rows") or sum(r["label"] for r in rows) != stats.get("positives"):
            bad.append(f"{os.path.relpath(f, repo)}: {len(rows)} rows / {sum(r['label'] for r in rows)} "
                       f"positive, its stats say {stats.get('rows')} / {stats.get('positives')}")
    m = 0
    for f in sorted(glob.glob(str(repo / "results" / "ranker" / "R*.json"))):
        model = json.loads(Path(f).read_text())
        m += 1
        for s in model.get("sources") or []:
            src = repo / s["path"]
            if not src.exists():
                bad.append(f"{os.path.relpath(f, repo)} was fitted on {s['path']}, which is gone")
            elif sha256_file(src) != s["sha256"]:
                bad.append(f"{os.path.relpath(f, repo)} was fitted on {s['path']} at {s['sha256'][:16]}; "
                           f"it is now {sha256_file(src)[:16]}")
    if bad:
        return [Check("results", BLOCK, f"{len(bad)} result file(s) disagree with what produced them",
                      "; ".join(bad), "re-extract or refit; a model must cite the rows it was fitted on")]
    return [Check("results", OK, f"{n} training file(s) match their stats; {m} fitted ranker(s) match "
                  "the rows they cite")]


# ─────────────────────────────── records ─────────────────────────────────

def record_files(paths):
    out = []
    for p in paths:
        out += [p] if os.path.isfile(p) else sorted(glob.glob(os.path.join(p, "**", "records.jsonl"),
                                                              recursive=True))
    return out


def check_records(repo, paths):
    if not paths:
        return [Check("records", LOOK, "no run records given",
                      "Pass --records RUN_DIR to check the hash chains, the kernel's certificates, "
                      "refusals and withdrawals of the runs a pull request reports.")]
    from proventhru import record as rec
    files = record_files(paths)
    if not files:
        return [Check("records", BLOCK, "no records.jsonl under the paths given", ", ".join(paths))]
    broken, unchecked, refused, withdrawn, unpinned, total = [], 0, 0, 0, [], 0
    corpus_text = None
    for f in files:
        entries = rec.load(f)
        total += 1
        problems = rec.verify(entries)
        if problems:
            broken.append(f"{f}: {len(problems)} problem(s), first: {problems[0]}")
            continue
        for e in entries:
            d = e["data"]
            if e["kind"] == "step":
                if (d.get("kernel") or {}).get("verdict") == "not_checked":
                    unchecked += 1
                if (d.get("session") or {}).get("outcome") == "refused":
                    refused += 1
            elif e["kind"] == "annotation" and d.get("label") in ("unsound", "retracted"):
                withdrawn += 1
        size, head = rec.head(entries)
        if corpus_text is None:
            corpus_text = ""
            for rel in tracked(repo):
                if rel.endswith((".md", ".json", ".txt")):
                    try:
                        corpus_text += (repo / rel).read_text(encoding="utf-8")
                    except (UnicodeDecodeError, OSError):
                        pass
        if head[:8] not in corpus_text:
            unpinned.append(f)
    out = []
    if broken:
        out.append(Check("records.integrity", BLOCK, f"{len(broken)} of {total} record(s) don't verify",
                         "; ".join(broken[:6]),
                         "don't trust a record that doesn't verify; find what edited or truncated it"))
    else:
        out.append(Check("records.integrity", OK, f"{total} record(s): chains intact, every entry well formed"))
    if unchecked:
        out.append(Check("records.certificates", DEGRADED,
                         f"{unchecked} finishing step(s) the kernel didn't check (verdict not_checked)",
                         "A proof the kernel didn't check is the search's claim, not the kernel's.",
                         "install coqc and rerun the affected statements"))
    else:
        out.append(Check("records.certificates", OK, "every finishing step was checked by the kernel"))
    if refused:
        out.append(Check("records.refusals", LOOK, f"{refused} tactic(s) refused by the guard"))
    if withdrawn:
        out.append(Check("records.withdrawn", LOOK, f"{withdrawn} outcome(s) annotated unsound or retracted",
                         "proventhru corpus RECORD shows them as withdrawn"))
    if unpinned:
        out.append(Check("records.pinned", LOOK,
                         f"{len(unpinned)} of {total} record head(s) are cited in no committed file",
                         "A hash chain shows only that the file agrees with itself. A head cited in "
                         "a committed results file is pinned outside it.",
                         "cite each head (proventhru verify RECORD prints it) in the results "
                         "document that reports the run"))
    else:
        out.append(Check("records.pinned", OK, "every record's head is cited in a committed file"))
    return out


# ──────────────────────────────── tests ──────────────────────────────────

def check_tests(repo, run):
    if not run:
        return [Check("tests", LOOK, "the test suite was not run", fix="python tools/doctor.py --tests")]
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=str(repo),
                       capture_output=True, text=True)
    tail = (r.stderr or r.stdout).strip().splitlines()[-1:]
    if r.returncode:
        return [Check("tests", BLOCK, "the test suite fails", " ".join(tail),
                      "python -m unittest discover -s tests -v; a failing test is the finding")]
    return [Check("tests", OK, "the test suite passes: " + " ".join(tail))]


# ───────────────────────────────── driver ────────────────────────────────

def run(repo, records=(), tests=False):
    checks = []
    checks += check_tree(repo)
    checks += check_protocol(repo)
    checks += check_frozen(repo)
    checks += check_drafts(repo)
    checks += check_claims(repo)
    checks += check_heldout(repo)
    checks += check_results(repo)
    checks += check_records(repo, list(records))
    checks += check_tests(repo, tests)
    return checks


def wrap(text, width, indent):
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(line)
    return ("\n" + indent).join(out)


def render(checks, verbose=False):
    print("proventhru doctor")
    print()
    for c in checks:
        print("  %-8s %s" % (c.status, c.headline))
        if c.status != OK or verbose:
            if c.detail:
                print("           " + wrap(c.detail, 68, "           "))
            if c.fix:
                print("           next: " + wrap(c.fix, 62, "                 "))
            print()
    failing = [c for c in checks if c.status in FAILING]
    if failing:
        print("  Start here: " + failing[0].headline)
        print()
    count = {s: len([c for c in checks if c.status == s]) for s in (BLOCK, DEGRADED, DECIDE, WARN, LOOK)}
    print("  %d blocked, %d degraded, %d decision(s) owed, %d warning(s), %d to look at."
          % (count[BLOCK], count[DEGRADED], count[DECIDE], count[WARN], count[LOOK]))
    return 1 if failing else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=".", help="the proventhru tree to check (default: here)")
    ap.add_argument("--records", nargs="*", default=[], help="run directories or records.jsonl files")
    ap.add_argument("--tests", action="store_true", help="also run the test suite")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable; what an agent should report instead of its own impression")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    checks = run(repo, a.records, a.tests)
    if a.json:
        failing = [c for c in checks if c.status in FAILING]
        print(json.dumps({"failing": len(failing), "next": failing[0].as_dict() if failing else None,
                          "checks": [c.as_dict() for c in checks]}, indent=2))
        return 1 if failing else 0
    return render(checks, a.verbose)


if __name__ == "__main__":
    sys.exit(main())
