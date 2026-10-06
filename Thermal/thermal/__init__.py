"""SDTwin thermal module: lumped six-node thermal network of one computing satellite.

Nodes S, J, C, B, D and R (solar array, computing node, cold plate, battery, power equipment and common
radiator) are joined by the paths SR, JC, CR, BR and DR. The public names follow appendix A of the thermal
design report: the four data objects of section 5.1 and the five functions of chapter 5, plus the error and warning classes.
SurfaceRecord and the order constants are available from thermal.types. Units are K, s, W, m, J/K and K/W.
"""

from .environment import calculate_surface_heat, prepare_surface_environment
from .model import calculate_heat_flows, thermal_derivative
from .parameters import assemble_thermal_parameters
from .types import (
    ThermalConfigurationError,
    ThermalError,
    ThermalEvaluation,
    ThermalInputError,
    ThermalInputs,
    ThermalParameters,
    ThermalRangeWarning,
    ThermalState,
)

__all__ = [
    "ThermalConfigurationError",
    "ThermalError",
    "ThermalEvaluation",
    "ThermalInputError",
    "ThermalInputs",
    "ThermalParameters",
    "ThermalRangeWarning",
    "ThermalState",
    "assemble_thermal_parameters",
    "calculate_heat_flows",
    "calculate_surface_heat",
    "prepare_surface_environment",
    "thermal_derivative",
]
