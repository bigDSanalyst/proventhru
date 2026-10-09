"""The experiment machinery: step budgets, the OpenAI-compatible policy, the
protocol check, resume, the report's failure classes and McNemar, and the
eval-set generator."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from proventhru.goals import Goal, Observation

HAVE_COQ = shutil.which("coqtop") and shutil.which("coqc")
HAVE_GIT = shutil.which("git")
PRE = "Require Import Arith Lia."


def chat(content, finish="stop", model="org/m", tokens=(50, 10)):
    return json.dumps({"id": "cmpl-1", "model": model,
                       "choices": [{"message": {"role": "assistant", "content": content},
                                    "finish_reason": finish}],
                       "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]}})


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def post(self, url, headers, body, timeout):
        self.requests.append({"url": url, "headers": headers, "body": json.loads(body)})
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok(content, **kw):
    return 200, {"x-inference-provider": "together", "X-Request-Id": "req-9"}, chat(content, **kw)


def obs():
    return Observation(goals=(Goal(1, "n + 0 = n", ("n : nat",)),))


def policy(replies, **kw):
    from proventhru.policy_openai import OpenAICompatPolicy
    t = FakeTransport(replies)
    kw.setdefault("sleep", lambda s: None)
    p = OpenAICompatPolicy(PRE, "org/m:together", "https://router.example/v1", transport=t, **kw)
    return p, t


class TestOpenAICompat(unittest.TestCase):
    def test_request_shape_and_key_from_the_environment(self):
        os.environ["PT_TEST_KEY"] = "sekrit"
        try:
            p, t = policy([ok('{"candidates": [{"tactic": "lia", "argument": ""}]}')],
                          key_env="PT_TEST_KEY", response_format="json_schema", seed=7)
            p.propose(obs(), ["intros n."])
        finally:
            del os.environ["PT_TEST_KEY"]
        r = t.requests[0]
        self.assertEqual(r["url"], "https://router.example/v1/chat/completions")
        self.assertEqual(r["headers"]["Authorization"], "Bearer sekrit")
        b = r["body"]
        self.assertEqual((b["model"], b["temperature"], b["seed"]), ("org/m:together", 0.0, 7))
        self.assertEqual(b["response_format"]["type"], "json_schema")
        cands = b["response_format"]["json_schema"]["schema"]["properties"]["candidates"]
        self.assertEqual((cands["minItems"], cands["maxItems"]), (5, 5))   # exactly k
        self.assertIn("Allowed tactic names: intros", b["messages"][0]["content"])
        state = json.loads(b["messages"][1]["content"])
        self.assertEqual(state["path"], ["intros n."])
        self.assertEqual(state["goals"][0]["type"], "n + 0 = n")
        self.assertNotIn("sekrit", json.dumps(p.identity))

    def test_fenced_reply_assembled_checked_and_costed(self):
        reply = ('Here:\n```json\n{"candidates": [{"tactic": "lia", "argument": ""},'
                 '{"tactic": "omega", "argument": ""}, {"tactic": "rewrite", "argument": "H; lia"},'
                 '{"tactic": "lia", "argument": ""}, {"tactic": "induction", "argument": "n"}]}\n```')
        p, _ = policy([ok(reply, model="org/m-served")])
        out = p.propose(obs(), [])
        self.assertEqual([t for t, _ in out], ["lia.", "induction n."])
        c = p.last_cost
        self.assertEqual(len(c["dropped"]), 3)       # out of vocabulary, tactical, duplicate
        self.assertIsNone(c["failure"])
        self.assertEqual((c["served_model"], c["served_provider"]), ("org/m-served", "together"))
        self.assertEqual((c["input_tokens"], c["output_tokens"]), (50, 10))
        self.assertEqual(c["request_id"], "req-9")

    def test_invalid_responses_are_invalid_not_api_failures(self):
        p, _ = policy([ok("I think you should use induction."),
                       ok('{"candidates": [{"tactic": "lia"', finish="length"),
                       ok('{"candidates": [{"tactic": "omega", "argument": ""}]}'),
                       ok('{"tactics": []}')])
        whys = []
        for _ in range(4):
            self.assertEqual(p.propose(obs(), []), [])
            self.assertEqual(p.last_cost["failure"]["kind"], "invalid")
            whys.append(p.last_cost["failure"]["why"])
        self.assertEqual(whys, ["not JSON", "cut off at max_tokens", "no valid candidate",
                                "no candidates list"])

    def test_transient_failures_are_retried_and_listed(self):
        slept = []
        p, t = policy([(429, {"Retry-After": "3"}, "slow down"), (503, {}, "busy"),
                       TimeoutError("read timed out"),
                       ok('{"candidates": [{"tactic": "lia", "argument": ""}]}')],
                      sleep=slept.append)
        self.assertEqual(p.propose(obs(), []), [("lia.", 1.0)])
        c = p.last_cost
        self.assertEqual(c["retries"], 3)
        self.assertEqual([e["status"] for e in c["api_errors"]], [429, 503, None])
        self.assertGreaterEqual(slept[0], 3.0)        # Retry-After is honoured
        self.assertIsNone(c["failure"])

    def test_exhausted_or_unfixable_api_failure_raises_with_its_cost(self):
        from proventhru.policy_openai import ModelUnavailable
        p, t = policy([(503, {}, "down")] * 3, retries=2)
        with self.assertRaises(ModelUnavailable) as cm:
            p.propose(obs(), [])
        self.assertEqual(cm.exception.cost["failure"]["kind"], "api")
        self.assertEqual(len(t.requests), 3)
        self.assertTrue(cm.exception.unavailable)
        p, t = policy([(401, {}, "bad token")], retries=5)
        with self.assertRaises(ModelUnavailable):
            p.propose(obs(), [])
        self.assertEqual(len(t.requests), 1)          # a 4xx is not retried

    def test_cache_makes_reruns_free_and_identical(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.jsonl")
            p, t = policy([ok('{"candidates": [{"tactic": "lia", "argument": ""}]}')], cache=path)
            first = p.propose(obs(), [])
            self.assertEqual(p.last_cost["cache"], "miss")
            from proventhru import policy_openai as po
            po._CACHES.clear()                        # as if a new process: from disk
            again, t2 = policy([], cache=path)
            self.assertEqual(again.propose(obs(), []), first)
            self.assertEqual(again.last_cost["cache"], "hit")
            self.assertEqual(t2.requests, [])
            other, t3 = policy([ok('{"candidates": []}')], cache=path, seed=1)
            other.propose(obs(), [])                  # a different request is not a hit
            self.assertEqual(len(t3.requests), 1)

    def test_prompt_hash_covers_the_template(self):
        from proventhru import policy_openai as po
        h = po.prompt_sha256()
        p, _ = policy([])
        self.assertEqual(p.identity["prompt_sha256"], h)
        saved = po.PROMPT
        try:
            po.PROMPT = saved + " "
            self.assertNotEqual(po.prompt_sha256(), h)
        finally:
            po.PROMPT = saved


class TestMcNemar(unittest.TestCase):
    def test_exact_values(self):
        from proventhru.report import mcnemar
        self.assertEqual(mcnemar(0, 0), 1.0)
        self.assertAlmostEqual(mcnemar(0, 6), 0.03125)      # 2 / 2**6
        self.assertAlmostEqual(mcnemar(1, 6), 0.125)
        self.assertGreater(mcnemar(2, 5), 0.05)


def git_repo(d):
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", d, *args], check=True)


def write_protocol(d, frozen):
    path = os.path.join(d, "PROTOCOL.md")
    with open(path, "w") as fh:
        fh.write("# Protocol\n\n```json frozen\n" + json.dumps(frozen, indent=1) + "\n```\n")
    return path


def commit(d):
    subprocess.run(["git", "-C", d, "add", "-A"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "protocol"], check=True)


@unittest.skipUnless(HAVE_GIT, "git not in PATH")
class TestProtocol(unittest.TestCase):
    STMTS = ["forall n : nat, n + 0 = n"]
    ENV = {"backend": "coqtop", "prover": "coq-8.18.0"}

    def frozen(self, **kw):
        from proventhru.protocol import statements_sha256
        f = {"sets": {"dev": statements_sha256(PRE, ["dev statement"]),
                      "test": statements_sha256(PRE, self.STMTS)},
             "held_out": ["test"], "environment": self.ENV,
             "searches": [{"budget": None, "step_budget": 250}],
             "policies": ["fixed-tactics/v1", "openai-compat/v1"],
             "prompts": [], "models": ["org/m:together"], "k": 5}
        f.update(kw)
        return f

    def test_uncommitted_or_modified_protocol_is_refused(self):
        from proventhru.protocol import load, ProtocolError
        with tempfile.TemporaryDirectory() as d:
            git_repo(d)
            path = write_protocol(d, self.frozen())
            with self.assertRaisesRegex(ProtocolError, "not committed"):
                load(path)
            commit(d)
            p = load(path)
            self.assertEqual(len(p["sha256"]), 64)
            self.assertEqual(len(p["commit"]), 40)
            with open(path, "a") as fh:
                fh.write("\nan unrecorded change\n")
            with self.assertRaisesRegex(ProtocolError, "differs"):
                load(path)

    def test_check(self):
        from proventhru.protocol import check, load, ProtocolError
        from proventhru.policy_openai import prompt_sha256
        model = {"id": "openai-compat/v1", "model": "org/m:together", "k": 5,
                 "prompt_sha256": prompt_sha256()}
        fixed = {"id": "fixed-tactics/v1", "model": None}
        search = {"budget": None, "step_budget": 250}
        with tempfile.TemporaryDirectory() as d:
            git_repo(d)
            path = write_protocol(d, self.frozen())
            commit(d)
            p = load(path)
            with self.assertRaisesRegex(ProtocolError, "not a registered set"):
                check(p, PRE, ["something else"], fixed, self.ENV, search)
            # dev: any prompt and model may run
            self.assertEqual(check(p, PRE, ["dev statement"], dict(model, model="x"),
                                   self.ENV, {"budget": 3})["set"], "dev")
            # held out: the baseline runs, the model waits for a frozen prompt
            stamp = check(p, PRE, self.STMTS, fixed, self.ENV, search)
            self.assertEqual((stamp["set"], stamp["sha256"]), ("test", p["sha256"]))
            with self.assertRaisesRegex(ProtocolError, "no prompt is frozen"):
                check(p, PRE, self.STMTS, model, self.ENV, search)
            with self.assertRaisesRegex(ProtocolError, "search"):
                check(p, PRE, self.STMTS, fixed, self.ENV, {"budget": 200, "step_budget": None})
            with self.assertRaisesRegex(ProtocolError, "prover"):
                check(p, PRE, self.STMTS, fixed, dict(self.ENV, prover="rocq-9.1.1"), search)
            # the amendment that freezes the prompt is a new commit and a new hash
            write_protocol(d, self.frozen(prompts=[prompt_sha256()]))
            commit(d)
            p2 = load(path)
            self.assertNotEqual(p2["sha256"], p["sha256"])
            self.assertEqual(check(p2, PRE, self.STMTS, model, self.ENV, search)["set"], "test")
            with self.assertRaisesRegex(ProtocolError, "model"):
                check(p2, PRE, self.STMTS, dict(model, model="org/other"), self.ENV, search)
            with self.assertRaisesRegex(ProtocolError, "k="):
                check(p2, PRE, self.STMTS, dict(model, k=8), self.ENV, search)
            with self.assertRaisesRegex(ProtocolError, "prompt"):
                check(p2, PRE, self.STMTS, dict(model, prompt_sha256="0" * 64), self.ENV, search)


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestStepBudget(unittest.TestCase):
    def test_every_submitted_tactic_counts_and_the_cap_is_exact(self):
        from proventhru.env import CoqEnv
        from proventhru.search import best_first, Policy

        class Stubborn(Policy):
            identity = {"id": "stubborn", "model": None, "provider": None}

            def propose(self, obs, path, last_failure=None):
                # one ok, one Coq error, one the guard refuses, per node
                return [("simpl.", 1.0), ("exact I.", 0.9), ("admit.", 0.8), ("intros.", 0.7)]

        with CoqEnv("forall n : nat, n * n >= n", PRE, backend="coqtop") as env:
            res = best_first(env, Stubborn(), budget=None, step_budget=7)
        self.assertFalse(res.proved)
        self.assertEqual(len(res.steps), 7)
        self.assertEqual(res.stopped, "step_budget")
        outcomes = {s.outcome for s in res.steps}
        self.assertTrue({"ok", "error", "refused"} <= outcomes)
        self.assertEqual(res.record()["invocations"], res.expansions)
        self.assertEqual(res.expansions, 2)            # 4 + 3 tactics: the cap fell mid-node


class Unavailable(RuntimeError):
    unavailable = True


@unittest.skipUnless(HAVE_COQ and HAVE_GIT, "coqtop/coqc or git not in PATH")
class TestPipelineProtocolAndResume(unittest.TestCase):
    STMTS = ["forall n : nat, n * n >= n", "forall n : nat, n * (n + 1) >= n"]

    def test_episodes_cite_the_protocol_resume_and_a_down_policy_stops_the_run(self):
        from proventhru import record as rec
        from proventhru.pipeline import run, RECORD, environment, PolicyUnavailable
        from proventhru.protocol import load, statements_sha256
        from proventhru.search import FixedTactics
        from proventhru.report import summarize
        env = environment(PRE, "coqtop")
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            git_repo(d)
            path = write_protocol(d, {
                "sets": {"test": statements_sha256(PRE, self.STMTS)}, "held_out": ["test"],
                "environment": {"backend": "coqtop", "prover": env["prover"]},
                "searches": [{"budget": None, "step_budget": 60}],
                "policies": ["fixed-tactics/v1", "flaky"]})
            commit(d)
            p = load(path)

            class Flaky(FixedTactics):
                identity = {"id": "flaky", "model": None, "provider": None}
                calls = 0

                def propose(self, obs, path, last_failure=None):
                    Flaky.calls += 1
                    if Flaky.down:
                        raise Unavailable("503 after retries")
                    return super().propose(obs, path, last_failure)

            Flaky.down = True
            kw = dict(budget=None, step_budget=60, protocol=p, log=lambda *_: None,
                      backend="coqtop")
            with self.assertRaises(PolicyUnavailable):
                run(self.STMTS, out, PRE, policy=Flaky(), **kw)
            entries = rec.load(os.path.join(out, RECORD))
            self.assertEqual(rec.verify(entries), [])
            self.assertEqual(len([e for e in entries if e["kind"] == "episode"]), 1)
            s = summarize(entries)
            self.assertEqual(s["incomplete"], [self.STMTS[0]])   # not a result
            Flaky.down = False
            summary = run(self.STMTS, out, PRE, policy=Flaky(), **kw)
            self.assertEqual(sum(summary.values()), 2)      # both settled this time
            again = run(self.STMTS, out, PRE, policy=Flaky(), **kw)
            self.assertEqual(again, {"resumed": 2})
            entries = rec.load(os.path.join(out, RECORD))
            self.assertEqual(rec.verify(entries), [])
            eps = [e["data"] for e in entries if e["kind"] == "episode"]
            self.assertTrue(all(e["protocol"]["sha256"] == p["sha256"] for e in eps))
            self.assertEqual([e["item"] for e in eps], [0, 0, 1])
            s = summarize(entries)
            self.assertEqual(s["incomplete"], [])
            self.assertIn(self.STMTS[0], s["proved"])
            self.assertLessEqual(max(r["data"]["stats"]["steps"] for r in entries
                                     if r["kind"] == "outcome" and "steps" in r["data"]["stats"]),
                                 60)


class TestModelFailuresInTheReport(unittest.TestCase):
    def test_api_invalid_and_unproductive_are_counted_apart(self):
        from proventhru.report import failures

        def cost(**kw):
            c = {"model": "org/m", "input_tokens": 10, "output_tokens": 5, "dropped": [],
                 "failure": None, "retries": 0, "cache": "miss", "cache_key": "k"}
            c.update(kw)
            return c

        props = [{"_seq": 1, "cost": cost(failure={"kind": "api"}, retries=6)},
                 {"_seq": 2, "cost": cost(failure={"kind": "invalid", "why": "not JSON"})},
                 {"_seq": 3, "cost": cost(dropped=[{"why": "duplicate"}],
                                          added=["rewrite app_nil_r."])},
                 {"_seq": 4, "cost": None}]                       # a policy with no model

        def step(prop, tactic, outcome, revisit=False):
            return {"proposal": prop, "tactic": tactic,
                    "session": {"outcome": outcome, "revisit": revisit}}

        steps = [step(3, "lia.", "error"), step(3, "simpl.", "ok", revisit=True),
                 step(3, "intros.", "ok"), step(3, "unfold Foo.", "timeout"),
                 step(3, "exact Require.", "refused"), step(3, "rewrite app_nil_r.", "error"),
                 step(4, "auto.", "error")]
        f = failures(props, steps)
        self.assertEqual(f["model_calls"], 3)
        self.assertEqual((f["api_failed_calls"], f["api_retries"]), (1, 6))
        self.assertEqual((f["invalid_responses"], f["invalid_candidates"], f["model_refused"]),
                         (1, 1, 1))
        self.assertEqual((f["unproductive"], f["productive"]), (3, 1))
        self.assertEqual((f["model_steps"], f["retrieval_steps"]), (5, 1))


class TestEvalGenerator(unittest.TestCase):
    def test_statements_hold_and_the_renamed_copy_matches(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import make_eval
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.txt"), os.path.join(d, "b.txt")
            make_eval.main(["--out", a, "--rename", b, "--n", "20", "--max-term", "4",
                            "--min-size", "4"])
            with open(a) as fa, open(b) as fb:
                la = [ln for ln in fa if not ln.startswith("#")]
                lb = [ln for ln in fb if not ln.startswith("#")]
            self.assertEqual(len(la), 20)
            self.assertEqual(len(la), len(lb))
            for x, y in zip(la, lb):
                for old, new in make_eval.RENAME.items():
                    x = __import__("re").sub(rf"\b{old}\b", new, x)
                self.assertEqual(x, y)
            self.assertTrue(all("list nat" in ln for ln in la))


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestParallelStatements(unittest.TestCase):
    STMTS = ["forall n : nat, n * n >= n", "forall n m : nat, n + m = n",
             "forall n : nat, n * (n + 1) >= n", "forall l : list nat, rev (rev l) = l",
             "forall n : nat, 2 * n = n + n"]

    def test_jobs_do_not_change_outcomes_and_policies_are_per_worker(self):
        from proventhru import record as rec
        from proventhru.pipeline import run, RECORD
        from proventhru.search import FixedTactics
        built = []

        def factory():
            built.append(FixedTactics())
            return built[-1]

        rows = {}
        for jobs in (1, 3):
            with tempfile.TemporaryDirectory() as out:
                run(self.STMTS, out, PRE + " Require Import List.", budget=None,
                    step_budget=80, log=lambda *_: None, backend="coqtop", jobs=jobs,
                    policy_factory=factory)
                entries = rec.load(os.path.join(out, RECORD))
                self.assertEqual(rec.verify(entries), [])
                rows[jobs] = {r["item"]: (r["standing"], tuple(r["proof"]))
                              for r in rec.corpus(entries)}
        self.assertEqual(rows[1], rows[3])
        self.assertGreaterEqual(len(built), 2)        # more than one worker policy

    def test_a_shared_cache_file_has_one_instance(self):
        from proventhru import policy_openai as po
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.jsonl")
            a, _ = policy([], cache=path)
            b, _ = policy([], cache=path)
            self.assertIs(a.cache, b.cache)
            po._CACHES.clear()


if __name__ == "__main__":
    unittest.main()
