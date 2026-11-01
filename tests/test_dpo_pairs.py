import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

HAVE_COQ = shutil.which("coqtop") and shutil.which("coqc")
PRE = ("Require Import Arith Lia. "
       "Fixpoint dbl (n : nat) : nat := match n with 0 => 0 | S k => S (S (dbl k)) end.")
STATEMENT = "forall n : nat, dbl n = n + n"      # open at the gate: needs induction


def chat(candidates):
    content = json.dumps({"candidates": [{"tactic": t, "argument": a} for t, a in candidates]})
    return 200, {}, json.dumps({"id": "c", "model": "org/m",
                                "choices": [{"message": {"role": "assistant", "content": content},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 5, "completion_tokens": 5}})


def wrong(*names):
    return [("exact", n) for n in names]


# The stand-in model's answer at each state, by (path, re-ask): the first ask at
# the root is refused everywhere, the re-ask finds induction, and one path
# finishes. Anything else gets five refused tactics.
ANSWERS = {
    ((), False): [("rewrite", "foo"), ("exact", "bar"), ("apply", "baz"), ("reflexivity", ""),
                  ("congruence", "")],
    ((), True): [("induction", "n")] + wrong("q1", "q2", "q3", "q4"),
    (("induction n.",), False): [("reflexivity", "")] + wrong("z1", "z2", "z3", "z4"),
    (("induction n.", "reflexivity."), False): [("simpl", "")] + wrong("y1", "y2", "y3", "y4"),
    (("induction n.", "reflexivity.", "simpl."), False): [("lia", "")] + wrong("x1", "x2", "x3",
                                                                               "x4"),
}


class Model:
    def post(self, url, headers, body, timeout):
        state = json.loads(json.loads(body)["messages"][1]["content"])
        key = (tuple(state["path"]), bool(state["tried_here"]))
        return chat(ANSWERS.get(key, wrong("w1", "w2", "w3", "w4", "w5")))


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestPairRule(unittest.TestCase):
    """A search whose first ask at the root is refused everywhere and whose
    re-ask finds the proof: the root state gives i < j pairs (rejected = the
    first ask as generated, chosen = it with the refused tactic replaced by
    t*), and every prompt is rebuilt from the record and verified against its
    cache key."""

    @classmethod
    def setUpClass(cls):
        import dpo_pairs
        from proventhru.pipeline import run
        from proventhru.policy_openai import OpenAICompatPolicy
        cls.dp = dpo_pairs
        cls.dir = tempfile.mkdtemp()
        cls.cache = os.path.join(cls.dir, "m1.jsonl")
        pol = OpenAICompatPolicy(PRE, "org/m", "http://localhost:8000/v1", key_env=None,
                                 response_format="json_schema", cache=cls.cache,
                                 transport=Model())
        run([STATEMENT], os.path.join(cls.dir, "C"), PRE, policy=pol, budget=None,
            step_budget=60, log=lambda *_: None, backend="coqtop")
        cls.trees = dpo_pairs.load(os.path.join(cls.dir, "C"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_every_prompt_rebuilds_to_its_cache_key(self):
        prompts = self.dp.Prompts()
        (t,) = self.trees
        for p in t.proposals:
            body, key = prompts.request(t, p)
            self.assertIsNotNone(body, key)
            self.assertEqual(key, p["cost"]["cache_key"], p["path"])

    def test_pairs_follow_the_rule(self):
        from collections import Counter
        old = self.dp.MIN_STEPS
        self.dp.MIN_STEPS = 0           # the test tree is short; the rule is what's tested
        try:
            chosen, fc = self.dp.frontier(self.trees)
            self.assertIn("an on-path tactic from a re-ask", fc)
            with open(self.cache) as fh:
                cache = {json.loads(ln)["key"]: json.loads(ln) for ln in fh}
            counts = Counter()
            out = self.dp.pairs("C", self.trees, chosen, cache, self.dp.Prompts(), {}, counts)
        finally:
            self.dp.MIN_STEPS = old
        root = [p for p in out if p["path"] == []]
        # three refused tactics of ask 1 (reflexivity and congruence beyond 3 per state)
        self.assertEqual([p["f"] for p in root], ["rewrite foo.", "exact bar.", "apply baz."])
        for p in root:
            self.assertEqual(p["branch"], "i < j")
            self.assertEqual(p["t_star"], "induction n.")
            rej, cho = json.loads(p["rejected"]), json.loads(p["chosen"])
            slot = [c["tactic"] + (" " + c["argument"] if c["argument"] else "") + "."
                    for c in rej["candidates"]].index(p["f"])
            self.assertEqual(cho["candidates"][slot], {"tactic": "induction", "argument": "n"})
            others = [i for i in range(5) if i != slot]
            self.assertEqual([cho["candidates"][i] for i in others],
                             [rej["candidates"][i] for i in others])
        self.assertEqual(counts["C: beyond 3 per state"], 1)
        # the later states' t* came from their only ask: no other ask, no pair
        self.assertFalse([p for p in out if p["path"]])

    def test_a_rerun_into_the_same_directory_is_set_aside(self):
        """The notebook's dev cell, run again after round 5, appended a replay of
        C's episodes to round 5's directory. Each statement keeps its first tree,
        and the replay adds no pairs past 3 per state."""
        from collections import Counter
        from proventhru.pipeline import run
        from proventhru.policy_openai import OpenAICompatPolicy
        d = os.path.join(self.dir, "C-rerun")
        shutil.copytree(os.path.join(self.dir, "C"), d)
        pol = OpenAICompatPolicy(PRE, "org/m", "http://localhost:8000/v1", key_env=None,
                                 response_format="json_schema", cache=self.cache,
                                 transport=Model())
        run([STATEMENT], d, PRE, policy=pol, budget=None, step_budget=60,
            log=lambda *_: None, backend="coqtop", resume=False)
        eps = [e for e in self.dp.rec.load(os.path.join(d, "records.jsonl"))
               if e["kind"] == "episode"]
        self.assertEqual(len(eps), 2)
        aside = Counter()
        trees = self.dp.load(d, aside)
        self.assertEqual([t.ep["episode"] for t in trees], [self.trees[0].ep["episode"]])
        self.assertEqual(aside, {"later episodes of a statement (a rerun)": 1})
        old = self.dp.MIN_STEPS
        self.dp.MIN_STEPS = 0
        try:
            chosen, _ = self.dp.frontier(trees)
            with open(self.cache) as fh:
                cache = {json.loads(ln)["key"]: json.loads(ln) for ln in fh}
            out = self.dp.pairs("C", trees, chosen, cache, self.dp.Prompts(), {}, Counter())
        finally:
            self.dp.MIN_STEPS = old
        self.assertEqual(len([p for p in out if p["path"] == []]), 3)

    def test_a_changed_record_doesnt_verify(self):
        prompts = self.dp.Prompts()
        (t,) = self.trees
        p = dict(t.proposals[1], path=list(t.proposals[1]["path"]))
        bad = dict(t.steps[0], session=dict(t.steps[0]["session"], error="another message"))
        t2 = self.dp.Tree(t.ep)
        t2.proposals, t2.steps = t.proposals, [bad] + t.steps[1:]
        _, key = prompts.request(t2, p)
        self.assertNotEqual(key, p["cost"]["cache_key"])


if __name__ == "__main__":
    unittest.main()
