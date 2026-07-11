"""Fine-grained AI workload models — WHAT the GPUs are actually running.

The physics engine's schedule blocks used to carry only a utilization number.
Each block now names a TYPED JOB (LLM pretraining / fine-tuning / batched or
interactive inference / vision inference / housekeeping) against a CONCRETE
model, and this module turns (gpu, job, utilization) into per-GPU numbers:

  achieved TFLOPS  = MFU × peak dense TFLOPS at the job's precision
  throughput       LLM:    tokens/s/GPU = achieved FLOPs / (k · params)
                            k = 6 for training, 2 for inference
                   vision: frames/s/GPU = achieved FLOPs / FLOPs-per-frame
  electrical power = the engine's calibrated TDP curve (idle floor 15 %,
                     linear in the block utilization) — kept as-is so the
                     power/thermal closure audit stays valid
  heat             = electrical power (a GPU converts essentially all input
                     power to heat; the ~5 % RF/light allowance is applied
                     once at the satellite level in the thermal model)

GPU peak numbers are public datasheet DENSE figures (no 2:1 sparsity):

  gpu      BF16 TF  FP8 TF  HBM      BW TB/s  TDP W
  H100 SXM   989     1979    80 GB    3.35     700
  H200 SXM   989     1979   141 GB    4.80     700
  B200      2250     4500   192 GB    8.00    1000
  MI300X    1307     2615   192 GB    5.30     750

MFU (model-FLOPs-utilization) baselines are conservative published ranges:
dense-batch LLM serving ~0.18, interactive (KV/bandwidth-bound) ~0.05,
large-model pretraining ~0.45, ViT-class vision at high batch 0.35-0.45.
MFU scales with the block's utilization relative to the job's nominal duty
(capped at 1.2×) so a hotter block also moves the throughput needle.
"""
from __future__ import annotations

from typing import Optional

from models import GpuJobDetail

# --- GPU datasheet table (dense tensor TFLOPS) ------------------------------
GPU_SPECS: dict[str, dict[str, float]] = {
    "H100":   {"bf16_tflops": 989.0,  "fp8_tflops": 1979.0, "hbm_gb": 80.0,
               "hbm_tbps": 3.35, "tdp_w": 700.0},
    "H200":   {"bf16_tflops": 989.0,  "fp8_tflops": 1979.0, "hbm_gb": 141.0,
               "hbm_tbps": 4.80, "tdp_w": 700.0},
    "B200":   {"bf16_tflops": 2250.0, "fp8_tflops": 4500.0, "hbm_gb": 192.0,
               "hbm_tbps": 8.00, "tdp_w": 1000.0},
    "MI300X": {"bf16_tflops": 1307.0, "fp8_tflops": 2615.0, "hbm_gb": 192.0,
               "hbm_tbps": 5.30, "tdp_w": 750.0},
}

# --- Model catalog -----------------------------------------------------------
AI_MODELS: dict[str, dict] = {
    "llama70b": {"label": "Llama-3.3-70B", "params": 70e9},
    "llama8b":  {"label": "Llama-3.1-8B",  "params": 8e9},
    "vit_eo":   {"label": "ViT-L/16 EO detector", "tflops_per_frame": 0.30},
}

# --- Typed jobs --------------------------------------------------------------
# kind: llm_train | llm_infer | vision | idle — selects the throughput law.
# precision picks the peak-TFLOPS column; mfu is the nominal model-FLOPs
# utilization at nominal_util (the block utilization the MFU was quoted at).
JOB_TYPES: dict[str, dict] = {
    "housekeeping": {
        "label": "Housekeeping / standby", "kind": "idle",
        "model": None, "precision": "-", "mfu": 0.0, "nominal_util": 0.10,
    },
    "vision_batch": {
        "label": "EO imagery batch inference", "kind": "vision",
        "model": "vit_eo", "precision": "FP8", "mfu": 0.35, "nominal_util": 0.70,
    },
    "vision_burst": {
        "label": "EO target burst classification", "kind": "vision",
        "model": "vit_eo", "precision": "FP8", "mfu": 0.45, "nominal_util": 0.95,
    },
    "llm_batch": {
        "label": "LLM batched inference", "kind": "llm_infer",
        "model": "llama70b", "precision": "FP8", "mfu": 0.18, "nominal_util": 0.80,
    },
    "llm_interactive": {
        "label": "LLM interactive serving", "kind": "llm_infer",
        "model": "llama70b", "precision": "FP8", "mfu": 0.05, "nominal_util": 0.30,
    },
    "llm_pretrain": {
        "label": "LLM pretraining", "kind": "llm_train",
        "model": "llama70b", "precision": "BF16", "mfu": 0.45, "nominal_util": 0.92,
    },
    "llm_finetune": {
        "label": "LLM adapter fine-tune", "kind": "llm_train",
        "model": "llama8b", "precision": "BF16", "mfu": 0.45, "nominal_util": 0.60,
    },
    "llm_eval": {
        "label": "LLM eval pass", "kind": "llm_infer",
        "model": "llama70b", "precision": "FP8", "mfu": 0.12, "nominal_util": 0.50,
    },
    "checkpoint_io": {
        "label": "Checkpoint write", "kind": "idle",
        "model": "llama70b", "precision": "-", "mfu": 0.0, "nominal_util": 0.35,
    },
}

_TRAIN_FLOPS_PER_TOKEN_FACTOR = 6.0   # fwd + bwd
_INFER_FLOPS_PER_TOKEN_FACTOR = 2.0   # fwd only


def job_detail(gpu_id: str, job_key: str, block_util: float,
               power_w_per_gpu: float, gpu_count: int) -> Optional[GpuJobDetail]:
    """Per-GPU compute/throughput/heat detail for the active schedule block.

    `block_util` is the block's power-duty fraction (the same number that
    drives the electrical/thermal physics); `power_w_per_gpu` is the engine's
    already-computed card power so the detail can never disagree with the
    physics. Returns None for unknown job keys."""
    job = JOB_TYPES.get(job_key)
    spec = GPU_SPECS.get(gpu_id)
    if job is None or spec is None:
        return None

    model_key = job["model"]
    model = AI_MODELS.get(model_key) if model_key else None

    # MFU tracks the block's duty relative to the job's nominal duty (a
    # hotter block of the same job also computes more), capped at +20 %.
    mfu = 0.0
    if job["mfu"] > 0.0:
        scale = min(1.2, max(0.0, block_util) / max(1e-6, job["nominal_util"]))
        mfu = job["mfu"] * scale

    peak_tflops = (spec["fp8_tflops"] if job["precision"] == "FP8"
                   else spec["bf16_tflops"])
    tflops = mfu * peak_tflops

    throughput = 0.0
    unit = "-"
    if model is not None and mfu > 0.0:
        if job["kind"] == "vision":
            throughput = tflops / model["tflops_per_frame"]
            unit = "frames/s"
        elif job["kind"] == "llm_train":
            throughput = (tflops * 1e12) / (_TRAIN_FLOPS_PER_TOKEN_FACTOR * model["params"])
            unit = "tok/s"
        else:  # llm_infer
            throughput = (tflops * 1e12) / (_INFER_FLOPS_PER_TOKEN_FACTOR * model["params"])
            unit = "tok/s"

    return GpuJobDetail(
        job=job_key,
        job_label=job["label"],
        model=model["label"] if model else "-",
        precision=job["precision"],
        mfu=round(mfu, 3),
        gpu_count=gpu_count,
        power_w_per_gpu=round(power_w_per_gpu, 1),
        heat_w_per_gpu=round(power_w_per_gpu, 1),
        tflops_per_gpu=round(tflops, 1),
        throughput_per_gpu=round(throughput, 1),
        throughput_total=round(throughput * gpu_count, 1),
        throughput_unit=unit,
    )
