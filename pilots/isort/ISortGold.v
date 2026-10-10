(* Held out: the development's own helper lemmas and main theorems, proved.
   The loop never loads this file; its statements are the gold the pilot's
   recall is measured against. *)
Require Import Arith Lia List Permutation. Import ListNotations.
From ISortPilot Require Import ISort.

Lemma insert_length : forall a l, length (insert a l) = S (length l).
Proof. intros a l; induction l as [|b t IH]; simpl; [reflexivity|]. destruct (a <=? b); simpl; lia. Qed.

Lemma sort_length : forall l, length (sort l) = length l.
Proof. induction l as [|a t IH]; simpl; [reflexivity|]. rewrite insert_length. lia. Qed.

Lemma insert_sorted : forall a l, sorted l -> sorted (insert a l).
Proof.
  intros a l H; induction H as [|x|x y t Hxy Ht IH]; simpl.
  - constructor.
  - destruct (a <=? x) eqn:E; [apply Nat.leb_le in E | apply Nat.leb_gt in E];
      repeat constructor; lia.
  - destruct (a <=? x) eqn:E1.
    + apply Nat.leb_le in E1. constructor; [lia | constructor; assumption].
    + apply Nat.leb_gt in E1. simpl in IH. destruct (a <=? y) eqn:E2.
      * apply Nat.leb_le in E2. constructor; [lia | exact IH].
      * constructor; [lia | exact IH].
Qed.

Lemma sort_sorted : forall l, sorted (sort l).
Proof. induction l as [|a t IH]; simpl; [constructor | apply insert_sorted; exact IH]. Qed.

Lemma insert_perm : forall a l, Permutation (a :: l) (insert a l).
Proof.
  intros a l; induction l as [|b t IH]; simpl; [reflexivity|].
  destruct (a <=? b); [reflexivity|].
  eapply perm_trans; [apply perm_swap | apply perm_skip; exact IH].
Qed.

Lemma sort_perm : forall l, Permutation l (sort l).
Proof.
  induction l as [|a t IH]; simpl; [reflexivity|].
  eapply perm_trans; [apply perm_skip; exact IH | apply insert_perm].
Qed.

Lemma insert_In : forall x a l, In x (insert a l) <-> x = a \/ In x l.
Proof.
  intros x a l; split; intro H.
  - apply Permutation_in with (l' := a :: l) in H; [simpl in H; intuition | symmetry; apply insert_perm].
  - apply Permutation_in with (l := a :: l); [apply insert_perm | simpl; intuition].
Qed.

Lemma sorted_sort_id : forall l, sorted l -> sort l = l.
Proof.
  intros l H; induction H as [|x|x y t Hxy Ht IH]; simpl; [reflexivity | reflexivity|].
  simpl in IH. rewrite IH. simpl. destruct (x <=? y) eqn:E; [reflexivity | apply Nat.leb_gt in E; lia].
Qed.

Lemma sort_idem : forall l, sort (sort l) = sort l.
Proof. intros; apply sorted_sort_id, sort_sorted. Qed.
