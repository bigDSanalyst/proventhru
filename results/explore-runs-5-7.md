# Why do open statements stay open? Classification, and three fixes it pointed to

`tools/classify_opens.py` sorts a run's open statements: those the gate passed and that
were never proved, derived or settled later. Each is tried against a ladder of scripted
proofs, with the run's final corpus loaded. It goes in the first class that closes it:

| class | closed by |
|---|---|
| 1 | the prover's own tactics, alone or with one corpus lemma at the top: search missed it |
| 1r | the same, but the lemma it needs was found in its own round or later: never retried |
| 2 | a corpus lemma inside an induction, or two corpus lemmas |
| 2s | every corpus lemma its terms allow, at its subterms, then one `lia`: a chain of several |
| 3v | tactics the prover never offered (see fix 2) |
| F | nothing: false, refuted by wider random inputs than the generator used |
| 3 | nothing: unexplained |

Classes 1 to 3v come with a closing script checked by Coq. Class 3 means only that these
scripts didn't find a proof. All counts below use the same ladder.

| | run 4 | run 6 | run 7 |
|---|---|---|---|
| generator's congruence filter | eval rule | fixed | fixed |
| prover | fixed tactics | fixed tactics | + structural tactics |
| lemmas admitted | 39 | 45 | **111** |
| derivations | 76 | 64 | 149 |
| open statements | 315 | 323 | **176** |
| 1 / 1r | 10 / 10 | 3 / 8 | 1 / 3 |
| 2 / 2s | 1 / 1 | 1 / 2 | **4 / 66** |
| 3v | 76 | 72 | 0 |
| F | 1 | 0 | 0 |
| 3 | 216 | 237 | 102 |
| citations inside proofs (top / inner) | 15 / 0 | 8 / 0 | 0 / 0 |

Run 5 is one round with `nth`, `last` and `count_occ` on run 4's corpus: 10 lemmas, and
55 of its 56 opens in class 3. Widening the signature gave more of the same.

## Three fixes, each found by the classification

1. **The generator never proposed the building blocks** (run 4 → run 6). Its congruence
   filter, written for the eval sets, dropped every `f(x) R f(y)` as an instance of a law
   about `x` and `y`. For lists there's usually no such law, so every monotonicity lemma
   was dropped: `list_max (removelast l) <= list_max l`,
   `list_sum (skipn n l) <= list_sum l`, `list_max (filter Nat.even l) <= list_max l`.
   Exploration now drops the pair only when `x` and `y` are equal on every input. The
   eval sets' rule is unchanged.
2. **The prover couldn't prove them** (run 6 → run 7). All six were class 3 in run 6. Each
   needs a proof shape the fixed tactics never offer: a case on the tail in the step case,
   a case on an `if`, or a number reverted before induction.
   `structural-tactics/v1` (`explore --prover structural`) offers these. Class 3v goes
   from 72 to 0, admitted lemmas from 45 to 111, and open statements from 323 to 176.
3. **False statements passed testing** (class F). Test values ran 0 to 5, so a bound such
   as `list_max (filter Nat.even l) <= S (S (S (S n)))` held on every test input.
   Exploration now also tests candidates on values up to 100 and lists up to 12 long.

## What run 7 shows

With the building blocks in the corpus, **70 of 176 opens (40%) are compositions of
corpus lemmas** (classes 2 and 2s), against 2 in run 6. For example:
- `list_max (filter Nat.even (removelast l)) <= list_sum l` takes three lemmas: removelast
  is monotone, filter is monotone, and `list_max <= list_sum`.
- `list_max (skipn n l) <= list_sum l` takes two: `pt_r0_20` and `pt_r0_0`.

The prover proved none of these. In fact no run-7 proof cites the corpus at all: the
structural tactics prove lemmas from scratch, or not at all. The corpus is now rich
enough for multi-lemma proofs, and the prover doesn't compose lemmas.

These compositions are chains at the top of the proof (`pose proof` several lemmas, then
`lia`), so under the position metric they're mechanical, not inner. That's the honest
read: what the corpus enables now is composition, not structural depth.

## What's left

102 statements stay in class 3. In 20 of them, no corpus lemma mentions only the
statement's terms, so the corpus lacks what they need. A sample of the rest needs:
- lemmas at instances that aren't subterms of the goal;
- invariance under `rev` (`list_max (rev (removelast l)) = list_max (removelast l)`);
- or uses inside an induction that the ladder doesn't try.

That residue is the first set of statements where a prover able to use the corpus
structurally, a model or otherwise, has something to find.
