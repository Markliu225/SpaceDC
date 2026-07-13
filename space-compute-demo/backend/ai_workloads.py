"""Fine-grained AI workload models — WHAT the GPUs are actually running.

The physics engine's schedule blocks used to carry only a utilization number.
Each block now names a TYPED JOB (LLM pretraining / fine-tuning / batched or
interactive inference / vision inference / housekeeping) against a CONCRETE
model, and this module turns (gpu, job, utilization) into per-GPU numbers:

LLM jobs (llm_infer / llm_train) now resolve through the ANALYTICAL
performance/power/thermal engine (llm_perf.py — the power-capped DVFS +
memory-floor decode law + thermal-throttle solve, validated against the
V100 measurement study in tools/validate_llm_perf.py):

  power cap        = the EPS budget the block's duty allocates per card
                     (TDP curve: idle floor 15 %, linear in utilization)
  operating point  = solve_operating_point(gpu, model, precision, phase,
                     cap, T_struct) — the thermal limit
                     (T_throttle − T_struct)/R_th shrinks the budget, the
                     DVFS aggregate maps budget → SM frequency, and the
                     phase law maps frequency → tokens/s
  electrical power = the REALIZED draw (decode pulls its natural draw,
                     which flattens below the cap on the bandwidth
                     plateau; compute-bound phases pull the full budget)
  die temperature  = T_struct + draw · R_th, with throttle/runaway flags

Vision / idle jobs (and GPU-model combos outside the llm_perf catalogs)
keep the MFU heuristic:

  achieved TFLOPS  = MFU × peak dense TFLOPS at the job's precision
  throughput       LLM:    tokens/s/GPU = achieved FLOPs / (k · params)
                            k = 6 for training, 2 for inference
                   vision: frames/s/GPU = achieved FLOPs / FLOPs-per-frame
  electrical power = the engine's calibrated TDP curve
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

import llm_perf as _perf
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
# LLM serving is the orbital DC's primary business: the catalog spans the
# deployed dense-model range (params must match llm_perf.LLM_PERF — the
# analytic engine resolves throughput; these labels feed the panels).
AI_MODELS: dict[str, dict] = {
    "llama70b":   {"label": "Llama-3.3-70B",       "params": 70e9},
    "llama8b":    {"label": "Llama-3.1-8B",        "params": 8e9},
    "llama405b":  {"label": "Llama-3.1-405B",      "params": 405e9},
    "qwen72b":    {"label": "Qwen2.5-72B",         "params": 72.7e9},
    "qwen32b":    {"label": "Qwen2.5-Coder-32B",   "params": 32.8e9},
    "mistral24b": {"label": "Mistral-Small-24B",   "params": 24e9},
    "vit_eo":     {"label": "ViT-L/16 EO detector", "tflops_per_frame": 0.30},
}

# --- Typed jobs --------------------------------------------------------------
# kind: llm_train | llm_infer | vision | idle — selects the throughput law.
# precision picks the peak-TFLOPS column; mfu is the nominal model-FLOPs
# utilization at nominal_util (the block utilization the MFU was quoted at) —
# used only on the MFU fallback path for LLM jobs.
# LLM jobs also carry the analytical-engine operating shape:
#   phase   — 'decode' (serving: memory-bound, bandwidth plateau) or
#             'train' (compute-bound, k=6 FLOPs/token)
#   batch   — concurrent decode rows per GPU (drives the KV memory floor)
#   context — effective KV window per row in tokens
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
        "phase": "decode", "batch": 48, "context": 2048,
    },
    "llm_interactive": {
        "label": "LLM interactive serving", "kind": "llm_infer",
        "model": "llama70b", "precision": "FP8", "mfu": 0.05, "nominal_util": 0.30,
        "phase": "decode", "batch": 8, "context": 1024,
    },
    "llm_pretrain": {
        "label": "LLM pretraining", "kind": "llm_train",
        "model": "llama70b", "precision": "BF16", "mfu": 0.45, "nominal_util": 0.92,
        "phase": "train", "batch": 0, "context": 8192,
    },
    "llm_finetune": {
        "label": "LLM adapter fine-tune", "kind": "llm_train",
        "model": "llama8b", "precision": "BF16", "mfu": 0.45, "nominal_util": 0.60,
        "phase": "train", "batch": 0, "context": 4096,
    },
    "llm_eval": {
        "label": "LLM eval pass", "kind": "llm_infer",
        "model": "llama70b", "precision": "FP8", "mfu": 0.12, "nominal_util": 0.50,
        "phase": "decode", "batch": 24, "context": 4096,
    },
    # --- LLM serving variety (the primary business) --------------------------
    "llm_chat_70b": {
        "label": "Chat serving · 70B", "kind": "llm_infer",
        "model": "llama70b", "precision": "FP8", "mfu": 0.14, "nominal_util": 0.70,
        "phase": "decode", "batch": 24, "context": 4096,
    },
    "llm_chat_8b": {
        "label": "Edge chat · 8B", "kind": "llm_infer",
        "model": "llama8b", "precision": "FP8", "mfu": 0.10, "nominal_util": 0.55,
        "phase": "decode", "batch": 64, "context": 2048,
    },
    "llm_code_32b": {
        "label": "Code assist · Coder-32B", "kind": "llm_infer",
        "model": "qwen32b", "precision": "FP8", "mfu": 0.10, "nominal_util": 0.60,
        "phase": "decode", "batch": 16, "context": 8192,
    },
    "llm_rag_72b": {
        "label": "RAG long-context · 72B", "kind": "llm_infer",
        "model": "qwen72b", "precision": "FP8", "mfu": 0.08, "nominal_util": 0.65,
        "phase": "decode", "batch": 8, "context": 16384,
    },
    "llm_summarize_24b": {
        "label": "Doc summarization · 24B", "kind": "llm_infer",
        "model": "mistral24b", "precision": "FP8", "mfu": 0.12, "nominal_util": 0.70,
        "phase": "decode", "batch": 32, "context": 8192,
    },
    "llm_frontier_405b": {
        "label": "Frontier serving · 405B", "kind": "llm_infer",
        "model": "llama405b", "precision": "FP8", "mfu": 0.10, "nominal_util": 0.85,
        "phase": "decode", "batch": 12, "context": 4096,
    },
    "checkpoint_io": {
        "label": "Checkpoint write", "kind": "idle",
        "model": "llama70b", "precision": "-", "mfu": 0.0, "nominal_util": 0.35,
    },
}

_TRAIN_FLOPS_PER_TOKEN_FACTOR = 6.0   # fwd + bwd
_INFER_FLOPS_PER_TOKEN_FACTOR = 2.0   # fwd only


def job_detail(gpu_id: str, job_key: str, block_util: float,
               power_w_per_gpu: float, gpu_count: int,
               t_struct_c: Optional[float] = None) -> Optional[GpuJobDetail]:
    """Per-GPU compute/throughput/heat detail for the active schedule block.

    `block_util` is the block's power-duty fraction; `power_w_per_gpu` is the
    engine's TDP-curve card power — the EPS budget per card. For LLM jobs
    with a structure temperature (`t_struct_c`), the ANALYTICAL engine
    resolves the coupled cap ∧ thermal-limit → frequency → tokens/s solve
    and the returned power is the REALIZED draw (the engine must then use it
    as the payload power so power/thermal physics and the detail agree).
    Vision/idle jobs — and combos outside the llm_perf catalogs — keep the
    MFU heuristic with the budget as the draw. Returns None for unknown
    job keys."""
    job = JOB_TYPES.get(job_key)
    spec = GPU_SPECS.get(gpu_id)
    if job is None or spec is None:
        return None

    model_key = job["model"]
    model = AI_MODELS.get(model_key) if model_key else None

    analytic = _analytic_detail(gpu_id, job_key, job, spec, model,
                                power_w_per_gpu, gpu_count, t_struct_c)
    if analytic is not None:
        return analytic

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


def _analytic_detail(gpu_id: str, job_key: str, job: dict, spec: dict,
                     model: Optional[dict], p_cap_w: float, gpu_count: int,
                     t_struct_c: Optional[float]) -> Optional[GpuJobDetail]:
    """LLM jobs through llm_perf's coupled power/thermal operating-point
    solve. Returns None when the analytic path doesn't apply (non-LLM job,
    no structure temperature, or GPU/model outside the perf catalogs)."""
    if t_struct_c is None or job["kind"] not in ("llm_infer", "llm_train"):
        return None
    model_key = job["model"]
    if gpu_id not in _perf.GPU_PERF or model_key not in _perf.LLM_PERF:
        return None

    phase = job.get("phase", "decode")
    batch = int(job.get("batch", 1) or 1)
    context = int(job.get("context", 2048))

    # The fitted cards serve as ONE ideal tensor-parallel group: weights, KV
    # and per-step compute all shard across gpu_count cards, so per-card
    # duty/draw/die-temp match the single-card solve and the aggregate
    # keeps its algebra (throughput_total = N × the full-model single-card
    # solve — the 1/N sharding cancels out of B/(T_mem + T_comp) exactly).
    # Communication overhead is NOT modeled; aggregates are ideal-TP upper
    # bounds (docs/physics.md §4a). Feasibility IS enforced: the weight
    # shard must fit per-card HBM (90 % usable, the rest for activations),
    # and the decode batch shrinks until the KV shard fits too.
    m_perf = _perf.LLM_PERF[model_key]
    group_hbm_bytes = spec["hbm_gb"] * 1e9 * 0.90 * max(1, gpu_count)
    kv_budget_bytes = group_hbm_bytes - m_perf.weight_bytes(job["precision"])
    if kv_budget_bytes <= 0:
        return None  # weights don't fit the whole group -> MFU fallback
    if phase == "decode":
        kv_row = context * m_perf.kv_bytes_per_tok(job["precision"])
        batch = max(1, min(batch, int(kv_budget_bytes // max(1.0, kv_row))))

    op = _perf.solve_operating_point(
        gpu_id, model_key, job["precision"], phase,
        p_cap_w=p_cap_w, t_struct_c=t_struct_c, batch=batch, context=context)
    if op is None:
        return None

    # Back out achieved TFLOPS / MFU from the model-level throughput so the
    # familiar columns stay comparable with the MFU-path jobs.
    k = 6.0 if phase == "train" else 2.0
    params = model["params"] if model else _perf.LLM_PERF[model_key].n_params
    tflops = k * params * op.tokens_s / 1e12
    peak_tflops = (spec["fp8_tflops"] if job["precision"] == "FP8"
                   else spec["bf16_tflops"])
    mfu = tflops / peak_tflops if peak_tflops > 0 else 0.0

    return GpuJobDetail(
        job=job_key,
        job_label=job["label"],
        model=model["label"] if model else _perf.LLM_PERF[model_key].name,
        precision=job["precision"],
        mfu=round(mfu, 3),
        gpu_count=gpu_count,
        power_w_per_gpu=round(op.draw_w, 1),
        heat_w_per_gpu=round(op.draw_w, 1),
        tflops_per_gpu=round(tflops, 1),
        throughput_per_gpu=round(op.tokens_s, 1),
        throughput_total=round(op.tokens_s * gpu_count, 1),
        throughput_unit="tok/s",
        engine="analytic",
        exec_phase=phase,
        batch=batch if phase == "decode" else 0,
        context=context,
        power_cap_w=round(p_cap_w, 1),
        freq_frac=round(op.freq_frac, 3),
        gpu_die_temp_c=round(op.die_temp_c, 1),
        thermal_throttled=op.throttled,
        thermal_runaway=op.thermal_runaway,
        t_mem_ms=round(op.t_mem_ms, 2),
        t_comp_ms=round(op.t_comp_ms, 2),
    )
