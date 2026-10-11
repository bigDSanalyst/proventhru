"""tools/doctor.py: every guard is mutation-tested. Each test shows the check
passing on a clean fixture, breaks the one thing it guards, and shows it fail
(syndicate-genesis's rule: a guard is trusted only after it has been seen to
fail on the thing it checks)."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
HAVE_NUMPY = importlib.util.find_spec("numpy") is not None

spec = importlib.util.spec_from_file_location("doctor", ROOT / "tools" / "doctor.py")
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


def sh(repo, *args):
    return subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def status(checks, key):
    return {c.key: c.status for c in checks}[key]


class Fixture(unittest.TestCase):
    """A throwaway git repository holding copies of the files the checks read."""

    PREAMBLE = "Require Import Arith Lia List. Import ListNotations."

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        for rel in ("AGENTS.md", "PROTOCOL.md", "examples/eval_test.txt",
                    "examples/eval_test_renamed.txt", "examples/eval_open.txt"):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, self.repo / rel)
        sh(self.repo, "git", "init", "-q")
        sh(self.repo, "git", "config", "user.email", "doctor@test")
        sh(self.repo, "git", "config", "user.name", "doctor test")
        self.write("docs/x.md", "# x\n\nfrozen text\n")
        self.commit("base")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def commit(self, msg):
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-q", "--allow-empty", "-m", msg)
        return sh(self.repo, "git", "rev-parse", "--short", "HEAD")

    def sets(self, H, T1=(), T2=(), rest=()):
        for name, stmts in (("H", H), ("T1", T1), ("T2", T2), ("rest", rest)):
            self.write(f"examples/ranker_{name}.txt",
                       f"# preamble: {self.PREAMBLE}\n" + "".join(s + "\n" for s in stmts))


class TestFrozen(Fixture):
    def register(self):
        c = self.commit("freeze x")
        digest = hashlib.sha256((self.repo / "docs/x.md").read_bytes()).hexdigest()
        self.write("docs/frozen.md", "| document | version | sha256 | frozen at commit | date |\n"
                   "|---|---|---|---|---|\n"
                   f"| `docs/x.md` | v1 | `{digest}` | `{c}` | 2026-10-11 |\n")
        self.commit("register x")

    def test_a_changed_frozen_document_blocks(self):
        self.register()
        self.assertEqual(status(doctor.check_frozen(self.repo), "frozen"), "ok")
        self.write("docs/x.md", "# x\n\nfrozen text, edited\n")
        self.assertEqual(status(doctor.check_frozen(self.repo), "frozen"), "BLOCK")

    def test_a_freezing_commit_missing_from_history_blocks_but_not_on_a_shallow_clone(self):
        digest = hashlib.sha256((self.repo / "docs/x.md").read_bytes()).hexdigest()
        self.write("docs/frozen.md", f"| `docs/x.md` | v1 | `{digest}` | `deadbeef` | 2026-10-11 |\n")
        self.commit("register against a commit that isn't here")
        self.assertEqual(status(doctor.check_frozen(self.repo), "frozen"), "BLOCK")
        real = doctor.git

        def shallow(repo, *args):
            return "true" if args[:2] == ("rev-parse", "--is-shallow-repository") else real(repo, *args)
        with mock.patch.object(doctor, "git", shallow):
            checks = doctor.check_frozen(self.repo)
        self.assertEqual(status(checks, "frozen"), "ok")
        self.assertEqual(status(checks, "frozen.commits"), "LOOK")


class TestCodeRows(Fixture):
    def test_changed_governed_code_blocks(self):
        def code(repo):
            return hashlib.sha256((Path(repo) / "docs/x.md").read_bytes()).hexdigest()
        c = self.commit("code")
        self.write("docs/frozen.md", f"| `code:test` | v1 | `{code(self.repo)}` | `{c}` | 2026-10-11 |\n")
        self.commit("register code")
        with mock.patch.dict(doctor.CODE_ROWS, {"code:test": code}):
            self.assertEqual(status(doctor.check_frozen(self.repo), "frozen"), "ok")
            self.write("docs/x.md", "# x\n\nchanged code\n")
            self.assertEqual(status(doctor.check_frozen(self.repo), "frozen"), "BLOCK")

    def test_a_code_row_without_a_rule_blocks(self):
        c = self.commit("code")
        self.write("docs/frozen.md", f"| `code:unknown` | v1 | `{'0' * 64}` | `{c}` | 2026-10-11 |\n")
        self.assertEqual(status(doctor.check_frozen(self.repo), "frozen"), "BLOCK")


class TestDrafts(Fixture):
    def test_a_draft_is_a_decision_owed(self):
        self.assertEqual(status(doctor.check_drafts(self.repo), "drafts"), "ok")
        self.write("docs/y.md", "# y\n\nStatus: draft, under review.\n")
        self.assertEqual(status(doctor.check_drafts(self.repo), "drafts"), "DECIDE")


class TestClaims(Fixture):
    # The names are read from AGENTS.md, never written here: this file is
    # tracked, and the guard rightly blocks any tracked file that cites them.
    def test_citing_a_tool_agents_md_records_as_not_real_blocks(self):
        self.assertEqual(status(doctor.check_claims(self.repo), "claims"), "ok")
        name = doctor.fabricated_names(self.repo)[0]
        self.write("docs/notes.md", f"We use {name} to compile.\n")
        self.commit("cite a tool that doesn't exist")
        self.assertEqual(status(doctor.check_claims(self.repo), "claims"), "BLOCK")

    def test_the_names_come_from_agents_md(self):
        names = doctor.fabricated_names(self.repo)
        self.assertEqual(len(names), 3)
        text = (self.repo / "AGENTS.md").read_text()
        self.assertTrue(all(f"`{n}`" in text for n in names))


class TestProtocol(Fixture):
    def test_a_changed_registered_set_blocks(self):
        self.commit("protocol")
        self.assertEqual(status(doctor.check_protocol(self.repo), "protocol.sets"), "ok")
        p = self.repo / "examples/eval_test.txt"
        lines = p.read_text().splitlines(keepends=True)
        p.write_text("".join(lines[:-1]))          # drop the last statement
        self.assertEqual(status(doctor.check_protocol(self.repo), "protocol.sets"), "BLOCK")

    def test_an_uncommitted_protocol_change_blocks(self):
        self.commit("protocol")
        with open(self.repo / "PROTOCOL.md", "a") as fh:
            fh.write("\nan edit\n")
        self.assertEqual(status(doctor.check_protocol(self.repo), "protocol"), "BLOCK")


@unittest.skipUnless(HAVE_NUMPY, "the ranker extra (numpy) isn't installed")
class TestHeldout(Fixture):
    H = ["forall (l1 : list nat), length (rev l1) <= length l1 + 1"]
    # neither is a twin of a test or dev statement (checked); the first T1 this
    # test used was one, and the guard caught it
    T1 = ["forall (l1 : list nat) (n : nat), length (firstn n (rev l1)) <= length l1 + n"]

    def test_clean_sets_pass(self):
        self.sets(self.H, self.T1)
        self.assertEqual(status(doctor.check_heldout(self.repo), "heldout"), "ok")

    def test_a_twin_across_sets_blocks(self):
        twin = "forall (xs : list nat) (k : nat), length (firstn k (rev xs)) <= k + length xs"
        self.sets(self.H + [twin], self.T1)
        self.assertEqual(status(doctor.check_heldout(self.repo), "heldout"), "BLOCK")

    def test_a_test_statement_in_a_set_blocks(self):
        test_stmt = [ln for ln in (self.repo / "examples/eval_test.txt").read_text().splitlines()
                     if ln and not ln.startswith("#")][0]
        self.sets(self.H, self.T1 + [test_stmt])
        self.assertEqual(status(doctor.check_heldout(self.repo), "heldout"), "BLOCK")

    def test_a_training_row_from_a_held_out_set_blocks(self):
        self.sets(self.H, self.T1)
        self.write("results/ranker/D0.jsonl", json.dumps({"statement": self.H[0], "label": 1}) + "\n")
        self.assertEqual(status(doctor.check_heldout(self.repo), "heldout"), "BLOCK")

    def test_a_wrong_preamble_blocks(self):
        self.sets(self.H, self.T1)
        p = self.repo / "examples/ranker_T1.txt"
        p.write_text(p.read_text().replace(self.PREAMBLE, "Require Import Arith Lia List."))
        self.assertEqual(status(doctor.check_heldout(self.repo), "heldout"), "BLOCK")


class TestResults(Fixture):
    def rows(self, n_pos, n_neg):
        return "".join(json.dumps({"statement": f"s{i}", "label": int(i < n_pos)}) + "\n"
                       for i in range(n_pos + n_neg))

    def test_rows_that_disagree_with_their_stats_block(self):
        self.write("results/ranker/D0.jsonl", self.rows(2, 3))
        self.write("results/ranker/D0.stats.json", json.dumps({"rows": 5, "positives": 2}))
        self.assertEqual(status(doctor.check_results(self.repo), "results"), "ok")
        self.write("results/ranker/D0.stats.json", json.dumps({"rows": 5, "positives": 3}))
        self.assertEqual(status(doctor.check_results(self.repo), "results"), "BLOCK")

    def test_a_ranker_whose_rows_changed_blocks(self):
        d = self.write("results/ranker/D0.jsonl", self.rows(1, 1))
        self.write("results/ranker/D0.stats.json", json.dumps({"rows": 2, "positives": 1}))
        digest = hashlib.sha256(d.read_bytes()).hexdigest()
        self.write("results/ranker/R1.json", json.dumps(
            {"sources": [{"path": "results/ranker/D0.jsonl", "sha256": digest}]}))
        self.assertEqual(status(doctor.check_results(self.repo), "results"), "ok")
        self.write("results/ranker/D0.jsonl", self.rows(2, 0))
        self.write("results/ranker/D0.stats.json", json.dumps({"rows": 2, "positives": 2}))
        self.assertEqual(status(doctor.check_results(self.repo), "results"), "BLOCK")


class TestRecords(Fixture):
    def record(self, kernel="accepted"):
        from proventhru import record as rec
        path = self.repo / "runs" / "r" / "records.jsonl"
        path.parent.mkdir(parents=True)
        book = rec.RecordLog(str(path))
        pre = self.PREAMBLE
        book.append("episode", {"episode": "e1", "statement": "1 = 1", "preamble": pre,
                                "preamble_sha256": rec.sha256(pre),
                                "environment": {"backend": "coqtop", "prover": "coq-8.18.0"}})
        book.append("step", {"episode": "e1", "path": [], "tactic": "reflexivity.",
                             "session": {"outcome": "ok", "finished": True},
                             "kernel": {"verdict": kernel},
                             "phase": {k: None for k in rec.PHASE_FIELDS}})
        book.append("outcome", {"episode": "e1", "standing": "proved" if kernel == "accepted" else "open",
                                "proof": ["reflexivity."], "kernel": kernel if kernel == "accepted" else None})
        return path, rec.head(rec.load(str(path)))[1]

    def test_a_tampered_record_blocks(self):
        path, _ = self.record()
        self.assertEqual(status(doctor.check_records(self.repo, [str(path)]), "records.integrity"), "ok")
        lines = path.read_text().splitlines()
        lines[1] = lines[1].replace("reflexivity.", "lia.")
        path.write_text("\n".join(lines) + "\n")
        self.assertEqual(status(doctor.check_records(self.repo, [str(path)]), "records.integrity"), "BLOCK")

    def test_a_proof_the_kernel_did_not_check_is_degraded(self):
        path, _ = self.record(kernel="not_checked")
        checks = doctor.check_records(self.repo, [str(path)])
        self.assertEqual(status(checks, "records.integrity"), "ok")
        self.assertEqual(status(checks, "records.certificates"), "DEGRADED")

    def test_a_head_cited_in_a_committed_file_is_pinned(self):
        path, head = self.record()
        self.assertEqual(status(doctor.check_records(self.repo, [str(path)]), "records.pinned"), "LOOK")
        self.write("results/run.md", f"Record head {head[:12]}.\n")
        self.commit("cite the head")
        self.assertEqual(status(doctor.check_records(self.repo, [str(path)]), "records.pinned"), "ok")


class TestExit(Fixture):
    def test_exit_is_one_on_block_or_degraded_only(self):
        checks = [doctor.Check("a", "ok", "x"), doctor.Check("b", "LOOK", "y"), doctor.Check("c", "DECIDE", "z")]
        with mock.patch("builtins.print"):
            self.assertEqual(doctor.render(checks), 0)
            self.assertEqual(doctor.render(checks + [doctor.Check("d", "DEGRADED", "w")]), 1)
            self.assertEqual(doctor.render(checks + [doctor.Check("e", "BLOCK", "v")]), 1)


if __name__ == "__main__":
    unittest.main()
