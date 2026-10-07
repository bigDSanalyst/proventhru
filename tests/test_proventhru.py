import os
import shutil
import tempfile
import unittest

from proventhru import goals
from proventhru.env import guard

HAVE_COQ = shutil.which("coqtop") and shutil.which("coqc")


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
                  "apply (f_equal S)."]:
            self.assertIsNone(guard(t), t)


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


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestEnv(unittest.TestCase):
    def setUp(self):
        from proventhru.env import CoqEnv
        self.env = CoqEnv("forall n : nat, n + 0 = n")
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


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestKernel(unittest.TestCase):
    def test_kernel_rejects_what_the_session_accepted(self):
        """A fixpoint that fails the guard condition closes every goal in the
        session, and proves n = S n. Only Qed catches it."""
        from proventhru.env import CoqEnv
        with CoqEnv("forall n : nat, n = S n") as env:
            a = env.step(env.reset(), "fix IH 1.").node
            st = env.step(a, "exact IH.")
        self.assertTrue(st.done)
        self.assertFalse(st.signals["kernel"])
        self.assertLess(st.reward, 0)

    def test_axiom_in_preamble_is_caught(self):
        from proventhru.kernel import certify
        c = certify("Axiom cheat : forall P : Prop, P.", "1 = 2", ["apply cheat."])
        self.assertFalse(c.ok)


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestGate(unittest.TestCase):
    def test_statuses(self):
        from proventhru.gate import classify
        cases = {"forall n, n + 1": "ill_formed",
                 "forall n : nat, foo n": "ill_formed",
                 "forall n : nat, n = n": "trivial",
                 "forall n : nat, n < 0 -> n = 5": "vacuous",
                 "forall n m : nat, n + m = n": "refuted",
                 "forall l : list nat, rev (rev l) = l": "open"}
        for stmt, want in cases.items():
            res = classify(stmt)
            self.assertEqual(res.status, want, stmt)
            if want == "refuted":
                self.assertTrue(res.kernel)


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestPipeline(unittest.TestCase):
    def test_corpus_lines(self):
        import json
        from proventhru.pipeline import run
        with tempfile.TemporaryDirectory() as out:
            summary = run(["forall n : nat, n * n >= n", "forall n m : nat, n + m = n",
                           "forall n, n + 1"], out, budget=10, log=lambda *_: None)
            self.assertEqual(summary, {"proved": 1, "refuted": 1, "rejected": 1})
            with open(os.path.join(out, "corpus.jsonl")) as fh:
                rows = [json.loads(ln) for ln in fh]
            self.assertEqual(rows[0]["search"]["kernel"], True)
            self.assertTrue(os.path.getsize(os.path.join(out, "trajectories.jsonl")) > 0)


if __name__ == "__main__":
    unittest.main()
