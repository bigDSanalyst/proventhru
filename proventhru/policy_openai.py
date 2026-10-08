"""A model policy over any OpenAI-compatible chat endpoint.

One adapter, configured by base URL, model and the name of the environment
variable that holds the key:

  Hugging Face router  https://router.huggingface.co/v1   HF_TOKEN   "org/model:provider"
  vLLM (e.g. Colab)    http://localhost:8000/v1            (none)     the served model name
  Gemini (compat)      https://generativelanguage.googleapis.com/v1beta/openai   GEMINI_API_KEY
  OpenRouter           https://openrouter.ai/api/v1        OPENROUTER_API_KEY

Same view, vocabulary, schema and argument checks as the Claude policy
(policy_claude), so conditions differ in the model and nothing else. The
prompt is fixed text, PROMPT below, and its hash (prompt_sha256, over the
template, the schema, the vocabulary and the code that renders the state) is
in the policy's identity: the protocol registers it, and a changed prompt is a
different hash.

Three kinds of failure are kept apart, because only the third is about the
model's reasoning:

  api      the call failed: timeout, connection error, 429, 5xx (retried with
           backoff; each failure is listed in cost.api_errors), or a 4xx that
           retrying cannot fix. When retries run out, ModelUnavailable is
           raised and the run stops: rerun it and it resumes.
  invalid  the model answered, but not usably: not JSON, no candidates list,
           cut off at max_tokens (cost.failure), or a candidate outside the
           vocabulary or with a bad argument (cost.dropped).
  unproductive  a valid tactic that Coq refused, that timed out, or that
           led back to a state already seen: visible in the steps, counted by
           the report.

Responses are cached on disk by a hash of the request, so a rerun (or a
resumed run) makes no calls for the requests it has already made and gets
exactly the responses it got before.
"""
import hashlib
import inspect
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request

from . import view
from .policy_claude import SCHEMA, VOCABULARY, assemble
from .record import canon
from .search import Policy

PROMPT = """You choose the next tactic in an interactive Coq (Rocq) proof.

You are given the current proof state as JSON: every open goal with its
hypotheses, the tactic path taken so far, and, when the last attempt failed,
that tactic and Coq's exact error message. The first goal is the one the next
tactic acts on.

Propose up to {k} candidate tactics for the next step, best first. Each
candidate is one tactic name from the allowed list, plus its argument:

- the argument is whatever follows the name, without the final period:
  hypothesis or variable names from the state ("n", "H as [x Hx]"), a term
  ("(S n)"), or a standard-library lemma name ("Nat.add_comm", "<- IHn",
  "app_nil_r"); use "" when the tactic takes none.
- one tactic per candidate: no ";", no "||", no "try", no second sentence.
- candidates must differ from each other. Prefer a step that makes progress
  on the first goal over one that only restates it.
- if the last failure is shown, do not repeat that tactic at the same path;
  read Coq's message for why it failed.

Allowed tactic names: {vocab}.

The libraries loaded are given by the preamble: {preamble}

Reply with one JSON object and nothing else, in exactly this form:
{{"candidates": [{{"tactic": "induction", "argument": "l"}}, {{"tactic": "simpl", "argument": ""}}]}}"""

USER = "the proof state: view.state(obs, path, last_failure) as json.dumps(sort_keys=True)"


def prompt_sha256():
    """Everything that decides what the model is shown and asked for."""
    return hashlib.sha256(canon({
        "template": PROMPT, "user": USER, "schema": SCHEMA, "vocabulary": list(VOCABULARY),
        "view": inspect.getsource(view),
    }).encode()).hexdigest()


class ModelUnavailable(RuntimeError):
    unavailable = True

    def __init__(self, msg, cost):
        super().__init__(msg)
        self.cost = cost


class HTTPTransport:
    def post(self, url, headers, body, timeout):
        req = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read().decode(errors="replace")


class ResponseCache:
    """Append-only JSONL of {key, status, headers, body}; successful responses only."""

    def __init__(self, path):
        self.path, self.lock, self.data = path, threading.Lock(), {}
        if os.path.exists(path):
            with open(path) as fh:
                for ln in fh:
                    if ln.strip():
                        e = json.loads(ln)
                        self.data[e["key"]] = e

    def get(self, key):
        return self.data.get(key)

    def put(self, key, status, headers, body):
        e = {"key": key, "status": status, "headers": headers, "body": body}
        with self.lock:
            with open(self.path, "a") as fh:
                fh.write(json.dumps(e, sort_keys=True) + "\n")
            self.data[key] = e


_CACHES, _CACHES_LOCK = {}, threading.Lock()


def shared_cache(path):
    """One ResponseCache per file in this process, so policies on parallel
    workers share its lock and what it holds."""
    key = os.path.abspath(path)
    with _CACHES_LOCK:
        if key not in _CACHES:
            _CACHES[key] = ResponseCache(key)
        return _CACHES[key]


RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 529}
KEEP_HEADERS = re.compile(r"^(x-inference|x-request-id|x-compute|x-ratelimit|openrouter|retry-after)",
                          re.I)


def extract_json(text):
    """The JSON object in a reply, tolerating code fences and prose around it."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i:j + 1])
        except ValueError:
            pass
    return None


class OpenAICompatPolicy(Policy):
    """response_format: "json_schema" (constrained to SCHEMA; vLLM and some
    providers), "json_object" (JSON mode), or "none" (prompt only)."""

    def __init__(self, preamble, model, base_url, key_env="HF_TOKEN", k=5, temperature=0.0,
                 seed=0, max_tokens=400, response_format="json_object", cache=None,
                 transport=None, retries=6, backoff=2.0, max_backoff=60.0, timeout=120,
                 max_calls=None, sleep=time.sleep, provider=None):
        self.model, self.base_url = model, base_url.rstrip("/")
        self.key_env, self.k = key_env, k
        self.temperature, self.seed, self.max_tokens = temperature, seed, max_tokens
        self.response_format = response_format
        self.cache = shared_cache(cache) if isinstance(cache, str) else cache
        self.transport = transport or HTTPTransport()
        self.retries, self.backoff, self.max_backoff = retries, backoff, max_backoff
        self.timeout, self.max_calls, self.calls, self.sleep = timeout, max_calls, 0, sleep
        self.system = PROMPT.format(k=k, vocab=", ".join(VOCABULARY),
                                    preamble=preamble.strip() or "(none)")
        self.identity = {"id": "openai-compat/v1", "model": model,
                         "provider": provider or self.base_url, "base_url": self.base_url,
                         "k": k, "temperature": temperature, "seed": seed,
                         "max_tokens": max_tokens, "response_format": response_format,
                         "prompt_sha256": prompt_sha256(), "vocabulary": list(VOCABULARY)}
        self.last_cost = None

    def _body(self, state):
        body = {"model": self.model,
                "messages": [{"role": "system", "content": self.system},
                             {"role": "user", "content": json.dumps(state, sort_keys=True)}],
                "temperature": self.temperature, "seed": self.seed,
                "max_tokens": self.max_tokens}
        if self.response_format == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "candidates", "schema": SCHEMA, "strict": True}}
        elif self.response_format == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    def _call(self, body, cost):
        """(status, headers, text) of a successful call; raises ModelUnavailable."""
        url = self.base_url + "/chat/completions"
        text = canon(body)
        key = hashlib.sha256(canon({"url": url, "body": body}).encode()).hexdigest()
        cost["cache_key"] = key
        hit = self.cache.get(key) if self.cache else None
        if hit:
            cost["cache"] = "hit"
            return hit["status"], hit["headers"], hit["body"]
        cost["cache"] = "miss" if self.cache else None
        headers = {"Content-Type": "application/json"}
        tok = os.environ.get(self.key_env) if self.key_env else None
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        for attempt in range(self.retries + 1):
            try:
                status, hdrs, resp = self.transport.post(url, headers, text, self.timeout)
            except Exception as e:  # timeouts, connection errors
                status, hdrs, resp = None, {}, repr(e)
            if status == 200:
                kept = {k.lower(): v for k, v in hdrs.items() if KEEP_HEADERS.match(k)}
                if self.cache:
                    self.cache.put(key, status, kept, resp)
                return status, kept, resp
            cost["api_errors"].append({"status": status, "detail": (resp or "")[:300]})
            if status is not None and status not in RETRYABLE:
                break
            if attempt < self.retries:
                cost["retries"] += 1
                wait = min(self.max_backoff, self.backoff * 2 ** attempt) * (0.5 + random.random())
                ra = {k.lower(): v for k, v in hdrs.items()}.get("retry-after")
                if ra and str(ra).replace(".", "", 1).isdigit():
                    wait = max(wait, float(ra))
                self.sleep(wait)
        cost["failure"] = {"kind": "api", "status": status,
                           "detail": cost["api_errors"][-1]["detail"]}
        raise ModelUnavailable(f"{self.model} at {self.base_url}: status {status} after "
                               f"{cost['retries']} retries", cost)

    def propose(self, obs, path, last_failure=None):
        if self.max_calls is not None and self.calls >= self.max_calls:
            self.last_cost = {"model": self.model, "skipped": "max_calls reached"}
            return []
        self.calls += 1
        state = view.state(obs, path, last_failure)
        cost = {"model": self.model, "served_model": None, "served_provider": None,
                "input_tokens": 0, "output_tokens": 0, "model_ms": None,
                "stop_reason": None, "request_id": None, "dropped": [], "failure": None,
                "retries": 0, "api_errors": [], "cache": None, "cache_key": None}
        self.last_cost = cost
        t0 = time.perf_counter()
        try:
            _, hdrs, text = self._call(self._body(state), cost)
        finally:
            cost["model_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        try:
            resp = json.loads(text)
            choice = resp["choices"][0]
            content = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError):
            cost["failure"] = {"kind": "invalid", "why": "not a chat completion",
                               "raw": text[:300]}
            return []
        u = resp.get("usage") or {}
        cost.update(served_model=resp.get("model"),
                    served_provider=hdrs.get("x-inference-provider") or resp.get("provider"),
                    input_tokens=u.get("prompt_tokens", 0) or 0,
                    output_tokens=u.get("completion_tokens", 0) or 0,
                    stop_reason=choice.get("finish_reason"),
                    request_id=hdrs.get("x-request-id") or resp.get("id"))
        if choice.get("finish_reason") == "length":
            cost["failure"] = {"kind": "invalid", "why": "cut off at max_tokens",
                               "raw": content[:300]}
            return []
        parsed = extract_json(content)
        raw = parsed.get("candidates") if isinstance(parsed, dict) else None
        if not isinstance(raw, list):
            cost["failure"] = {"kind": "invalid",
                               "why": "not JSON" if parsed is None else "no candidates list",
                               "raw": content[:300]}
            return []
        out, seen = [], set()
        for i, c in enumerate(raw[: self.k]):
            if not isinstance(c, dict):
                cost["dropped"].append({"candidate": c, "why": "not an object"})
                continue
            tac, why = assemble(c.get("tactic"), c.get("argument"))
            if tac is None:
                cost["dropped"].append({"candidate": c, "why": why})
            elif tac in seen:
                cost["dropped"].append({"candidate": c, "why": "duplicate"})
            else:
                seen.add(tac)
                out.append((tac, 1.0 - i / max(self.k, 1)))
        if not out:
            cost["failure"] = {"kind": "invalid", "why": "no valid candidate",
                               "raw": content[:300]}
        return out
