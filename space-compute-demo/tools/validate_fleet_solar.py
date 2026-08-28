"""validate_fleet_solar.py — the fleet aggregate and the tracked satellite
must run ONE solar array model.

Regression guard for the dawn-dusk power bug: FleetSnapshot.solar_total_w and
the solar histogram used to bin/scale by max(0, r_hat.s_hat) — a body-fixed
NADIR array — while the satellite card ran the attitude-aware model
(state_engine._panel_incidence). In a dawn-dusk SSO the Sun is perpendicular
to the orbit plane and r_hat lies IN it, so r_hat.s_hat ~ 0 for the entire
orbit: the fleet reported ~2% of peak on the orbit that is in PERMANENT
sunlight, right next to a satellite card reading full power.

Checks (all in-process — no running backend, no HTTP, no new dependencies):

  A1 1-sat fleet invariant on an eclipsing orbit (single_iss): solar_total_w
     == solar_input_w for every attitude mode, sampled across a full orbit
     including eclipse. Both sides share _array_scale_w (eta . area . S(r) .
     eta(T) . deployed fraction), so the equality is exact — not "within a
     factor", and not "modulo the temperature and deployment terms".
  A2 the same invariant on a 1-sat DAWN-DUSK SSO (permanent sunlight), plus
     the per-mode physics that orbit implies: sun/free/inertial collect,
     body-fixed nadir/ram collect ~nothing (which is precisely the array the
     old aggregate was silently modelling for everyone).
  B  velocity/inertial really consume the plumbed-through sgp4 velocities:
     the fleet harvest reproduces an INDEPENDENT recomputation from
     propagate_fleet_rv, and differs from the nadir number.
  C  a 24-sat dawn-dusk SSO above its critical beta: 0 eclipsed and the fleet
     at full array power — while the OLD formula, recomputed here, still
     reads near zero (the reported bug, reproduced and quantified).
  D  solar histogram: it bins the SAME per-sat collection factor (eclipse
     fraction x panel incidence) and the same array chain, so its bars sum
     back to solar_total_w and an eclipsed sat sits in bin 0 - checked both
     on the never-eclipsed SSO and on an eclipsing Walker fleet.

Run:  backend/.venv/Scripts/python tools/validate_fleet_solar.py
"""
from __future__ import annotations

import math
import pathlib
import sys
import time

try:                                    # console may be cp1252 on Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001 — output only
    pass

_BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND))

import state_engine as se                      # noqa: E402
from services import constellations as consts  # noqa: E402
from services import geodyn, timebase          # noqa: E402

_results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    _results.append((bool(ok), msg))
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")


def new_engine() -> se.StateEngine:
    eng = se.StateEngine(on_state=lambda _p: None)
    # The snapshot read path (_refresh_display_kinematics) is where the fleet
    # harvest is re-scaled onto the live array chain; it is gated on a running
    # engine with a tick anchor, exactly as in the server.
    eng._running = True
    return eng


def step(eng: se.StateEngine, dt: float = 1.0):
    """One physics tick, then a /state read — the same order the server uses.
    The anchor is set immediately before the read so the read's fractional
    time is ~0 and the tracked sat's geometry is the tick's geometry."""
    eng._sim_time_s += dt
    eng._update_placeholder_physics(dt)
    eng._last_tick_wall = time.monotonic()
    return eng.snapshot()


# ---------------------------------------------------------------------------
# A. one satellite, one number
# ---------------------------------------------------------------------------
def one_sat_run(label: str, preset_id: str, mode: str, samples: int) -> dict:
    eng = new_engine()
    assert eng.set_constellation(preset_id), preset_id
    assert consts.get_preset(preset_id).total_sats == 1, "needs a 1-sat fleet"
    eng.set_attitude_mode(mode)
    worst = worst_at = peak = total = 0.0
    penumbra = lit = dark = 0
    for _ in range(samples):
        p = step(eng)
        sat, fleet = p.satellite, p.constellation
        peak = max(peak, sat.solar_input_w, fleet.solar_total_w)
        total += sat.solar_input_w
        illum = sat.solar_illum
        if 0.0 < illum < 0.5:
            # Penumbra: the tracked sat hard-gates on "majority of the solar
            # disc visible" (sunlit -> incidence 0) while the fleet scales
            # continuously by the visible fraction. Bounded by construction at
            # half a satellite's peak; counted here, not asserted equal.
            penumbra += 1
            continue
        lit += illum >= 0.5
        dark += illum <= 0.0
        d = abs(fleet.solar_total_w - sat.solar_input_w)
        if d > worst:
            worst, worst_at = d, sat.solar_input_w
    # Tolerance: the 0.1 W rounding on solar_total_w, plus the sub-tick
    # (~1 ms wall = 60 ms sim) geometry drift between the tick's fleet pass
    # and the read-path refresh, which only bites the three geometric modes.
    tol = 0.1 + (0.0 if mode in ("sun", "free") else 1e-3 * max(1.0, peak))
    check(worst <= tol,
          f"{label}/{mode}: max |fleet - sat| = {worst:.4f} W (tol "
          f"{tol:.2f} W) over {lit} sunlit + {dark} eclipsed samples "
          f"[{penumbra} penumbra skipped, peak {peak:.0f} W, worst sample "
          f"at {worst_at:.0f} W]")
    return {"peak": peak, "mean": total / max(1, samples),
            "lit": lit, "dark": dark, "worst": worst}


def check_single_sat_invariant() -> None:
    print("\n-- A1. 1-sat eclipsing fleet (single_iss) --")
    for mode in ("free", "sun", "nadir", "velocity", "inertial"):
        r = one_sat_run("iss", "single_iss", mode, 150)
        check(r["lit"] > 0 and r["dark"] > 0,
              f"iss/{mode}: window covered daylight ({r['lit']}) AND "
              f"eclipse ({r['dark']})")

    print("\n-- A2. 1-sat dawn-dusk SSO (permanent sunlight) --")
    sso = consts.make_sso_preset(600.0, 600.0, 1, 1, 0, consts.LTAN_DUSK_H)
    beta = consts.sso_shell_plan(600.0, 600.0, 1, 1,
                                 consts.LTAN_DUSK_H)[0]["beta_deg"]
    cos_beta = abs(math.cos(math.radians(beta)))
    scale = 0.0
    peak = {}
    mean = {}
    for mode in ("free", "sun", "nadir", "velocity", "inertial"):
        r = one_sat_run("sso", consts.CUSTOM_ID, mode, 60)
        peak[mode], mean[mode] = r["peak"], r["mean"]
        scale = max(scale, r["peak"])
        check(r["dark"] == 0,
              f"sso/{mode}: never eclipsed ({r['lit']} sunlit samples)")
    # Physics of a terminator orbit (beta = {beta:.1f} deg here): the Sun is
    # nearly normal to the orbit plane, so a sun-tracking (or orbit-normal)
    # array is at its best, while an array bolted to the local vertical or the
    # ram vector is near edge-on all orbit long — its projection peaks at
    # cos(beta) and averages ~cos(beta)/pi. The old aggregate applied that
    # nadir case to EVERY design, which is the bug.
    check(peak["sun"] > 0.9 * scale,
          f"sso/sun collects {peak['sun']:.0f} W — the best case "
          f"(orbit beta {beta:.1f} deg)")
    check(peak["free"] > 0.9 * se._POINTING_EFF * scale,
          f"sso/free (SADA) collects {peak['free']:.0f} W")
    check(peak["inertial"] > 0.5 * scale,
          f"sso/inertial (orbit-normal panels) collects "
          f"{peak['inertial']:.0f} W — the Sun is on the orbit normal")
    check(peak["nadir"] < 1.15 * cos_beta * scale
          and peak["velocity"] < 1.15 * cos_beta * scale,
          f"sso/nadir peaks at {peak['nadir']:.0f} W and sso/velocity at "
          f"{peak['velocity']:.0f} W — both capped by cos(beta)="
          f"{cos_beta:.3f} of the {scale:.0f} W array")
    check(mean["nadir"] < 0.2 * mean["sun"]
          and mean["velocity"] < 0.25 * mean["sun"],
          f"orbit-averaged, sso/nadir {mean['nadir']:.0f} W and sso/velocity "
          f"{mean['velocity']:.0f} W are ~cos(beta)/pi of sso/sun "
          f"{mean['sun']:.0f} W — the near-zero the old fleet formula "
          f"reported for the whole constellation")
    assert sso.total_sats == 1


# ---------------------------------------------------------------------------
# B. the velocity plumbing is real
# ---------------------------------------------------------------------------
def _independent_factors(preset, t: float, mode: str) -> list[float]:
    """Per-sat (illum x incidence) recomputed from scratch — deliberately NOT
    calling _panel_incidence, so a wrong normal or a dropped velocity shows up
    as a mismatch."""
    sun_km, _r = geodyn.sun_teme(timebase.jd_utc_at(t))
    sn = math.sqrt(sum(c * c for c in sun_km)) or 1.0
    s = tuple(c / sn for c in sun_km)
    out: list[float] = []
    for (p, v) in consts.propagate_fleet_rv(preset, t):
        if p == (0.0, 0.0, 0.0):
            out.append(0.0)
            continue
        illum = geodyn.sun_visible_fraction(p, sun_km)
        if mode == "sun":
            inc = 1.0
        elif mode == "free":
            inc = se._POINTING_EFF
        else:
            if mode == "nadir":
                n = p
            elif mode == "velocity":
                n = v
            else:                                # inertial: r x v
                n = (p[1] * v[2] - p[2] * v[1],
                     p[2] * v[0] - p[0] * v[2],
                     p[0] * v[1] - p[1] * v[0])
            ln = math.sqrt(sum(c * c for c in n)) or 1.0
            inc = max(0.0, sum(a * b for a, b in zip(n, s)) / ln)
        out.append(illum * inc)
    return out


def _independent_geom(preset, t: float, mode: str) -> float:
    """The fleet harvest sum: the per-sat factors of sats that are not in full
    umbra (the engine skips illum <= 0, which contribute 0 anyway)."""
    return sum(_independent_factors(preset, t, mode))


def check_velocity_plumbing() -> None:
    print("\n-- B. velocity / inertial fleet modes use the real sgp4 v --")
    preset = consts.make_sso_preset(500.0, 700.0, 3, 8, 1, consts.LTAN_DUSK_H)
    geoms = {}
    for mode in ("nadir", "velocity", "inertial"):
        eng = new_engine()
        assert eng.set_constellation(consts.CUSTOM_ID)
        eng.set_attitude_mode(mode)
        for _ in range(3):
            step(eng)
        want = _independent_geom(preset, eng._sim_time_s, mode)
        got = eng._fleet_solar_geom
        geoms[mode] = got
        check(abs(got - want) < 1e-6 * max(1.0, want),
              f"{mode}: fleet sum(illum x incidence) = {got:.6f} matches an "
              f"independent recomputation {want:.6f}")
    check(abs(geoms["velocity"] - geoms["nadir"]) > 1e-3,
          f"velocity ({geoms['velocity']:.3f}) is not the nadir number "
          f"({geoms['nadir']:.3f}) — v_hat really reached the fleet loop")
    check(abs(geoms["inertial"] - geoms["nadir"]) > 1e-3,
          f"inertial ({geoms['inertial']:.3f}) is not the nadir number "
          f"({geoms['nadir']:.3f}) — r_hat x v_hat really reached the loop")


# ---------------------------------------------------------------------------
# C + D. the reported bug, and the histogram that showed it
# ---------------------------------------------------------------------------
def check_dawn_dusk() -> None:
    print("\n-- C. 24-sat dawn-dusk SSO above beta_crit: full sun, full power --")
    preset = consts.make_sso_preset(500.0, 700.0, 3, 8, 1, consts.LTAN_DUSK_H)
    eng = new_engine()
    assert eng.set_constellation(consts.CUSTOM_ID)
    eng.set_attitude_mode("free")            # SADA sun-tracking, the default
    eng.set_ground_target(True, "Singapore", 1.3521, 103.8198)
    p = None
    for _ in range(3):
        p = step(eng)
    fleet, sat = p.constellation, p.satellite
    n = preset.total_sats
    check(fleet.eclipse == 0, f"eclipse = 0 / {n} (beta > beta_crit)")
    check(fleet.solar_lit_sats == n, f"solar_lit_sats = {n} / {n}")

    # The tracked satellite is SHELL 0. Under the |sin beta| array model each
    # SSO shell has its own inclination and therefore its own beta, so the fleet
    # MEAN is legitimately a hair under shell 0's value -- for a 500-700 km
    # stack, sin|beta| runs 0.9460 / 0.9438 / 0.9415, a mean 0.24 % below the
    # top. Asserting exact equality here would only hold under the old constant
    # -incidence model, i.e. it would re-assert the very bug this file guards.
    per_sat = fleet.solar_total_w / n
    check(per_sat <= sat.solar_input_w + 0.5,
          f"per-sat fleet mean {per_sat:.1f} W does not exceed the shell-0 "
          f"tracked satellite {sat.solar_input_w:.1f} W")
    check(abs(per_sat - sat.solar_input_w) < 0.01 * sat.solar_input_w,
          f"per-sat fleet mean {per_sat:.1f} W is within 1 % of shell 0's "
          f"{sat.solar_input_w:.1f} W (the residual is the per-shell beta "
          f"spread: {100 * (1 - per_sat / sat.solar_input_w):.2f} %)")
    sada_peak = se._POINTING_EFF * eng._array_scale_w()
    check(per_sat > 0.99 * sada_peak,
          f"per-sat power {per_sat:.1f} W is AT the SADA-tracking peak "
          f"({sada_peak:.1f} W), not near zero")

    # The bug, reproduced: what the old aggregate would have reported.
    old = _independent_geom(preset, eng._sim_time_s, "nadir") * eng._array_scale_w()
    check(old < 0.15 * fleet.solar_total_w,
          f"the old r_hat.s_hat formula reads {old:.0f} W vs the physics "
          f"{fleet.solar_total_w:.0f} W — "
          f"{fleet.solar_total_w / max(old, 1e-9):.0f}x understated, which is "
          f"the reported bug")

    print("\n-- D. solar histogram is the same physics --")
    gt = p.ground_target
    ok = gt is not None and gt.enabled
    check(ok, "ground target enabled (histogram live)")
    if ok:
        # The histogram is scaled once per tick, the aggregate is re-scaled on
        # every read, so the two can differ by one tick of thermal drift in
        # eta(T) — ~1% during the startup transient, well under 0.1% once the
        # structure temperature settles. Everything else about them is now the
        # same computation.
        tot = sum(b.collection_w for b in gt.solar_hist)
        d = abs(tot - fleet.solar_total_w)
        check(d <= 0.02 * fleet.solar_total_w,
              f"sum(histogram collection_w) {tot:.1f} W == solar_total_w "
              f"{fleet.solar_total_w:.1f} W within one tick of eta(T) drift "
              f"({100 * d / max(1.0, fleet.solar_total_w):.2f}%, no sat in "
              f"shadow)")
        top = sum(b.sat_count for b in gt.solar_hist if b.lo >= 90)
        check(top == n,
              f"all {n} sats land in the top intensity bin, not the bottom "
              f"one (occupied bins: "
              f"{[(b.lo, b.sat_count) for b in gt.solar_hist if b.sat_count]})")

    print("\n-- E. eclipsing fleet: the histogram still sums to the aggregate --")
    consts.make_custom_preset(altitude_km=550.0, eccentricity=0.001,
                              inclination_deg=53.0, raan_deg=0.0,
                              arg_perigee_deg=0.0, mean_anomaly_deg=0.0,
                              planes=6, sats_per_plane=8, phasing=1)
    walker = consts.get_preset(consts.CUSTOM_ID)
    eng = new_engine()
    assert eng.set_constellation(consts.CUSTOM_ID)
    eng.set_attitude_mode("free")
    eng.set_ground_target(True, "Singapore", 1.3521, 103.8198, 10.0, "X", 5)
    q = None
    for _ in range(3):
        q = step(eng)
    fl, g = q.constellation, q.ground_target
    check(fl.eclipse > 0,
          f"{fl.eclipse} of {fl.total} sats are really in shadow "
          f"(i=53 deg, 550 km — a normally eclipsing fleet)")
    tot = sum(b.collection_w for b in g.solar_hist)
    d = abs(tot - fl.solar_total_w)
    check(d <= 0.02 * fl.solar_total_w,
          f"sum(histogram collection_w) {tot:.1f} W == solar_total_w "
          f"{fl.solar_total_w:.1f} W with sats in shadow "
          f"({100 * d / max(1.0, fl.solar_total_w):.2f}%)")
    factors = _independent_factors(walker, eng._sim_time_s, "free")
    want0 = sum(1 for f in factors if f * 100.0 < g.solar_bin)
    got0 = next(b.sat_count for b in g.solar_hist if b.lo == 0)
    check(got0 == want0 and want0 > 0,
          f"{got0} eclipsed sats land in bin 0 (independent count {want0}) "
          f"instead of being credited with daylight power")


def main() -> int:
    print("== validate_fleet_solar (in-process) ==")
    check_single_sat_invariant()
    check_velocity_plumbing()
    check_dawn_dusk()
    fails = [m for ok, m in _results if not ok]
    print()
    print(f"{len(fails)} FAILED of {len(_results)}" if fails
          else f"ALL {len(_results)} CHECKS PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
