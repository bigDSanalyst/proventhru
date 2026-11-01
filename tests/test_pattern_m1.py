import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pattern_m1 as M  # noqa: E402

HAVE_COQ = shutil.which("coqtop") and shutil.which("coqc")


def reply(statements):
    content = json.dumps({"conjectures": [{"statement": s, "why": "w"} for s in statements]})
    return 200, {}, json.dumps({"model": M.MODEL, "choices": [
        {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]})


class Stand:
    """A stand-in server: K conjectures per call, and a count of calls."""

    def __init__(self):
        self.calls = 0

    def post(self, url, headers, body, timeout):
        self.calls += 1
        b = json.loads(body)
        assert b["response_format"]["json_schema"]["schema"] == M.SCHEMA
        return reply([f"forall l, length (sort l) = length l + {b['seed']} * 0"] * M.K)


class TestPrompt(unittest.TestCase):
    def test_shows_the_definitions_and_never_the_gold(self):
        text = M.body(M.MODEL, "invariance", 0)["messages"][0]["content"]
        self.assertIn("Fixpoint insert", text)
        self.assertIn("Inductive sorted", text)
        self.assertNotIn("(*", text)                    # comments removed
        gold = open(os.path.join(M.HERE, "pilots", "isort", "ISortGold.v")).read()
        for name in ("insert_length", "sort_length", "insert_sorted", "sort_perm", "sort_idem",
                     "sorted_sort_id", "insert_In", "insert_perm", "sort_sorted"):
            self.assertIn(name, gold)
            self.assertNotIn(name, text)

    def test_identity_is_stable_and_seeds_differ(self):
        self.assertEqual(M.prompt_sha256(), M.prompt_sha256())
        self.assertNotEqual(M.body(M.MODEL, "duality", 0), M.body(M.MODEL, "duality", 1))
        self.assertEqual(set(M.BATCHES["A"]) & set(M.BATCHES["B"]), set())

    def test_the_model_is_pinned(self):
        with self.assertRaises(SystemExit):
            M.preflight("Qwen/Qwen2.5-7B-Instruct")

    def test_proposals_are_cached_and_complete(self):
        d = tempfile.mkdtemp()
        try:
            stand = Stand()
            rows = M.propose("http://localhost:8000/v1", M.MODEL, d, os.path.join(d, "c.jsonl"),
                             transport=stand, log=lambda *_: None)
            calls = len(M.KINDS) * sum(len(s) for s in M.BATCHES.values())
            self.assertEqual(stand.calls, calls)
            self.assertEqual(len(rows), calls * M.K)
            self.assertEqual({r["batch"] for r in rows}, {"A", "B"})
            again = M.propose("http://localhost:8000/v1", M.MODEL, d, os.path.join(d, "c.jsonl"),
                              transport=stand, log=lambda *_: None)
            self.assertEqual(stand.calls, calls)        # every request came from the cache
            self.assertEqual(again, rows)
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestStatements(unittest.TestCase):
    def test_model_statements_become_candidates(self):
        from proventhru import pattern as P
        coq = P.Coq(notations=False, extra=("Require Import Sorted.",))
        rows = [{"batch": "A", "kind": "composition", "seed": 0, "index": i, "statement": s}
                for i, s in enumerate(["forall l, sort (sort l) = sort l.",
                                       "forall x l, In x (sort l) <-> In x l",
                                       "forall f l, map f (sort l) = sort (map f l)",
                                       "forall l, sort l = undefined_fn l",
                                       "forall l, length l"])] + [
            {"batch": "A", "kind": "duality", "seed": 0, "failure": "no conjectures list"}]
        try:
            out, counts = P.from_statements(coq, rows)
        finally:
            coq.close()
        self.assertEqual(out[0]["prefix"], "forall (l1 : list nat), eq (sort (sort l1)) (sort l1)")
        self.assertEqual(out[1]["data"], [("n", "nat"), ("l1", "list nat")])
        self.assertIsNone(out[2]["data"])               # a function variable: untested, kept
        self.assertEqual(counts, {"outside the first-order fragment": 1,
                                  "doesn't elaborate as a Prop": 2, "no usable answer": 1})


if __name__ == "__main__":
    unittest.main()
