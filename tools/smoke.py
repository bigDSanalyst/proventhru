"""Smoke-test a model endpoint: N calls, one per dev statement, at the root state.

    python tools/smoke.py --base-url http://localhost:8000/v1 --model NAME --key-env '' \
        --response-format json_schema --n 10 --protocol PROTOCOL.md

No search, and nothing written to a run record. For each call it reports
whether the endpoint answered, whether the answer parsed against the schema,
which candidates survived the vocabulary and argument checks, the tokens in
and out, and the latency. Then the totals that decide whether a run fits a
budget: tokens per call, and a projection for a 600-step run on the 120-
statement test set (up to 120 calls per statement at k=5).

It only runs on a set the protocol registers as not held out (dev), so it can
run before the prompt is frozen and cannot touch the test sets.
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proventhru.cli import _statements  # noqa: E402
from proventhru.policy_openai import ModelUnavailable, OpenAICompatPolicy  # noqa: E402
from proventhru.protocol import check, load  # noqa: E402
from proventhru.session import open_session  # noqa: E402
from proventhru.pipeline import environment  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="examples/eval_open.txt")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--key-env", default="HF_TOKEN")
    ap.add_argument("--response-format", default="json_object",
                    choices=["json_schema", "json_object", "none"])
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--backend", default="coqtop")
    ap.add_argument("--protocol", required=True)
    ap.add_argument("--json", default=None, help="also write every call's details here")
    a = ap.parse_args(argv)

    preamble, stmts = _statements(a.set)
    pol = OpenAICompatPolicy(preamble, a.model, a.base_url, key_env=a.key_env or None,
                             k=a.k, response_format=a.response_format, retries=2)
    stamp = check(load(a.protocol), preamble, stmts, pol.identity,
                  environment(preamble, a.backend), {"budget": None, "step_budget": None})
    if stamp["set"] in (load(a.protocol)["frozen"].get("held_out") or []):
        raise SystemExit("smoke tests run on dev sets only")
    rows = []
    for stmt in stmts[: a.n]:
        s = open_session(preamble, stmt, a.backend)
        try:
            try:
                out = pol.propose(s.root_obs, [])
            except ModelUnavailable as e:
                out = None
                pol.last_cost = e.cost
        finally:
            s.close()
        c = dict(pol.last_cost or {})
        rows.append({"statement": stmt, "candidates": [t for t, _ in (out or [])], **c})
        status = ("API FAILED" if out is None else
                  f"invalid: {c['failure']['why']}" if c.get("failure") else
                  f"{len(out)} valid, {len(c.get('dropped', []))} dropped")
        print(f"- {stmt}\n    {status}; tokens {c.get('input_tokens')} in / "
              f"{c.get('output_tokens')} out; {c.get('model_ms')} ms; served "
              f"{c.get('served_model')} via {c.get('served_provider')}")
        if out:
            print("    " + "  ".join(t for t, _ in out))
        for d in c.get("dropped", []):
            print(f"    dropped {d.get('candidate')}: {d.get('why')}")
        if c.get("api_errors"):
            print(f"    api errors: {c['api_errors'][-1]}")

    answered = [r for r in rows if r.get("input_tokens")]
    valid = [r for r in rows if r["candidates"]]
    print(f"\n{len(rows)} calls: {len(answered)} answered, {len(valid)} with a valid candidate, "
          f"{sum(1 for r in rows if (r.get('failure') or {}).get('kind') == 'invalid')} invalid, "
          f"{sum(1 for r in rows if (r.get('failure') or {}).get('kind') == 'api')} api failures")
    if answered:
        tin = statistics.mean(r["input_tokens"] for r in answered)
        tout = statistics.mean(r["output_tokens"] for r in answered)
        ms = statistics.median(r["model_ms"] for r in answered)
        calls = 120 * 120
        print(f"per call: {tin:.0f} tokens in, {tout:.0f} out, median {ms:.0f} ms")
        print(f"a 600-step run on test (at most {calls:,} calls): at most "
              f"{calls * (tin + tout) / 1e6:.1f}M tokens; sequential wall time at most "
              f"{calls * ms / 3.6e6:.1f} h (less with --jobs, and less as proofs end early)")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rows, fh, indent=1)


if __name__ == "__main__":
    main()
