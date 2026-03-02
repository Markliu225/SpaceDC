"""
============================================================
  workload_model.py — GPU compute workload model
  Migrated from: js/simulation.js (workload-driven compute block)
============================================================
"""
import random
from .constants import WORKLOADS


def compute_workload_metrics(
    workload_key: str,
    eclipse: bool,
    bat_soc: float,
) -> dict:
    """
    Compute instantaneous workload metrics.

    Returns dict with keys:
        compute_load_kw, heat_load_kw, flops, gpu_util_pct
    """
    wl = WORKLOADS[workload_key]

    compute_load = wl["totalComputekW"]
    heat_load = compute_load * wl["heatFraction"]

    if eclipse:
        flops = wl["peakFLOPS"] * (bat_soc / 100.0)
        gpu_pct = int(wl["gpuUtil"] * 100 * bat_soc / 100.0)
    else:
        flops = wl["peakFLOPS"] * (
            wl["gpuUtil"] + random.random() * (1.0 - wl["gpuUtil"]) * 0.3
        )
        gpu_pct = int(
            wl["gpuUtil"] * 100 * (0.87 + random.random() * 0.13)
        )

    return {
        "compute_load_kw": compute_load,
        "heat_load_kw":    heat_load,
        "flops":           flops,
        "gpu_util_pct":    gpu_pct,
    }
