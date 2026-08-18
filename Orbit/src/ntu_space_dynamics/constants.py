"""Physical constants used by the public models (SI units)."""

from __future__ import annotations

import numpy as np

MU_EARTH = 3.986004418e14  # m^3 / s^2, IERS 2010
R_EARTH_EQUATOR = 6_378_137.0  # m, WGS-84
R_EARTH_POLAR = 6_356_752.314245  # m, WGS-84
WGS84_FLATTENING = 1.0 / 298.257223563
J2_EARTH = 1.08262668e-3
OMEGA_EARTH = 7.2921150e-5  # rad / s

MU_SUN = 1.32712440018e20  # m^3 / s^2
MU_MOON = 4.9048695e12  # m^3 / s^2
R_SUN = 695_700_000.0  # m, IAU nominal solar radius
ASTRONOMICAL_UNIT = 149_597_870_700.0  # m, exact IAU definition
SOLAR_CONSTANT = 1361.0  # W / m^2 at 1 au
SOLAR_PRESSURE_1_AU = 4.56e-6  # N / m^2
STEFAN_BOLTZMANN = 5.670374419e-8  # W / (m^2 K^4)

SECONDS_PER_DAY = 86_400.0
TWOPI = 2.0 * np.pi

