"""proventhru: Coq as the environment for conjecture, proof search and corpus.

  gate.classify   Position 1  is the conjecture a formal, non-trivial statement?
  env.CoqEnv      Position 2  proof search as step-by-step interaction with Coq
  kernel.certify  Position 3  the kernel check that admits a proof to the corpus

Backends (session.py): coqtop (any Coq with coqtop) and petanque (Rocq 9 +
coq-lsp's pet, via Pytanque). Both pass the same tests.
"""
__version__ = "0.2.0"
