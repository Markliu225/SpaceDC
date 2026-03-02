"""
============================================================
  battery_model.py — Battery SOC charge/discharge model
  Migrated from: js/simulation.js (batSOC logic)
============================================================
"""


def update_battery_soc(
    bat_soc: float,
    eclipse: bool,
    compute_load_kw: float,
    solar_pwr_kw: float,
    dt: float,
    speed: int,
) -> float:
    """
    Battery State-of-Charge update per simulation tick.

    Eclipse:
        SOC -= (computeLoad / 1400) × 0.85 × dt × speed / 60
    Sunlit (surplus solar):
        SOC += 1.25 × dt × speed / 60

    Clamped to [10, 100] %.
    """
    if eclipse:
        discharge = (compute_load_kw / 1400.0) * 0.85 * dt * speed / 60.0
        bat_soc = max(10.0, bat_soc - discharge)
    else:
        surplus = 1.0 if (solar_pwr_kw - compute_load_kw) > 0 else 0.0
        charge = surplus * 1.25 * dt * speed / 60.0
        bat_soc = min(100.0, bat_soc + charge)
    return bat_soc
