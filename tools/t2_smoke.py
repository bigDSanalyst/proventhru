"""Target 2's smoke test (docs/rsi-target2-prover-dpo.md, step 3): the update rule on 50 pairs.

    python tools/t2_smoke.py --pairs PAIRS.jsonl --weights SNAPSHOT_DIR --out DIR

It runs in Colab on the A100, after vLLM is stopped (training needs the GPU's memory).
It takes 50 of step 2's 82 pairs (a sample with seed 0), trains one LoRA adapter with DPO
under the doc's fixed values, and writes DIR/smoke.json with what the amendment needs:
the loss curve with DPO reward accuracy and margin per step, the training time per pair,
peak GPU memory, the longest pair in tokens, the adapter's sha256, and the exact torch,
transformers, trl, peft, accelerate and datasets versions. The adapter goes to
DIR/adapter, for the notebook to serve with vLLM as `MODEL+dpo-smoke`.

The doc fixes the values; nothing is tuned here. Two are the amendment's to fix after
this runs: the effective batch size (tried here as 1 x 8) and the versions (trl 1.17.1
and peft 0.21.2, installed next to vLLM 0.31.0's torch and transformers). TRL's default
would zero every dropout, LoRA's included, so disable_dropout is off to keep the doc's
LoRA dropout of 0.05.
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import time

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOC, CODE_ROW = "docs/rsi-target2-prover-dpo.md", "code:target-2-smoke"
MODEL = "Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28"   # M1
PAIRS_SHA256 = "53eada391ce8f1a7c1d1be9b36c848084c5ccea7bde724cbf961f59d6d3f21bd"   # step 2's
N, SAMPLE_SEED = 50, 0
# The doc's update rule. Attention and MLP projections: Qwen2's q, k, v, o and gate, up, down.
LORA = {"r": 16, "lora_alpha": 32, "lora_dropout": 0.05, "bias": "none", "task_type": "CAUSAL_LM",
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                           "gate_proj", "up_proj", "down_proj"]}
DPO = {"beta": 0.1, "learning_rate": 5e-6, "num_train_epochs": 1, "loss_type": ["sigmoid"],
       "label_smoothing": 0.0, "max_length": 3072,
       "optim": "adamw_torch", "adam_beta1": 0.9, "adam_beta2": 0.999, "weight_decay": 0.0,
       "lr_scheduler_type": "linear", "warmup_steps": 0.1,      # a float below 1: a ratio
       "seed": 0, "data_seed": 0, "bf16": True, "gradient_checkpointing": True,
       "disable_dropout": False,                                # keep LoRA's 0.05
       "per_device_train_batch_size": 1, "gradient_accumulation_steps": 8,   # the amendment's
       "logging_steps": 1, "save_strategy": "no", "report_to": []}
GOVERNED = ["tools/t2_smoke.py"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_hash(repo, paths=GOVERNED):
    h = hashlib.sha256()
    for p in paths:
        h.update(f"{p} {sha256_file(os.path.join(repo, p))}\n".encode())
    return h.hexdigest()


def preflight(pairs, repo=HERE):
    """The smoke test runs on step 2's pairs, under the frozen doc and its open code row."""
    got = sha256_file(pairs)
    if got != PAIRS_SHA256:
        raise SystemExit(f"{pairs} has sha256 {got[:16]}, not step 2's pairs ({PAIRS_SHA256[:16]})")
    with open(os.path.join(repo, "docs", "frozen.md")) as fh:
        rows = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([0-9a-f]{64})`\s*\|",
                          fh.read(), re.M)
    digest = sha256_file(os.path.join(repo, DOC))
    docs = [r for r in rows if r[0] == DOC]
    if not docs or docs[-1][2] != digest:
        raise SystemExit(f"{DOC} isn't frozen at its current hash ({digest[:16]})")
    codes = [r for r in rows if r[0] == CODE_ROW]
    current = code_hash(repo)
    if not codes or codes[-1][1].strip() == "closed" or codes[-1][2] != current:
        raise SystemExit(f"the smoke test's code hashes to {current[:16]}, which isn't the "
                         f"latest open `{CODE_ROW}` row")
    return digest, current


def sample(rows):
    """The 50 pairs, by a seeded sample of their positions in the file."""
    return sorted(random.Random(SAMPLE_SEED).sample(range(len(rows)), N))


def examples(rows):
    """Pairs as TRL's conversational preference rows: the prompt's messages, and the
    chosen and rejected responses as the assistant's message."""
    return [{"prompt": r["prompt"],
             "chosen": [{"role": "assistant", "content": r["chosen"]}],
             "rejected": [{"role": "assistant", "content": r["rejected"]}]} for r in rows]


def versions():
    import importlib.metadata as md
    return {p: md.version(p) for p in
            ("torch", "transformers", "trl", "peft", "accelerate", "datasets")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True,
                    help="step 2's pairs file (Drive runs/t2-pairs-dev5.jsonl)")
    ap.add_argument("--weights", required=True, help="M1's snapshot at the pinned revision")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    doc_sha, code_sha = preflight(a.pairs)
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import DPOConfig, DPOTrainer

    gpu = torch.cuda.get_device_name(0)
    if "A100" not in gpu:
        raise SystemExit(f"the smoke test runs on the registered GPU class, an A100, not {gpu}")
    with open(a.pairs) as fh:
        rows = [json.loads(ln) for ln in fh if ln.strip()]
    idx = sample(rows)
    data = examples([rows[i] for i in idx])
    tok = AutoTokenizer.from_pretrained(a.weights)
    lengths = [len(tok.apply_chat_template(d["prompt"] + d[side], tokenize=True))
               for d in data for side in ("chosen", "rejected")]
    model = AutoModelForCausalLM.from_pretrained(a.weights, dtype=torch.bfloat16)
    os.makedirs(a.out, exist_ok=True)
    trainer = DPOTrainer(model=model, ref_model=None,
                         args=DPOConfig(output_dir=os.path.join(a.out, "trainer"), **DPO),
                         train_dataset=Dataset.from_list(data), processing_class=tok,
                         peft_config=LoraConfig(**LORA))
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    trainer.train()
    torch.cuda.synchronize()
    seconds = time.perf_counter() - t0
    adapter = os.path.join(a.out, "adapter")
    trainer.save_model(adapter)
    weights = os.path.join(adapter, "adapter_model.safetensors")
    out = {"model": MODEL, "gpu": gpu, "versions": versions(),
           "pairs_sha256": PAIRS_SHA256, "pairs_in_file": len(rows), "indices": idx,
           "by_condition": {c: sum(rows[i]["condition"] == c for i in idx) for c in ("C", "D")},
           "lora": LORA, "dpo": DPO, "max_tokens": max(lengths),
           "over_max_length": sum(x > DPO["max_length"] for x in lengths),
           "train_seconds": round(seconds, 1), "seconds_per_pair": round(seconds / N, 2),
           "optimizer_steps": trainer.state.global_step,
           "peak_gpu_memory_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
           "log": trainer.state.log_history,
           "adapter": {"path": adapter, "sha256": sha256_file(weights)},
           "doc_sha256": doc_sha, "code_sha256": code_sha}
    with open(os.path.join(a.out, "smoke.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps({k: out[k] for k in ("versions", "train_seconds", "seconds_per_pair",
                                          "optimizer_steps", "peak_gpu_memory_gib", "max_tokens",
                                          "over_max_length", "adapter")}, indent=1))
    for e in trainer.state.log_history:
        if "loss" in e:
            print({k: e[k] for k in e if k in ("step", "loss", "rewards/accuracies",
                                               "rewards/margins", "learning_rate")})


if __name__ == "__main__":
    sys.exit(main())
