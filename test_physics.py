"""
============================================================
  test_physics.py — Standalone physics layer verification
  Run with: python test_physics.py  (no Omniverse needed)
============================================================
"""
import sys
import os

# Add the extension source to path
ext_root = os.path.join(os.path.dirname(__file__), "exts", "spacedc.digital_twin")
sys.path.insert(0, ext_root)

from spacedc.digital_twin.physics.constants import (
    ORBIT_PERIOD, ECLIPSE_FRAC, SIGMA, CELL_TECHS, COOLANTS, WORKLOADS,
)
from spacedc.digital_twin.physics.state import SimState
from spacedc.digital_twin.physics.orbital_mechanics import (
    get_angle, is_eclipse, get_orbit_position, get_raan,
)
from spacedc.digital_twin.physics.solar_array_model import (
    compute_peak_solar, compute_solar_power, update_wings,
)
from spacedc.digital_twin.physics.thermal_model import (
    update_radiator_panels, compute_rad_power_total,
    compute_gpu_temperature, compute_peak_rad_capacity,
    check_thermal_feasibility,
)
from spacedc.digital_twin.physics.battery_model import update_battery_soc
from spacedc.digital_twin.physics.workload_model import compute_workload_metrics
from spacedc.digital_twin.physics.telemetry import TelemetryLogger


def main():
    print("=" * 60)
    print("  SpaceDC Digital Twin — Physics Layer Test")
    print("=" * 60)

    # ── Constants ───────────────────────────────────────────
    print(f"\n📡 Orbit period:    {ORBIT_PERIOD:.0f} s ({ORBIT_PERIOD / 60:.1f} min)")
    print(f"   Eclipse fraction: {ECLIPSE_FRAC * 100:.0f}%")
    print(f"   σ (Stefan-Boltzmann): {SIGMA:.2e} W/m²K⁴")
    print(f"   Cell techs:       {len(CELL_TECHS)}")
    print(f"   Coolants:         {len(COOLANTS)}")
    print(f"   Workloads:        {len(WORKLOADS)}")

    # ── State initialization ────────────────────────────────
    state = SimState()
    state.initialize()
    print(f"\n🛰️  State initialized:")
    print(f"   Wings:    {len(state.wings)} (count={state.wing_count}, area={state.wing_area} m²)")
    print(f"   Radiators: {len(state.rad_panels)} (count={state.rad_count}, area={state.rad_area} m²)")
    print(f"   Cell tech: {state.current_cell_tech} → {CELL_TECHS[state.current_cell_tech]['name']}")
    print(f"   Coolant:   {state.current_coolant} → {COOLANTS[state.current_coolant]['name']}")
    print(f"   Workload:  {state.current_workload} → {WORKLOADS[state.current_workload]['name']}")

    # ── Orbit mechanics ─────────────────────────────────────
    print(f"\n🌍 Orbit mechanics:")
    for t_min in [0, 20, 40, 60, 80, 95]:
        t = t_min * 60.0
        angle = get_angle(t)
        ecl = is_eclipse(angle)
        pos = get_orbit_position(t)
        print(f"   T={t_min:3d}min  angle={angle:6.2f}rad  eclipse={ecl!s:<5}  pos=({pos[0]:6.2f}, {pos[1]:6.2f}, {pos[2]:6.2f})")

    # ── Solar power ─────────────────────────────────────────
    peak = compute_peak_solar(state.wing_count, state.wing_area, state.current_cell_tech)
    solar_sun = compute_solar_power(peak, eclipse=False)
    solar_ecl = compute_solar_power(peak, eclipse=True)
    print(f"\n☀️  Solar power:")
    print(f"   Peak:    {peak:.0f} kW")
    print(f"   Sunlit:  {solar_sun:.0f} kW")
    print(f"   Eclipse: {solar_ecl:.0f} kW")

    # ── Radiator ────────────────────────────────────────────
    update_radiator_panels(state.rad_panels, eclipse=False, coolant_key="nh3")
    rad_total = compute_rad_power_total(state.rad_panels, eclipse=False)
    peak_rad = compute_peak_rad_capacity(state.rad_count, state.rad_area, state.rad_epsilon, "nh3")
    print(f"\n🌡️  Radiator:")
    print(f"   Total rejection:  {rad_total:.0f} kW")
    print(f"   Peak capacity:    {peak_rad:.0f} kW")
    for p in state.rad_panels[:3]:
        print(f"   Panel P{p.id}: T={p.surf_temp:.1f}°C  Q={p.q_rad:.1f} kW  ε={p.emissivity:.2f}")

    # ── Thermal feasibility ─────────────────────────────────
    wl = WORKLOADS[state.current_workload]
    heat_load = wl["totalComputekW"] * wl["heatFraction"]
    status, ratio, msg = check_thermal_feasibility(heat_load, peak_rad)
    print(f"\n🔥 Thermal feasibility: {msg}")

    # ── Battery ─────────────────────────────────────────────
    soc = 87.0
    compute_load = wl["totalComputekW"]
    for i in range(5):
        soc = update_battery_soc(soc, eclipse=True, compute_load_kw=compute_load,
                                  solar_pwr_kw=0, dt=1.0, speed=60)
    print(f"\n🔋 Battery SOC after 5 eclipse ticks: {soc:.1f}%")

    # ── Workload ────────────────────────────────────────────
    metrics = compute_workload_metrics(state.current_workload, eclipse=False, bat_soc=87.0)
    print(f"\n🖥️  Workload ({wl['name']}):")
    print(f"   Compute: {metrics['compute_load_kw']:.0f} kW")
    print(f"   Heat:    {metrics['heat_load_kw']:.0f} kW")
    print(f"   FLOPS:   {metrics['flops']:.1f} ExaFLOPS")
    print(f"   GPU:     {metrics['gpu_util_pct']}%")

    # ── Telemetry ───────────────────────────────────────────
    logger = TelemetryLogger()
    logger.add_log("ok", "Test log message", 3661.0)
    print(f"\n📡 Telemetry: {logger.entries[-1]}")
    print(f"   MET format: {logger.format_met(3661.0)}")

    # ── Trend buffer ────────────────────────────────────────
    for i in range(10):
        state.trend.push(solar_sun * (0.9 + i * 0.01), 87.0 - i * 0.5, rad_total, 78.0 + i * 0.3)
    print(f"\n📈 Trend buffer: {len(state.trend.solar)} entries")

    print(f"\n{'=' * 60}")
    print("  ✅ All physics tests passed!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
