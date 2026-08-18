from __future__ import annotations

import unittest
import warnings
from datetime import datetime, timezone

import numpy as np

from ntu_space_dynamics import (
    ClassicalElements,
    OrbitState,
    ecef_to_eci,
    eclipse_fraction,
    eci_to_ecef,
    oe_to_rv,
    sun_beta_angle,
    sun_intensity,
    sun_position_analytical,
    sun_position_ephemeris,
    sun_radiation_pressure,
)
from ntu_space_dynamics.constants import ASTRONOMICAL_UNIT, SOLAR_CONSTANT


class CoordinateTests(unittest.TestCase):
    def test_gcrs_itrs_round_trip_includes_velocity(self) -> None:
        epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
        elements = ClassicalElements.from_degrees(7_000_000.0, 0.01, 50.0, 20.0, 10.0, 0.0)
        position, velocity = oe_to_rv(elements)
        source = OrbitState(epoch, position, velocity)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            recovered = ecef_to_eci(eci_to_ecef(source))
        np.testing.assert_allclose(recovered.position_m, source.position_m, atol=1e-5)
        np.testing.assert_allclose(recovered.velocity_m_s, source.velocity_m_s, atol=1e-8)


class SolarTests(unittest.TestCase):
    def test_analytical_and_builtin_ephemeris_directions_agree(self) -> None:
        epoch = datetime(2024, 4, 6, tzinfo=timezone.utc)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            analytical = sun_position_analytical(epoch)
            ephemeris = sun_position_ephemeris(epoch)
        angle = np.arccos(
            np.clip(
                np.dot(analytical, ephemeris)
                / (np.linalg.norm(analytical) * np.linalg.norm(ephemeris)),
                -1.0,
                1.0,
            )
        )
        self.assertLess(np.rad2deg(angle), 0.05)

    def test_eclipse_and_sunward_cases(self) -> None:
        sun = np.array([ASTRONOMICAL_UNIT, 0.0, 0.0])
        self.assertEqual(eclipse_fraction([-7_000_000.0, 0.0, 0.0], sun), 0.0)
        self.assertEqual(eclipse_fraction([7_000_000.0, 0.0, 0.0], sun), 1.0)
        self.assertAlmostEqual(
            sun_intensity([0.0, 0.0, 0.0], sun, include_eclipse=False),
            SOLAR_CONSTANT,
        )

    def test_beta_angle_sign_and_srp_direction(self) -> None:
        beta = sun_beta_angle([7e6, 0, 0], [0, 7.5e3, 0], [0, 0, 1.5e11])
        self.assertAlmostEqual(beta, np.pi / 2.0)
        acceleration = sun_radiation_pressure(
            [7e6, 0, 0],
            [ASTRONOMICAL_UNIT, 0, 0],
            area_to_mass_m2_kg=0.01,
            include_eclipse=False,
        )
        self.assertLess(acceleration[0], 0.0)
        self.assertAlmostEqual(acceleration[1], 0.0)


if __name__ == "__main__":
    unittest.main()

