(* The insertion-sort pilot development: definitions only. The loop sees
   this file and nothing else from the pilot. *)
Require Import Arith Lia List. Import ListNotations.

Fixpoint insert (a : nat) (l : list nat) : list nat :=
  match l with
  | [] => [a]
  | b :: t => if a <=? b then a :: b :: t else b :: insert a t
  end.

Fixpoint sort (l : list nat) : list nat :=
  match l with
  | [] => []
  | a :: t => insert a (sort t)
  end.

Inductive sorted : list nat -> Prop :=
  | sorted_nil : sorted []
  | sorted_one : forall x, sorted [x]
  | sorted_cons : forall x y l, x <= y -> sorted (y :: l) -> sorted (x :: y :: l).
