import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

HAVE_COQ = shutil.which("coqc")


@unittest.skipUnless(HAVE_COQ, "coqc not in PATH")
class TestNecessity(unittest.TestCase):
    """A premise the recorded proof doesn't use is replaced by True and the proof
    still closes the statement, so its symbol isn't needed. One the proof uses is."""

    @classmethod
    def setUpClass(cls):
        import pattern_recount as R
        cls.R = R
        R.PR.configure(4)
        cls.pre = R.PR.base_preamble()

    def check(self, statement, prefix, proof, connects):
        corpus = [{"name": "pt_r0_0", "statement": statement, "proof": proof, "cites": []}]
        r = {"statement": statement, "prefix": prefix, "connects": connects}
        return self.R.necessity(r, corpus, self.pre)

    def test_an_unused_premise_connects_nothing(self):
        # run 4's pt_r0_3, with its recorded proof
        out = self.check(
            "forall l1 l2 : list nat, sorted l1 -> sorted l2 -> l1 = l2 -> Permutation l1 l2",
            "forall (l1 : list nat) (l2 : list nat), forall (_ : sorted l1), "
            "forall (_ : sorted l2), forall (_ : eq l1 l2), Permutation l1 l2",
            ["intros.", "induction H1.", "reflexivity."], [["Permutation", "sorted"]])
        self.assertTrue(out["control"])
        self.assertEqual(out["symbols"]["Permutation"]["where"], "conclusion")
        self.assertEqual(out["symbols"]["sorted"]["where"], "premises")
        self.assertFalse(out["symbols"]["sorted"]["needed"])
        self.assertIn("forall (_ : True), forall (_ : True)", out["symbols"]["sorted"]["replaced"])
        self.assertEqual(out["kept"], [])

    def test_a_used_premise_is_needed(self):
        out = self.check("forall l1 : list nat, length l1 = 0 -> sorted l1",
                         "forall (l1 : list nat), forall (_ : eq (length l1) 0), sorted l1",
                         ["intros.", "destruct l1.", "constructor.", "discriminate."],
                         [["length", "sorted"]])
        self.assertTrue(out["control"])
        self.assertTrue(out["symbols"]["length"]["needed"])
        self.assertEqual(out["kept"], [["length", "sorted"]])

    def test_without_the_control_the_pairs_stand(self):
        out = self.check("forall l1 : list nat, length l1 = 0 -> sorted l1",
                         "forall (l1 : list nat), forall (_ : eq (length l1) 0), sorted l1",
                         ["intros.", "reflexivity."], [["length", "sorted"]])
        self.assertFalse(out["control"])
        self.assertEqual(out["symbols"], {})
        self.assertEqual(out["kept"], [["length", "sorted"]])


if __name__ == "__main__":
    unittest.main()
