from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

from ntu_space_dynamics import (
    ClassicalElements,
    HighPrecisionPropagator,
    J2Propagator,
    OrbitState,
    SGP4Propagator,
    TwoBodyPropagator,
    oe_to_rv,
    rv_to_oe,
)
from ntu_space_dynamics.constants import J2_EARTH, MU_EARTH, R_EARTH_EQUATOR


EPOCH = datetime(2020, 6, 27, 18, 50, 19, 734000, tzinfo=timezone.utc)


class ElementTests(unittest.TestCase):
    def test_nonsingular_round_trip(self) -> None:
        source = ClassicalElements.from_degrees(7_000_000.0, 0.01, 55.0, 40.0, 30.0, 20.0)
        position, velocity = oe_to_rv(source)
        result = rv_to_oe(position, velocity)
        self.assertAlmostEqual(result.semi_major_axis_m, source.semi_major_axis_m, places=6)
        self.assertAlmostEqual(result.eccentricity, source.eccentricity, places=13)
        np.testing.assert_allclose(result.angles_deg, source.angles_deg, atol=1e-10)

    def test_circular_equatorial_convention_round_trip(self) -> None:
        source = ClassicalElements.from_degrees(7_200_000.0, 0.0, 0.0, 0.0, 0.0, 123.0)
        position, velocity = oe_to_rv(source)
        result = rv_to_oe(position, velocity)
        self.assertAlmostEqual(result.raan_rad, 0.0)
        self.assertAlmostEqual(result.argument_of_periapsis_rad, 0.0)
        recovered_position, recovered_velocity = oe_to_rv(result)
        np.testing.assert_allclose(recovered_position, position, atol=1e-7)
        np.testing.assert_allclose(recovered_velocity, velocity, atol=1e-10)

    def test_retrograde_circular_equatorial_round_trip(self) -> None:
        source = ClassicalElements.from_degrees(7_200_000.0, 0.0, 180.0, 0.0, 0.0, 123.0)
        position, velocity = oe_to_rv(source)
        result = rv_to_oe(position, velocity)
        recovered_position, recovered_velocity = oe_to_rv(result)
        np.testing.assert_allclose(recovered_position, position, atol=1e-7)
        np.testing.assert_allclose(recovered_velocity, velocity, atol=1e-10)


class PropagatorTests(unittest.TestCase):
    def setUp(self) -> None:
        elements = ClassicalElements.from_degrees(
            7_000_000.0, 0.001, 45.0, 20.0, 10.0, 5.0, EPOCH
        )
        position, velocity = oe_to_rv(elements)
        self.state = OrbitState(EPOCH, position, velocity)

    def test_two_body_closes_after_one_period(self) -> None:
        period = 2.0 * np.pi * np.sqrt(7_000_000.0**3 / MU_EARTH)
        result = TwoBodyPropagator().propagate(
            self.state, (EPOCH, EPOCH + timedelta(seconds=float(period)))
        )
        self.assertLess(np.linalg.norm(result.positions_m[-1] - self.state.position_m), 0.01)
        self.assertLess(np.linalg.norm(result.velocities_m_s[-1] - self.state.velocity_m_s), 1e-5)

    def test_j2_conserves_energy_over_short_arc(self) -> None:
        result = J2Propagator(max_step_s=60.0).propagate_grid(
            self.state, EPOCH + timedelta(hours=3), 60.0
        )
        radius = np.linalg.norm(result.positions_m, axis=1)
        speed2 = np.sum(result.velocities_m_s**2, axis=1)
        sine_latitude = result.positions_m[:, 2] / radius
        p2 = 0.5 * (3.0 * sine_latitude**2 - 1.0)
        potential = -MU_EARTH / radius * (
            1.0 - J2_EARTH * (R_EARTH_EQUATOR / radius) ** 2 * p2
        )
        energy = 0.5 * speed2 + potential
        self.assertLess(np.ptp(energy) / abs(np.mean(energy)), 1e-10)

    def test_hpop_baseline_can_match_j2_stack(self) -> None:
        times = (EPOCH, EPOCH + timedelta(minutes=20), EPOCH + timedelta(minutes=40))
        expected = J2Propagator(max_step_s=60.0).propagate(self.state, times)
        actual = HighPrecisionPropagator(
            gravity_degree=None,
            include_third_body=False,
            include_relativity=False,
            max_step_s=60.0,
        ).propagate(self.state, times)
        np.testing.assert_allclose(actual.positions_m, expected.positions_m, atol=1e-6)
        np.testing.assert_allclose(actual.velocities_m_s, expected.velocities_m_s, atol=1e-9)


class SGP4Tests(unittest.TestCase):
    def test_vallado_verification_case_at_epoch(self) -> None:
        line1 = "1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753"
        line2 = "2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667"
        propagator = SGP4Propagator(line1, line2)
        from astropy.time import Time

        satellite = propagator._satellite
        epoch = Time(
            satellite.jdsatepoch + satellite.jdsatepochF, format="jd", scale="utc"
        ).to_datetime(timezone.utc)
        result = propagator.propagate((epoch,))
        np.testing.assert_allclose(
            result.positions_m[0] / 1000.0,
            [7022.46529266, -1400.08296755, 0.03995155],
            atol=2e-5,
        )
        np.testing.assert_allclose(
            result.velocities_m_s[0] / 1000.0,
            [1.893841015, 6.405893759, 4.534807250],
            atol=2e-8,
        )
        self.assertEqual(result.frame, "TEME")


if __name__ == "__main__":
    unittest.main()
