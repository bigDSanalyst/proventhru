import shutil
import unittest

import numpy as np

from proventhru.goals import Goal
from proventhru.ranker import (FEATURES, Ranker, RankedRetrievalPolicy, conclusion, design,
                               features, fit, head, premises, relation)
from proventhru.retrieval import RetrievalPolicy
from proventhru.search import FixedTactics

HAVE_COQ = shutil.which("coqtop") and shutil.which("coqc")


class TestStatementParts(unittest.TestCase):
    def test_conclusion_and_premises(self):
        s = "forall [A : Type] (x y : list A), rev (x ++ y) = rev y ++ rev x"
        self.assertEqual(conclusion(s), "rev (x ++ y) = rev y ++ rev x")
        self.assertEqual(premises(s), 0)
        t = "forall n m : nat, n <= m -> forall p, p <= n -> p <= m"
        self.assertEqual(conclusion(t), "p <= m")
        self.assertEqual(premises(t), 2)

    def test_relation_and_head(self):
        rel, lhs, rhs = relation("length (l1 ++ l2) = length l1 + length l2")
        self.assertEqual((rel, lhs, rhs), ("eq", "length (l1 ++ l2)", "length l1 + length l2"))
        self.assertEqual(head(lhs), "length")
        self.assertEqual(head(rhs), "+")
        self.assertEqual(head("(l1 ++ l2)"), "++")
        self.assertEqual(relation("(a = b) <-> c")[0], "iff")

    def test_features(self):
        f = features("list_sum (l1 ++ l2) <= list_sum l1 + list_sum l2", ("l1, l2 : list nat",),
                     "list_sum_app",
                     "forall l1 l2 : list nat, list_sum (l1 ++ l2) = list_sum l1 + list_sum l2",
                     0, 0.1)
        self.assertEqual(set(f), set(FEATURES))
        self.assertEqual(f["cov_all"], 0.0)     # the goal's <= is not in the lemma
        self.assertEqual(f["cov_share"], 0.75)
        self.assertEqual(f["back_all"], 1.0)
        self.assertEqual(f["is_eq"], 1.0)
        self.assertEqual(f["rel_match"], 0.0)
        self.assertEqual(f["head_match"], 1.0)
        self.assertEqual(f["log_rank"], 0.0)


def rows_for(labels):
    """Training rows over two lemmas: 'good' always positive, 'bad' never."""
    out = []
    for i, (lemma, label, x) in enumerate(labels):
        f = {k: 0.0 for k in FEATURES if k != "prior"}
        f["cov_share"] = x
        out.append({"statement": f"s{i}", "lemma": lemma, "label": label, "features": f})
    return out


class TestModel(unittest.TestCase):
    def test_fit_is_deterministic_and_finds_the_sign(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(400, 3))
        y = (X[:, 0] - 0.5 * X[:, 1] + 0.3 * rng.normal(size=400) > 0).astype(float)
        a, b = fit(X, y), fit(X, y)
        self.assertEqual(a, b)
        self.assertGreater(a["weights"][0], 0)
        self.assertLess(a["weights"][1], 0)
        self.assertLess(a["gradient_norm"], 1e-6)

    def test_prior_is_out_of_fold(self):
        # each statement holds one row, so a row's prior never sees its own label
        rows = rows_for([("only_here", 1, 0.5)] + [("other", 0, 0.1)] * 20)
        X, y = design(rows)
        prior = X[0, FEATURES.index("prior")]
        self.assertLess(prior, 0.5)

    def test_select_keeps_ties_in_order_and_reports_positions(self):
        rows = rows_for([("good", 1, 1.0)] * 30 + [("bad", 0, 0.0)] * 30)
        r = Ranker.train(rows, sources=["test"])
        found = [("x%d" % i, "forall n : nat, n = n") for i in range(8)]
        picked, positions = r.select(Goal(0, "n = n"), found, 6)
        self.assertEqual(positions, sorted(positions))     # all equal: B's order
        self.assertEqual(len(picked), 6)
        self.assertEqual(r.sha256, Ranker(r.model).sha256)


class TestHook(unittest.TestCase):
    def test_retrieval_default_select_is_the_first_top(self):
        p = RetrievalPolicy(FixedTactics(), top=6)
        found = [(str(i), "") for i in range(10)]
        self.assertEqual(p.select(None, found), found[:6])

    def test_ranked_identity(self):
        rows = rows_for([("good", 1, 1.0)] * 5 + [("bad", 0, 0.0)] * 5)
        r = Ranker.train(rows, sources=["test"])
        p = RankedRetrievalPolicy(FixedTactics(), r)
        self.assertTrue(p.identity["id"].startswith("retrieval/v1+ranker/"))
        self.assertTrue(p.identity["id"].endswith("+fixed-tactics/v1"))
        self.assertEqual(p.identity["retrieval"]["ranker"]["sha256"], r.sha256)


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestRankedInSearch(unittest.TestCase):
    def test_proves_with_a_ranker_and_records_positions(self):
        from proventhru.env import CoqEnv
        from proventhru.search import best_first
        rows = rows_for([("good", 1, 1.0)] * 5 + [("bad", 0, 0.0)] * 5)
        pol = RankedRetrievalPolicy(FixedTactics(), Ranker.train(rows, sources=["test"]))
        stmt = "forall (l1 : list nat), length (rev l1) = length l1"
        with CoqEnv(stmt, "Require Import Arith Lia List. Import ListNotations.",
                    backend="coqtop") as env:
            res = best_first(env, pol, budget=None, step_budget=200)
        self.assertTrue(res.proved)
        self.assertIn("ranker", pol.last_cost)


if __name__ == "__main__":
    unittest.main()
