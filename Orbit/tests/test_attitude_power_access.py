from __future__ import annotations

import unittest
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np

from ntu_space_dynamics import (
    ClassicalElements,
    EulerDynamics,
    GroundTarget,
    NadirSensor,
    OrbitState,
    SolarPanel,
    TwoBodyPropagator,
    access_propagation,
    euler_to_dcm,
    oe_to_rv,
    power_considering_thermal,
    ypr_to_euler,
)


class AttitudeTests(unittest.TestCase):
    def test_ypr_conversion_preserves_rotation(self) -> None:
        ypr = np.deg2rad([20.0, -10.0, 5.0])
        xyz = ypr_to_euler(*ypr, output_sequence="XYZ")
        expected = euler_to_dcm(ypr, "ZYX")
        actual = euler_to_dcm(xyz, "XYZ")
        np.testing.assert_allclose(actual, expected, atol=1e-14)

    def test_torque_free_euler_dynamics_conserves_invariants(self) -> None:
        inertia = np.array([10.0, 12.0, 15.0])
        result = EulerDynamics(inertia).propagate(
            [0.0, 0.0, 0.0, 1.0],
            [0.01, 0.02, 0.03],
            np.linspace(0.0, 500.0, 101),
        )
        energy = 0.5 * np.sum(result.angular_velocity_body_rad_s**2 * inertia, axis=1)
        momentum_norm = np.linalg.norm(result.angular_velocity_body_rad_s * inertia, axis=1)
        self.assertLess(np.ptp(energy), 1e-11)
        self.assertLess(np.ptp(momentum_norm), 1e-10)
        np.testing.assert_allclose(
            np.linalg.norm(result.quaternions_xyzw, axis=1), 1.0, atol=2e-15
        )


class PowerTests(unittest.TestCase):
    def test_heating_reduces_temperature_sensitive_power(self) -> None:
        times = np.linspace(0.0, 1200.0, 41)
        panel = SolarPanel(area_m2=2.0, efficiency_reference=0.3)
        result = power_considering_thermal(
            times,
            np.full_like(times, 1361.0),
            np.ones_like(times),
            panel,
            initial_temperature_k=298.15,
        )
        self.assertGreater(result.temperature_k[-1], result.temperature_k[0])
        self.assertLess(result.electrical_power_w[-1], result.electrical_power_w[0])


class AccessTests(unittest.TestCase):
    def test_access_boundaries_are_refined_between_orbit_samples(self) -> None:
        epoch = datetime(2024, 4, 6, tzinfo=timezone.utc)
        elements = ClassicalElements.from_degrees(
            7_000_000.0, 0.001, 45.0, 0.0, 0.0, 0.0, epoch
        )
        position, velocity = oe_to_rv(elements)
        state = OrbitState(epoch, position, velocity)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = access_propagation(
                TwoBodyPropagator(),
                state,
                GroundTarget.from_degrees(0.0, -30.0),
                NadirSensor.from_degrees(70.0),
                start=epoch,
                stop=epoch + timedelta(hours=2),
                propagation_step_s=120.0,
                scan_step_s=30.0,
                boundary_tolerance_s=0.1,
            )
        self.assertGreaterEqual(len(result.windows), 1)
        first = result.windows[0]
        self.assertGreater(first.duration_s, 100.0)
        # A refined boundary should not simply be snapped to the 120 s ephemeris grid.
        offset = (first.start - epoch).total_seconds()
        self.assertGreater(abs(offset / 120.0 - round(offset / 120.0)), 1e-3)


if __name__ == "__main__":
    unittest.main()

