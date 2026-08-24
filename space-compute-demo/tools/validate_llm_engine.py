"""Closed-loop scenario validation of the analytical LLM engine INSIDE the
simulator (llm_perf -> ai_workloads -> state_engine).

validate_llm_perf.py proves the theory library against the measurement
study; THIS script proves the integration: drive the real engine tick with
an LLM-serving schedule and check the coupled story end to end —

  Scenario A (healthy design): OSR radiators sized for the load. The
    analytic operating point runs unthrottled, payload power equals the
    model's realized draw (decode pulls its NATURAL draw, below the EPS
    cap), die temp = T_struct + P*R_th, no thermal alarms.

  Scenario B (sabotaged radiator): bare-aluminum stub radiators (eps 0.10,
    ~1/20 the emitting power). Structure heats, the thermal power limit
    (T_throttle - T_struct)/R_th falls into the operating range, throttling
    engages: die pins at the throttle target, per-card draw AND tokens/s
    fall while the job keeps running -- the negative feedback the model
    predicts, now visible through the satellite thermal loop.

  Scenario C: workload adaptation reports analytic (natural-draw) energy
    and token forecasts for LLM profiles.

Run:  backend/.venv/Scripts/python tools/validate_llm_engine.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import llm_perf as lp  # noqa: E402
from state_engine import StateEngine  # noqa: E402

FAILS = 0


def check_true(label: str, ok: bool) -> None:
    global FAILS
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS += 1


def make_engine() -> StateEngine:
    eng = StateEngine(on_state=lambda s: None)
    eng._running = True
    # Big battery so eclipse power-save never swaps the job out from under
    # the thermal story (we are validating the GPU loop, not the EPS).
    eng._sat.battery_soc = 1.0
    eng._sat.battery_capacity_wh = 5e6
    eng.set_config({"gpu": "H100"}, mark_custom=False)
    eng.set_workload_profile("inference", mark_custom=False)
    return eng


def run(eng: StateEngine, seconds: int, trace_every: int = 0) -> list[dict]:
    """Advance the real physics tick 1 s at a time; return per-tick samples."""
    out = []
    for i in range(seconds):
        t_pre = eng._sat.temperature_c   # the T_struct this tick's solve sees
        eng._sim_time_s += 1.0
        eng._update_placeholder_physics(1.0)
        d = eng._sat.workload_detail
        row = {
            "t": eng._sim_time_s,
            "T_pre": t_pre,
            "job": d.job if d else "-",
            "engine": d.engine if d else "-",
            "draw": d.power_w_per_gpu if d else 0.0,
            "cap": d.power_cap_w if d else 0.0,
            "tok": d.throughput_per_gpu if d else 0.0,
            "x": d.freq_frac if d else 0.0,
            "die": d.gpu_die_temp_c if d else 0.0,
            "throttled": bool(d and d.thermal_throttled),
            "runaway": bool(d and d.thermal_runaway),
            "T_struct": eng._sat.temperature_c,
            "payload_w": eng._sat.payload_power_w,
            "alarms": list(eng._sat.alarms),
        }
        out.append(row)
        if trace_every and i % trace_every == 0:
            print(f"    t={row['t']:5.0f}s {row['job']:<16} T_struct={row['T_struct']:5.1f}C "
                  f"die={row['die']:5.1f}C draw={row['draw']:6.1f}W x={row['x']:.2f} "
                  f"tok/s={row['tok']:7.1f} thr={row['throttled']}")
    return out


print("== Scenario A: healthy design (OSR radiators) — no throttle ==")
eng = make_engine()
eng.set_config({"radiator_material": "OSR"}, mark_custom=False)
eng.set_twin_geometry({"radiator_long": 5.0, "radiator_ratio": 2.5}, mark_custom=False)
hist_a = run(eng, 720, trace_every=120)
llm = [r for r in hist_a if r["job"] in ("llm_batch", "llm_interactive", "llm_eval")]
batch = [r for r in llm if r["job"] == "llm_batch"]
check_true(f"LLM blocks run the analytic engine ({len(llm)} ticks)",
           len(llm) > 400 and all(r["engine"] == "analytic" for r in llm))
check_true("decode realized draw < EPS cap (natural draw) on every llm_batch tick",
           all(r["draw"] < r["cap"] - 1.0 for r in batch))
check_true("payload power = draw x gpu_count (physics uses the model's draw)",
           all(abs(r["payload_w"] - r["draw"] * eng._gpu_count) < 1.0 for r in llm))
g = lp.GPU_PERF["H100"]
check_true("die temp = T_struct + draw*R_th on every LLM tick (max err < 0.2 K)",
           max(abs(r["die"] - (r["T_pre"] + r["draw"] * g.r_th_k_per_w))
               for r in llm) < 0.2)
steady = [r for r in batch if r["t"] > 300]
check_true("healthy: never throttled, die below target",
           not any(r["throttled"] or r["runaway"] for r in llm)
           and all(r["die"] < g.t_throttle_c - 1.0 for r in llm))
check_true("healthy: no GPU thermal alarms",
           not any(a.startswith("gpu_thermal") for r in hist_a for a in r["alarms"]))
tok_healthy = sum(r["tok"] for r in steady) / max(1, len(steady))
plateau = lp.decode_plateau_tokens_s(g, lp.LLM_PERF["llama70b"], "FP8", 48, 2048)
check_true(f"healthy llm_batch tok/s near model plateau "
           f"({tok_healthy:.0f} vs plateau {plateau:.0f})",
           0.85 * plateau <= tok_healthy <= 1.001 * plateau)

print("== Scenario B: bare-aluminum radiators (eps 0.10) — throttle feedback loop ==")
# Same panel area as A but emissivity sabotaged 0.92 -> 0.10: the structure
# heats until the thermal power limit cuts the GPU draw, which sheds heat
# input — the loop must SETTLE in deep throttle, below thermal runaway.
eng2 = make_engine()
eng2.set_config({"radiator_material": "Aluminum"}, mark_custom=False)
eng2.set_twin_geometry({"radiator_long": 5.0, "radiator_ratio": 2.5}, mark_custom=False)
hist_b = run(eng2, 1400, trace_every=200)
llm_b = [r for r in hist_b if r["job"] in ("llm_batch", "llm_interactive", "llm_eval")]
throttled = [r for r in llm_b if r["throttled"]]
check_true(f"structure heats up (max T_struct {max(r['T_struct'] for r in hist_b):.1f}C)",
           max(r["T_struct"] for r in hist_b) > 55.0)
check_true(f"thermal throttling engages ({len(throttled)} throttled LLM ticks)",
           len(throttled) > 50)
check_true("throttled: die pinned at the throttle target (within 0.2 K)",
           all(abs(r["die"] - g.t_throttle_c) < 0.2 for r in throttled))
nat_draw = lp.decode_natural_draw_w(
    g, lp.decode_t_mem_s(g, lp.LLM_PERF["llama70b"], "FP8", 48, 2048),
    lp.decode_c_comp_s(g, lp.LLM_PERF["llama70b"], "FP8", 48))
check_true(f"throttled: per-card draw = thermal limit, below natural {nat_draw:.0f} W",
           len(throttled) > 0
           and all(r["draw"] < nat_draw for r in throttled)
           and all(abs(r["draw"] - lp.thermal_power_limit_w(g, r["T_pre"])) < 1.0
                   for r in throttled))
thr_batch = [r for r in throttled if r["job"] == "llm_batch"]
tok_thr = (sum(r["tok"] for r in thr_batch) / len(thr_batch)) if thr_batch else 0.0
check_true(f"throttled llm_batch tok/s falls vs healthy ({tok_thr:.0f} < {tok_healthy:.0f})",
           0.0 < tok_thr < tok_healthy * 0.97)
check_true("gpu_thermal alarm raised while throttled",
           all(any(a.startswith("gpu_thermal") for a in r["alarms"]) for r in throttled))
# Negative feedback under the orbital environment: throttling sheds
# electrical load, and the eclipse phase sheds the solar/albedo input, so
# the loop cycles as a bounded limit cycle — sunlit stress (deep throttle /
# runaway episodes on bare aluminum, whose alpha/eps=2.5 cannot reject even
# the environment at 95 C) followed by eclipse recovery — instead of
# diverging onto the 95 C clamp permanently.
tail = hist_b[-600:]
t_min = min(r["T_struct"] for r in tail)
railed = sum(1 for r in tail if r["T_struct"] >= 94.5) / len(tail)
stressed = sum(1 for r in tail if r["throttled"] or r["runaway"])
check_true(f"feedback + eclipse cycling keeps the loop bounded (tail min "
           f"{t_min:.1f}C recovers below 85C, railed {railed:.0%} < 70%, "
           f"{stressed} stressed ticks)",
           t_min < 85.0 and railed < 0.70 and stressed > 0)

print("== Scenario B2: stub radiators — thermal runaway flagged ==")
eng3 = make_engine()
eng3.set_config({"radiator_material": "Aluminum"}, mark_custom=False)
eng3.set_twin_geometry({"radiator_long": 1.2, "radiator_ratio": 5.0}, mark_custom=False)
hist_c = run(eng3, 900)
run_ticks = [r for r in hist_c if r["runaway"]]
check_true(f"thermal runaway reached and flagged ({len(run_ticks)} ticks)",
           len(run_ticks) > 100)
check_true("runaway: die never below the throttle target, well above at steady state",
           all(r["die"] >= g.t_throttle_c - 0.1 for r in run_ticks)
           and all(r["die"] > g.t_throttle_c + 1.0 for r in run_ticks[-100:]))
check_true("runaway: clocks parked at the idle floor (draw ~ P_static)",
           all(r["draw"] <= g.p_static_w * 1.02 + 0.5 for r in run_ticks))
check_true("gpu_thermal_runaway alarm raised",
           all("gpu_thermal_runaway" in r["alarms"] for r in run_ticks))

print("== Scenario D: TP-group HBM feasibility clamps the decode batch ==")
import ai_workloads as ai  # noqa: E402

# 8×H100 group: 8×80 GB×0.9 = 576 GB >> 70 GB weights + 15.7 GB KV — the
# catalog batch (48) survives untouched.
d8 = ai.job_detail("H100", "llm_batch", 0.80, 581.0, 8, t_struct_c=25.0)
check_true(f"8xH100 group: catalog batch kept (B={d8.batch})", d8.batch == 48)
# A single H100 cannot hold 70 GB FP8 weights + 48 rows of ctx-2048 KV in
# 72 GB usable: the batch must shrink to what fits (~6 rows), and the
# operating point must still solve (plateau scales with B).
d1 = ai.job_detail("H100", "llm_batch", 0.80, 581.0, 1, t_struct_c=25.0)
check_true(f"1xH100: batch clamped to fit HBM (B={d1.batch} < 48)",
           0 < d1.batch < 48)
kv_row = 2048 * lp.LLM_PERF["llama70b"].kv_bytes_per_tok("FP8")
fit_bytes = (80e9 * 0.9 * 1
             - lp.LLM_PERF["llama70b"].weight_bytes("FP8"))
check_true(f"1xH100: clamped batch exactly fills the KV budget "
           f"({d1.batch} == floor({fit_bytes / kv_row:.1f}))",
           d1.batch == int(fit_bytes // kv_row))
check_true(f"1xH100: throughput follows the smaller batch "
           f"({d1.throughput_per_gpu:.0f} < {d8.throughput_per_gpu:.0f} tok/s)",
           0 < d1.throughput_per_gpu < d8.throughput_per_gpu)

print("== Scenario E: live design check demand == adaptation demand ==")
ad_e = eng.workload_adaptation("inference")
eng._sim_time_s += 1.0
eng._update_placeholder_physics(1.0)
check_true(f"solar_demand_avg_w matches adaptation demand "
           f"({eng._sat.solar_demand_avg_w:.0f} vs {ad_e['demand_avg_w']}) ",
           abs(eng._sat.solar_demand_avg_w - ad_e["demand_avg_w"]) < 1.0)

print("== Scenario F: multi-model LLM serving profiles fly analytic per block ==")
# Every LLM block of each serving profile must resolve through the analytic
# engine, with a genuinely different model mix per profile (the serving
# catalog: 8B/24B/32B/70B/72B/405B). H200x8 hosts all of them (405B needs
# the 8-card TP group's 1 TB HBM pool).
_PROFILE_MODELS = {
    "chat_serving": {"Llama-3.3-70B", "Llama-3.1-8B"},
    "code_rag": {"Qwen2.5-Coder-32B", "Qwen2.5-72B", "Mistral-Small-24B"},
    "frontier": {"Llama-3.1-405B"},
}
for prof, want_models in _PROFILE_MODELS.items():
    engf = make_engine()
    engf.set_config({"gpu": "H200"}, mark_custom=False)
    engf.set_workload_profile(prof, mark_custom=False)
    seen = set()
    llm_ticks = 0
    ok_analytic = True
    for _ in range(370):                      # one full cycle + margin
        engf._sim_time_s += 1.0
        engf._update_placeholder_physics(1.0)
        d = engf._sat.workload_detail
        if d is not None and d.job.startswith("llm_"):
            llm_ticks += 1
            seen.add(d.model)
            if d.engine != "analytic":
                ok_analytic = False
    check_true(f"{prof}: every LLM block analytic ({llm_ticks} ticks)",
               ok_analytic and llm_ticks > 200)
    check_true(f"{prof}: model mix {sorted(seen)} covers {sorted(want_models)}",
               want_models <= seen)

# HBM infeasibility falls back gracefully: 405B weights (405 GB) cannot fit
# a 2-card H100 group (144 GB usable) — MFU fallback, no crash.
d_infeasible = ai.job_detail("H100", "llm_frontier_405b", 0.85, 610.0, 2,
                             t_struct_c=25.0)
check_true("405B on 2xH100: graceful MFU fallback (engine="
           f"{d_infeasible.engine})", d_infeasible.engine == "mfu")

print("== Scenario C: workload adaptation uses the analytic forecasts ==")
ad = eng.workload_adaptation("inference")
check_true(f"inference profile forecast tokens/cycle > 0 ({ad['outputs_per_cycle']['tokens']:,})",
           ad["outputs_per_cycle"]["tokens"] > 1e6)
# Natural-draw energy: a cycle of the inference profile must cost LESS than
# the TDP-curve estimate (decode never pulls its full cap).
IDLE = 0.15
tdp_kwh = 0.0
from state_engine import _WORKLOAD_PROFILES  # noqa: E402
for _, dur, util, _ in _WORKLOAD_PROFILES["inference"]["schedule"]:
    tdp_kwh += (700.0 * (IDLE + (1 - IDLE) * util) * eng._gpu_count
                + eng._platform_power_w) * dur / 3.6e6
check_true(f"analytic cycle energy below TDP-curve estimate "
           f"({ad['outputs_per_cycle']['payload_kwh']} < {tdp_kwh:.2f} kWh)",
           0 < ad["outputs_per_cycle"]["payload_kwh"] < tdp_kwh)

print()
if FAILS:
    print(f"{FAILS} ENGINE-SCENARIO CHECK(S) FAILED")
    sys.exit(1)
print("ALL LLM-ENGINE SCENARIO CHECKS PASS")
