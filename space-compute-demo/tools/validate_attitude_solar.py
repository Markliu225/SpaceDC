"""validate_attitude_solar.py — end-to-end check that attitude drives solar.

Against a RUNNING backend (default :8001; pass a port arg for an isolated
stack). For each attitude pointing mode it commands the mode, samples /state
over a chunk of orbit, and asserts the physical behavior:

  sun      -> incidence == 1 whenever sunlit (always full power in daylight)
  free     -> incidence == 0.95 whenever sunlit (SADA sun-tracking default)
  nadir    -> incidence == sun_factor (panels ride local vertical) and swings
  velocity -> incidence swings over the orbit (edge-on for part of it)
  inertial -> incidence quasi-constant while sunlit (orbit-normal panels)
  all      -> incidence == 0 in eclipse

Plus: sun-pointing collects strictly more mean daylight power than nadir, and
the battery material/size config changes the reported capacity. Run:
  backend/.venv/Scripts/python tools/validate_attitude_solar.py [PORT]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8001"
BASE = f"http://127.0.0.1:{PORT}"
_results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    _results.append((ok, msg))
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")


def req(path: str, payload=None):
    r = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(r, timeout=10) as f:
        return json.loads(f.read())


def sample_mode(mode: str, seconds: float, dt: float = 0.2):
    req("/attitude_mode", {"mode": mode})
    time.sleep(0.4)
    rows = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        s = req("/state")["satellite"]
        rows.append({
            "sunlit": s["sunlit"],
            "inc": s.get("solar_incidence", 0.0),
            "sun_factor": s.get("sun_factor", 0.0),
            "solar_w": s["solar_input_w"],
        })
        time.sleep(dt)
    return rows


def lit(rows):
    return [r for r in rows if r["sunlit"]]


def main() -> int:
    print(f"== validate_attitude_solar ({BASE}) ==")
    # Deterministic orbit with a real day/night cycle + a known design.
    req("/constellation/single_iss", {})
    req("/designs/baseline/apply", {})
    time.sleep(2.0)

    WIN = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

    means = {}
    for mode in ("free", "sun", "nadir", "velocity", "inertial"):
        rows = sample_mode(mode, WIN)
        L = lit(rows)
        eclipse = [r for r in rows if not r["sunlit"]]
        incs = [r["inc"] for r in L]
        means[mode] = sum(incs) / len(incs) if incs else 0.0
        # eclipse: incidence exactly 0 for every dark sample
        check(all(r["inc"] == 0.0 for r in eclipse) if eclipse else True,
              f"{mode}: incidence == 0 in eclipse ({len(eclipse)} dark samples)")
        if not L:
            print(f"  SKIP {mode}: window fell entirely in eclipse")
            continue
        lo, hi = min(incs), max(incs)
        if mode == "sun":
            check(all(abs(i - 1.0) < 1e-3 for i in incs),
                  f"sun: incidence == 1 for all {len(L)} sunlit samples (range {lo:.3f}..{hi:.3f})")
        elif mode == "free":
            check(all(abs(i - 0.95) < 1e-3 for i in incs),
                  f"free: incidence == 0.95 (SADA) for all sunlit samples (range {lo:.3f}..{hi:.3f})")
        elif mode == "nadir":
            worst = max(abs(r["inc"] - r["sun_factor"]) for r in L)
            check(worst < 0.02,
                  f"nadir: incidence == sun_factor within {worst:.4f} (local-vertical panels)")
            check((hi - lo) > 0.15 or hi < 0.85,
                  f"nadir: incidence varies with orbit (range {lo:.3f}..{hi:.3f})")
        elif mode == "velocity":
            check((hi - lo) > 0.1,
                  f"velocity: incidence swings over the orbit (range {lo:.3f}..{hi:.3f})")
        elif mode == "inertial":
            n = len(incs)
            mean = means[mode]
            var = sum((i - mean) ** 2 for i in incs) / n
            check(var ** 0.5 < 0.12,
                  f"inertial: incidence quasi-constant while sunlit (std {var**0.5:.3f}, mean {mean:.3f})")

    # Sun-pointing collects strictly more daylight power than nadir.
    if means.get("sun") and "nadir" in means:
        check(means["sun"] > means["nadir"] + 0.05,
              f"sun-pointing collects more than nadir (mean incidence {means['sun']:.3f} > {means['nadir']:.3f})")

    # Battery config: capacity = mass x density; efficiency taxes charging.
    req("/attitude_mode", {"mode": "free"})
    caps = {}
    for mat, size, want in [("LiIon", "L", 8000), ("LiS", "XL", 24000),
                            ("LiFePO4", "S", 1600), ("SolidState", "M", 7000)]:
        req("/satellite_config", {"battery_material": mat, "battery_size": size})
        time.sleep(1.2)
        cap = req("/state")["satellite"]["battery_capacity_wh"]
        caps[(mat, size)] = cap
        check(abs(cap - want) < 1.0,
              f"battery {mat}/{size} -> {cap:.0f} Wh (mass x density, want {want})")
    # restore
    req("/satellite_config", {"battery_material": "LiIon", "battery_size": "L"})
    req("/attitude_mode", {"mode": "free"})

    fails = [m for ok, m in _results if not ok]
    print()
    print(f"{len(fails)} FAILED" if fails else f"ALL {len(_results)} CHECKS PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
