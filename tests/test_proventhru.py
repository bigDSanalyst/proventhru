import os
import shutil
import tempfile
import unittest

from proventhru import goals
from proventhru.env import guard
from proventhru.session import petanque_available

HAVE_COQ = shutil.which("coqtop") and shutil.which("coqc")
HAVE_PET = petanque_available()


class TestGuard(unittest.TestCase):
    def test_refuses_escape_hatches(self):
        for t in ["admit.", "Admitted.", "give_up.", "Abort.", "BackTo 2.", "Qed.",
                  "Require Import Classical.", "Axiom ax : False.", "Unshelve."]:
            self.assertIsNotNone(guard(t), t)

    def test_refuses_more_than_one_sentence(self):
        self.assertIsNotNone(guard("intros. admit."))
        self.assertIsNotNone(guard("intros"))
        self.assertIsNotNone(guard("(* hi *) intros."))
        self.assertIsNotNone(guard("- reflexivity."))

    def test_allows_tactics_and_qualified_names(self):
        for t in ["intros n m.", "rewrite Nat.add_comm.", "induction n; simpl; auto.",
                  "apply (f_equal S).", "all: lia.", "2: reflexivity.", "1-2: auto.",
                  "(intros; auto).", "try (simpl; reflexivity).", "now rewrite IHn."]:
            self.assertIsNone(guard(t), t)

    def test_refuses_commands(self):
        """Commands that run mid-proof and change the session: found by probing
        the earlier blocklist, which let them through."""
        for t in ['Cd "/tmp".', "Register nat as evil.nat.", "Optimize Heap.",
                  "Print LoadPath.", "Search nat.", "Show.", "Check nat.",
                  'Extraction "x.ml" nat.', "all: Cd \"/tmp\"."]:
            self.assertIsNotNone(guard(t), t)

    def test_baseline_policy_only_proposes_actions(self):
        from proventhru.goals import Goal, Observation
        from proventhru.search import FixedTactics
        obs = Observation((Goal(1, "n + 0 = n", ("n : nat", "IHn : n = n")),))
        for t, _ in FixedTactics().propose(obs, ()):
            self.assertIsNone(guard(t), t)


class TestStatement(unittest.TestCase):
    def test_sentence_breaks_are_refused(self):
        from proventhru.session import check_statement
        for bad in ["True. Axiom cheat : False", "True.", "1 = 1 (* hi *)"]:
            with self.assertRaises(ValueError, msg=bad):
                check_statement(bad)
        for ok in ["forall n : nat, Nat.add n 0 = n", "1.5 = 1.5"]:
            check_statement(ok)


class TestParse(unittest.TestCase):
    def test_two_goals(self):
        obs = goals.parse("2 goals (ID 7)\n  \n  n : nat\n  IHn : n + 0 = n\n"
                          "  ============================\n  0 + 0 = 0\n\n"
                          "goal 2 (ID 10) is:\n S n + 0 = S n\n\n")
        self.assertEqual([g.conclusion for g in obs.goals], ["0 + 0 = 0", "S n + 0 = S n"])
        self.assertEqual(obs.goals[0].hypotheses, ("n : nat", "IHn : n + 0 = n"))
        self.assertFalse(obs.finished)

    def test_finished(self):
        self.assertTrue(goals.parse("No more goals.\n\n").finished)

    def test_key_ignores_goal_ids(self):
        a = goals.parse("1 goal (ID 3)\n  ============================\n  n = n\n")
        b = goals.parse("1 goal (ID 9)\n  ============================\n  n = n\n")
        self.assertEqual(a.key, b.key)


class TestEnv:
    BACKEND = None
    def setUp(self):
        from proventhru.env import CoqEnv
        self.env = CoqEnv("forall n : nat, n + 0 = n", backend=self.BACKEND)
        self.root = self.env.reset()

    def tearDown(self):
        self.env.close()

    def test_step_error_leaves_state(self):
        st = self.env.step(self.root, "bogus.")
        self.assertIsNotNone(st.error)
        self.assertIsNone(st.node)
        self.assertLess(st.reward, 0)

    def test_branching(self):
        a = self.env.step(self.root, "intros n.").node
        b = self.env.step(a, "induction n.").node
        self.assertEqual(len(b.obs.goals), 2)
        c = self.env.step(a, "destruct n.").node        # sibling of b
        self.assertEqual(len(c.obs.goals), 2)
        d = self.env.step(b, "reflexivity.").node       # back into b's branch
        self.assertEqual(d.obs.goals[0].hypotheses[-1], "IHn : n + 0 = n")

    def test_finish_certifies(self):
        a = self.env.step(self.root, "intros n.").node
        st = self.env.step(a, "induction n; simpl; auto.")
        self.assertTrue(st.done)
        self.assertTrue(st.signals["kernel"])
        self.assertGreater(st.reward, 0.9)

    def test_revisit_penalised(self):
        st = self.env.step(self.root, "idtac.")
        self.assertTrue(st.signals["revisit"])

    def test_timeout_recovers(self):
        st = self.env.step(self.root, "repeat (assert True by trivial).")
        self.assertIsNotNone(st.error)
        a = self.env.step(self.root, "intros n.")
        self.assertIsNone(a.error)


class TestKernel:
    BACKEND = None
    def test_kernel_rejects_what_the_session_accepted(self):
        """A fixpoint that fails the guard condition closes every goal in the
        session, and proves n = S n. Only Qed catches it."""
        from proventhru.env import CoqEnv
        with CoqEnv("forall n : nat, n = S n", backend=self.BACKEND) as env:
            a = env.step(env.reset(), "fix IH 1.").node
            st = env.step(a, "exact IH.")
        self.assertTrue(st.done)
        self.assertFalse(st.signals["kernel"])
        self.assertLess(st.reward, 0)

    def test_axiom_in_preamble_is_caught(self):
        from proventhru.kernel import certify
        from proventhru.session import open_session
        s = open_session("", "True", self.BACKEND)
        compiler = s.compiler
        s.close()
        c = certify("Axiom cheat : forall P : Prop, P.", "1 = 2", ["apply cheat."],
                    compiler=compiler)
        self.assertFalse(c.ok)


class TestGate:
    BACKEND = None
    def test_statuses(self):
        from proventhru.gate import classify
        cases = {"forall n, n + 1": "ill_formed",
                 "True. Axiom cheat : False": "ill_formed",
                 "forall n : nat, foo n": "ill_formed",
                 "forall n : nat, n = n": "trivial",
                 "forall n : nat, n < 0 -> n = 5": "vacuous",
                 "forall n m : nat, n + m = n": "refuted",
                 "forall l : list nat, rev (rev l) = l": "open"}
        for stmt, want in cases.items():
            res = classify(stmt, backend=self.BACKEND)
            self.assertEqual(res.status, want, stmt)
            if want == "refuted":
                self.assertTrue(res.kernel)


class TestPipeline:
    BACKEND = None
    def test_corpus_lines(self):
        import json
        from proventhru.pipeline import run
        with tempfile.TemporaryDirectory() as out:
            summary = run(["forall n : nat, n * n >= n", "forall n m : nat, n + m = n",
                           "forall n, n + 1"], out, budget=10, log=lambda *_: None,
                          backend=self.BACKEND)
            self.assertEqual(summary, {"proved": 1, "refuted": 1, "rejected": 1})
            with open(os.path.join(out, "corpus.jsonl")) as fh:
                rows = [json.loads(ln) for ln in fh]
            self.assertEqual(rows[0]["search"]["kernel"], True)
            self.assertTrue(os.path.getsize(os.path.join(out, "trajectories.jsonl")) > 0)


def _per_backend(mixin, name, backend, available, why):
    cls = type(name, (mixin, unittest.TestCase), {"BACKEND": backend})
    globals()[name] = unittest.skipUnless(available, why)(cls)


for _mixin in (TestEnv, TestKernel, TestGate, TestPipeline):
    _per_backend(_mixin, _mixin.__name__ + "Coqtop", "coqtop", HAVE_COQ,
                 "coqtop/coqc not in PATH")
    _per_backend(_mixin, _mixin.__name__ + "Petanque", "petanque", HAVE_PET,
                 "pet (coq-lsp) or pytanque not installed")


@unittest.skipUnless(HAVE_PET, "pet (coq-lsp) or pytanque not installed")
class TestPetanqueRecovery(unittest.TestCase):
    def test_killed_process_replays_the_path(self):
        """Handles outlive the pet process that made them: a stale one is
        rebuilt by replaying its tactic path."""
        from proventhru.env import CoqEnv
        with CoqEnv("forall n : nat, n + 0 = n", backend="petanque") as env:
            a = env.step(env.reset(), "intros n.").node
            env.session.worker.kill()
            st = env.step(a, "induction n.")
            self.assertIsNone(st.error)
            self.assertEqual(len(st.node.obs.goals), 2)

    def test_every_goal_has_its_hypotheses(self):
        from proventhru.env import CoqEnv
        with CoqEnv("forall n m : nat, n + m = m + n", backend="petanque") as env:
            a = env.step(env.reset(), "intros n m.").node
            b = env.step(a, "induction n.").node
            self.assertEqual(b.obs.goals[1].hypotheses[-1], "IHn : n + m = m + n")


@unittest.skipUnless(HAVE_PET, "pet (coq-lsp) or pytanque not installed")
class TestPool(unittest.TestCase):
    STMT = "forall n : nat, n + 0 = n"

    def test_second_session_reuses_the_process(self):
        import time
        from proventhru.pool import Pool
        from proventhru.petanque import PetanqueSession
        pool = Pool(size=1)
        try:
            PetanqueSession("", self.STMT, pool=pool).close()          # launches pet
            t0 = time.perf_counter()
            s = PetanqueSession("", "forall n : nat, n * 1 = n", pool=pool)
            elapsed = time.perf_counter() - t0
            s.close()
            self.assertEqual(pool.workers[0].gen, 1, "one process served both")
            self.assertLess(elapsed, 0.3)
        finally:
            pool.close()

    def test_sessions_on_one_worker_are_isolated(self):
        from proventhru.pool import Pool
        from proventhru.petanque import PetanqueSession
        pool = Pool(size=1)
        try:
            a = PetanqueSession("Definition two := 2.", "two = 2", pool=pool)
            b = PetanqueSession("", self.STMT, pool=pool)
            self.assertIs(a.worker, b.worker)
            with self.assertRaises(Exception):
                b.query(b.root, "Check two.")
            h, obs = a.run(a.root, "reflexivity.")
            self.assertTrue(obs.finished)
            a.close(), b.close()
        finally:
            pool.close()

    def test_kill_on_a_shared_worker_is_recovered_by_the_other_session(self):
        """Session a's runaway tactic kills the worker at a's deadline; b's
        handles were made in the dead process and are rebuilt from their path."""
        from proventhru.pool import Pool
        from proventhru.petanque import PetanqueSession
        from proventhru.session import CoqTimeout
        pool = Pool(size=1)
        try:
            a = PetanqueSession("", "True", deadline=1.0, pool=pool)
            b = PetanqueSession("", self.STMT, pool=pool)
            hb, _ = b.run(b.root, "intros n.")
            gen = pool.workers[0].gen
            with self.assertRaises(CoqTimeout):
                a.run(a.root, "repeat (assert True by trivial).")   # no Rocq Timeout
            _, obs = b.run(hb, "induction n.")
            self.assertEqual(len(obs.goals), 2)
            self.assertGreater(pool.workers[0].gen, gen)
            a.close(), b.close()
        finally:
            pool.close()

    def test_sessions_on_different_workers_run_in_parallel(self):
        import threading
        from proventhru.pool import Pool
        from proventhru.petanque import PetanqueSession
        pool = Pool(size=2)
        results, errors = [], []

        def prove(stmt):
            try:
                s = PetanqueSession("", stmt, pool=pool)
                h, _ = s.run(s.root, "intros n.")
                _, obs = s.run(h, "induction n; simpl; auto.")
                results.append(obs.finished)
                s.close()
            except Exception as e:                      # surfaced below
                errors.append(repr(e))
        try:
            ts = [threading.Thread(target=prove, args=(st,)) for st in
                  ["forall n : nat, n + 0 = n", "forall n : nat, n * 1 = n",
                   "forall n : nat, 0 + n = n", "forall n : nat, n - 0 = n"]]
            [t.start() for t in ts]
            [t.join(60) for t in ts]
            self.assertEqual(errors, [])
            self.assertEqual(results, [True] * 4)
            self.assertEqual({w.gen for w in pool.workers}, {1})
        finally:
            pool.close()


if __name__ == "__main__":
    unittest.main()
