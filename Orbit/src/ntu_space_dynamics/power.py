"""Solar-array electrical power coupled to a one-node thermal model."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike
from scipy.integrate import solve_ivp

from .constants import STEFAN_BOLTZMANN


@dataclass(frozen=True)
class SolarPanel:
    area_m2: float
    efficiency_reference: float
    temperature_reference_k: float = 298.15
    efficiency_temperature_coefficient_per_k: float = -0.004
    absorptivity: float = 0.9
    emissivity: float = 0.85
    radiating_area_m2: float | None = None
    heat_capacity_j_k: float = 5000.0
    space_temperature_k: float = 3.0

    def __post_init__(self) -> None:
        if self.area_m2 <= 0.0 or self.heat_capacity_j_k <= 0.0:
            raise ValueError("panel area and heat capacity must be positive")
        if not 0.0 <= self.efficiency_reference <= 1.0:
            raise ValueError("efficiency_reference must lie in [0,1]")
        if not 0.0 <= self.absorptivity <= 1.0 or not 0.0 <= self.emissivity <= 1.0:
            raise ValueError("absorptivity and emissivity must lie in [0,1]")
        if self.radiating_area_m2 is not None and self.radiating_area_m2 <= 0.0:
            raise ValueError("radiating_area_m2 must be positive")

    @property
    def thermal_area_m2(self) -> float:
        return self.radiating_area_m2 or self.area_m2

    def efficiency(self, temperature_k: ArrayLike) -> np.ndarray:
        temperature = np.asarray(temperature_k, dtype=float)
        value = self.efficiency_reference * (
            1.0
            + self.efficiency_temperature_coefficient_per_k
            * (temperature - self.temperature_reference_k)
        )
        return np.clip(value, 0.0, 1.0)


@dataclass(frozen=True)
class ThermalPowerResult:
    times_s: np.ndarray
    temperature_k: np.ndarray
    electrical_power_w: np.ndarray
    incident_power_w: np.ndarray


def power_considering_thermal(
    times_s: ArrayLike,
    irradiance_w_m2: ArrayLike,
    incidence_cosine: ArrayLike,
    panel: SolarPanel,
    *,
    initial_temperature_k: float = 298.15,
) -> ThermalPowerResult:
    """Simulate panel temperature and temperature-dependent electrical power.

    ``incidence_cosine`` is clipped to [0,1], so the rear side does not generate
    electrical power.  Irradiance should already include any eclipse fraction.
    """

    times = np.asarray(times_s, dtype=float)
    irradiance = np.asarray(irradiance_w_m2, dtype=float)
    cosine = np.clip(np.asarray(incidence_cosine, dtype=float), 0.0, 1.0)
    if times.ndim != 1 or len(times) == 0 or np.any(np.diff(times) <= 0.0):
        raise ValueError("times_s must be a non-empty strictly increasing array")
    if irradiance.shape != times.shape or cosine.shape != times.shape:
        raise ValueError("irradiance and incidence_cosine must match times_s")
    if np.any(irradiance < 0.0) or initial_temperature_k <= 0.0:
        raise ValueError("irradiance must be non-negative and temperature positive")
    origin = times[0]
    integration_times = times - origin

    def environment(time_s: float) -> tuple[float, float]:
        return (
            float(np.interp(time_s, integration_times, irradiance)),
            float(np.interp(time_s, integration_times, cosine)),
        )

    def thermal_derivative(time_s: float, temperature: np.ndarray) -> np.ndarray:
        flux, incidence = environment(time_s)
        incident = panel.area_m2 * flux * incidence
        electrical = float(panel.efficiency(temperature[0])) * incident
        absorbed_heat = panel.absorptivity * incident - electrical
        radiated = (
            panel.emissivity
            * STEFAN_BOLTZMANN
            * panel.thermal_area_m2
            * (temperature[0] ** 4 - panel.space_temperature_k**4)
        )
        return np.array([(absorbed_heat - radiated) / panel.heat_capacity_j_k])

    if integration_times[-1] == 0.0:
        temperatures = np.array([initial_temperature_k])
    else:
        solution = solve_ivp(
            thermal_derivative,
            (0.0, float(integration_times[-1])),
            [initial_temperature_k],
            method="DOP853",
            t_eval=integration_times,
            rtol=1e-9,
            atol=1e-8,
            max_step=max(1.0, min(60.0, float(integration_times[-1]) / 10.0)),
        )
        if not solution.success:
            raise RuntimeError(f"thermal integration failed: {solution.message}")
        temperatures = solution.y[0]
    incident_power = panel.area_m2 * irradiance * cosine
    electrical_power = panel.efficiency(temperatures) * incident_power
    return ThermalPowerResult(times, temperatures, electrical_power, incident_power)

