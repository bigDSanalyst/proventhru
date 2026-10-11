(* Decision procedures for testing the pattern extractor's candidates in Coq.

   An instance of Dec P decides P with a proof either way, so a candidate is
   tested against its own Prop, not against a boolean copy written by hand: a
   wrong decision procedure doesn't typecheck. The development's predicates go
   through the harness's reflection lemmas (sortedb_spec, permb_spec).

   A candidate's test is decide (P) at every input of the falsifier space
   below. decide_false turns a failing input into a kernel-checked disproof. *)
Require Import Arith List Permutation. Import ListNotations.
From ISortPilot Require Import ISort ISortTest.

Class Dec (P : Prop) := dec : {P} + {~ P}.

Definition decide (P : Prop) {d : Dec P} : bool := if d then true else false.

Lemma decide_false (P : Prop) {d : Dec P} : decide P = false -> ~ P.
Proof. unfold decide; destruct d as [p|np]; intro H; [discriminate | exact np]. Qed.

#[export] Instance dec_True : Dec True := left I.
#[export] Instance dec_False : Dec False := right (fun x => x).

#[export] Instance dec_not P `{Dec P} : Dec (~ P).
Proof. destruct (dec : {P} + {~ P}); [right; tauto | left; assumption]. Defined.

#[export] Instance dec_and P Q `{Dec P} `{Dec Q} : Dec (P /\ Q).
Proof. destruct (dec : {P} + {~ P}), (dec : {Q} + {~ Q}); [left | right..]; tauto. Defined.

#[export] Instance dec_or P Q `{Dec P} `{Dec Q} : Dec (P \/ Q).
Proof. destruct (dec : {P} + {~ P}), (dec : {Q} + {~ Q}); [left.. | right]; tauto. Defined.

#[export] Instance dec_impl P Q `{Dec P} `{Dec Q} : Dec (P -> Q).
Proof. destruct (dec : {P} + {~ P}), (dec : {Q} + {~ Q}); [left | right | left..]; tauto. Defined.

#[export] Instance dec_iff P Q `{Dec P} `{Dec Q} : Dec (P <-> Q).
Proof. destruct (dec : {P} + {~ P}), (dec : {Q} + {~ Q}); [left | right | right | left]; tauto. Defined.

#[export] Instance dec_eq_nat (x y : nat) : Dec (x = y) := Nat.eq_dec x y.
#[export] Instance dec_eq_list (x y : list nat) : Dec (x = y) := list_eq_dec Nat.eq_dec x y.
#[export] Instance dec_le (x y : nat) : Dec (x <= y) := le_dec x y.
#[export] Instance dec_lt (x y : nat) : Dec (x < y) := lt_dec x y.
#[export] Instance dec_In (x : nat) (l : list nat) : Dec (In x l) := in_dec Nat.eq_dec x l.

(* ListDec's NoDup_dec and incl_dec build their proofs as they compute, which
   vm_compute evaluates at every input (minutes per candidate), so NoDup and
   incl go through boolean versions with Qed reflection lemmas instead. *)
Fixpoint nodupb (l : list nat) : bool :=
  match l with
  | [] => true
  | x :: t => negb (inb x t) && nodupb t
  end.

Lemma nodupb_spec : forall l, nodupb l = true <-> NoDup l.
Proof.
  induction l as [|x t IH]; simpl; [split; constructor|].
  rewrite Bool.andb_true_iff, Bool.negb_true_iff, IH. split.
  - intros [H1 H2]; constructor; [|exact H2].
    intro Hin; apply inb_spec in Hin; congruence.
  - intro H; inversion H as [|y u Hy Hu]; subst; split; [|exact Hu].
    destruct (inb x t) eqn:E; [|reflexivity]. apply inb_spec in E; contradiction.
Qed.

Definition inclb (l1 l2 : list nat) : bool := forallb (fun x => inb x l2) l1.

Lemma inclb_spec : forall l1 l2, inclb l1 l2 = true <-> incl l1 l2.
Proof.
  intros l1 l2; unfold inclb, incl; rewrite forallb_forall; split.
  - intros H x Hx; apply inb_spec, H, Hx.
  - intros H x Hx; apply inb_spec, H, Hx.
Qed.

#[export] Instance dec_NoDup (l : list nat) : Dec (NoDup l).
Proof.
  destruct (nodupb l) eqn:E; [left | right]; rewrite <- nodupb_spec; congruence.
Defined.

#[export] Instance dec_incl (l1 l2 : list nat) : Dec (incl l1 l2).
Proof.
  destruct (inclb l1 l2) eqn:E; [left | right]; rewrite <- inclb_spec; congruence.
Defined.

#[export] Instance dec_sorted (l : list nat) : Dec (sorted l).
Proof.
  destruct (sortedb l) eqn:E; [left | right]; rewrite <- sortedb_spec; congruence.
Defined.

#[export] Instance dec_perm (l1 l2 : list nat) : Dec (Permutation l1 l2).
Proof.
  destruct (permb l1 l2) eqn:E; [left | right]; rewrite <- permb_spec; congruence.
Defined.

(* The falsifier space, fixed in docs/pattern-run-1.md: every list over
   {0, 1, 2} up to a length, every number up to 3. A statement about one list
   is tested on every list up to length 5 (364 lists); one about two lists on
   every pair up to length 3 (1,600 pairs). Each with every pair of numbers. *)
Fixpoint exactly (k : nat) : list (list nat) :=
  match k with
  | 0 => [[]]
  | S k' => flat_map (fun l => map (fun x => x :: l) [0; 1; 2]) (exactly k')
  end.

Definition lists (k : nat) : list (list nat) := flat_map exactly (seq 0 (S k)).

Definition nums : list nat := [0; 1; 2; 3].

Definition space (ls1 ls2 : list (list nat)) : list (list nat * list nat * nat * nat) :=
  flat_map (fun l1 => flat_map (fun l2 => flat_map (fun n => map (fun m => (l1, l2, n, m))
    nums) nums) ls2) ls1.

Definition one_list : list (list nat * list nat * nat * nat) := space (lists 5) [[]].
Definition two_lists : list (list nat * list nat * nat * nat) := space (lists 3) (lists 3).
