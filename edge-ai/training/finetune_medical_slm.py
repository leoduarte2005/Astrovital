"""Layer 2: QLoRA (CUDA) / LoRA (CPU, opt-in) fine-tuning -> merged HF -> GGUF Q4_K_M.

Base model: ``Qwen/Qwen2.5-1.5B-Instruct``. Data: ``training/data/nasa_medical_instruct.jsonl``.
Heavy dependencies come from ``pip install -e .[finetune]`` in a dedicated training venv.
``--check-env`` and ``--dry-run`` never download models or start training.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_DEFAULT_DATA = Path(__file__).resolve().parent / "data" / "nasa_medical_instruct.jsonl"
_DEFAULT_OUT = Path(__file__).resolve().parents[1] / "models" / "slm"
_DEFAULT_WORK = Path(__file__).resolve().parent / "work" / "slm"
_REQUIRED_PKGS = ("torch", "transformers", "peft", "datasets", "trl", "accelerate")


def check_environment() -> dict[str, Any]:
    """Inspect the fine-tuning stack and hardware without mutating anything."""
    pkgs = {pkg: importlib.util.find_spec(pkg) is not None for pkg in (*_REQUIRED_PKGS, "bitsandbytes")}
    cuda_ok = False
    gpu_name = None
    if pkgs["torch"]:
        import torch

        cuda_ok = bool(torch.cuda.is_available())
        gpu_name = torch.cuda.get_device_name(0) if cuda_ok else None
    return {
        "packages": pkgs,
        "cuda_available": cuda_ok,
        "gpu_name": gpu_name,
        "recommended_mode": "qlora_4bit_cuda" if (cuda_ok and pkgs["bitsandbytes"]) else "lora_fp32_cpu",
        "ready_for_training": all(pkgs[p] for p in _REQUIRED_PKGS),
        "llama_quantize_bin": shutil.which("llama-quantize"),
    }


def load_chatml_split(data_path: Path, eval_ratio: float = 0.1) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [json.loads(ln) for ln in data_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not rows:
        raise ValueError(f"Empty dataset: {data_path}")
    # Keep only the chat turns; ``meta`` is bookkeeping and breaks Dataset schema inference.
    rows = [{"messages": r["messages"]} for r in rows]
    cut = max(1, int(len(rows) * (1.0 - eval_ratio)))
    return rows[:cut], rows[cut:] or rows[-1:]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fine-tune Qwen2.5-1.5B-Instruct on the EdgeSpace medical corpus.")
    p.add_argument("--data", type=Path, default=_DEFAULT_DATA)
    p.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT, help="Directory receiving the final GGUF")
    p.add_argument("--work-dir", type=Path, default=_DEFAULT_WORK)
    p.add_argument("--base-model", default="Qwen/Qwen2.5-1.5B-Instruct")
    p.add_argument("--check-env", action="store_true", help="Print environment report and exit")
    p.add_argument("--dry-run", action="store_true", help="Validate data + env, never train")
    p.add_argument("--allow-cpu", action="store_true", help="Permit slow fp32 LoRA when no CUDA GPU exists")
    p.add_argument("--force-no-4bit", action="store_true")
    p.add_argument("--lora-r", type=int, default=8)
    p.add_argument("--max-seq-len", type=int, default=768)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--max-steps", type=int, default=-1, help="Use e.g. 20 for a smoke run that measures s/step")
    p.add_argument("--resume", default=None, help="Checkpoint path to resume from")
    p.add_argument("--llama-cpp-convert", type=Path, default=None, help="Path to llama.cpp convert_hf_to_gguf.py")
    return p


def _train(args: argparse.Namespace, env: dict[str, Any], train_rows: list, eval_rows: list) -> Path:
    """Run (Q)LoRA SFT and return the merged HF directory. Imports heavy deps lazily."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    use_4bit = bool(env["cuda_available"] and env["packages"]["bitsandbytes"] and not args.force_no_4bit)
    tok = AutoTokenizer.from_pretrained(args.base_model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    kwargs: dict[str, Any] = {}
    if use_4bit:
        bf16 = torch.cuda.is_bf16_supported()
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16 if bf16 else torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        kwargs["device_map"] = "auto"
    else:
        kwargs["torch_dtype"] = torch.float32
    model = AutoModelForCausalLM.from_pretrained(args.base_model, **kwargs)
    if use_4bit:
        model = prepare_model_for_kbit_training(model)
    model = get_peft_model(
        model,
        LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_r * 2,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        ),
    )

    def _fmt(ex: dict[str, Any]) -> dict[str, str]:
        return {"text": tok.apply_chat_template(ex["messages"], tokenize=False)}

    train_ds = Dataset.from_list(train_rows).map(_fmt, remove_columns=["messages"])
    eval_ds = Dataset.from_list(eval_rows).map(_fmt, remove_columns=["messages"])

    args.work_dir.mkdir(parents=True, exist_ok=True)
    half = bool(use_4bit)
    cfg = SFTConfig(
        output_dir=str(args.work_dir / "checkpoints"),
        max_seq_length=args.max_seq_len,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        logging_steps=5,
        eval_strategy="steps",
        eval_steps=50,
        save_steps=50,
        save_total_limit=2,
        bf16=half and torch.cuda.is_bf16_supported(),
        fp16=half and not torch.cuda.is_bf16_supported(),
        report_to="none",
        dataset_text_field="text",
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=train_ds, eval_dataset=eval_ds, processing_class=tok)
    trainer.train(resume_from_checkpoint=args.resume)

    merged_dir = args.work_dir / "merged_hf"
    merged_dir.mkdir(parents=True, exist_ok=True)
    model.merge_and_unload().save_pretrained(merged_dir, safe_serialization=True)
    tok.save_pretrained(merged_dir)
    return merged_dir


def _export_gguf(args: argparse.Namespace, merged_dir: Path) -> None:
    """HF -> f16 GGUF -> Q4_K_M. Falls back to printing the exact commands when tools are absent."""
    args.out_dir.mkdir(parents=True, exist_ok=True)
    f16 = args.work_dir / "edgespace-medical-f16.gguf"
    q4 = args.out_dir / "edgespace-medical-q4_k_m.gguf"
    convert = args.llama_cpp_convert
    quant = shutil.which("llama-quantize")
    if convert and Path(convert).is_file():
        subprocess.run(
            [sys.executable, str(convert), str(merged_dir), "--outfile", str(f16), "--outtype", "f16"], check=True
        )
        if quant:
            subprocess.run([quant, str(f16), str(q4), "Q4_K_M"], check=True)
            print(f"GGUF ready: {q4}")
            return
        print(f"f16 GGUF at {f16}. Quantize: llama-quantize {f16} {q4} Q4_K_M")
        return
    print(
        f"Merged model: {merged_dir}\n"
        f"  python <llama.cpp>/convert_hf_to_gguf.py {merged_dir} --outfile {f16} --outtype f16\n"
        f"  llama-quantize {f16} {q4} Q4_K_M"
    )


def main() -> None:
    args = build_parser().parse_args()
    env = check_environment()
    if args.check_env:
        print(json.dumps(env, indent=2))
        return
    train_rows, eval_rows = load_chatml_split(args.data)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "env": env, "train": len(train_rows), "eval": len(eval_rows),
                          "target_gguf": str(args.out_dir / "edgespace-medical-q4_k_m.gguf")}, indent=2))
        return
    if not env["ready_for_training"]:
        missing = [k for k, ok in env["packages"].items() if not ok and k != "bitsandbytes"]
        raise SystemExit(f"Missing packages {missing}. Use a dedicated venv: pip install -e .[finetune]")
    if not env["cuda_available"] and not args.allow_cpu:
        raise SystemExit("No CUDA GPU. Run on an external CUDA machine, or pass --allow-cpu (very slow).")
    _export_gguf(args, _train(args, env, train_rows, eval_rows))


if __name__ == "__main__":
    main()

