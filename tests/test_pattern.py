import shutil
import unittest

from proventhru import pattern as P

HAVE_COQ = shutil.which("coqtop") and shutil.which("coqc")

# Lines as Coq 8.18 prints them under Unset Printing Notations (Search _ inside List).
REV_LENGTH = "forall [A : Type] (l : list A), eq (length (rev l)) (length l)"
NODUP_REV = "forall [A : Type] [l : list A] (_ : NoDup l), NoDup (rev l)"
FORALL_REV = ("forall [A : Type] [P : forall _ : A, Prop] [l : list A] (_ : Forall P l), "
              "Forall P (rev l)")
REV_INVOLUTIVE = "forall [A : Type] (l : list A), eq (rev (rev l)) l"
REV_APP = "forall [A : Type] (x y : list A), eq (rev (app x y)) (app (rev y) (rev x))"
IN_CONS = "forall [A : Type] (a b : A) (l : list A) (_ : In b l), In b (cons a l)"
ADD_COMM = "forall n m : nat, eq (Nat.add n m) (Nat.add m n)"


class TestTerms(unittest.TestCase):
    def test_parse_render_round_trip(self):
        # render writes every binder explicit: a statement's meaning doesn't
        # depend on which arguments are implicit
        def explicit(t):
            if t[0] in ("forall", "fun"):
                return (t[0], tuple((ns, explicit(ty), False) for ns, ty, _ in t[1]),
                        explicit(t[2]))
            if t[0] == "app":
                return ("app", explicit(t[1]), tuple(explicit(a) for a in t[2]))
            return t
        for text in (REV_LENGTH, NODUP_REV, FORALL_REV, REV_APP, IN_CONS, ADD_COMM,
                     "forall (A : Type) (n : nat), eq (firstn n nil) nil"):
            t = P.parse(text)
            self.assertEqual(P.parse(P.render(t)), explicit(t), text)

    def test_outside_the_grammar(self):
        for text in ("RelationClasses.Symmetric (Permutation_transp (A:=A))",
                     "forall l, match l with nil => True | _ => False end", "forall x, (x"):
            with self.assertRaises(P.ParseError):
                P.parse(text)

    def test_free_respects_binders(self):
        t = P.parse("forall (l : list nat) (_ : NoDup l), NoDup (rev l)")
        self.assertEqual(P.free(t), ["list", "nat", "NoDup", "rev"])


class TestStatements(unittest.TestCase):
    def test_specialize_first_order(self):
        data, hyps, concl = P.specialize(P.parse(NODUP_REV))
        self.assertEqual(data, [("l", "list nat")])
        self.assertEqual([P.render(h) for h in hyps], ["NoDup l"])
        self.assertEqual(P.render(concl), "NoDup (rev l)")

    def test_specialize_refuses_higher_order(self):
        with self.assertRaises(P.ParseError):
            P.specialize(P.parse(FORALL_REV))
        with self.assertRaises(P.ParseError):
            P.specialize(P.parse("forall (b : bool) (l : list nat), eq (length l) (length l)"))

    def test_key_ignores_names_and_binder_order(self):
        a = P.specialize(P.parse("forall (a : nat) (l : list nat), "
                                 "eq (length (insert a l)) (S (length l))"))
        b = P.specialize(P.parse("forall (xs : list nat) (k : nat), "
                                 "eq (length (insert k xs)) (S (length xs))"))
        self.assertEqual(P.key(*a), P.key(*b))
        c = P.specialize(P.parse("forall (k : nat) (xs : list nat), "
                                 "eq (S (length xs)) (length (insert k xs))"))
        self.assertNotEqual(P.key(*a), P.key(*c))
        self.assertEqual(P.swapped_key(*a), P.key(*c))

    def test_rename_drops_unused_and_orders_by_use(self):
        data, hyps, concl = P.rename([("x", "nat"), ("l", "list nat"), ("u", "nat")], [],
                                     P.parse("eq (insert x l) l"))
        self.assertEqual(data, [("n", "nat"), ("l1", "list nat")])
        self.assertEqual(P.render(concl), "eq (insert n l1) l1")

    def test_relation_variables_and_folding(self):
        sorted_cons = ("forall [A : Type] [R : forall (_ : A) (_ : A), Prop] [a : A] [l : list A] "
                       "(_ : Sorted R l) (_ : HdRel R a l), Sorted R (cons a l)")
        with self.assertRaises(P.ParseError):
            P.specialize(P.parse(sorted_cons))          # v1: a relation variable is higher-order
        data, hyps, concl = P.specialize(P.parse(sorted_cons), relation="le")
        self.assertEqual(data, [("a", "nat"), ("l", "list nat")])
        self.assertEqual(P.render(concl), "Sorted le (cons a l)")
        folded = P.fold(concl, "le")
        self.assertEqual(folded, ("app", ("id", "Sorted@le"), (P.parse("cons a l"),)))
        self.assertEqual(P.unfold(folded, "le"), concl)
        self.assertEqual(P.render(P.unfold(P.subst(folded, {"Sorted@le": ("id", "sorted")}),
                                           "le")), "sorted (cons a l)")

    def test_kind(self):
        def k(text, syms):
            return P.kind(P.specialize(P.parse(text)), syms)
        self.assertEqual(k(REV_LENGTH, ["rev"]), "invariance")
        self.assertEqual(k(NODUP_REV, ["NoDup", "rev"]), "invariance")
        self.assertEqual(k(NODUP_REV, ["NoDup"]), "invariance")
        self.assertEqual(k(IN_CONS, ["cons"]), "invariance")
        self.assertEqual(k(REV_INVOLUTIVE, ["rev"]), "composition")
        self.assertEqual(k(REV_APP, ["rev"]), "composition")
        self.assertEqual(k(ADD_COMM, ["Nat.add"]), "symmetry")
        self.assertEqual(k("forall (A : Type) (a : A) (l : list A), "
                           "eq (length (cons a l)) (S (length l))", ["cons"]), "transfer")


@unittest.skipUnless(HAVE_COQ, "coqtop/coqc not in PATH")
class TestInCoq(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = P.Coq(notations=False)
        cls.coq = P.Coq(notations=True)

    @classmethod
    def tearDownClass(cls):
        cls.raw.close()
        cls.coq.close()

    def cands(self, entries):
        out, _ = P.proposals(self.raw, entries)
        return {c["key"]: c for c in out}

    def test_carries_patterns_over(self):
        got = self.cands([("rev_length", REV_LENGTH), ("NoDup_rev", NODUP_REV),
                          ("in_cons", IN_CONS)])
        want = {
            "forall (l1 : list nat), eq (length (sort l1)) (length l1)",
            "forall (l1 : list nat) (n : nat), forall (_ : sorted l1), sorted (insert n l1)",
            "forall (l1 : list nat) (m n : nat), forall (_ : In n l1), In n (insert m l1)",
        }
        keys = {P.key(*P.specialize(P.parse(w))) for w in want}
        self.assertLessEqual(keys, set(got))
        # every candidate mentions one of the development's symbols
        for c in got.values():
            self.assertTrue(set(P.OWN) & set(P.free(P.parse(c["prefix"]))), c["prefix"])

    def test_constructor_equations(self):
        coq = P.Coq(notations=False)
        try:
            eqs = dict(P.equations(coq))
        finally:
            coq.close()
        self.assertEqual(eqs["length:cons@0"],
                         "forall (a : nat) (t : list nat), eq (length (cons a t)) (S (length t))")
        self.assertEqual(eqs["In:cons@1"],
                         "forall (x0 : nat) (a : nat) (t : list nat), iff (In x0 (cons a t)) "
                         "(or (eq a x0) (In x0 t))")
        self.assertNotIn("app:cons@1", eqs)          # cbn makes no progress on app's second list
        # the equation carries over: length's gives insert_length
        got = self.cands([("length:cons@0", eqs["length:cons@0"])])
        want = P.key(*P.specialize(P.parse(
            "forall (a : nat) (l : list nat), eq (length (insert a l)) (S (length l))")))
        self.assertIn(want, got)

    def test_sorted_import_keeps_the_developments_sort(self):
        # Coq.Sorting.Sorted defines the notation sort := Sorted; imported after
        # the development, it would cover the development's sort
        import sys
        sys.path.insert(0, "tools")
        import pattern_run as R
        coq = P.Coq(notations=False, extra=("Require Import Sorted.",))
        try:
            text = coq.must("Check (forall l, length (sort l) = length l).")
            self.assertNotIn("Sorted", text)
        finally:
            coq.close()
        R.configure(2)
        try:
            pre = R.base_preamble()
        finally:
            R.configure(1)
        self.assertLess(pre.index("Require Import Sorted."), pre.index("Fixpoint sort"))

    def test_one_constructor_step_is_present_in_the_development(self):
        import sys
        sys.path.insert(0, "tools")
        import pattern_run as R
        R.configure(3)
        try:
            pre = R.base_preamble()
            ctor = R.follows(pre, "forall (n : nat) (l1 : list nat) (m : nat), sorted (n :: l1) -> "
                                  "m <= n -> sorted (m :: n :: l1)", R.CONSTRUCTOR_CLOSERS)
            helper = R.follows(pre, "forall (l1 : list nat) (n : nat), sorted l1 -> "
                                    "sorted (insert n l1)", R.CONSTRUCTOR_CLOSERS)
        finally:
            R.configure(1)
        self.assertEqual(ctor, "intros; constructor; assumption.")    # sorted_cons, premises swapped
        self.assertIsNone(helper)                                      # needs an induction

    def test_run_6_reads_run_5_under_its_recount(self):
        import sys
        sys.path.insert(0, "tools")
        import pattern_run as R
        R.configure(6)
        try:
            out = "\n".join(R.stopping({"present_in_development": 0, "gold_proved": [],
                                         "significant": 0}, []))
        finally:
            R.configure(1)
        self.assertIn("as docs/pattern-run-6.md reads it", out)
        self.assertIn("run 5 0 (of its 1 by its own rules)", out)   # docs/pattern-recount-4-5.md

    def test_sorted_le_stands_for_sorted(self):
        coq = P.Coq(notations=False, extra=("Require Import Sorted.",))
        try:
            text = coq.must("Search _ inside Sorted.")
            entries = [(n, t) for n, t in (ln.split(": ", 1) for ln in text.splitlines()
                                           if ln.startswith("Sorted_cons: "))]
            out, _ = P.proposals(coq, entries, relation="le")
        finally:
            coq.close()
        stmts = {c["prefix"] for c in out}
        self.assertIn("forall (l1 : list nat) (n : nat), forall (_ : sorted l1), "
                      "forall (_ : HdRel le n l1), sorted (insert n l1)", stmts)
        # each symbol alone, too: Sorted le kept with cons as insert, and the reverse
        self.assertIn("forall (l1 : list nat) (n : nat), forall (_ : sorted l1), "
                      "forall (_ : HdRel le n l1), sorted (cons n l1)", stmts)

    def test_falsifier_space_sizes(self):
        for name, size in (("one_list", 5824), ("two_lists", 25600)):
            text = self.coq.must(f"Eval vm_compute in length {name}.")
            self.assertIn(f"= {size}", text)

    def test_verdicts(self):
        got = self.cands([("rev_length", REV_LENGTH), ("rev_app_distr", REV_APP)])
        by = {c["prefix"]: P.test(self.coq, c) for c in got.values()}
        sort_len = by["forall (l1 : list nat), eq (length (sort l1)) (length l1)"]
        self.assertEqual(sort_len["status"], "passed")
        app = [r for p, r in by.items() if p.startswith("forall (l1 : list nat) (l2 : list nat), "
                                                         "eq (sort (app l1 l2))")][0]
        self.assertEqual(app["status"], "refuted")
        self.assertEqual(app["space"], "two_lists")

    def test_untestable_is_fast_and_named(self):
        c = {"data": [("n", "nat"), ("l1", "list nat")], "hyps": [],
             "concl": "Add n l1 (insert n l1)"}
        r = P.test(self.coq, c)
        self.assertEqual(r, {"status": "untestable",
                             "reason": "no decision procedure for part of it"})
        many = {"data": [("l1", "list nat"), ("l2", "list nat"), ("l3", "list nat")], "hyps": [],
                "concl": "eq (app l1 (app l2 l3)) (app (app l1 l2) l3)"}
        self.assertEqual(P.test(self.coq, many)["status"], "untestable")

    def test_disproofs_are_checked_not_trusted(self):
        c = {"data": [("l1", "list nat"), ("l2", "list nat")], "hyps": [],
             "concl": "eq (sort (app l1 l2)) (app (sort l1) (sort l2))"}
        c["prefix"] = P.render(P.statement(c["data"], [], P.parse(c["concl"])))
        r = P.test(self.coq, c)
        self.assertEqual(r["status"], "refuted")
        true = {"data": [("l1", "list nat")], "hyps": [],
                "concl": "eq (length (sort l1)) (length l1)"}
        true["prefix"] = P.render(P.statement(true["data"], [], P.parse(true["concl"])))
        # a made-up counterexample to a true statement doesn't certify
        self.assertEqual(P.certify_disproofs([P.disproof(c, r),
                                              P.disproof(true, {"args": [[1, 0]]})]),
                         ["accepted", "rejected"])


if __name__ == "__main__":
    unittest.main()
