"""NTU Space Dynamics public API.

All orbital lengths use metres, velocities use metres per second, angles use
radians unless a function explicitly exposes ``degrees=True``, and datetimes
must be timezone-aware UTC values.
"""

from .access import (
    AccessResult,
    AccessWindow,
    GroundTarget,
    NadirSensor,
    access_interpolation,
    access_propagation,
)
from .attitude import EulerDynamics, euler_to_dcm, ypr_to_euler
from .coordinates import (
    ecef_to_eci,
    ecef_to_geodetic,
    eci_to_ecef,
    geodetic_to_ecef,
    transform_ephemeris,
)
from .gravity import (
    EarthOrientationCache,
    GravityFieldCoefficients,
    SphericalHarmonicGravity,
    load_builtin_egm2008,
)
from .orbits import (
    HighPrecisionPropagator,
    J2Propagator,
    SGP4Propagator,
    TwoBodyPropagator,
    oe_to_rv,
    rv_to_oe,
)
from .power import SolarPanel, ThermalPowerResult, power_considering_thermal
from .solar import (
    eclipse_fraction,
    sun_beta_angle,
    sun_intensity,
    sun_position_analytical,
    sun_position_ephemeris,
    sun_radiation_pressure,
)
from .types import AttitudeEphemeris, ClassicalElements, Ephemeris, OrbitState

__all__ = [
    "AccessResult",
    "AccessWindow",
    "AttitudeEphemeris",
    "ClassicalElements",
    "Ephemeris",
    "EulerDynamics",
    "EarthOrientationCache",
    "GroundTarget",
    "GravityFieldCoefficients",
    "HighPrecisionPropagator",
    "J2Propagator",
    "NadirSensor",
    "OrbitState",
    "SGP4Propagator",
    "SolarPanel",
    "SphericalHarmonicGravity",
    "ThermalPowerResult",
    "TwoBodyPropagator",
    "access_interpolation",
    "access_propagation",
    "ecef_to_eci",
    "ecef_to_geodetic",
    "eci_to_ecef",
    "eclipse_fraction",
    "euler_to_dcm",
    "geodetic_to_ecef",
    "load_builtin_egm2008",
    "oe_to_rv",
    "power_considering_thermal",
    "rv_to_oe",
    "sun_beta_angle",
    "sun_intensity",
    "sun_position_analytical",
    "sun_position_ephemeris",
    "sun_radiation_pressure",
    "transform_ephemeris",
    "ypr_to_euler",
]
