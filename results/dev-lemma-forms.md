# Dev check: do library lemmas get lost at the tactic form?

`tools/dev_lemma_forms.py`, dev set (`examples/eval_open.txt`, 29 statements), 600 steps,
coqtop, Coq 8.18.0. Dev only, so no amendment; the registered B is unchanged.

| condition | proved | vs B | steps | steps in the new form | new-form steps that closed a goal |
|---|---|---|---|---|---|
| B (retrieval/v1, as registered) | 15 / 29 | – | 10,925 | – | – |
| B + `pose proof (L x ..); lia` | 15 / 29 | +0 −0 | 11,016 | 835 (228 distinct) | 1, on a statement B proves anyway |
| B + `eapply Nat.le_trans; [eapply L\|]; lia` (both sides) | 15 / 29 | +0 −0 | 11,073 | 210 (68 distinct) | 0 |

B reproduces its registered dev result (15). Both variants prove exactly the same 15
statements.

**Reading.** For library lemmas the loss isn't at the tactic form. It's at retrieval. The
lemmas retrieval ranks first for these goals are mostly unrelated to the step needed:
`Nat.even_0`, `Nat.even_2` and `Nat.EvenT_even` for goals mentioning `Nat.even`, and
`Nat.log2_mul_pow2` for goals with `*`. So no tactic form can use them. In exploration
the corpus lemma `pt_r0_0` *was* the right lemma, retrieved by name match on
`list_max` and `list_sum`, and only the form was missing. That's why the same change
mattered there (exploration run 3: four proofs cite it) and is a null here.

So the registered B is not understated by its tactic forms, at least on dev. If
retrieval is to improve, the lever is the ranking: by what the lemma's conclusion shares
with the goal's, not by any mention, or retrieving similar proofs, as Rango does. That
would be a new condition and would need an amendment before any test-set run.
