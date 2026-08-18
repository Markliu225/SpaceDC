"""Two-body, J2, and configurable high-precision numerical propagators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

import numpy as np
from scipy.integrate import solve_ivp

from ..constants import MU_EARTH
from ..gravity import GravityFieldCoefficients, SphericalHarmonicGravity, load_builtin_egm2008
from ..time import ensure_utc_sequence, seconds_since, time_grid
from ..types import ClassicalElements, Ephemeris, OrbitState
from .elements import oe_to_rv, rv_to_oe
from .forces import (
    BodyEphemerisCache,
    ExponentialAtmosphericDrag,
    ForceModel,
    J2Gravity,
    PointMassGravity,
    SchwarzschildCorrection,
    SolarRadiationPressureForce,
    ThirdBodyGravity,
)


def _require_gcrs(initial_state: OrbitState) -> None:
    if initial_state.frame != "GCRS":
        raise ValueError("numerical propagation requires an initial state in the GCRS frame")


def _solve_kepler(mean_anomaly: np.ndarray, eccentricity: float) -> np.ndarray:
    anomaly = np.asarray(mean_anomaly, dtype=float)
    eccentric_anomaly = anomaly.copy()
    if eccentricity > 0.8:
        eccentric_anomaly.fill(np.pi)
        eccentric_anomaly += np.floor(anomaly / (2.0 * np.pi)) * 2.0 * np.pi
    for _ in range(30):
        correction = (
            eccentric_anomaly - eccentricity * np.sin(eccentric_anomaly) - anomaly
        ) / (1.0 - eccentricity * np.cos(eccentric_anomaly))
        eccentric_anomaly -= correction
        if np.max(np.abs(correction)) < 1e-13:
            return eccentric_anomaly
    raise RuntimeError("Kepler equation failed to converge")


class TwoBodyPropagator:
    """Exact elliptic Kepler propagation using the initial osculating state."""

    def __init__(self, mu_m3_s2: float = MU_EARTH) -> None:
        self.mu_m3_s2 = float(mu_m3_s2)

    def propagate(self, initial_state: OrbitState, times: Iterable[datetime]) -> Ephemeris:
        _require_gcrs(initial_state)
        requested_times = ensure_utc_sequence(times)
        offsets = seconds_since(requested_times, initial_state.epoch)
        initial_elements = rv_to_oe(
            initial_state.position_m,
            initial_state.velocity_m_s,
            epoch=initial_state.epoch,
            mu_m3_s2=self.mu_m3_s2,
        )
        e = initial_elements.eccentricity
        nu0 = initial_elements.anomaly_rad
        eccentric0 = 2.0 * np.arctan2(
            np.sqrt(1.0 - e) * np.sin(nu0 / 2.0),
            np.sqrt(1.0 + e) * np.cos(nu0 / 2.0),
        )
        mean0 = eccentric0 - e * np.sin(eccentric0)
        mean_motion = np.sqrt(self.mu_m3_s2 / initial_elements.semi_major_axis_m**3)
        eccentric = _solve_kepler(mean0 + mean_motion * offsets, e)
        true = 2.0 * np.arctan2(
            np.sqrt(1.0 + e) * np.sin(eccentric / 2.0),
            np.sqrt(1.0 - e) * np.cos(eccentric / 2.0),
        )
        positions = np.empty((len(requested_times), 3))
        velocities = np.empty_like(positions)
        for index, anomaly in enumerate(true):
            elements = ClassicalElements(
                initial_elements.semi_major_axis_m,
                e,
                initial_elements.inclination_rad,
                initial_elements.raan_rad,
                initial_elements.argument_of_periapsis_rad,
                float(anomaly),
            )
            positions[index], velocities[index] = oe_to_rv(elements, self.mu_m3_s2)
        return Ephemeris(requested_times, positions, velocities, "GCRS")

    def propagate_grid(
        self, initial_state: OrbitState, stop: datetime, step_s: float, start: datetime | None = None
    ) -> Ephemeris:
        return self.propagate(
            initial_state, time_grid(start or initial_state.epoch, stop, step_s)
        )


@dataclass
class NumericalPropagator:
    force_models: Sequence[ForceModel]
    relative_tolerance: float = 1e-11
    position_tolerance_m: float = 1e-3
    velocity_tolerance_m_s: float = 1e-6
    max_step_s: float = 300.0

    def propagate(self, initial_state: OrbitState, times: Iterable[datetime]) -> Ephemeris:
        _require_gcrs(initial_state)
        requested_times = ensure_utc_sequence(times)
        offsets = seconds_since(requested_times, initial_state.epoch)
        if np.any(offsets < 0.0):
            raise ValueError("numerical propagation currently requires times at or after the epoch")
        if np.any(np.diff(offsets) <= 0.0):
            raise ValueError("numerical propagation times must be strictly increasing")

        def dynamics(elapsed_s: float, state: np.ndarray) -> np.ndarray:
            acceleration = np.zeros(3)
            for model in self.force_models:
                acceleration += model.acceleration(elapsed_s, state, initial_state.epoch)
            return np.concatenate((state[3:], acceleration))

        if offsets[-1] == 0.0:
            return Ephemeris(
                requested_times,
                initial_state.position_m[None, :],
                initial_state.velocity_m_s[None, :],
                "GCRS",
            )
        for model in self.force_models:
            prepare = getattr(model, "prepare", None)
            if prepare is not None:
                prepare(initial_state.epoch, float(offsets[-1]))
        solution = solve_ivp(
            dynamics,
            (0.0, float(offsets[-1])),
            initial_state.vector,
            method="DOP853",
            t_eval=offsets,
            rtol=self.relative_tolerance,
            atol=np.array([self.position_tolerance_m] * 3 + [self.velocity_tolerance_m_s] * 3),
            max_step=self.max_step_s,
        )
        if not solution.success:
            raise RuntimeError(f"orbit integration failed: {solution.message}")
        return Ephemeris(requested_times, solution.y[:3].T, solution.y[3:].T, "GCRS")

    def propagate_grid(
        self, initial_state: OrbitState, stop: datetime, step_s: float, start: datetime | None = None
    ) -> Ephemeris:
        return self.propagate(
            initial_state, time_grid(start or initial_state.epoch, stop, step_s)
        )


class J2Propagator(NumericalPropagator):
    def __init__(
        self,
        *,
        relative_tolerance: float = 1e-11,
        position_tolerance_m: float = 1e-3,
        velocity_tolerance_m_s: float = 1e-6,
        max_step_s: float = 300.0,
    ) -> None:
        super().__init__(
            [PointMassGravity(), J2Gravity()],
            relative_tolerance,
            position_tolerance_m,
            velocity_tolerance_m_s,
            max_step_s,
        )


class HighPrecisionPropagator(NumericalPropagator):
    """Engineering HPOP with an explicit, auditable force-model stack.

    The baseline uses the bundled EGM2008 field through degree/order 70, plus
    Sun/Moon third bodies and the Schwarzschild correction.  Drag and SRP are
    enabled when a positive area-to-mass ratio is supplied.  Set
    ``gravity_degree=None`` for the legacy point-mass-plus-J2 stack, or supply
    mission-specific ICGEM coefficients with ``gravity_coefficients``.
    """

    def __init__(
        self,
        *,
        area_to_mass_m2_kg: float = 0.0,
        drag_coefficient: float = 2.2,
        reflectivity_coefficient: float = 1.3,
        gravity_degree: int | None = 70,
        gravity_order: int | None = None,
        gravity_coefficients: GravityFieldCoefficients | None = None,
        include_third_body: bool = True,
        include_relativity: bool = True,
        extra_forces: Sequence[ForceModel] = (),
        relative_tolerance: float = 1e-11,
        position_tolerance_m: float = 1e-3,
        velocity_tolerance_m_s: float = 1e-6,
        max_step_s: float = 120.0,
    ) -> None:
        if area_to_mass_m2_kg < 0.0:
            raise ValueError("area_to_mass_m2_kg must be non-negative")
        models: list[ForceModel] = []
        if gravity_degree is None:
            models.extend((PointMassGravity(), J2Gravity()))
        else:
            coefficients = gravity_coefficients or load_builtin_egm2008(gravity_degree)
            models.extend(
                (
                    PointMassGravity(coefficients.mu_m3_s2),
                    SphericalHarmonicGravity(
                        coefficients,
                        max_degree=gravity_degree,
                        max_order=gravity_order,
                    ),
                )
            )
        body_ephemeris = BodyEphemerisCache()
        if include_third_body:
            models.extend(
                (
                    ThirdBodyGravity("sun", body_ephemeris),
                    ThirdBodyGravity("moon", body_ephemeris),
                )
            )
        if area_to_mass_m2_kg > 0.0:
            models.extend(
                (
                    ExponentialAtmosphericDrag(area_to_mass_m2_kg, drag_coefficient),
                    SolarRadiationPressureForce(
                        area_to_mass_m2_kg, reflectivity_coefficient, body_ephemeris
                    ),
                )
            )
        if include_relativity:
            models.append(SchwarzschildCorrection())
        models.extend(extra_forces)
        super().__init__(
            models,
            relative_tolerance,
            position_tolerance_m,
            velocity_tolerance_m_s,
            max_step_s,
        )
