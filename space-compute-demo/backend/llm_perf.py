"""Analytical LLM-inference performance / power / thermal models.

THEORY (condensed from the measurement study MODEL_AND_RESULTS.zh.md — a
V100 power-cap sweep across 10 workloads × 5 models; every derived number
below is cross-checked against that study in tools/validate_llm_perf.py):

Per-token latency is the SUM of a memory term and a compute term,
    time/token = T_mem + T_comp = D_mem/BW(f_mem) + O_comp/OPS(f_sm).
The DVFS/power-cap knob moves ONLY the SM frequency; the memory controller
frequency is pinned (V100 877 MHz fixed; Hopper likewise), hence

    BW(f_mem) = const  =>  T_mem = const        (the "memory floor")

and the entire phase distinction is the size of that floor.

POWER SIDE.  SM frequency maps to power through the DVFS aggregate
    P(x) = P_static + chi * x^theta,   x = f_sm/f_max in (0,1], theta in [2,4]
inverted (with the clamp x<=1 once the cap exceeds P(f_max)) as
    x(P) = ((P - P_static)/chi)^(1/theta).

PREFILL (compute-bound, weights reused across B*S positions, I >> I*):
    T_mem ~ 0  =>  tok/s(P) = T_fmax * x(P)^p          -- single power-law
    T_fmax = eff_prefill * OPS_peak / (k * N_params)   -- k=2 fwd, 6 training
    energy optimum at P* = P_static/(1-a), a = p/theta (interior peak).

DECODE (memory-bound, every step re-reads all weights + B rows of KV):
    tok/s(P) = B / ( T_mem + C_comp * (x(P)^-p - 1) )
    T_mem  = (W_bytes + B*C_eff*kv_bytes) / BW_eff
    C_comp = k*N*B / (eff_decode * OPS_peak)           -- compute at f_max
Three phases: (I) pseudo-compute-bound ~ (P-P_static)^(p/theta) (approx
linear); (II) marginal-utility collapse; (III) bandwidth plateau B/T_mem,
throughput independent of P.  Phase boundaries (from T_comp = T_mem and
T_comp = 0.05*T_mem):
    x1 = (C/(T_mem+C))^(1/p),   x2 = (C/(0.05*T_mem+C))^(1/p).
The ceiling law  T_max = B*BW_eff/(W + B*C_eff*kv)  held over ~140x
(6.4..900 tok/s) in the study.

NATURAL DRAW.  A power cap is an upper bound, not a demand.  Compute-bound
phases pull the full DVFS top P_static+chi; memory-bound decode stalls the
SMs and the measured draw flattens near the II/III boundary.  We model
    P_nat_decode = P_static + chi * (0.70 + 0.30 * duty),
    duty = C_comp/(T_mem + C_comp)  at f_max,
anchored to the V100 measurement (duty 0.17 -> P_nat ~ 168 W vs measured
~171 W at the II/III knee).

THERMAL THROTTLING (the space twist).  The GPU die couples to the satellite
structure through a conduction stack:
    T_die = T_struct + P_gpu * R_th          (quasi-static; die tau << tick)
The driver holds T_die <= T_throttle by shrinking the effective power
budget — EXACTLY the power-cap knob this whole model is built on:
    P_thermal_limit = (T_throttle - T_struct)/R_th
    P_effective     = min(P_cap, P_thermal_limit)     (floored at P_static)
so an undersized radiator (hot structure) shows up as a *computable*
throughput loss through the same tok/s(P) curves.  If the limit falls
below P_static the package cannot even idle within budget: thermal runaway
flag (the survival action — park the job — is the engine's call).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GpuPerfSpec:
    name: str
    tdp_w: float
    f_max_mhz: float
    ops_fp16_tflops: float        # dense tensor peak
    ops_fp8_tflops: float
    bw_peak_tbps: float
    # DVFS power aggregate P(x) = p_static + chi * x^theta
    p_static_w: float
    chi_w: float
    theta: float
    # throughput-frequency effective exponents (OPS ~ f^p)
    p_prefill: float
    p_decode: float
    # achievable fractions (model x hardware x engine properties)
    eff_prefill: float            # MFU for compute-bound phases
    eff_decode: float             # fraction of dense peak in decode GEMV/GEMM
    bw_frac: float                # achieved / peak HBM bandwidth in decode
    # thermal stack
    r_th_k_per_w: float           # junction -> satellite structure
    t_throttle_c: float           # slowdown target (clock/power management)


# V100 entries are the measurement study's fitted values and exist for
# validation; the modern parts carry datasheet peaks + serving-stack
# fractions (documented assumptions, checked for sanity in the validator).
GPU_PERF: dict[str, GpuPerfSpec] = {
    "V100": GpuPerfSpec(
        name="V100-DGXS-32GB", tdp_w=250.0, f_max_mhz=1530.0,
        ops_fp16_tflops=125.0, ops_fp8_tflops=125.0,   # no fp8 on Volta
        bw_peak_tbps=0.90,
        p_static_w=50.0, chi_w=155.5, theta=2.15,   # decode-sweep power fit
        p_prefill=1.0,            # study table median p≈0.99 (direct DVFS: 0.90)
        p_decode=1.84,
        eff_prefill=0.48,         # calibrated: T(155 W)=6200 tok/s, Phi-3
        eff_decode=0.190,         # calibrated: C_comp = 30.8 ms @ B=96, Phi-3
        bw_frac=0.207,            # 186 GB/s effective (eager HF stack)
        r_th_k_per_w=0.12, t_throttle_c=83.0,
    ),
    "A100": GpuPerfSpec(
        name="A100 SXM4-80GB", tdp_w=400.0, f_max_mhz=1410.0,
        ops_fp16_tflops=312.0, ops_fp8_tflops=312.0,   # no fp8 on Ampere
        bw_peak_tbps=2.039,
        p_static_w=80.0, chi_w=320.0, theta=2.3,
        p_prefill=1.0, p_decode=2.5,
        eff_prefill=0.48, eff_decode=0.30, bw_frac=0.55,
        # 400 W package, larger junction-to-plate resistance than Hopper's
        # 700 W stack and smaller than Volta's 250 W one.
        r_th_k_per_w=0.085, t_throttle_c=85.0,
    ),
    "H200": GpuPerfSpec(
        name="H200 SXM", tdp_w=700.0, f_max_mhz=1980.0,
        ops_fp16_tflops=989.0, ops_fp8_tflops=1979.0, bw_peak_tbps=4.80,
        p_static_w=145.0, chi_w=555.0, theta=2.4,
        p_prefill=1.0, p_decode=2.6,
        eff_prefill=0.50, eff_decode=0.35, bw_frac=0.60,
        r_th_k_per_w=0.060, t_throttle_c=85.0,
    ),
    "B200": GpuPerfSpec(
        name="B200", tdp_w=1000.0, f_max_mhz=1965.0,
        ops_fp16_tflops=2250.0, ops_fp8_tflops=4500.0, bw_peak_tbps=8.00,
        p_static_w=200.0, chi_w=800.0, theta=2.4,
        p_prefill=1.0, p_decode=2.6,
        eff_prefill=0.50, eff_decode=0.35, bw_frac=0.60,
        r_th_k_per_w=0.045, t_throttle_c=85.0,
    ),
}


@dataclass(frozen=True)
class LlmPerfSpec:
    name: str
    n_params: float               # parameter count
    n_layers: int
    n_kv_heads: int
    head_dim: int

    def weight_bytes(self, precision: str) -> float:
        return self.n_params * (1.0 if precision == "FP8" else 2.0)

    def kv_bytes_per_tok(self, precision: str) -> float:
        b = 1.0 if precision == "FP8" else 2.0
        return 2.0 * self.n_layers * self.n_kv_heads * self.head_dim * b


LLM_PERF: dict[str, LlmPerfSpec] = {
    # Study models (validation)
    "phi3mini":  LlmPerfSpec("Phi-3-mini (MHA)",   3.8e9, 32, 32, 96),   # 384 KB/tok fp16
    "qwen15b":   LlmPerfSpec("Qwen2.5-1.5B (GQA)", 1.5e9, 28,  2, 128),
    "qwen3b":    LlmPerfSpec("Qwen2.5-3B (GQA)",   3.1e9, 36,  2, 128),
    # Simulator serving models — the orbital DC's business is LLM inference,
    # so the catalog spans the deployed dense-model range (all GQA; layer /
    # kv-head / head-dim figures from the public model cards).
    "llama70b":  LlmPerfSpec("Llama-3.3-70B (GQA)",  70e9, 80,  8, 128),  # 160 KB/tok fp8
    "llama8b":   LlmPerfSpec("Llama-3.1-8B (GQA)",    8e9, 32,  8, 128),
    "llama405b": LlmPerfSpec("Llama-3.1-405B (GQA)", 405e9, 126, 8, 128),  # 252 KB/tok fp8
    "qwen72b":   LlmPerfSpec("Qwen2.5-72B (GQA)",   72.7e9, 80,  8, 128),
    "qwen32b":   LlmPerfSpec("Qwen2.5-32B (GQA)",   32.8e9, 64,  8, 128),
    "mistral24b": LlmPerfSpec("Mistral-Small-24B (GQA)", 24e9, 40, 8, 128),
}


# ---------------------------------------------------------------------------
# DVFS power aggregate
# ---------------------------------------------------------------------------

def x_of_power(p_w: float, g: GpuPerfSpec) -> float:
    """Frequency fraction the DVFS governor reaches under power budget p_w,
    clamped to (0, 1]. Below P_static the package cannot run: returns 0."""
    if p_w <= g.p_static_w:
        return 0.0
    return min(1.0, ((p_w - g.p_static_w) / g.chi_w) ** (1.0 / g.theta))


def power_of_x(x: float, g: GpuPerfSpec) -> float:
    return g.p_static_w + g.chi_w * min(1.0, max(0.0, x)) ** g.theta


# ---------------------------------------------------------------------------
# Prefill / compute-bound phase
# ---------------------------------------------------------------------------

def prefill_tokens_s_fmax(g: GpuPerfSpec, m: LlmPerfSpec, precision: str,
                          flops_per_token_factor: float = 2.0) -> float:
    ops = (g.ops_fp8_tflops if precision == "FP8" else g.ops_fp16_tflops) * 1e12
    return g.eff_prefill * ops / (flops_per_token_factor * m.n_params)


def prefill_tokens_s(p_budget_w: float, g: GpuPerfSpec, m: LlmPerfSpec,
                     precision: str, flops_per_token_factor: float = 2.0) -> float:
    x = x_of_power(p_budget_w, g)
    return prefill_tokens_s_fmax(g, m, precision, flops_per_token_factor) * x ** g.p_prefill


def prefill_energy_opt_w(g: GpuPerfSpec) -> float:
    """Interior tokens-per-joule peak P* = P_static / (1 - p/theta)."""
    a = g.p_prefill / g.theta
    return g.p_static_w / (1.0 - a) if a < 1.0 else power_of_x(1.0, g)


# ---------------------------------------------------------------------------
# Decode / memory-bound phase
# ---------------------------------------------------------------------------

def decode_t_mem_s(g: GpuPerfSpec, m: LlmPerfSpec, precision: str,
                   batch: int, context: int) -> float:
    """The frequency-independent memory floor: every step re-reads all
    weights plus B rows of KV. C_eff adds the half-window average growth."""
    c_eff = context  # steady-state serving: window growth folded into `context`
    d_mem = m.weight_bytes(precision) + batch * c_eff * m.kv_bytes_per_tok(precision)
    return d_mem / (g.bw_frac * g.bw_peak_tbps * 1e12)


def decode_c_comp_s(g: GpuPerfSpec, m: LlmPerfSpec, precision: str,
                    batch: int) -> float:
    ops = (g.ops_fp8_tflops if precision == "FP8" else g.ops_fp16_tflops) * 1e12
    return 2.0 * m.n_params * batch / (g.eff_decode * ops)


def decode_tokens_s(p_budget_w: float, g: GpuPerfSpec, m: LlmPerfSpec,
                    precision: str, batch: int, context: int,
                    t_mem_s: Optional[float] = None,
                    c_comp_s: Optional[float] = None) -> float:
    """B / (T_mem + C*(x^-p - 1)) — the three-phase decode law."""
    x = x_of_power(p_budget_w, g)
    if x <= 0.0:
        return 0.0
    t_mem = decode_t_mem_s(g, m, precision, batch, context) if t_mem_s is None else t_mem_s
    c_comp = decode_c_comp_s(g, m, precision, batch) if c_comp_s is None else c_comp_s
    return batch / (t_mem + c_comp * (x ** (-g.p_decode) - 1.0))


def decode_plateau_tokens_s(g: GpuPerfSpec, m: LlmPerfSpec, precision: str,
                            batch: int, context: int) -> float:
    """Ceiling law T_max = B*BW_eff/(W + B*C_eff*kv)."""
    return batch / decode_t_mem_s(g, m, precision, batch, context)


def decode_phase_boundaries(g: GpuPerfSpec, t_mem_s: float, c_comp_s: float,
                            ) -> tuple[float, float, float, float]:
    """(x1, P1, x2, P2): pseudo-compute-bound / marginal-collapse / plateau
    boundaries at T_comp = T_mem and T_comp = 0.05*T_mem."""
    x1 = (c_comp_s / (t_mem_s + c_comp_s)) ** (1.0 / g.p_decode)
    x2 = (c_comp_s / (0.05 * t_mem_s + c_comp_s)) ** (1.0 / g.p_decode)
    return x1, power_of_x(x1, g), x2, power_of_x(x2, g)


def decode_natural_draw_w(g: GpuPerfSpec, t_mem_s: float, c_comp_s: float) -> float:
    """What a memory-bound decode actually pulls with an unlimited cap:
    SMs at f_max but stalled most of the time — draw flattens near the
    II/III knee (V100 anchor: duty 0.17 -> ~168 W vs ~171 W measured)."""
    duty = c_comp_s / (t_mem_s + c_comp_s)
    return g.p_static_w + g.chi_w * (0.70 + 0.30 * duty)


# ---------------------------------------------------------------------------
# Thermal throttling
# ---------------------------------------------------------------------------

@dataclass
class OperatingPoint:
    tokens_s: float               # aggregate for the batch (decode) / stream (prefill)
    draw_w: float                 # realized electrical power per GPU
    p_budget_w: float             # effective budget after cap + thermal limit
    freq_frac: float              # x = f_sm/f_max the governor settles at
    die_temp_c: float
    throttled: bool
    thermal_runaway: bool
    phase: str                    # 'decode' | 'prefill' | 'train'
    t_mem_ms: float
    t_comp_ms: float


def thermal_power_limit_w(g: GpuPerfSpec, t_struct_c: float) -> float:
    """Max sustained draw before the die crosses the throttle target."""
    return (g.t_throttle_c - t_struct_c) / g.r_th_k_per_w


def solve_operating_point(gpu_id: str, model_id: str, precision: str,
                          phase: str, p_cap_w: float, t_struct_c: float,
                          batch: int = 1, context: int = 2048,
                          flops_per_token_factor: float = 2.0,
                          ) -> Optional[OperatingPoint]:
    """The full coupled solve: power cap ∧ thermal limit → realized budget →
    frequency → throughput → realized draw → die temperature.

    The thermal limit acts on realized DRAW; since draw <= budget, capping
    the budget at the thermal limit is exact for compute-bound phases and
    conservative-by-<1 K for decode (whose natural draw is below budget).
    `throttled` is set only when the limit CUTS the draw the job would
    otherwise pull (cap ∧ natural draw) — a limit that sits between a
    decode's natural draw and its cap changes nothing and is not a
    throttle. Corollary: whenever throttled, draw == p_limit and the die
    sits exactly at the throttle target."""
    g = GPU_PERF.get(gpu_id)
    m = LLM_PERF.get(model_id)
    if g is None or m is None:
        return None

    p_limit = thermal_power_limit_w(g, t_struct_c)
    runaway = p_limit <= g.p_static_w * 1.02
    p_floor = g.p_static_w * 1.02
    p_budget = max(p_floor, min(p_cap_w, p_limit))
    if runaway:
        # Cannot hold the throttle target even at the idle floor — park the
        # clocks at the floor and report the real (over-target) die temp.
        p_budget = p_floor

    x = x_of_power(p_budget, g)

    if phase == "decode":
        t_mem = decode_t_mem_s(g, m, precision, batch, context)
        c_comp = decode_c_comp_s(g, m, precision, batch)
        tok_s = decode_tokens_s(p_budget, g, m, precision, batch, context,
                                t_mem_s=t_mem, c_comp_s=c_comp)
        p_natural = decode_natural_draw_w(g, t_mem, c_comp)
        draw = min(p_budget, p_natural)
        unthrottled_draw = min(p_cap_w, p_natural)
        t_comp = c_comp * (x ** (-g.p_decode) - 1.0) if x > 0 else float("inf")
    else:  # 'prefill' | 'train' — compute-bound
        k = 6.0 if phase == "train" else flops_per_token_factor
        tok_s = prefill_tokens_s(p_budget, g, m, precision, k)
        draw = p_budget                       # compute-bound pulls its budget
        unthrottled_draw = min(p_cap_w, power_of_x(1.0, g))
        t_mem, t_comp = 0.0, (1.0 / tok_s if tok_s > 0 else float("inf"))

    throttled = (p_limit < unthrottled_draw) and not runaway

    die = t_struct_c + draw * g.r_th_k_per_w
    return OperatingPoint(
        tokens_s=tok_s, draw_w=draw, p_budget_w=p_budget, freq_frac=x,
        die_temp_c=die, throttled=throttled, thermal_runaway=runaway,
        phase=phase, t_mem_ms=t_mem * 1e3,
        t_comp_ms=(t_comp * 1e3 if math.isfinite(t_comp) else -1.0),
    )
