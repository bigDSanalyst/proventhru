#!/bin/sh
# Rocq 9.1.1 + stdlib + coq-lsp (pet) + Pytanque, for machines where opam's
# package server is unreachable but apt and git to GitHub work. With opam,
# use instead:  opam install rocq-core.9.1.1 rocq-stdlib coq-lsp.0.2.5+9.1
#
# Installs Rocq under /opt/rocq; add /opt/rocq/bin to the END of PATH so an
# apt Coq's coqtop/coqc (the coqtop backend) stay first. Takes ~30 min on 4 cores.
set -eu
SRC=${SRC:-/opt/src}
LIB=/usr/local/lib/ocaml/4.14.1
apt-get install -y ocaml-dune ocaml-findlib cppo libzarith-ocaml-dev libyojson-ocaml-dev \
  libcmdliner-ocaml-dev liburi-ocaml-dev libppx-deriving-yojson-ocaml-dev libppxlib-ocaml-dev \
  libppx-deriving-ocaml-dev libppx-import-ocaml-dev libsexplib-ocaml-dev \
  libppx-sexp-conv-ocaml-dev libppx-compare-ocaml-dev libppx-hash-ocaml-dev \
  libmenhir-ocaml-dev menhir libtyxml-ocaml-dev libppx-inline-test-ocaml-dev
mkdir -p "$SRC" "$LIB" /opt/rocq/lib && cd "$SRC"
[ -d rocq ] || git clone --depth 1 -b V9.1.1 https://github.com/rocq-prover/rocq
[ -d stdlib ] || git clone --depth 1 -b V9.0.0 https://github.com/rocq-prover/stdlib
[ -d coq-lsp ] || git clone --depth 1 -b 0.2.5+9.1 https://github.com/ejgallego/coq-lsp
[ -d memprof-limits ] || git clone --depth 1 https://gitlab.com/gadmm/memprof-limits
[ -d dune-src ] || git clone --depth 1 -b 3.14.0 https://github.com/ocaml/dune dune-src
[ -d pytanque ] || git clone https://github.com/LLM4Rocq/pytanque
# Everything links against apt's findlib, as Rocq does: one findlib in the link.
export OCAMLPATH="$LIB:/usr/lib/ocaml"
(cd memprof-limits && dune build -p memprof-limits && dune install -p memprof-limits --prefix /usr/local --libdir "$LIB")
(cd dune-src && dune build -p dune-build-info && dune install -p dune-build-info --prefix /usr/local --libdir "$LIB")
(cd rocq && ./configure -prefix /opt/rocq -libdir /opt/rocq/lib/coq -native-compiler no \
  && make dunestrap && dune build -p rocq-runtime,coq-core,rocq-core @install \
  && dune install -p rocq-runtime,coq-core,rocq-core --prefix /opt/rocq --libdir "$LIB")
ln -sfn "$LIB/coq" /opt/rocq/lib/coq
ln -sfn "$LIB/rocq-runtime" /opt/rocq/lib/rocq-runtime
ln -sfn "$LIB/coq-core" /opt/rocq/lib/coq-core
export PATH="/opt/rocq/bin:$PATH"
(cd stdlib && make -j"$(nproc)" && make install)
(cd coq-lsp && dune build -p coq-lsp && dune install -p coq-lsp --prefix /opt/rocq --libdir "$LIB")
(cd pytanque && git checkout 4092b1238b56468fdc1b3d100e078791c9690fd4 && pip install .)
/opt/rocq/bin/rocq --version && command -v /opt/rocq/bin/pet
