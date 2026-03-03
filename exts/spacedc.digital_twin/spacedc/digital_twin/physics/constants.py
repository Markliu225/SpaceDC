"""
============================================================
  constants.py — Orbital & physics constants, tech databases
  Migrated from: js/constants.js
============================================================
"""
import math

# ── Orbital parameters ──────────────────────────────────────
ORBIT_PERIOD: float = 95.7 * 60.0          # seconds per orbit
ECLIPSE_FRAC: float = 0.36                 # fraction of orbit in shadow
ECLIPSE_START: float = math.pi * (1.0 - ECLIPSE_FRAC)
SIGMA: float = 5.67e-8                     # Stefan-Boltzmann constant (W/m²K⁴)

ORBIT_ALTITUDE_KM: float = 550.0           # km above Earth surface
ORBIT_INCLINATION_DEG: float = 97.6        # SSO inclination
EARTH_RADIUS_KM: float = 6371.0
SOLAR_IRRADIANCE: float = 1367.0           # W/m² at 1 AU
TREND_MAX: int = 600                       # trend buffer length

# ── Solar cell technology database ──────────────────────────
CELL_TECHS: dict = {
    "tj": {
        "name":    "TJ InGaP/GaAs/Ge",
        "eff":     0.295,
        "bolEff":  "32.0%",
        "eolEff":  "28.8%",
        "voc":     "2.67V/cell",
        "tcoef":   0.002,
        "tcoefStr": "-0.20%/°C",
        "radTol":  "1e15 e/cm²",
    },
    "imm4j": {
        "name":    "4J IMM InGaP/GaAs/InGaAsP/InGaAs",
        "eff":     0.340,
        "bolEff":  "36.8%",
        "eolEff":  "33.2%",
        "voc":     "3.42V/cell",
        "tcoef":   0.0018,
        "tcoefStr": "-0.18%/°C",
        "radTol":  "8e14 e/cm²",
    },
    "perov": {
        "name":    "Perovskite/Si Tandem",
        "eff":     0.260,
        "bolEff":  "28.0%",
        "eolEff":  "22.5%",
        "voc":     "1.92V/cell",
        "tcoef":   0.0025,
        "tcoefStr": "-0.25%/°C",
        "radTol":  "5e13 e/cm²",
    },
    "si": {
        "name":    "Silicon PERC",
        "eff":     0.220,
        "bolEff":  "24.0%",
        "eolEff":  "21.2%",
        "voc":     "0.72V/cell",
        "tcoef":   0.003,
        "tcoefStr": "-0.30%/°C",
        "radTol":  "1e14 e/cm²",
    },
}

# ── Coolant / heat-pipe fluid database ──────────────────────
COOLANTS: dict = {
    "nh3": {
        "name": "NH₃ 2-phase",
        "flow": 4.2,            # kg/s
        "tIn":  85,             # °C
        "tOut": 45,             # °C
        "heatCapFactor": 1.0,
    },
    "propylene": {
        "name": "Propylene 1-phase",
        "flow": 5.8,
        "tIn":  80,
        "tOut": 50,
        "heatCapFactor": 0.72,
    },
    "r134a": {
        "name": "R-134a 2-phase",
        "flow": 6.1,
        "tIn":  78,
        "tOut": 48,
        "heatCapFactor": 0.85,
    },
}

# ── Workload database ───────────────────────────────────────
# Each workload defines GPU demand, per-GPU TDP, total compute load,
# peak ExaFLOPS, and heat output (fraction of compute power)
WORKLOADS: dict = {
    # --- Training workloads ---
    "llama70b_train": {
        "name":           "LLaMA-3 70B Training",
        "type":           "train",
        "model":          "70B",
        "desc":           "70B dense LLM · FP16/BF16 · data-parallel + tensor-parallel",
        "gpuCount":       5120,
        "gpuModel":       "H100 80GB",
        "perGpuTDP":      0.700,            # kW per GPU (TDP)
        "gpuUtil":        0.92,
        "totalComputekW": 5120 * 0.700 * 0.92,   # ~3,297 kW
        "heatFraction":   0.40,
        "peakFLOPS":      12.8,             # ExaFLOPS
        "batchInfo":      "4096 global batch · micro-bs 4",
    },
    "llama405b_train": {
        "name":           "LLaMA-3 405B Training",
        "type":           "train",
        "model":          "405B",
        "desc":           "405B dense LLM · FP16/BF16 · 4D-parallel (TP×PP×DP×CP)",
        "gpuCount":       5120,
        "gpuModel":       "H100 80GB",
        "perGpuTDP":      0.700,
        "gpuUtil":        0.88,
        "totalComputekW": 5120 * 0.700 * 0.88,
        "heatFraction":   0.42,
        "peakFLOPS":      11.2,
        "batchInfo":      "2048 global batch · 8-way PP",
    },
    "gpt4_train": {
        "name":           "GPT-4 1.8T MoE Training",
        "type":           "train",
        "model":          "1.8T MoE",
        "desc":           "1.8T Mixture-of-Experts · FP16 · expert-parallel",
        "gpuCount":       5120,
        "gpuModel":       "H100 80GB",
        "perGpuTDP":      0.700,
        "gpuUtil":        0.85,
        "totalComputekW": 5120 * 0.700 * 0.85,
        "heatFraction":   0.43,
        "peakFLOPS":      10.6,
        "batchInfo":      "1024 global batch · 16 experts",
    },
    # --- Inference workloads ---
    "llama70b_infer": {
        "name":           "LLaMA-3 70B Inference",
        "type":           "infer",
        "model":          "70B",
        "desc":           "70B dense LLM · INT8/FP8 · vLLM continuous batching",
        "gpuCount":       2560,
        "gpuModel":       "H100 80GB",
        "perGpuTDP":      0.700,
        "gpuUtil":        0.55,
        "totalComputekW": 2560 * 0.700 * 0.55,
        "heatFraction":   0.35,
        "peakFLOPS":      6.4,
        "batchInfo":      "128 concurrent reqs · KV-cache",
    },
    "llama405b_infer": {
        "name":           "LLaMA-3 405B Inference",
        "type":           "infer",
        "model":          "405B",
        "desc":           "405B dense LLM · INT8 · tensor-parallel across 8 GPUs",
        "gpuCount":       5120,
        "gpuModel":       "H100 80GB",
        "perGpuTDP":      0.700,
        "gpuUtil":        0.50,
        "totalComputekW": 5120 * 0.700 * 0.50,
        "heatFraction":   0.38,
        "peakFLOPS":      8.0,
        "batchInfo":      "64 concurrent reqs · 8-way TP",
    },
    "sd_xl_infer": {
        "name":           "Stable Diffusion XL Inference",
        "type":           "infer",
        "model":          "SDXL 6.6B",
        "desc":           "6.6B UNet + VAE · FP16 · batched image generation",
        "gpuCount":       1280,
        "gpuModel":       "H100 80GB",
        "perGpuTDP":      0.700,
        "gpuUtil":        0.70,
        "totalComputekW": 1280 * 0.700 * 0.70,
        "heatFraction":   0.33,
        "peakFLOPS":      3.2,
        "batchInfo":      "512 imgs/batch · 50 steps",
    },
}

def compute_orbit_period(altitude_km: float) -> float:
    """Kepler's 3rd law: T = 2π * sqrt(a³/μ)"""
    mu = 398600.4418  # Earth gravitational constant km³/s²
    r = 6371.0 + altitude_km
    return 2.0 * math.pi * math.sqrt(math.pow(r, 3) / mu)

def compute_eclipse_fraction(altitude_km: float) -> float:
    """Approximate eclipse fraction for circular orbit."""
    r_earth = 6371.0
    r_orbit = r_earth + altitude_km
    # θ = asin(Re/Ro)
    half_angle = math.asin(r_earth / r_orbit)
    return half_angle / math.pi
