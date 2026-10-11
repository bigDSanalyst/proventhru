(* Testing harness: boolean versions of the development's predicates, each
   tied to its predicate by a proved reflection lemma, so a wrong boolean
   version cannot pass silently. Compiled before any candidate is tested. *)
Require Import Arith Lia List Permutation. Import ListNotations.
From ISortPilot Require Import ISort.

Fixpoint sortedb (l : list nat) : bool :=
  match l with
  | x :: ((y :: _) as t) => (x <=? y) && sortedb t
  | _ => true
  end.

Lemma sortedb_spec : forall l, sortedb l = true <-> sorted l.
Proof.
  induction l as [|x t IH]; simpl; [split; constructor|].
  destruct t as [|y u]; [split; constructor|].
  rewrite Bool.andb_true_iff, Nat.leb_le, IH. split.
  - intros [H1 H2]; constructor; assumption.
  - intro H; inversion H; subst; split; assumption.
Qed.

Definition inb (x : nat) (l : list nat) : bool := existsb (Nat.eqb x) l.

Lemma inb_spec : forall x l, inb x l = true <-> In x l.
Proof.
  intros x l; unfold inb; rewrite existsb_exists; split.
  - intros [y [Hy E]]; apply Nat.eqb_eq in E; subst; exact Hy.
  - intro H; exists x; split; [exact H | apply Nat.eqb_refl].
Qed.

Definition permb (l1 l2 : list nat) : bool :=
  forallb (fun x => count_occ Nat.eq_dec l1 x =? count_occ Nat.eq_dec l2 x) (l1 ++ l2).

Lemma permb_spec : forall l1 l2, permb l1 l2 = true <-> Permutation l1 l2.
Proof.
  intros l1 l2; unfold permb; rewrite forallb_forall, (Permutation_count_occ Nat.eq_dec).
  split.
  - intros H x. destruct (in_dec Nat.eq_dec x (l1 ++ l2)) as [Hin|Hout].
    + apply Nat.eqb_eq, H, Hin.
    + rewrite in_app_iff in Hout.
      assert (A : count_occ Nat.eq_dec l1 x = 0) by (apply count_occ_not_In; intuition).
      assert (B : count_occ Nat.eq_dec l2 x = 0) by (apply count_occ_not_In; intuition).
      rewrite A, B; reflexivity.
  - intros H x _. apply Nat.eqb_eq, H.
Qed.
