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


class TestRecord(unittest.TestCase):
    """The run record without a prover: chain, checks, annotations."""
    ENV = {"backend": "coqtop", "prover": "coq-8.18.0"}

    def setUp(self):
        from proventhru import record as rec
        self.rec = rec
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "r.jsonl")
        self.log = rec.RecordLog(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def _episode(self, standing="proved", kernel="accepted"):
        ep = self.log.episode("1 = 1", "", self.ENV, policy={"id": "t"})
        seq = ep.outcome(standing, ["reflexivity."], kernel=kernel)
        return ep, seq

    def test_chain_verifies_and_continues_across_opens(self):
        self._episode()
        log2 = self.rec.RecordLog(self.path)
        ep = log2.episode("2 = 2", "", self.ENV)
        ep.outcome("open")
        entries = self.rec.load(self.path)
        self.assertEqual(self.rec.verify(entries), [])
        self.assertEqual([e["seq"] for e in entries], list(range(len(entries))))

    def test_edit_deletion_and_reorder_are_caught(self):
        self._episode()
        self._episode()
        lines = open(self.path).read().splitlines()
        import json
        e = json.loads(lines[1])
        e["data"]["standing"] = "open"
        edited = lines[:1] + [self.rec.canon(e)] + lines[2:]
        cases = {"edited": edited, "dropped": lines[:1] + lines[2:],
                 "reordered": [lines[1], lines[0]] + lines[2:]}
        for name, ls in cases.items():
            entries = [json.loads(x) for x in ls]
            self.assertTrue(self.rec.verify(entries), name)

    def test_refuses_to_append_to_a_broken_record(self):
        self._episode()
        with open(self.path, "a") as fh:
            fh.write('{"format": "proventhru-record/v1", "seq": 99}\n')
        with self.assertRaises(self.rec.RecordError):
            self.rec.RecordLog(self.path)

    def test_malformed_entries_are_refused_at_write(self):
        R = self.rec
        with self.assertRaises(R.RecordError):      # proved without the kernel
            self._episode(standing="proved", kernel="not_checked")
        with self.assertRaises(R.RecordError):      # a step for no episode
            self.log.append("step", {"episode": "nope", "path": [], "tactic": "x.",
                                     "session": {"outcome": "ok"}, "phase": R.no_phase()})
        with self.assertRaises(R.RecordError):      # environment without a prover
            self.log.episode("1 = 1", "", {"backend": "coqtop"})
        ep = self.log.episode("1 = 1", "", self.ENV)
        with self.assertRaises(R.RecordError):      # session outcome must be known
            self.log.append("step", {"episode": ep.id, "path": [], "tactic": "x.",
                                     "session": {"outcome": "maybe"}, "phase": R.no_phase()})
        ep.outcome("open")
        with self.assertRaises(R.RecordError):      # nothing after an outcome
            self.log.append("proposal", {"episode": ep.id, "path": [], "policy": None,
                                         "candidates": [], "cost": None})

    def test_annotation_withdraws_without_rewriting(self):
        ep, seq = self._episode()
        before = open(self.path).read()
        self.log.annotate(seq, "unsound", "kernel bug in this version", by="test")
        after = open(self.path).read()
        self.assertTrue(after.startswith(before))           # appended, nothing rewritten
        row = self.rec.corpus(self.rec.load(self.path))[0]
        self.assertEqual(row["standing"], "withdrawn")
        self.assertEqual(row["annotations"][0]["label"], "unsound")
        self.assertEqual(self.rec.verify(self.rec.load(self.path)), [])

    def test_annotation_must_name_an_existing_entry_by_hash(self):
        self._episode()
        with self.assertRaises(self.rec.RecordError):
            self.log.append("annotation", {"target": {"seq": 0, "hash": "0" * 64},
                                           "label": "note", "reason": "x"})


class FakeBlock:
    def __init__(self, text):
        self.type, self.text = "text", text


class FakeUsage:
    def __init__(self):
        self.input_tokens, self.output_tokens = 900, 120
        self.cache_read_input_tokens, self.cache_creation_input_tokens = 700, 0


class FakeResponse:
    def __init__(self, payload, stop_reason="end_turn"):
        import json
        self.content = [FakeBlock(json.dumps(payload) if not isinstance(payload, str) else payload)]
        self.usage, self.stop_reason, self.model = FakeUsage(), stop_reason, "claude-opus-5-5"


class FakeClient:
    """Stands in for anthropic.Anthropic: returns scripted responses and keeps
    every request, so tests can read what the model would have been sent."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        outer = self

        class Messages:
            def create(self, **kw):
                outer.requests.append(kw)
                return outer.script.pop(0)

        class Beta:
            messages = Messages()
        self.beta = Beta()


class TestView(unittest.TestCase):
    def test_hypotheses_are_split_by_name(self):
        from proventhru.view import hypotheses
        self.assertEqual(hypotheses("n, m : nat"),
                         [{"name": "n", "type": "nat"}, {"name": "m", "type": "nat"}])
        self.assertEqual(hypotheses("x := 3 : nat"),
                         [{"name": "x", "type": "nat", "value": "3"}])

    def test_state_carries_every_goal_and_the_exact_error(self):
        from proventhru.goals import Goal, Observation
        from proventhru.view import state
        obs = Observation((Goal(1, "0 + 0 = 0"), Goal(2, "S n + 0 = S n", ("n : nat",))))
        err = "In environment\nn : nat\nUnable to unify \"0\" with \"n\"."
        v = state(obs, ["intros n.", "induction n."],
                  {"path": [], "tactic": "exact I.", "outcome": "error", "error": err})
        self.assertEqual(v["goal_count"], 2)
        self.assertEqual(v["goals"][1]["hypotheses"], [{"name": "n", "type": "nat"}])
        self.assertEqual(v["last_failure"]["error"], err)       # verbatim
        self.assertIs(v["given_up"], False)


class TestClaudePolicy(unittest.TestCase):
    def _policy(self, script, **kw):
        from proventhru.policy_claude import ClaudePolicy
        self.client = FakeClient(script)
        return ClaudePolicy("Require Import Arith.", client=self.client, **kw)

    def _obs(self):
        from proventhru.goals import Goal, Observation
        return Observation((Goal(1, "forall n : nat, n + 0 = n"),))

    def test_request_shape(self):
        pol = self._policy([FakeResponse({"candidates": []})])
        pol.propose(self._obs(), ())
        r = self.client.requests[0]
        self.assertEqual(r["model"], "claude-opus-5-5")
        self.assertEqual(r["system"][0]["cache_control"], {"type": "ephemeral"})
        fmt = r["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        enum = fmt["schema"]["properties"]["candidates"]["items"]["properties"]["tactic"]["enum"]
        self.assertIn("lia", enum)
        self.assertNotIn("omega", enum)          # removed from Coq 8.17 and Rocq 9
        self.assertEqual(r["output_config"]["effort"], "medium")
        self.assertEqual(r["fallbacks"], "default")
        self.assertNotIn("thinking", r)          # adaptive by default on this model

    def test_candidates_assembled_checked_and_costed(self):
        pol = self._policy([FakeResponse({"candidates": [
            {"tactic": "intros", "argument": "n"},
            {"tactic": "lia", "argument": ""},
            {"tactic": "simpl", "argument": "; auto"},          # a tactical: dropped
            {"tactic": "lia", "argument": ""},                  # duplicate: dropped
            {"tactic": "rewrite", "argument": "<- Nat.add_comm"}]})])
        got = pol.propose(self._obs(), ())
        self.assertEqual([t for t, _ in got], ["intros n.", "lia.", "rewrite <- Nat.add_comm."])
        self.assertEqual(len(pol.last_cost["dropped"]), 2)
        self.assertEqual(pol.last_cost["input_tokens"], 900)
        for t, _ in got:
            self.assertIsNone(guard(t), t)

    def test_refusal_and_bad_json_give_no_candidates(self):
        pol = self._policy([FakeResponse({"candidates": []}, stop_reason="refusal"),
                            FakeResponse("not json")])
        self.assertEqual(pol.propose(self._obs(), ()), [])
        self.assertEqual(pol.last_cost["stop_reason"], "refusal")
        self.assertEqual(pol.propose(self._obs(), ()), [])
        self.assertEqual(pol.last_cost["dropped"][0]["why"], "not JSON")

    def test_max_calls_caps_spend(self):
        pol = self._policy([FakeResponse({"candidates": []})], max_calls=1)
        pol.propose(self._obs(), ())
        self.assertEqual(pol.propose(self._obs(), ()), [])
        self.assertEqual(len(self.client.requests), 1)


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestClaudePolicyInSearch(unittest.TestCase):
    def test_last_failure_reaches_the_next_call_and_everything_is_recorded(self):
        import json
        from proventhru import record as rec
        from proventhru.env import CoqEnv
        from proventhru.policy_claude import ClaudePolicy
        from proventhru.search import best_first
        from proventhru.pipeline import environment
        client = FakeClient([
            FakeResponse({"candidates": [{"tactic": "exact", "argument": "I"},
                                         {"tactic": "intros", "argument": "n"}]}),
            FakeResponse({"candidates": [{"tactic": "nia", "argument": ""}]}),
        ])
        stmt = "forall n : nat, n * n >= n"
        with tempfile.TemporaryDirectory() as d:
            log = rec.RecordLog(os.path.join(d, "r.jsonl"))
            pol = ClaudePolicy("Require Import Arith Lia.", client=client)
            with CoqEnv(stmt, "Require Import Arith Lia.", backend="coqtop") as env:
                ep = log.episode(stmt, env.preamble, environment(env.preamble, "coqtop"),
                                 policy=pol.identity)
                res = best_first(env, pol, budget=5, episode=ep)
            self.assertTrue(res.proved)
            self.assertEqual(list(res.proof), ["intros n.", "nia."])
            sent = json.loads(client.requests[1]["messages"][0]["content"])
            failed = [s for s in res.steps if s.tactic == "exact I."][0]
            self.assertEqual(sent["last_failure"]["tactic"], "exact I.")
            self.assertEqual(sent["last_failure"]["error"], failed.error)   # verbatim
            props = [e["data"] for e in log.entries if e["kind"] == "proposal"]
            self.assertEqual(props[0]["policy"]["model"], "claude-opus-5-5")
            self.assertEqual(props[0]["cost"]["output_tokens"], 120)
            self.assertEqual(rec.verify(log.entries), [])


class TestReport(unittest.TestCase):
    def test_distribution_flags_a_collapsed_policy(self):
        from proventhru.report import distribution
        flat = distribution(["intros n.", "simpl.", "rewrite H.", "lia.", "auto.", "split."])
        collapsed = distribution(["lia."] * 8 + ["auto."] * 8 + ["intros."])
        self.assertEqual(flat["entropy"], 1.0)
        self.assertGreater(collapsed["top3_share"], 0.99)
        self.assertLess(collapsed["entropy"], flat["entropy"])


class TestPoolAcquire(unittest.TestCase):
    """Worker choice without a prover: no process is started here."""

    def test_callers_arriving_together_get_different_workers(self):
        from proventhru.pool import Pool
        pool = Pool(size=3)
        got = [pool.acquire() for _ in range(3)]       # none has launched yet
        self.assertEqual(len({id(w) for w in got}), 3)

    def test_a_sequential_caller_reuses_the_launched_idle_worker(self):
        from proventhru.pool import Pool
        pool = Pool(size=3)
        first = pool.acquire()
        first.gen = 1                                   # as if its process started
        self.assertIs(pool.acquire(), first)
        self.assertIs(pool.acquire(), first)

    def test_a_busy_launched_worker_is_passed_over(self):
        from proventhru.pool import Pool
        pool = Pool(size=2)
        first = pool.acquire()
        first.gen = 1
        with first.lock:                                # mid-request
            self.assertIsNot(pool._choose(), first)


class TestRetrievalParts(unittest.TestCase):
    """Retrieval without a prover: terms, parsing, ranking."""

    def test_terms_skip_bound_names_and_take_operators(self):
        from proventhru.retrieval import terms
        self.assertEqual(terms("forall l1 l2 : list nat, length (rev (l1 ++ l2)) = length l1 + length l2"),
                         ["length", "rev", '"++"', '"+"'])
        self.assertEqual(terms("rev (map f l) = map f (rev l)", ("A, B : Type", "f : A -> B", "l : list A")),
                         ["rev", "map"])

    def test_parse_both_backends_formats_and_drop_generated_and_private_names(self):
        from proventhru.retrieval import parse
        coqtop = ("rev_app_distr: forall [A : Type] (x y : list A), rev (x ++ y) = rev y ++ rev x\n"
                  "list_ind: forall (A : Type) (P : list A -> Prop), P [] -> ...\n")
        pet = ("rev_app_distr:\n  forall [A : Type] (x y : list A),\n  rev (x ++ y) = rev y ++ rev x\n"
               "Nat.PrivateImplementsBitwiseSpec.div2_double: forall n, Nat.div2 (2 * n) = n\n")
        want = [("rev_app_distr", "forall [A : Type] (x y : list A), rev (x ++ y) = rev y ++ rev x")]
        self.assertEqual(parse(coqtop), want)
        self.assertEqual(parse(pet), want)

    def test_rank_prefers_covering_equations(self):
        from proventhru.retrieval import rank
        found = [("rev_unit", "forall l a, rev (l ++ [a]) = a :: rev l"),
                 ("length_rev", "forall l, length (rev l) = length l"),
                 ("rev_length_le", "forall l, length (rev l) <= length l")]
        self.assertEqual(rank(found, ["length", "rev"])[0][0], "length_rev")

    def test_head_of_a_composite_tactic(self):
        from proventhru.report import head
        self.assertEqual(head("simpl; rewrite IHn."), "simpl")
        self.assertEqual(head("lia."), "lia")


class TestRetrieval:
    BACKEND = None
    PRE = "Require Import Arith Lia List. Import ListNotations."

    def test_gate_rejects_a_library_lemma_as_known(self):
        from proventhru.gate import classify
        res = classify("forall l : list nat, rev (rev l) = l", self.PRE, backend=self.BACKEND)
        self.assertEqual(res.status, "trivial")
        self.assertIn("library", res.detail)
        res = classify("forall (A : Type) (l : list A) (n : nat), firstn n l ++ skipn n l = l",
                       self.PRE, backend=self.BACKEND)
        self.assertEqual(res.script, ("intros; apply firstn_skipn.",))   # binder order differs

    def test_retrieval_proves_what_the_baseline_cannot(self):
        from proventhru.env import CoqEnv
        from proventhru.retrieval import RetrievalPolicy
        from proventhru.search import best_first, FixedTactics
        stmt = "forall (f : nat -> nat) (l : list nat), length (rev (map f l)) = length l"
        with CoqEnv(stmt, self.PRE, backend=self.BACKEND) as env:
            plain = best_first(env, FixedTactics(), budget=8)
        with CoqEnv(stmt, self.PRE, backend=self.BACKEND) as env:
            pol = RetrievalPolicy(FixedTactics())
            res = best_first(env, pol, budget=8)
        self.assertFalse(plain.proved)
        self.assertTrue(res.proved)
        self.assertEqual(res.certificate.verdict, "accepted")
        # The proof cites a library lemma (length_rev in Rocq 9, rev_length in
        # Coq 8.18): a rewrite or apply of a name that is not a hypothesis.
        cited = [t for t in res.proof if t.startswith(("rewrite ", "apply "))
                 and not t.split()[-1].rstrip(".").startswith(("IH", "H"))]
        self.assertTrue(cited, res.proof)
        self.assertIn("lemmas", pol.last_cost)


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
        self.assertEqual(st.kernel, "accepted")
        self.assertGreater(st.reward, 0.9)

    def test_revisit_penalised(self):
        st = self.env.step(self.root, "idtac.")
        self.assertTrue(st.signals["revisit"])

    def test_timeout_recovers(self):
        st = self.env.step(self.root, "repeat (assert True by trivial).")
        self.assertEqual(st.outcome, "timeout")
        self.assertEqual(st.reward, self.env.weights.step)   # not punished as an error
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
        self.assertEqual(st.outcome, "ok")          # the session's verdict...
        self.assertEqual(st.kernel, "rejected")     # ...and the kernel's, apart
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
                 "forall l : list nat, rev (rev l) = l": "trivial",          # rev_involutive
                 "forall (f : nat -> nat) (l : list nat), length (rev (map f l)) = length l": "open"}
        for stmt, want in cases.items():
            res = classify(stmt, backend=self.BACKEND)
            self.assertEqual(res.status, want, stmt)
            if want == "refuted":
                self.assertEqual(res.kernel, "accepted")


class TestPipeline:
    BACKEND = None

    def test_record_holds_and_corpus_is_a_view(self):
        from proventhru import record as rec
        from proventhru.pipeline import run, RECORD
        with tempfile.TemporaryDirectory() as out:
            summary = run(["forall n : nat, n * n >= n", "forall n m : nat, n + m = n",
                           "forall n, n + 1"], out, budget=10, log=lambda *_: None,
                          backend=self.BACKEND)
            self.assertEqual(summary, {"proved": 1, "refuted": 1, "rejected": 1})
            entries = rec.load(os.path.join(out, RECORD))
            self.assertEqual(rec.verify(entries), [])
            rows = {r["statement"]: r for r in rec.corpus(entries)}
            self.assertEqual(rows["forall n : nat, n * n >= n"]["kernel"], "accepted")
            self.assertEqual(rows["forall n m : nat, n + m = n"]["standing"], "refuted")
            env = entries[0]["data"]["environment"]
            self.assertEqual(env["backend"], self.BACKEND)
            self.assertRegex(env["prover"], r"^(coq|rocq)-\d")

    def test_recorded_step_replays_from_the_statement(self):
        """Every step carries its full path: replaying it in a fresh session
        reaches the observation the record holds."""
        from proventhru import record as rec
        from proventhru.env import CoqEnv
        from proventhru.pipeline import run, RECORD
        with tempfile.TemporaryDirectory() as out:
            run(["forall n : nat, n * n >= n"], out, budget=6,
                log=lambda *_: None, backend=self.BACKEND)
            entries = rec.load(os.path.join(out, RECORD))
            ep = entries[0]["data"]
            ok = [s for s in rec.steps(entries) if s["session"]["outcome"] == "ok"
                  and not s["session"]["finished"]]
            self.assertTrue(ok)
            target = max(ok, key=lambda s: len(s["path"]))
            with CoqEnv(ep["statement"], ep["preamble"], backend=self.BACKEND,
                        certify_on_finish=False) as env:
                node = env.reset()
                for tac in target["path"] + [target["tactic"]]:
                    node = env.step(node, tac).node
                self.assertEqual(node.obs.key, target["session"]["observation"]["key"])


def _per_backend(mixin, name, backend, available, why):
    cls = type(name, (mixin, unittest.TestCase), {"BACKEND": backend})
    globals()[name] = unittest.skipUnless(available, why)(cls)


for _mixin in (TestEnv, TestKernel, TestGate, TestPipeline, TestRetrieval):
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
