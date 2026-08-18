from __future__ import annotations

import tempfile
import unittest
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ntu_space_dynamics.constants import J2_EARTH, MU_EARTH, R_EARTH_EQUATOR
from ntu_space_dynamics.gravity import (
    EarthOrientationCache,
    GravityFieldCoefficients,
    SphericalHarmonicGravity,
    load_builtin_egm2008,
)
from ntu_space_dynamics.orbits import HighPrecisionPropagator
from ntu_space_dynamics.orbits.forces import J2Gravity
from ntu_space_dynamics.types import OrbitState


def j2_coefficients() -> GravityFieldCoefficients:
    cosine = np.zeros((3, 3))
    sine = np.zeros_like(cosine)
    cosine[0, 0] = 1.0
    cosine[2, 0] = -J2_EARTH / np.sqrt(5.0)
    return GravityFieldCoefficients(
        "J2 verification", MU_EARTH, R_EARTH_EQUATOR, cosine, sine
    )


class GravitySynthesisTests(unittest.TestCase):
    def test_packaged_egm2008_metadata_and_published_zonals(self) -> None:
        coefficients = load_builtin_egm2008(120)
        self.assertEqual(coefficients.model_name, "EGM2008")
        self.assertEqual(coefficients.max_degree, 120)
        self.assertEqual(coefficients.tide_system, "tide_free")
        self.assertEqual(coefficients.mu_m3_s2, 3.986004415e14)
        self.assertEqual(coefficients.reference_radius_m, 6_378_136.3)
        self.assertEqual(coefficients.cosine[2, 0], -0.484165143790815e-3)
        self.assertEqual(coefficients.cosine[3, 0], 0.957161207093473e-6)
        self.assertEqual(coefficients.cosine[10, 0], 0.533304381729473e-7)

    def test_high_degrees_materially_change_the_fixed_frame_acceleration(self) -> None:
        coefficients = load_builtin_egm2008(120)
        position = np.array([6_520_000.0, -1_850_000.0, 2_600_000.0])
        degree_two = SphericalHarmonicGravity(
            coefficients, max_degree=2
        ).acceleration_fixed(position)
        degree_seventy = SphericalHarmonicGravity(
            coefficients, max_degree=70
        ).acceleration_fixed(position)
        self.assertGreater(np.linalg.norm(degree_seventy - degree_two), 5e-5)

    def test_hpop_uses_egm2008_degree_seventy_by_default(self) -> None:
        propagator = HighPrecisionPropagator(
            include_third_body=False,
            include_relativity=False,
        )
        gravity = [
            model
            for model in propagator.force_models
            if isinstance(model, SphericalHarmonicGravity)
        ]
        self.assertEqual(len(gravity), 1)
        self.assertEqual(gravity[0].coefficients.model_name, "EGM2008")
        self.assertEqual(gravity[0].max_degree, 70)
        self.assertEqual(gravity[0].max_order, 70)

    def test_high_degree_hpop_propagates_a_gcrs_arc(self) -> None:
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
        initial = OrbitState(
            epoch,
            np.array([7_000_000.0, 0.0, 0.0]),
            np.array([0.0, 7_500.0, 1_000.0]),
            "GCRS",
        )
        propagator = HighPrecisionPropagator(
            include_third_body=False,
            include_relativity=False,
            max_step_s=60.0,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = propagator.propagate(
                initial,
                (epoch, epoch.replace(minute=1)),
            )
        self.assertTrue(np.all(np.isfinite(result.positions_m)))
        self.assertTrue(np.all(np.isfinite(result.velocities_m_s)))
        self.assertGreater(np.linalg.norm(result.positions_m[-1] - initial.position_m), 1e5)

    def test_fully_normalized_c20_reduces_exactly_to_j2(self) -> None:
        model = SphericalHarmonicGravity(j2_coefficients())
        reference = J2Gravity()
        epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
        positions = (
            np.array([7_000_000.0, 0.0, 0.0]),
            np.array([5_000_000.0, 3_000_000.0, 4_000_000.0]),
            np.array([-2_000_000.0, 6_000_000.0, -3_500_000.0]),
        )
        for position in positions:
            actual = model.acceleration_fixed(position)
            expected = reference.acceleration(0.0, np.r_[position, np.zeros(3)], epoch)
            np.testing.assert_allclose(actual, expected, rtol=2e-14, atol=2e-17)

    def test_acceleration_matches_cartesian_potential_gradient(self) -> None:
        rng = np.random.default_rng(42)
        degree = 8
        cosine = np.zeros((degree + 1, degree + 1))
        sine = np.zeros_like(cosine)
        cosine[0, 0] = 1.0
        for n in range(2, degree + 1):
            scale = 1e-4 / n**2
            cosine[n, : n + 1] = rng.normal(0.0, scale, n + 1)
            sine[n, 1 : n + 1] = rng.normal(0.0, scale, n)
        model = SphericalHarmonicGravity(
            GravityFieldCoefficients(
                "synthetic", MU_EARTH, R_EARTH_EQUATOR, cosine, sine
            )
        )
        position = np.array([5_200_000.0, -2_800_000.0, 4_100_000.0])
        step_m = 0.5
        finite_difference = np.empty(3)
        for axis in range(3):
            delta = np.zeros(3)
            delta[axis] = step_m
            finite_difference[axis] = (
                model.potential_fixed(position + delta)
                - model.potential_fixed(position - delta)
            ) / (2.0 * step_m)
        np.testing.assert_allclose(
            model.acceleration_fixed(position), finite_difference, rtol=2e-8, atol=2e-10
        )

    def test_icgem_static_loader_and_truncation(self) -> None:
        content = """\
product_type gravity_field
modelname TEST-GRAVITY
earth_gravity_constant 3.986004418D+14
radius 6.378137D+06
max_degree 3
errors no
norm fully_normalized
tide_system tide_free
end_of_head
gfc 0 0 1.0D+00 0.0D+00
gfc 1 0 0.0D+00 0.0D+00
gfc 2 0 -4.8416514379D-04 0.0D+00
gfc 2 1 1.0D-10 -2.0D-10
gfc 2 2 2.0D-06 1.0D-06
gfc 3 0 9.0D-07 0.0D+00
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.gfc"
            path.write_text(content, encoding="utf-8")
            coefficients = GravityFieldCoefficients.from_icgem(
                path, max_degree=2, max_order=1
            )
        self.assertEqual(coefficients.model_name, "TEST-GRAVITY")
        self.assertEqual(coefficients.max_degree, 2)
        self.assertEqual(coefficients.tide_system, "tide_free")
        self.assertAlmostEqual(coefficients.cosine[2, 0], -4.8416514379e-4)
        self.assertAlmostEqual(coefficients.sine[2, 1], -2.0e-10)
        self.assertEqual(coefficients.cosine[2, 2], 0.0)

    def test_earth_orientation_rotation_is_orthonormal(self) -> None:
        cache = EarthOrientationCache(sample_step_s=300.0)
        epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cache.prepare(epoch, 1800.0)
            matrix = cache.rotation(725.0, epoch).as_matrix()
        np.testing.assert_allclose(matrix.T @ matrix, np.eye(3), atol=3e-15)
        self.assertAlmostEqual(np.linalg.det(matrix), 1.0, places=14)


if __name__ == "__main__":
    unittest.main()
