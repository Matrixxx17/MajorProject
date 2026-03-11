"""
train_ppo.py — Offline TRL+PPO fine-tuning for code refactoring
================================================================
Trains a GPT-2-scale model (default: Salesforce/codegen-350M-mono)
to refactor Python code using a static reward function identical
to the one used in Codexter's live simulated-PPO tab.

Hardware: works on CPU / integrated GPU (AMD Ryzen 7 5800HS).
          Expect ~2-6 hours for 1 epoch on a 200-sample dataset.

Usage
-----
  pip install trl transformers datasets torch pycodestyle radon

  # 1. Generate a training dataset from your codebase
  python train_ppo.py --build-dataset --source-dir ./my_project --output dataset.json

  # 2. Train
  python train_ppo.py --train --dataset dataset.json --output-dir ./codexter_ppo_model

  # 3. Run inference with fine-tuned model
  python train_ppo.py --infer --model-dir ./codexter_ppo_model --input my_file.py

Dependencies
------------
  pip install trl>=0.7 transformers>=4.38 datasets torch pycodestyle radon
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# ── Optional imports — degrade gracefully if not installed ────────────────────
try:
    import torch
    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False

try:
    import pycodestyle
    _PEP8_OK = True
except ImportError:
    _PEP8_OK = False

try:
    from radon.complexity import cc_visit
    from radon.metrics import h_visit
    _RADON_OK = True
except ImportError:
    _RADON_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# Reward function  (mirrors main.py exactly)
# ══════════════════════════════════════════════════════════════════════════════

REWARD_WEIGHTS = {"cyclomatic": 0.35, "pep8": 0.30, "halstead": 0.20, "loc": 0.15}


def _pep8_count(code: str) -> int:
    if not _PEP8_OK:
        return 0
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code); fname = f.name
        r = subprocess.run(
            [sys.executable, "-m", "pycodestyle", "--statistics", "-q", fname],
            capture_output=True, text=True, timeout=10)
        os.unlink(fname)
        return sum(int(p.split()[0]) for p in r.stdout.strip().splitlines()
                   if p.split() and p.split()[0].isdigit())
    except Exception:
        return 0


def _cyclomatic(code: str) -> float:
    if _RADON_OK:
        try:
            res = cc_visit(code)
            if res:
                return round(sum(r.complexity for r in res) / len(res), 2)
            return 1.0
        except Exception:
            pass
    kw = ["if ", "elif ", "for ", "while ", "except ", "and ", "or "]
    count = sum(code.count(k) for k in kw)
    lines = [l for l in code.splitlines() if l.strip()]
    return round(1 + count / max(len(lines), 1) * 10, 2)


def _halstead(code: str) -> float:
    if _RADON_OK:
        try:
            result = h_visit(code)
            if result:
                return round(result[0].difficulty, 2)
        except Exception:
            pass
    try:
        tree = ast.parse(code)
        ops, ods = 0, 0; uo, ud = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                                  ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq,
                                  ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                ops += 1; uo.add(type(node).__name__)
            if isinstance(node, ast.Name):
                ods += 1; ud.add(node.id)
            elif isinstance(node, ast.Constant):
                ods += 1
        if ud:
            return round((len(uo) / 2.0) * (ods / len(ud)), 2)
    except Exception:
        pass
    return 0.0


def _loc(code: str) -> int:
    return sum(1 for l in code.splitlines()
               if l.strip() and not l.strip().startswith("#"))


def compute_metrics(code: str) -> dict:
    return {
        "loc":        _loc(code),
        "cyclomatic": _cyclomatic(code),
        "halstead":   _halstead(code),
        "pep8":       _pep8_count(code),
    }


def compute_reward(before: dict, after: dict) -> float:
    """Returns reward in [-1.0, 1.0]. Positive = improvement."""
    total = 0.0
    for key, weight in REWARD_WEIGHTS.items():
        bv = before[key]; av = after[key]
        if bv == 0:
            comp = 0.0 if av == 0 else -1.0
        else:
            ratio = bv / max(av, 0.01)
            comp  = max(-1.0, min(1.0, ratio - 1.0))
        total += weight * comp
    return round(total, 4)


# ══════════════════════════════════════════════════════════════════════════════
# Dataset builder
# ══════════════════════════════════════════════════════════════════════════════

PROMPT_TEMPLATE = (
    "Refactor the following Python module to improve readability, "
    "reduce complexity, and fix PEP8 violations. "
    "Return only the refactored code.\n\n"
    "```python\n{code}\n```\n\nRefactored:\n"
)


def build_dataset(source_dir: str, output_path: str, max_files: int = 500):
    """
    Scan source_dir for .py files and build a JSON dataset of
    (prompt, original_code) pairs suitable for PPO training.

    The reward signal is computed at training time by comparing
    the model's output to the original using compute_reward().
    """
    source_dir = Path(source_dir)
    files = list(source_dir.rglob("*.py"))
    files = [f for f in files if not f.name.startswith("test_")][:max_files]

    if not files:
        print(f"[ERROR] No Python files found in {source_dir}")
        sys.exit(1)

    samples = []
    skipped = 0
    for fp in files:
        try:
            code = fp.read_text(encoding="utf-8")
            # skip trivially small or auto-generated files
            loc = _loc(code)
            if loc < 10 or loc > 600:
                skipped += 1; continue
            ast.parse(code)  # skip files with syntax errors
            samples.append({
                "prompt":      PROMPT_TEMPLATE.format(code=code),
                "source_code": code,
                "filename":    str(fp),
                "metrics":     compute_metrics(code),
            })
        except Exception:
            skipped += 1

    print(f"Built {len(samples)} samples ({skipped} skipped).")
    with open(output_path, "w") as f:
        json.dump(samples, f, indent=2)
    print(f"Saved to {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# Training
# ══════════════════════════════════════════════════════════════════════════════

BASE_MODEL = "Salesforce/codegen-350M-mono"   # ~700 MB, fits in CPU RAM


def train(
    dataset_path: str,
    output_dir: str,
    base_model: str = BASE_MODEL,
    learning_rate: float = 1.41e-5,
    batch_size: int = 1,        # keep at 1 for CPU
    mini_batch_size: int = 1,
    ppo_epochs: int = 4,
    max_train_steps: int = 200,
    max_new_tokens: int = 512,
):
    if not _TORCH_OK:
        print("[ERROR] torch not installed. Run: pip install torch")
        sys.exit(1)

    try:
        from trl import PPOTrainer, PPOConfig, AutoModelForCausalLMWithValueHead
        from transformers import AutoTokenizer, pipeline
    except ImportError:
        print("[ERROR] trl/transformers not installed.")
        print("  Run: pip install trl transformers")
        sys.exit(1)

    print(f"Loading base model: {base_model}")
    print("Note: first run downloads ~700 MB. Subsequent runs use cache.")

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLMWithValueHead.from_pretrained(base_model)
    ref_model = AutoModelForCausalLMWithValueHead.from_pretrained(base_model)

    ppo_config = PPOConfig(
        model_name=base_model,
        learning_rate=learning_rate,
        batch_size=batch_size,
        mini_batch_size=mini_batch_size,
        ppo_epochs=ppo_epochs,
        log_with=None,
        ratio_threshold=10.0,
        use_score_scaling=True,
        use_score_norm=True,
        whiten_rewards=True,
    )

    trainer = PPOTrainer(
        config=ppo_config,
        model=model,
        ref_model=ref_model,
        tokenizer=tokenizer,
    )

    print(f"Loading dataset from {dataset_path}")
    with open(dataset_path) as f:
        samples = json.load(f)

    print(f"Training for up to {max_train_steps} steps on {len(samples)} samples.")
    print("This will take a while on CPU — expect ~2-6 hours for 200 steps.\n")

    step = 0
    for epoch in range(max(1, max_train_steps // max(len(samples), 1)) + 1):
        for sample in samples:
            if step >= max_train_steps:
                break

            prompt        = sample["prompt"]
            original_code = sample["source_code"]
            before        = sample.get("metrics") or compute_metrics(original_code)

            # ── Tokenise prompt ───────────────────────────────────────────────
            input_ids = tokenizer.encode(prompt, return_tensors="pt",
                                         max_length=512, truncation=True)
            query_tensors = [input_ids[0]]

            # ── Generate response ─────────────────────────────────────────────
            with torch.no_grad():
                response_tensors = trainer.generate(
                    query_tensors,
                    max_new_tokens=max_new_tokens,
                    pad_token_id=tokenizer.eos_token_id,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.9,
                )

            response_text = tokenizer.decode(
                response_tensors[0][input_ids.shape[1]:],
                skip_special_tokens=True,
            )

            # ── Compute reward ────────────────────────────────────────────────
            generated_code = _extract_code(response_text) or response_text
            try:
                after  = compute_metrics(generated_code)
                reward = compute_reward(before, after)
            except Exception:
                reward = -0.5   # penalise unparseable output

            reward_tensor = torch.tensor([reward], dtype=torch.float32)

            # ── PPO update ────────────────────────────────────────────────────
            stats = trainer.step(query_tensors, response_tensors, [reward_tensor])

            step += 1
            if step % 10 == 0:
                mean_reward = stats.get("ppo/mean_scores", reward)
                print(f"  step {step:>4}/{max_train_steps}  "
                      f"reward={reward:+.3f}  mean={mean_reward:.3f}")

        if step >= max_train_steps:
            break

    print(f"\nTraining complete ({step} steps). Saving to {output_dir} …")
    os.makedirs(output_dir, exist_ok=True)
    trainer.model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"Model saved to {output_dir}")
    print("\nTo use in Codexter, set the Ollama model field to 'local' and point")
    print("the backend at this directory (advanced config — see README).")


def _extract_code(text: str) -> Optional[str]:
    """Pull Python code from markdown fences or return raw text."""
    m = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```[a-z]*\s*\n(.*?)```", text, re.DOTALL)
    if m:
        c = m.group(1).strip()
        if "def " in c or "import " in c:
            return c
    m = re.search(r"^(import |from |def |class )", text, re.MULTILINE)
    if m:
        return text[m.start():].strip()
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Inference with fine-tuned model
# ══════════════════════════════════════════════════════════════════════════════

def infer(model_dir: str, input_file: str, output_file: Optional[str] = None):
    if not _TORCH_OK:
        print("[ERROR] torch not installed.")
        sys.exit(1)
    try:
        from transformers import AutoTokenizer, AutoModelForCausalLM
    except ImportError:
        print("[ERROR] transformers not installed.")
        sys.exit(1)

    code = Path(input_file).read_text(encoding="utf-8")
    before = compute_metrics(code)
    print(f"Before — LOC:{before['loc']}  CC:{before['cyclomatic']}  "
          f"HD:{before['halstead']}  PEP8:{before['pep8']}")

    print(f"Loading fine-tuned model from {model_dir} …")
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model     = AutoModelForCausalLM.from_pretrained(model_dir)
    model.eval()

    prompt    = PROMPT_TEMPLATE.format(code=code)
    input_ids = tokenizer.encode(prompt, return_tensors="pt",
                                 max_length=512, truncation=True)

    print("Generating …")
    with torch.no_grad():
        output_ids = model.generate(
            input_ids,
            max_new_tokens=512,
            pad_token_id=tokenizer.eos_token_id,
            do_sample=True,
            temperature=0.4,
            top_p=0.9,
        )

    response = tokenizer.decode(
        output_ids[0][input_ids.shape[1]:], skip_special_tokens=True)
    refactored = _extract_code(response) or response

    after  = compute_metrics(refactored)
    reward = compute_reward(before, after)

    print(f"After  — LOC:{after['loc']}  CC:{after['cyclomatic']}  "
          f"HD:{after['halstead']}  PEP8:{after['pep8']}")
    print(f"Reward: {reward:+.3f}  "
          f"(LOC Δ{before['loc']-after['loc']:+d}  "
          f"CC Δ{before['cyclomatic']-after['cyclomatic']:+.2f}  "
          f"PEP8 Δ{before['pep8']-after['pep8']:+d})")

    if output_file:
        Path(output_file).write_text(refactored, encoding="utf-8")
        print(f"Saved refactored code to {output_file}")
    else:
        print("\n── Refactored code ──────────────────────────────────\n")
        print(refactored)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Codexter offline TRL+PPO training for code refactoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build-dataset", action="store_true",
                      help="Scan source files and build training dataset")
    mode.add_argument("--train",  action="store_true",
                      help="Run TRL+PPO training")
    mode.add_argument("--infer",  action="store_true",
                      help="Run inference with a fine-tuned model")

    # dataset builder
    parser.add_argument("--source-dir", default=".",
                        help="Directory to scan for .py files (--build-dataset)")
    parser.add_argument("--max-files", type=int, default=500,
                        help="Max files to include in dataset")

    # shared
    parser.add_argument("--dataset",    default="codexter_dataset.json",
                        help="Dataset JSON path (used by --build-dataset and --train)")
    parser.add_argument("--output-dir", default="./codexter_ppo_model",
                        help="Where to save the fine-tuned model (--train)")
    parser.add_argument("--output",     default=None,
                        help="Output file for refactored code (--infer)")

    # training hyper-params
    parser.add_argument("--base-model",  default=BASE_MODEL)
    parser.add_argument("--lr",          type=float, default=1.41e-5)
    parser.add_argument("--steps",       type=int,   default=200)
    parser.add_argument("--ppo-epochs",  type=int,   default=4)
    parser.add_argument("--max-tokens",  type=int,   default=512)

    # inference
    parser.add_argument("--model-dir", default="./codexter_ppo_model",
                        help="Fine-tuned model directory (--infer)")
    parser.add_argument("--input",     default=None,
                        help="Python file to refactor (--infer)")

    args = parser.parse_args()

    if args.build_dataset:
        build_dataset(args.source_dir, args.dataset, args.max_files)

    elif args.train:
        if not os.path.exists(args.dataset):
            print(f"[ERROR] Dataset not found: {args.dataset}")
            print("  Run first: python train_ppo.py --build-dataset --source-dir .")
            sys.exit(1)
        train(
            dataset_path=args.dataset,
            output_dir=args.output_dir,
            base_model=args.base_model,
            learning_rate=args.lr,
            max_train_steps=args.steps,
            ppo_epochs=args.ppo_epochs,
            max_new_tokens=args.max_tokens,
        )

    elif args.infer:
        if not args.input:
            print("[ERROR] --input <file.py> required for --infer")
            sys.exit(1)
        infer(args.model_dir, args.input, args.output)


if __name__ == "__main__":
    main()