"""Multi-round validation of backend/llm_perf.py against the V100
measurement study (MODEL_AND_RESULTS.zh.md) plus model-property and
thermal-throttle checks. Run: backend/.venv/Scripts/python tools/validate_llm_perf.py
Exits non-zero on any failure."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import llm_perf as lp  # noqa: E402

FAIL = 0


def check(name: str, got, want, tol_pct: float = 1.0) -> None:
    global FAIL
    ok = abs(got - want) <= abs(want) * tol_pct / 100.0
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got:.4g}, want {want:.4g} (±{tol_pct}%)")
    if not ok:
        FAIL += 1


def check_true(name: str, cond: bool) -> None:
    global FAIL
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        FAIL += 1


V = lp.GPU_PERF["V100"]
PHI3 = lp.LLM_PERF["phi3mini"]

print("== Round 1: V100 + Phi-3 decode calibration anchors (study §4.5) ==")
# The study's fitted latency-side values for the B=96 sweep:
T_MEM, C_COMP, B = 0.1493, 0.0308, 96
x1, p1, x2, p2 = lp.decode_phase_boundaries(V, T_MEM, C_COMP)
check("I/II boundary freq (MHz)", x1 * V.f_max_mhz, 585, 1.0)
check("I/II boundary power (W)", p1, 70, 1.5)
check("II/III boundary freq (MHz)", x2 * V.f_max_mhz, 1359, 1.0)
check("II/III boundary power (W)", p2, 171, 1.0)
check("bandwidth plateau (tok/s)", B / T_MEM, 643, 0.5)
check("phase-1 exponent p/theta", V.p_decode / V.theta, 0.855, 0.5)
# First-principles C_comp must reproduce the fitted 30.8 ms (eff_decode calib)
check("C_comp from first principles (ms)",
      lp.decode_c_comp_s(V, PHI3, "FP16", B) * 1e3, 30.8, 2.0)
# kv bytes/tok for Phi-3 MHA
check("Phi-3 kv bytes/tok (fp16)", PHI3.kv_bytes_per_tok("FP16"), 384e3, 3.0)
# Curve/boundary cross-consistency: at the I/II boundary T_comp = T_mem by
# construction, so the full curve must read plateau/2 there; at the II/III
# boundary T_comp = 0.05*T_mem, so plateau/1.05. These exercise the
# x_of_power/power_of_x round-trip + the boundary algebra against the
# throughput law (a wrong theta/p would break them; a check at x=1 would
# be an identity and validate nothing).
tok_p1 = lp.decode_tokens_s(p1, V, PHI3, "FP16", B, 2048,
                            t_mem_s=T_MEM, c_comp_s=C_COMP)
check("full curve at I/II boundary = plateau/2", tok_p1, B / T_MEM / 2.0, 0.5)
tok_p2 = lp.decode_tokens_s(p2, V, PHI3, "FP16", B, 2048,
                            t_mem_s=T_MEM, c_comp_s=C_COMP)
check("full curve at II/III boundary = plateau/1.05", tok_p2, B / T_MEM / 1.05, 0.5)
# Natural decode draw anchors near the II/III knee (~171 W measured)
check("natural decode draw (W)", lp.decode_natural_draw_w(V, T_MEM, C_COMP), 171, 4.0)

print("== Round 2: ceiling law blind anchors (study §5.2/§5.4 plateaus) ==")
# T_max = B*BW_eff/(W + B*C_eff*kv) with the study's per-model BW_eff —
# reproduced here from OUR spec fields (bw_frac*peak for V100 = 186 GB/s).
check("V100 effective BW (GB/s)", V.bw_frac * V.bw_peak_tbps * 1e3, 186, 1.0)
check("chat-phi3 plateau (tok/s, B=64 C=272)",
      lp.decode_plateau_tokens_s(V, PHI3, "FP16", 64, 272), 825, 4.0)
Q15, Q3 = lp.LLM_PERF["qwen15b"], lp.LLM_PERF["qwen3b"]
# study BW_eff differs per model (launch-bound small models): emulate via
# explicit t_mem with their calibrated bandwidths.
bw15, bw3 = 57e9, 65e9
tm = (Q15.weight_bytes("FP16") + 64 * 528 * Q15.kv_bytes_per_tok("FP16")) / bw15
check("fastchat-qwen1.5b plateau (tok/s)", 64 / tm, 900, 4.0)
tm = (Q3.weight_bytes("FP16") + 64 * 528 * Q3.kv_bytes_per_tok("FP16")) / bw3
check("translate-qwen3b plateau (tok/s)", 64 / tm, 559, 4.0)

print("== Round 3: prefill anchors + energy optima (study §3) ==")
# Prefill absolute rate: study energy peak 40 tok/J @ ~155 W => T(155)=6200 tok/s.
# The study's PREFILL power-side fits carried P_static≈80 W and a≈0.48
# (p≈1.04 at theta 2.15) — distinct from the decode-sweep fit in the
# catalog; reconstruct that fit explicitly.
import dataclasses
Vpf = dataclasses.replace(V, p_static_w=80.0, chi_w=125.5, p_prefill=1.04)
tok155 = lp.prefill_tokens_s(155.0, Vpf, PHI3, "FP16")
check("prefill tok/s at 155 W", tok155, 6200, 6.0)
check("prefill energy peak location P* (W)", lp.prefill_energy_opt_w(Vpf), 155, 8.0)
# energy peak is interior: numeric argmax of T/P on the curve
grid = [(p, lp.prefill_tokens_s(p, Vpf, PHI3, "FP16") / p) for p in range(85, 206)]
p_star_num = max(grid, key=lambda t: t[1])[0]
check("numeric energy argmax matches analytic", p_star_num, lp.prefill_energy_opt_w(Vpf), 5.0)
# prefill:decode energy ratio ~10x (study §0): tok/J at V100 tops
e_pf = lp.prefill_tokens_s(lp.power_of_x(1.0, Vpf), Vpf, PHI3, "FP16") / lp.power_of_x(1.0, Vpf)
e_dec = (B / T_MEM) / lp.decode_natural_draw_w(V, T_MEM, C_COMP)
check_true(f"prefill/decode energy ratio in [6,14] (got {e_pf/e_dec:.1f})",
           6.0 <= e_pf / e_dec <= 14.0)

print("== Round 4: model properties (monotonicity, asymptotes, phases) ==")
for gid in ("V100", "H100", "B200", "MI300X"):
    g = lp.GPU_PERF[gid]
    m = lp.LLM_PERF["llama70b" if gid != "V100" else "phi3mini"]
    prec = "FP8" if gid != "V100" else "FP16"
    caps = [g.p_static_w * 1.05 + i * (g.tdp_w - g.p_static_w) / 40 for i in range(41)]
    dec = [lp.decode_tokens_s(c, g, m, prec, 48, 2048) for c in caps]
    pf = [lp.prefill_tokens_s(c, g, m, prec) for c in caps]
    check_true(f"{gid}: decode monotone non-decreasing in P",
               all(b >= a - 1e-9 for a, b in zip(dec, dec[1:])))
    check_true(f"{gid}: prefill monotone non-decreasing in P",
               all(b >= a - 1e-9 for a, b in zip(pf, pf[1:])))
    plateau = lp.decode_plateau_tokens_s(g, m, prec, 48, 2048)
    check(f"{gid}: decode top-of-curve = plateau", dec[-1], plateau, 0.5)
    tm = lp.decode_t_mem_s(g, m, prec, 48, 2048)
    cc = lp.decode_c_comp_s(g, m, prec, 48)
    bx1, bp1, bx2, bp2 = lp.decode_phase_boundaries(g, tm, cc)
    check_true(f"{gid}: phase boundaries ordered (x1<x2<=1, P1<P2)",
               0 < bx1 < bx2 <= 1.0 and bp1 < bp2)
# batch scaling of the ceiling: sublinear once KV dominates, ~linear when
# weights dominate
g, m = lp.GPU_PERF["H100"], lp.LLM_PERF["llama70b"]
r_small = (lp.decode_plateau_tokens_s(g, m, "FP8", 16, 8192)
           / lp.decode_plateau_tokens_s(g, m, "FP8", 8, 8192))
r_weights = (lp.decode_plateau_tokens_s(g, m, "FP8", 8, 128)
             / lp.decode_plateau_tokens_s(g, m, "FP8", 4, 128))
check_true(f"ceiling: KV-dominated batch ratio < weights-dominated ({r_small:.2f} < {r_weights:.2f})",
           r_small < r_weights <= 2.0)

print("== Round 5: modern-GPU absolute sanity (serving-stack expectations) ==")
h100 = lp.solve_operating_point("H100", "llama70b", "FP8", "decode", 700, 30, 48, 2048)
check_true(f"H100 70B fp8 decode B=48 in [700,1500] tok/s (got {h100.tokens_s:.0f})",
           700 <= h100.tokens_s <= 1500)
pf100 = lp.solve_operating_point("H100", "llama70b", "FP8", "prefill", 700, 30)
check_true(f"H100 70B fp8 prefill in [5000,9000] tok/s (got {pf100.tokens_s:.0f})",
           5000 <= pf100.tokens_s <= 9000)
b200 = lp.solve_operating_point("B200", "llama70b", "FP8", "decode", 1000, 30, 48, 2048)
check_true(f"B200 decode > 1.8x H100 at same B (got {b200.tokens_s/h100.tokens_s:.2f}x)",
           b200.tokens_s / h100.tokens_s > 1.8)
check_true(f"decode natural draw < prefill draw ({h100.draw_w:.0f} < {pf100.draw_w:.0f} W)",
           h100.draw_w < pf100.draw_w)

print("== Round 6: thermal throttling unit checks ==")
g = lp.GPU_PERF["H100"]
cold = lp.solve_operating_point("H100", "llama70b", "FP8", "prefill", 700, 20)
check_true(f"cold structure (20C): no throttle, die {cold.die_temp_c:.0f}C < {g.t_throttle_c}C",
           not cold.throttled and cold.die_temp_c < g.t_throttle_c)
hot = lp.solve_operating_point("H100", "llama70b", "FP8", "prefill", 700, 60)
check_true(f"hot structure (60C): throttled, draw {hot.draw_w:.0f} W < 700 W cap",
           hot.throttled and hot.draw_w < 690)
check("throttled die temp pins at target", hot.die_temp_c, g.t_throttle_c, 0.5)
check("throttled draw = (T_thr - T_s)/R_th", hot.draw_w,
      (g.t_throttle_c - 60) / g.r_th_k_per_w, 0.5)
check_true(f"throttle costs throughput ({hot.tokens_s:.0f} < {cold.tokens_s:.0f} tok/s)",
           hot.tokens_s < cold.tokens_s * 0.8)
# monotone degradation with structure temperature
ts_sweep = [lp.solve_operating_point("H100", "llama70b", "FP8", "prefill", 700, t).tokens_s
            for t in range(20, 84, 4)]
check_true("throughput non-increasing as structure heats",
           all(b <= a + 1e-9 for a, b in zip(ts_sweep, ts_sweep[1:])))
runaway = lp.solve_operating_point("H100", "llama70b", "FP8", "prefill", 700, 82)
check_true(f"near-threshold structure (82C): runaway flagged, die {runaway.die_temp_c:.0f}C",
           runaway.thermal_runaway and runaway.die_temp_c > g.t_throttle_c)
# decode degrades LESS than prefill under the same thermal squeeze (its
# memory floor is frequency-immune; only the compute tail stretches)
d_cold = lp.solve_operating_point("H100", "llama70b", "FP8", "decode", 700, 20, 48, 2048)
d_warm = lp.solve_operating_point("H100", "llama70b", "FP8", "decode", 700, 58, 48, 2048)
pf_warm = lp.solve_operating_point("H100", "llama70b", "FP8", "prefill", 700, 58)
ret_dec = d_warm.tokens_s / d_cold.tokens_s
ret_pf = pf_warm.tokens_s / cold.tokens_s
check_true(f"decode retention under throttle > prefill retention "
           f"({ret_dec:.2f} > {ret_pf:.2f})", ret_dec > ret_pf)
# mild squeeze: decode barely moves (throttle above its natural knee zone)
d_mild = lp.solve_operating_point("H100", "llama70b", "FP8", "decode", 700, 50, 48, 2048)
check_true(f"mild squeeze (50C): decode keeps >=90% plateau "
           f"({d_mild.tokens_s:.0f}/{d_cold.tokens_s:.0f})",
           d_mild.tokens_s >= d_cold.tokens_s * 0.90)

print()
if FAIL:
    print(f"{FAIL} CHECK(S) FAILED")
    sys.exit(1)
print("ALL LLM-PERF VALIDATION ROUNDS PASS")
