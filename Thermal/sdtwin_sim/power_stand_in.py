"""Stand-in for the SDTwin Power module, written from the Power design report.

This module is a stand-in written from the interfaces and equations of the Power design report
(``Power/SDTwin_Power_Design_Report_CN.docx``). It is not the production Power module. It exists so that the thermal
module and the coupled procedure can be exercised against the Power interface the design specifies:

* the public names of design table 4 and appendix A: :class:`PowerParameters`, :class:`PowerEnvironment`,
  :class:`PowerInputs`, :class:`PowerState`, :class:`SolarPowerResult`, :class:`BatteryResponse`,
  :class:`PowerResult`, :class:`PowerEvent`, :func:`load_power_parameters`, :func:`battery_response`,
  :func:`solar_power`, :func:`solve_power_allocation` and :func:`apply_power_event`;
* equations P1 to P11: port power balance P1, fixed-efficiency solar array P2 with the eclipse already inside ``G``,
  distribution P3, single cell to pack conversion P4, lithium fractions P5, quadratic-profile surface fractions P6
  with the particle centre check, terminal voltage P7 with the symmetric Butler-Volmer ``asinh`` term, heat P8
  including the signed reversible term, Arrhenius and polynomial material functions P10, and the current solve P11
  (Brent root finding inside a valid bracket that starts from zero current). P9 belongs to Thermal and is not
  integrated here;
* the controller rules of design 4.5 and 5.5 (charge-limit curtailment of ``P_pv``, a confirmed supply shortfall or
  device boundary returns ``event_required=True``, an input or numerical failure returns ``valid=False``; neither
  case carries ports or derivatives) and the protection update of design 5.6.

Sign conventions follow the design: cell current ``i`` and pack port power ``P_B`` are positive on discharge, the
battery heat ``Q_B`` keeps its sign. Units are SI (W, A, V, K, s, C, m).

:func:`example_power_parameters` returns illustrative battery and panel test values. They are recorded as such in the
parameter provenance and do not describe a selected or measured device. ``CALL_STATS`` counts solve calls and battery
evaluations for test diagnostics.
"""

from __future__ import annotations

import copy
import dataclasses
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import brentq, minimize_scalar
from scipy.spatial.transform import Rotation

__all__ = [
    "FARADAY_C_MOL",
    "GAS_CONSTANT_J_MOLK",
    "PORT_NAMES",
    "EVENT_KINDS",
    "PowerError",
    "PowerConfigurationError",
    "PowerInputError",
    "SolarParameters",
    "ElectrodeParameters",
    "BatteryLimits",
    "BatteryParameters",
    "PowerNumerics",
    "PowerParameters",
    "PowerEnvironment",
    "PowerInputs",
    "PowerState",
    "SolarPowerResult",
    "BatteryResponse",
    "PowerResult",
    "PowerEvent",
    "PowerCallStats",
    "CALL_STATS",
    "load_power_parameters",
    "battery_response",
    "solar_power",
    "solve_power_allocation",
    "apply_power_event",
    "power_state_from_scene",
    "example_power_records",
    "example_power_parameters",
]

FARADAY_C_MOL = 96485.33212  # C mol^-1 (design 4.4.3)
GAS_CONSTANT_J_MOLK = 8.314462618  # J mol^-1 K^-1 (design 4.4.3)
PORT_NAMES = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")
ELECTRODE_IDS = ("n", "p")
EVENT_KINDS = ("start", "stop", "supply_loss")
FRAMES = ("GCRS", "ITRS", "TEME", "MOD")
UNIT_TOLERANCE = 1e-9  # |norm - 1| allowed for unit normals and quaternions
_EPS = float(np.finfo(float).eps)
_INTERIOR_SHRINK = 1e-12  # keeps the analytic linear-constraint end strictly inside its material range

ReasonCode = Literal[
    "supplied",
    "charge_limited",
    "load_disconnected",
    "supply_shortfall",
    "device_boundary",
    "invalid_input",
    "temperature_out_of_range",
    "numerical_failure",
]


# ----------------------------------------------------------------------------------------------------------------------
# errors and call statistics
# ----------------------------------------------------------------------------------------------------------------------


class PowerError(ValueError):
    """Base class of Power stand-in errors."""


class PowerConfigurationError(PowerError):
    """Asset, scene or parameter record problem found while preparing parameters."""


class PowerInputError(PowerError):
    """Runtime input problem: a dynamic record, an alignment mismatch or a value outside a model domain."""


class PowerCallStats:
    """Simple counters for test diagnostics: solve calls and battery evaluations."""

    __slots__ = ("solve_calls", "battery_evaluations")

    def __init__(self) -> None:
        self.solve_calls = 0
        self.battery_evaluations = 0

    def reset(self) -> None:
        self.solve_calls = 0
        self.battery_evaluations = 0

    def snapshot(self) -> dict[str, int]:
        return {"solve_calls": self.solve_calls, "battery_evaluations": self.battery_evaluations}


CALL_STATS = PowerCallStats()


# ----------------------------------------------------------------------------------------------------------------------
# validation helpers
# ----------------------------------------------------------------------------------------------------------------------


def _finite(value: Any, where: str, error: type[PowerError]) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise error(f"{where} must be a finite number, got a boolean {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise error(f"{where} must be a finite number, got {value!r}") from None
    if not math.isfinite(number):
        raise error(f"{where} must be finite, got {number!r}")
    return number


def _positive(value: Any, where: str, error: type[PowerError]) -> float:
    number = _finite(value, where, error)
    if number <= 0.0:
        raise error(f"{where} must be > 0, got {number!r}")
    return number


def _nonnegative(value: Any, where: str, error: type[PowerError]) -> float:
    number = _finite(value, where, error)
    if number < 0.0:
        raise error(f"{where} must be >= 0, got {number!r}")
    return number


def _count(value: Any, where: str, minimum: int, error: type[PowerError]) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise error(f"{where} must be an integer, got {value!r}")
    if int(value) < minimum:
        raise error(f"{where} must be >= {minimum}, got {value!r}")
    return int(value)


def _flag(value: Any, where: str, error: type[PowerError]) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise error(f"{where} must be a boolean, got {value!r}")
    return bool(value)


def _text(value: Any, where: str, error: type[PowerError]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{where} must be a non-empty string, got {value!r}")
    return value


def _vector(value: Any, where: str, length: int, error: type[PowerError]) -> NDArray[np.float64]:
    try:
        array = np.array(value, dtype=float)
    except (TypeError, ValueError):
        raise error(f"{where} must be a numeric array of shape ({length},), got {value!r}") from None
    if array.shape != (length,):
        raise error(f"{where} must have shape ({length},), got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise error(f"{where} must contain only finite values")
    array.setflags(write=False)
    return array


def _interval(
    value: Any,
    where: str,
    error: type[PowerError],
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> tuple[float, float]:
    """A strictly increasing pair ``(lo, hi)``, optionally strictly inside ``(lower, upper)``."""

    try:
        items = list(value)
    except TypeError:
        raise error(f"{where} must be a pair [low, high], got {value!r}") from None
    if len(items) != 2:
        raise error(f"{where} must be a pair [low, high], got {len(items)} entries")
    lo = _finite(items[0], f"{where}[0]", error)
    hi = _finite(items[1], f"{where}[1]", error)
    if not lo < hi:
        raise error(f"{where} must be ordered low to high, got [{lo!r}, {hi!r}]")
    if lower is not None and not lo > lower:
        raise error(f"{where} must lie strictly above {lower!r}, got low {lo!r}")
    if upper is not None and not hi < upper:
        raise error(f"{where} must lie strictly below {upper!r}, got high {hi!r}")
    return (lo, hi)


def _within(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _freeze(value: Any) -> Any:
    """Read-only deep copy: mappings become ``MappingProxyType``, lists become tuples, arrays become read-only."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, np.ndarray):
        array = np.array(value, copy=True)
        array.setflags(write=False)
        return array
    if isinstance(value, np.generic):
        return value.item()
    return value


def _plain(value: Any) -> Any:
    """JSON-friendly copy used for provenance entries (arrays to lists)."""

    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _mapping(value: Any, where: str, error: type[PowerError]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise error(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _get(record: Mapping[str, Any], key: str, where: str, error: type[PowerError]) -> Any:
    if key not in record:
        raise error(f"{where}: missing field '{key}'")
    return record[key]


def _only_keys(record: Mapping[str, Any], allowed: Sequence[str], where: str, error: type[PowerError]) -> None:
    unknown = sorted(set(record) - set(allowed))
    if unknown:
        raise error(f"{where}: unknown field(s) {unknown}; allowed fields are {sorted(allowed)}")


def _electrode_charge_C(active_fraction: float, electrode_area_m2: float, thickness_m: float, c_max: float) -> float:
    """Design 4.4.5: Q_k = F eps_k A_el L_k c_k,max, the charge for a lithium fraction change from 0 to 1."""

    return FARADAY_C_MOL * active_fraction * electrode_area_m2 * thickness_m * c_max


def _horner(coefficients: tuple[float, ...], x: float) -> float:
    """Polynomial with coefficients ordered from the constant term to the highest power."""

    accumulator = 0.0
    for coefficient in reversed(coefficients):
        accumulator = accumulator * x + coefficient
    return accumulator


# ----------------------------------------------------------------------------------------------------------------------
# parameter records (design 5.1 and 5.2)
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SolarParameters:
    """Solar array of P2: effective cell area, maximum-power-point efficiency and body-frame mounting normal."""

    area_m2: float
    efficiency: float
    normal_body: ArrayLike

    def __post_init__(self) -> None:
        error = PowerConfigurationError
        object.__setattr__(self, "area_m2", _positive(self.area_m2, "solar.area_m2", error))
        efficiency = _finite(self.efficiency, "solar.efficiency", error)
        if not 0.0 < efficiency <= 1.0:
            raise error(f"solar.efficiency must lie in (0, 1], got {efficiency!r}")
        object.__setattr__(self, "efficiency", efficiency)
        normal = _vector(self.normal_body, "solar.normal_body", 3, error)
        norm = float(np.linalg.norm(normal))
        if norm == 0.0:
            raise error("solar.normal_body must be non-zero")
        if abs(norm - 1.0) > UNIT_TOLERANCE:
            raise error(f"solar.normal_body must be a unit vector within {UNIT_TOLERANCE}, got norm {norm!r}")
        object.__setattr__(self, "normal_body", normal)


@dataclass(frozen=True)
class ElectrodeParameters:
    """One electrode of the single-particle model (P6, P7, P10); ``electrode_id`` is ``"n"`` or ``"p"``.

    ``b_V`` and ``d_V_K`` hold the open-circuit potential and its temperature coefficient as polynomials in the surface
    lithium fraction, ordered from the constant term up; both have length ``M_k + 1``. ``charge_C`` is ``Q_k``.
    """

    electrode_id: str
    radius_m: float
    active_fraction: float
    electrode_area_m2: float
    thickness_m: float
    c_max_mol_m3: float
    D_ref_m2_s: float
    I0_ref_A: float
    E_D_J_mol: float
    E_I_J_mol: float
    b_V: ArrayLike
    d_V_K: ArrayLike
    charge_C: float = field(init=False)
    _b: tuple[float, ...] = field(init=False, repr=False, compare=False)
    _d: tuple[float, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        error = PowerConfigurationError
        if self.electrode_id not in ELECTRODE_IDS:
            raise error(f"battery.electrodes: electrode_id must be 'n' or 'p', got {self.electrode_id!r}")
        record = f"battery.electrodes[{self.electrode_id}]"
        for name in ("radius_m", "electrode_area_m2", "thickness_m", "c_max_mol_m3", "D_ref_m2_s", "I0_ref_A"):
            object.__setattr__(self, name, _positive(getattr(self, name), f"{record}.{name}", error))
        fraction = _finite(self.active_fraction, f"{record}.active_fraction", error)
        if not 0.0 < fraction <= 1.0:
            raise error(f"{record}.active_fraction must lie in (0, 1], got {fraction!r}")
        object.__setattr__(self, "active_fraction", fraction)
        for name in ("E_D_J_mol", "E_I_J_mol"):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), f"{record}.{name}", error))
        arrays = {}
        for name in ("b_V", "d_V_K"):
            try:
                array = np.array(getattr(self, name), dtype=float)
            except (TypeError, ValueError):
                raise error(f"{record}.{name} must be a numeric coefficient array") from None
            if array.ndim != 1 or array.size == 0:
                raise error(f"{record}.{name} must be a non-empty one-dimensional array, got shape {array.shape}")
            if not np.all(np.isfinite(array)):
                raise error(f"{record}.{name} must contain only finite values")
            array.setflags(write=False)
            arrays[name] = array
        if arrays["b_V"].shape != arrays["d_V_K"].shape:
            raise error(
                f"{record}: b_V and d_V_K must both have length M_k + 1, got {arrays['b_V'].size} and "
                f"{arrays['d_V_K'].size}"
            )
        object.__setattr__(self, "b_V", arrays["b_V"])
        object.__setattr__(self, "d_V_K", arrays["d_V_K"])
        object.__setattr__(self, "_b", tuple(float(c) for c in arrays["b_V"]))
        object.__setattr__(self, "_d", tuple(float(c) for c in arrays["d_V_K"]))
        object.__setattr__(
            self,
            "charge_C",
            _electrode_charge_C(self.active_fraction, self.electrode_area_m2, self.thickness_m, self.c_max_mol_m3),
        )


@dataclass(frozen=True)
class BatteryLimits:
    """Device and material bounds of ``battery.limits``; each interval is ordered low to high (design 5.1)."""

    i_min_A: float
    i_max_A: float
    v_min_V: float
    v_max_V: float
    x_n_range: tuple[float, float]
    x_p_range: tuple[float, float]
    T_range_K: tuple[float, float]

    def __post_init__(self) -> None:
        error = PowerConfigurationError
        i_min = _finite(self.i_min_A, "battery.limits.i_min_A", error)
        i_max = _finite(self.i_max_A, "battery.limits.i_max_A", error)
        if not i_min < 0.0 < i_max:
            raise error(
                f"battery.limits: i_min_A must be < 0 (charge) and i_max_A > 0 (discharge), got {i_min!r} and {i_max!r}"
            )
        object.__setattr__(self, "i_min_A", i_min)
        object.__setattr__(self, "i_max_A", i_max)
        v_range = _interval((self.v_min_V, self.v_max_V), "battery.limits.[v_min_V, v_max_V]", error, lower=0.0)
        object.__setattr__(self, "v_min_V", v_range[0])
        object.__setattr__(self, "v_max_V", v_range[1])
        for name in ("x_n_range", "x_p_range"):
            # design 4.4.2: the material range must lie inside 0 and 1
            bounds = _interval(getattr(self, name), f"battery.limits.{name}", error, lower=0.0, upper=1.0)
            object.__setattr__(self, name, bounds)
        object.__setattr__(
            self, "T_range_K", _interval(self.T_range_K, "battery.limits.T_range_K", error, lower=0.0)
        )


@dataclass(frozen=True)
class BatteryParameters:
    """Cell-level SPM parameters, series and parallel counts, SOC end points and limits (design 4.4, 5.1)."""

    N_s: int
    N_p: int
    R_ohm_ohm: float
    T_ref_K: float
    electrodes: Mapping[str, ElectrodeParameters]
    x_n_0: float
    x_n_100: float
    x_p_100: float
    limits: BatteryLimits
    parameter_level: str
    Q_n_C: float = field(init=False)
    Q_p_C: float = field(init=False)

    def __post_init__(self) -> None:
        error = PowerConfigurationError
        object.__setattr__(self, "N_s", _count(self.N_s, "battery.N_s", 1, error))
        object.__setattr__(self, "N_p", _count(self.N_p, "battery.N_p", 1, error))
        object.__setattr__(self, "R_ohm_ohm", _nonnegative(self.R_ohm_ohm, "battery.R_ohm_ohm", error))
        object.__setattr__(self, "T_ref_K", _positive(self.T_ref_K, "battery.T_ref_K", error))
        if self.parameter_level != "cell":
            raise error(
                f"battery.parameter_level must be 'cell' (P4 and P8 convert cell values to the pack once), "
                f"got {self.parameter_level!r}"
            )
        if not isinstance(self.limits, BatteryLimits):
            raise error(f"battery.limits must be BatteryLimits, got {type(self.limits).__name__}")
        electrodes = _mapping(self.electrodes, "battery.electrodes", error)
        if set(electrodes) != set(ELECTRODE_IDS):
            raise error(f"battery.electrodes must have exactly the keys 'n' and 'p', got {sorted(electrodes)}")
        for key in ELECTRODE_IDS:
            item = electrodes[key]
            if not isinstance(item, ElectrodeParameters):
                raise error(f"battery.electrodes[{key}] must be ElectrodeParameters, got {type(item).__name__}")
            if item.electrode_id != key:
                raise error(f"battery.electrodes[{key}].electrode_id is {item.electrode_id!r}, expected {key!r}")
        object.__setattr__(self, "electrodes", MappingProxyType({key: electrodes[key] for key in ELECTRODE_IDS}))
        for name, bounds in (("x_n_0", self.limits.x_n_range), ("x_n_100", self.limits.x_n_range),
                             ("x_p_100", self.limits.x_p_range)):
            value = _finite(getattr(self, name), f"battery.{name}", error)
            if not _within(value, bounds):
                raise error(f"battery.{name}={value!r} lies outside the material range {bounds}")
            object.__setattr__(self, name, value)
        if self.x_n_0 == self.x_n_100:
            raise error("battery.x_n_0 and battery.x_n_100 must differ (SOC end points)")
        object.__setattr__(self, "Q_n_C", self.electrodes["n"].charge_C)
        object.__setattr__(self, "Q_p_C", self.electrodes["p"].charge_C)

    @property
    def cells(self) -> int:
        return self.N_s * self.N_p

    @property
    def reference_inventory_mol(self) -> float:
        """Cyclable lithium in one cell at the SOC 100 point, the inventory every state must keep."""

        return (self.x_n_100 * self.Q_n_C + self.x_p_100 * self.Q_p_C) / FARADAY_C_MOL

    def lithium_inventory_mol(self, x_n: float, x_p: float) -> float:
        return (x_n * self.Q_n_C + x_p * self.Q_p_C) / FARADAY_C_MOL

    def soc(self, x_n: float) -> float:
        """Design 4.4.5: SOC = (x_n - x_n,0) / (x_n,100 - x_n,0); never mixed with a single-electrode fraction."""

        return (x_n - self.x_n_0) / (self.x_n_100 - self.x_n_0)


@dataclass(frozen=True)
class PowerNumerics:
    """``parameters.numerics`` of design table 7, plus the scan density and inventory tolerance of this stand-in."""

    rtol: float
    atol_x: float
    atol_T_K: float
    current_xtol_A: float
    power_residual_tol_W: float
    event_time_tol_s: float
    max_step_s: float
    environment_step_s: float
    output_step_s: float
    current_scan_points: int
    inventory_rtol: float

    def __post_init__(self) -> None:
        error = PowerConfigurationError
        for item in dataclasses.fields(self):
            if item.name == "current_scan_points":
                object.__setattr__(self, item.name, _count(self.current_scan_points, "numerics.current_scan_points",
                                                           2, error))
            else:
                object.__setattr__(self, item.name, _positive(getattr(self, item.name), f"numerics.{item.name}", error))


@dataclass(frozen=True)
class PowerParameters:
    """Resolved Power parameters: ``solar``, ``battery``, ``eta_D``, ``links``, ``numerics``, ``provenance``.

    Fixed parameters never hold the running lithium state or the battery temperature (design 5.1).
    """

    solar: SolarParameters
    battery: BatteryParameters
    eta_D: float
    links: Mapping[str, str]
    numerics: PowerNumerics
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        error = PowerConfigurationError
        for name, kind in (("solar", SolarParameters), ("battery", BatteryParameters), ("numerics", PowerNumerics)):
            if not isinstance(getattr(self, name), kind):
                raise error(f"PowerParameters.{name} must be {kind.__name__}, got {type(getattr(self, name)).__name__}")
        eta = _finite(self.eta_D, "PowerParameters.eta_D", error)
        if not 0.0 < eta <= 1.0:
            raise error(f"PowerParameters.eta_D must lie in (0, 1], got {eta!r}")
        object.__setattr__(self, "eta_D", eta)
        links = _mapping(self.links, "PowerParameters.links", error)
        if set(links) != set(PORT_NAMES):
            raise error(f"PowerParameters.links must map exactly the ports {list(PORT_NAMES)}, got {sorted(links)}")
        object.__setattr__(
            self,
            "links",
            MappingProxyType({port: _text(links[port], f"PowerParameters.links[{port}]", error) for port in PORT_NAMES}),
        )
        provenance = _mapping(self.provenance, "PowerParameters.provenance", error)
        _text(_get(provenance, "instance_id", "PowerParameters.provenance", error),
              "PowerParameters.provenance.instance_id", error)
        object.__setattr__(self, "provenance", _freeze(provenance))

    @property
    def instance_id(self) -> str:
        return str(self.provenance["instance_id"])


# ----------------------------------------------------------------------------------------------------------------------
# dynamic records (design 5.1, 6.1)
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PowerEnvironment:
    """Same-instant orbit inputs: ``G_W_m2`` already includes the eclipse; positions in GCRS; body-to-GCRS quaternion."""

    G_W_m2: float
    position_m: ArrayLike
    sun_position_m: ArrayLike
    quaternion_xyzw: ArrayLike
    frame: str

    def __post_init__(self) -> None:
        error = PowerInputError
        object.__setattr__(self, "G_W_m2", _nonnegative(self.G_W_m2, "PowerEnvironment.G_W_m2", error))
        object.__setattr__(self, "position_m", _vector(self.position_m, "PowerEnvironment.position_m", 3, error))
        object.__setattr__(
            self, "sun_position_m", _vector(self.sun_position_m, "PowerEnvironment.sun_position_m", 3, error)
        )
        quaternion = _vector(self.quaternion_xyzw, "PowerEnvironment.quaternion_xyzw", 4, error)
        norm = float(np.linalg.norm(quaternion))
        if abs(norm - 1.0) > UNIT_TOLERANCE:
            raise error(f"PowerEnvironment.quaternion_xyzw must be a unit quaternion within {UNIT_TOLERANCE}, "
                        f"got norm {norm!r}")
        object.__setattr__(self, "quaternion_xyzw", quaternion)
        if self.frame not in FRAMES:
            raise error(f"PowerEnvironment.frame: unsupported frame {self.frame!r}")


@dataclass(frozen=True)
class PowerInputs:
    """Same-instant environment, non-negative load request and battery temperature from Thermal."""

    run_id: str
    instance_id: str
    time_s: float
    environment: PowerEnvironment
    P_request_W: float
    T_B_K: float

    def __post_init__(self) -> None:
        error = PowerInputError
        _text(self.run_id, "PowerInputs.run_id", error)
        _text(self.instance_id, "PowerInputs.instance_id", error)
        object.__setattr__(self, "time_s", _finite(self.time_s, "PowerInputs.time_s", error))
        environment = self.environment
        if isinstance(environment, Mapping):
            environment = PowerEnvironment(**environment)
        if not isinstance(environment, PowerEnvironment):
            raise error(f"PowerInputs.environment must be PowerEnvironment, got {type(environment).__name__}")
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "P_request_W", _nonnegative(self.P_request_W, "PowerInputs.P_request_W", error))
        object.__setattr__(self, "T_B_K", _positive(self.T_B_K, "PowerInputs.T_B_K", error))


@dataclass(frozen=True)
class PowerState:
    """Lithium fractions ``x_n``, ``x_p`` (integrated) and the discrete protection state (design 5.1)."""

    run_id: str
    instance_id: str
    time_s: float
    x_n: float
    x_p: float
    load_connected: bool
    trip_latched: bool
    handled_command_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        error = PowerInputError
        _text(self.run_id, "PowerState.run_id", error)
        _text(self.instance_id, "PowerState.instance_id", error)
        object.__setattr__(self, "time_s", _finite(self.time_s, "PowerState.time_s", error))
        object.__setattr__(self, "x_n", _finite(self.x_n, "PowerState.x_n", error))
        object.__setattr__(self, "x_p", _finite(self.x_p, "PowerState.x_p", error))
        connected = _flag(self.load_connected, "PowerState.load_connected", error)
        latched = _flag(self.trip_latched, "PowerState.trip_latched", error)
        if connected and latched:
            raise error("PowerState: load_connected and trip_latched cannot both be true (a latched trip disconnects)")
        object.__setattr__(self, "load_connected", connected)
        object.__setattr__(self, "trip_latched", latched)
        if isinstance(self.handled_command_ids, str):
            raise error("PowerState.handled_command_ids must be a sequence of command ids, got a string")
        try:
            ids = tuple(self.handled_command_ids)
        except TypeError:
            raise error("PowerState.handled_command_ids must be a sequence of command ids") from None
        for index, command_id in enumerate(ids):
            _text(command_id, f"PowerState.handled_command_ids[{index}]", error)
        if len(set(ids)) != len(ids):
            raise error("PowerState.handled_command_ids contains duplicates")
        object.__setattr__(self, "handled_command_ids", ids)


@dataclass(frozen=True)
class SolarPowerResult:
    """P2 result: incidence cosine (negative when facing away), panel irradiance and available solar power."""

    cos_incidence: float
    G_S_W_m2: float
    P_pv_max_W: float


@dataclass(frozen=True)
class BatteryResponse:
    """Battery response to one trial cell current (P4 to P8, P10).

    ``constraint_margins`` holds the distance of current (A), voltage (V) and the mean, surface and centre lithium
    fractions to their bounds; zero means the bound is reached and a negative value means it is exceeded. The five
    summary keys are ``current_A``, ``voltage_V``, ``x_mean``, ``x_surface`` and ``x_center``; per-electrode keys
    ``x_n_mean`` ... ``x_p_center`` follow. Temperature is checked separately in kelvin.
    """

    v_cell_V: float
    I_B_A: float
    V_B_V: float
    P_B_W: float
    Q_B_W: float
    dx_n_dt: float
    dx_p_dt: float
    constraint_margins: Mapping[str, float]
    i_A: float
    T_B_K: float
    x_n_surface: float
    x_p_surface: float
    x_n_center: float
    x_p_center: float
    U_n_V: float
    U_p_V: float
    dv_n_V: float
    dv_p_V: float
    beta_V_K: float
    q_cell_W: float
    q_reversible_cell_W: float

    def __post_init__(self) -> None:
        for item in dataclasses.fields(self):
            if item.name == "constraint_margins":
                continue
            value = getattr(self, item.name)
            if not math.isfinite(value):
                raise PowerInputError(f"BatteryResponse.{item.name} is not finite ({value!r})")
        object.__setattr__(self, "constraint_margins", MappingProxyType(dict(self.constraint_margins)))


@dataclass(frozen=True)
class PowerResult:
    """Power evaluation at one instant (design 5.1, 5.5).

    Only ``valid=True`` with ``event_required=False`` carries the four ports, the two lithium derivatives and the
    battery response. An input or numerical failure (``valid=False``) and a confirmed shortfall or device boundary
    (``valid=True, event_required=True``) leave them as ``None``; no zero heat source stands in for success.
    ``reason`` is ``"<code>"`` or ``"<code>: <detail>"``.
    """

    run_id: str
    instance_id: str
    time_s: float
    P_pv_W: float | None
    P_load_W: float | None
    Q_B_W: float | None
    Q_D_W: float | None
    dx_n_dt: float | None
    dx_p_dt: float | None
    battery: BatteryResponse | None
    valid: bool
    event_required: bool
    can_supply_request: bool
    reason: str
    solar: SolarPowerResult | None
    P_bus_W: float | None
    diagnostics: Mapping[str, Any]

    def __post_init__(self) -> None:
        error = PowerInputError
        valid = _flag(self.valid, "PowerResult.valid", error)
        event = _flag(self.event_required, "PowerResult.event_required", error)
        can_supply = _flag(self.can_supply_request, "PowerResult.can_supply_request", error)
        _text(self.reason, "PowerResult.reason", error)
        object.__setattr__(self, "diagnostics", _freeze(dict(self.diagnostics)))
        payload = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W", "dx_n_dt", "dx_p_dt", "battery", "P_bus_W")
        if not valid or event:
            if not valid and event:
                raise error("PowerResult: an invalid result cannot also require an event")
            if can_supply and event:
                raise error("PowerResult: an event result cannot report can_supply_request=True")
            filled = [name for name in payload if getattr(self, name) is not None]
            if filled:
                raise error(f"PowerResult: invalid or event results carry no ports or derivatives, got {filled}")
            return
        if not isinstance(self.battery, BatteryResponse):
            raise error("PowerResult.battery must be a BatteryResponse for a usable result")
        for name in payload[:-2] + ("P_bus_W",):
            object.__setattr__(self, name, _finite(getattr(self, name), f"PowerResult.{name}", error))
        for name in ("P_pv_W", "P_load_W", "Q_D_W", "P_bus_W"):
            if getattr(self, name) < 0.0:
                raise error(f"PowerResult.{name} must be >= 0, got {getattr(self, name)!r}")
        if self.Q_B_W != self.battery.Q_B_W or self.dx_n_dt != self.battery.dx_n_dt \
                or self.dx_p_dt != self.battery.dx_p_dt:
            raise error("PowerResult: Q_B_W and the derivatives must equal the battery response")
        scale = max(1.0, abs(self.P_pv_W) + abs(self.battery.P_B_W) + abs(self.P_load_W) + abs(self.Q_D_W))
        imbalance = self.P_pv_W + self.battery.P_B_W - self.P_load_W - self.Q_D_W
        if abs(imbalance) > 1e-9 * scale:
            raise error(f"PowerResult: P1 imbalance P_pv + P_B - P_load - Q_D = {imbalance!r} W")
        if self.solar is not None and self.P_pv_W > self.solar.P_pv_max_W * (1.0 + 1e-12) + 1e-12:
            raise error(f"PowerResult.P_pv_W={self.P_pv_W!r} exceeds P_pv_max_W={self.solar.P_pv_max_W!r}")

    @property
    def reason_code(self) -> str:
        return self.reason.split(":", 1)[0]

    @property
    def ports(self) -> dict[str, float] | None:
        """The four cross-domain ports, or ``None`` when the result is not usable for integration."""

        if not self.valid or self.event_required:
            return None
        return {name: getattr(self, name) for name in PORT_NAMES}


@dataclass(frozen=True)
class PowerEvent:
    """An accepted protection event of kind ``start``, ``stop`` or ``supply_loss`` with a unique ``command_id``."""

    kind: str
    command_id: str
    accepted: bool
    run_id: str
    instance_id: str
    time_s: float

    def __post_init__(self) -> None:
        error = PowerInputError
        if self.kind not in EVENT_KINDS:
            raise error(f"PowerEvent.kind must be one of {list(EVENT_KINDS)}, got {self.kind!r}")
        _text(self.command_id, "PowerEvent.command_id", error)
        object.__setattr__(self, "accepted", _flag(self.accepted, "PowerEvent.accepted", error))
        _text(self.run_id, "PowerEvent.run_id", error)
        _text(self.instance_id, "PowerEvent.instance_id", error)
        object.__setattr__(self, "time_s", _finite(self.time_s, "PowerEvent.time_s", error))


# ----------------------------------------------------------------------------------------------------------------------
# parameter loading (design 5.2)
# ----------------------------------------------------------------------------------------------------------------------

_ASSET_GROUPS = ("solar", "battery", "pdu")
_GROUP_META = ("asset_id", "asset_version", "source", "notes")
_SOLAR_FIELDS = ("area_m2", "efficiency", "normal_body")
_BATTERY_FIELDS = ("parameter_level", "N_s", "N_p", "R_ohm_ohm", "T_ref_K", "electrodes", "x_n_0", "x_n_100",
                   "x_p_100", "limits")
_PDU_FIELDS = ("eta_D", "covered_wiring")
_ELECTRODE_FIELDS = ("radius_m", "active_fraction", "electrode_area_m2", "thickness_m", "c_max_mol_m3", "D_ref_m2_s",
                     "I0_ref_A", "E_D_J_mol", "E_I_J_mol", "b_V", "d_V_K")
_LIMIT_FIELDS = ("i_min_A", "i_max_A", "v_min_V", "v_max_V", "x_n_range", "x_p_range", "T_range_K")
_NUMERICS_FIELDS = tuple(item.name for item in dataclasses.fields(PowerNumerics))
_INITIAL_FIELDS = ("time_s", "x_n", "x_p", "T_B_K", "load_connected", "trip_latched")
_ALLOWED_OVERRIDES = {"solar": ("area_m2", "efficiency", "normal_body"), "battery": ("N_s", "N_p"), "pdu": ("eta_D",)}
_SCENE_FIELDS = ("instance_id", "asset_refs", "links", "overrides", "initial_state", "numerics", "notes")


def load_power_parameters(asset_record: Mapping[str, Any], scene_record: Mapping[str, Any]) -> PowerParameters:
    """Resolve fixed-version asset parameters and the scene into :class:`PowerParameters` (design 5.2).

    ``asset_record`` has the groups ``solar``, ``battery`` and ``pdu`` (each with ``asset_id``, ``asset_version``,
    ``source`` and the fields of design 5.1) and an optional ``data_status``. ``scene_record`` has ``instance_id``,
    ``asset_refs`` (expected id and version per group), ``links``, ``overrides`` (``{group: {field: value}, "source"}``),
    ``initial_state`` and ``numerics``. The function checks versions and required fields, applies the allowed
    overrides, computes ``Q_n_C`` and ``Q_p_C``, and checks the initial lithium inventory, the zero-current voltage
    and the initial temperature without advancing any state. Errors name the record and field.
    """

    error = PowerConfigurationError
    asset = _mapping(asset_record, "asset_record", error)
    scene = _mapping(scene_record, "scene_record", error)
    _only_keys(asset, _ASSET_GROUPS + ("data_status", "notes"), "asset_record", error)
    _only_keys(scene, _SCENE_FIELDS, "scene_record", error)
    instance_id = _text(_get(scene, "instance_id", "scene_record", error), "scene_record.instance_id", error)

    groups: dict[str, dict[str, Any]] = {}
    asset_provenance: dict[str, Any] = {}
    refs = _mapping(_get(scene, "asset_refs", "scene_record", error), "scene_record.asset_refs", error)
    _only_keys(refs, _ASSET_GROUPS, "scene_record.asset_refs", error)
    group_fields = {"solar": _SOLAR_FIELDS, "battery": _BATTERY_FIELDS, "pdu": _PDU_FIELDS}
    for group in _ASSET_GROUPS:
        where = f"asset_record.{group}"
        record = _mapping(_get(asset, group, "asset_record", error), where, error)
        _only_keys(record, _GROUP_META + group_fields[group], where, error)
        for name in ("asset_id", "asset_version", "source"):
            _text(_get(record, name, where, error), f"{where}.{name}", error)
        for name in group_fields[group]:
            _get(record, name, where, error)
        ref = _mapping(_get(refs, group, "scene_record.asset_refs", error), f"scene_record.asset_refs.{group}", error)
        for name in ("asset_id", "asset_version"):
            expected = _get(ref, name, f"scene_record.asset_refs.{group}", error)
            if expected != record[name]:
                raise error(
                    f"scene_record.asset_refs.{group}.{name}={expected!r} does not match {where}.{name}={record[name]!r}"
                )
        groups[group] = copy.deepcopy(dict(record))
        asset_provenance[group] = {name: record[name] for name in ("asset_id", "asset_version", "source")}
    asset_provenance["pdu"]["covered_wiring"] = _text(groups["pdu"]["covered_wiring"],
                                                      "asset_record.pdu.covered_wiring", error)

    overrides = _mapping(_get(scene, "overrides", "scene_record", error), "scene_record.overrides", error)
    _only_keys(overrides, _ASSET_GROUPS + ("source",), "scene_record.overrides", error)
    applied: list[dict[str, Any]] = []
    override_fields = {group: overrides.get(group, {}) for group in _ASSET_GROUPS}
    if any(override_fields.values()):
        source = _text(_get(overrides, "source", "scene_record.overrides", error), "scene_record.overrides.source",
                       error)
        for group in _ASSET_GROUPS:
            changes = _mapping(override_fields[group], f"scene_record.overrides.{group}", error)
            for name, new in changes.items():
                if name not in _ALLOWED_OVERRIDES[group]:
                    raise error(
                        f"scene_record.overrides.{group}.{name} is not an allowed instance override; allowed fields "
                        f"are {list(_ALLOWED_OVERRIDES[group])}"
                    )
                applied.append({"target": group, "field": name, "old": _plain(groups[group][name]),
                                "new": _plain(new), "source": source})
                groups[group][name] = copy.deepcopy(new)

    solar = SolarParameters(**{name: groups["solar"][name] for name in _SOLAR_FIELDS})
    battery = _battery_from_record(groups["battery"])
    eta_D = groups["pdu"]["eta_D"]

    links = _mapping(_get(scene, "links", "scene_record", error), "scene_record.links", error)
    numerics_record = _mapping(_get(scene, "numerics", "scene_record", error), "scene_record.numerics", error)
    _only_keys(numerics_record, _NUMERICS_FIELDS, "scene_record.numerics", error)
    for name in _NUMERICS_FIELDS:
        _get(numerics_record, name, "scene_record.numerics", error)
    numerics = PowerNumerics(**{name: numerics_record[name] for name in _NUMERICS_FIELDS})

    initial = _mapping(_get(scene, "initial_state", "scene_record", error), "scene_record.initial_state", error)
    _only_keys(initial, _INITIAL_FIELDS, "scene_record.initial_state", error)
    for name in _INITIAL_FIELDS:
        _get(initial, name, "scene_record.initial_state", error)
    initial_checks = _check_initial_state(initial, battery, numerics)

    provenance = {
        "instance_id": instance_id,
        "data_status": asset.get("data_status", "not stated"),
        "assets": asset_provenance,
        "overrides_applied": applied,
        "derived": {
            "Q_n_C": battery.Q_n_C,
            "Q_p_C": battery.Q_p_C,
            "reference_inventory_mol": battery.reference_inventory_mol,
        },
        "initial_state": _plain(dict(initial)),
        "initial_checks": initial_checks,
        "units": {"power": "W", "current": "A", "voltage": "V", "temperature": "K", "time": "s", "charge": "C",
                  "length": "m"},
        "sign_convention": "cell current and battery port power positive on discharge; Q_B_W keeps its sign",
        "model": "sdtwin_sim.power_stand_in: P1 to P11 of the Power design report, not the production Power module",
    }
    return PowerParameters(solar=solar, battery=battery, eta_D=eta_D, links=links, numerics=numerics,
                           provenance=provenance)


def _battery_from_record(record: Mapping[str, Any]) -> BatteryParameters:
    error = PowerConfigurationError
    electrodes_record = _mapping(record["electrodes"], "asset_record.battery.electrodes", error)
    if set(electrodes_record) != set(ELECTRODE_IDS):
        raise error(f"asset_record.battery.electrodes must have exactly the keys 'n' and 'p', "
                    f"got {sorted(electrodes_record)}")
    electrodes = {}
    for key in ELECTRODE_IDS:
        where = f"asset_record.battery.electrodes[{key}]"
        item = _mapping(electrodes_record[key], where, error)
        _only_keys(item, _ELECTRODE_FIELDS + ("source", "notes"), where, error)
        for name in _ELECTRODE_FIELDS:
            _get(item, name, where, error)
        electrodes[key] = ElectrodeParameters(electrode_id=key, **{name: item[name] for name in _ELECTRODE_FIELDS})
    limits_record = _mapping(record["limits"], "asset_record.battery.limits", error)
    _only_keys(limits_record, _LIMIT_FIELDS, "asset_record.battery.limits", error)
    for name in _LIMIT_FIELDS:
        _get(limits_record, name, "asset_record.battery.limits", error)
    limits = BatteryLimits(**{name: limits_record[name] for name in _LIMIT_FIELDS})
    return BatteryParameters(
        N_s=record["N_s"],
        N_p=record["N_p"],
        R_ohm_ohm=record["R_ohm_ohm"],
        T_ref_K=record["T_ref_K"],
        electrodes=electrodes,
        x_n_0=record["x_n_0"],
        x_n_100=record["x_n_100"],
        x_p_100=record["x_p_100"],
        limits=limits,
        parameter_level=record["parameter_level"],
    )


def _check_initial_state(
    initial: Mapping[str, Any], battery: BatteryParameters, numerics: PowerNumerics
) -> dict[str, float]:
    error = PowerConfigurationError
    where = "scene_record.initial_state"
    _finite(initial["time_s"], f"{where}.time_s", error)
    x_n = _finite(initial["x_n"], f"{where}.x_n", error)
    x_p = _finite(initial["x_p"], f"{where}.x_p", error)
    T = _positive(initial["T_B_K"], f"{where}.T_B_K", error)
    connected = _flag(initial["load_connected"], f"{where}.load_connected", error)
    latched = _flag(initial["trip_latched"], f"{where}.trip_latched", error)
    if connected and latched:
        raise error(f"{where}: load_connected and trip_latched cannot both be true")
    limits = battery.limits
    if not _within(x_n, limits.x_n_range):
        raise error(f"{where}.x_n={x_n!r} lies outside battery.limits.x_n_range {limits.x_n_range}")
    if not _within(x_p, limits.x_p_range):
        raise error(f"{where}.x_p={x_p!r} lies outside battery.limits.x_p_range {limits.x_p_range}")
    if not _within(T, limits.T_range_K):
        raise error(f"{where}.T_B_K={T!r} lies outside battery.limits.T_range_K {limits.T_range_K}")
    reference = battery.reference_inventory_mol
    inventory = battery.lithium_inventory_mol(x_n, x_p)
    relative = abs(inventory - reference) / reference
    if relative > numerics.inventory_rtol:
        raise error(
            f"{where}: lithium inventory of x_n={x_n!r}, x_p={x_p!r} is {inventory!r} mol, the SOC 100 point of the "
            f"parameter set holds {reference!r} mol (relative difference {relative:.3e} > numerics.inventory_rtol)"
        )
    try:
        response = _cell_response(0.0, x_n, x_p, T, battery)
    except PowerInputError as exc:
        raise error(f"{where}: zero-current response cannot be evaluated: {exc}") from None
    if response.constraint_margins["voltage_V"] < 0.0:
        raise error(
            f"{where}: zero-current cell voltage {response.v_cell_V!r} V lies outside "
            f"[{limits.v_min_V!r}, {limits.v_max_V!r}] V"
        )
    return {
        "zero_current_voltage_V": response.v_cell_V,
        "SOC": battery.soc(x_n),
        "inventory_relative_difference": relative,
    }


def power_state_from_scene(scene_record: Mapping[str, Any], run_id: str) -> PowerState:
    """Initial :class:`PowerState` from a scene's ``initial_state`` (empty ``handled_command_ids``, design 9.4)."""

    scene = _mapping(scene_record, "scene_record", PowerConfigurationError)
    initial = _mapping(_get(scene, "initial_state", "scene_record", PowerConfigurationError),
                       "scene_record.initial_state", PowerConfigurationError)
    return PowerState(
        run_id=run_id,
        instance_id=scene["instance_id"],
        time_s=initial["time_s"],
        x_n=initial["x_n"],
        x_p=initial["x_p"],
        load_connected=initial["load_connected"],
        trip_latched=initial["trip_latched"],
        handled_command_ids=(),
    )


# ----------------------------------------------------------------------------------------------------------------------
# solar array (P2, design 5.4)
# ----------------------------------------------------------------------------------------------------------------------


def solar_power(environment: PowerEnvironment, parameters: PowerParameters) -> SolarPowerResult:
    """P2: ``G_S = G max(0, cos theta)`` and ``P_pv_max = eta_pv A G_S``; ``G`` already includes the eclipse.

    The body-frame normal is rotated to GCRS by the body-to-GCRS quaternion (SciPy xyzw) and dotted with the unit
    spacecraft-to-Sun direction. Only round-off beyond [-1, 1] is corrected. Raises :class:`PowerInputError` for a
    non-GCRS frame or a zero Sun direction.
    """

    if not isinstance(environment, PowerEnvironment):
        raise TypeError(f"environment must be PowerEnvironment, got {type(environment).__name__}")
    if not isinstance(parameters, PowerParameters):
        raise TypeError(f"parameters must be PowerParameters, got {type(parameters).__name__}")
    if environment.frame != "GCRS":
        raise PowerInputError(
            f"PowerEnvironment.frame must be 'GCRS', got {environment.frame!r}; relabelling is not a frame transformation"
        )
    direction = environment.sun_position_m - environment.position_m
    distance = float(np.linalg.norm(direction))
    if distance == 0.0:
        raise PowerInputError("PowerEnvironment: sun_position_m equals position_m, the Sun direction is undefined")
    quaternion = environment.quaternion_xyzw / np.linalg.norm(environment.quaternion_xyzw)
    normal_gcrs = Rotation.from_quat(quaternion).apply(np.array(parameters.solar.normal_body, copy=True))
    cos_incidence = float(np.clip(np.dot(normal_gcrs, direction / distance), -1.0, 1.0))
    G_S = environment.G_W_m2 * max(0.0, cos_incidence)
    return SolarPowerResult(
        cos_incidence=cos_incidence,
        G_S_W_m2=G_S,
        P_pv_max_W=parameters.solar.efficiency * parameters.solar.area_m2 * G_S,
    )


# ----------------------------------------------------------------------------------------------------------------------
# battery (P4 to P8, P10, design 5.3)
# ----------------------------------------------------------------------------------------------------------------------


def _arrhenius(activation_J_mol: float, T: float, T_ref: float) -> float:
    return math.exp(activation_J_mol / GAS_CONSTANT_J_MOLK * (1.0 / T_ref - 1.0 / T))


def _surface_slopes(T: float, battery: BatteryParameters) -> tuple[float, float, float, float]:
    """P10 diffusivities and the P6 slopes ``a_k = R_k^2 / (15 D_k Q_k)`` (surface shift per ampere)."""

    negative = battery.electrodes["n"]
    positive = battery.electrodes["p"]
    D_n = negative.D_ref_m2_s * _arrhenius(negative.E_D_J_mol, T, battery.T_ref_K)
    D_p = positive.D_ref_m2_s * _arrhenius(positive.E_D_J_mol, T, battery.T_ref_K)
    a_n = negative.radius_m ** 2 / (15.0 * D_n * battery.Q_n_C)
    a_p = positive.radius_m ** 2 / (15.0 * D_p * battery.Q_p_C)
    return D_n, D_p, a_n, a_p


def _band(value: float, bounds: tuple[float, float]) -> float:
    return min(value - bounds[0], bounds[1] - value)


def _check_temperature(T: float, battery: BatteryParameters, where: str) -> None:
    if not _within(T, battery.limits.T_range_K):
        raise PowerInputError(f"{where}={T!r} K lies outside battery.limits.T_range_K {battery.limits.T_range_K}")


def _cell_response(i: float, x_n: float, x_p: float, T: float, battery: BatteryParameters) -> BatteryResponse:
    CALL_STATS.battery_evaluations += 1
    negative = battery.electrodes["n"]
    positive = battery.electrodes["p"]
    limits = battery.limits
    _, _, a_n, a_p = _surface_slopes(T, battery)
    # P6 surface fractions and the quadratic-profile centre x_c = (5 x - 3 x_s) / 2
    x_n_s = x_n - a_n * i
    x_p_s = x_p + a_p * i
    x_n_c = 0.5 * (5.0 * x_n - 3.0 * x_n_s)
    x_p_c = 0.5 * (5.0 * x_p - 3.0 * x_p_s)
    for name, value in (("negative", x_n_s), ("positive", x_p_s)):
        if not 0.0 < value < 1.0:
            raise PowerInputError(
                f"battery_response: {name} surface lithium fraction {value!r} at i={i!r} A lies outside (0, 1); "
                "it cannot enter the exchange-current square root and is not clipped"
            )
    # P10 exchange currents and open-circuit potentials at the surface fractions
    I0_n = 2.0 * negative.I0_ref_A * math.sqrt(x_n_s * (1.0 - x_n_s)) * _arrhenius(negative.E_I_J_mol, T,
                                                                                    battery.T_ref_K)
    I0_p = 2.0 * positive.I0_ref_A * math.sqrt(x_p_s * (1.0 - x_p_s)) * _arrhenius(positive.E_I_J_mol, T,
                                                                                    battery.T_ref_K)
    dT = T - battery.T_ref_K
    dUdT_n = _horner(negative._d, x_n_s)
    dUdT_p = _horner(positive._d, x_p_s)
    U_n = _horner(negative._b, x_n_s) + dT * dUdT_n
    U_p = _horner(positive._b, x_p_s) + dT * dUdT_p
    beta = dUdT_p - dUdT_n
    # P7 terminal voltage with symmetric Butler-Volmer reaction terms
    thermal_voltage = 2.0 * GAS_CONSTANT_J_MOLK * T / FARADAY_C_MOL
    dv_n = thermal_voltage * math.asinh(i / (2.0 * I0_n))
    dv_p = thermal_voltage * math.asinh(i / (2.0 * I0_p))
    v = U_p - U_n - dv_p - dv_n - i * battery.R_ohm_ohm
    # P5 lithium fractions
    dx_n_dt = -i / battery.Q_n_C + 0.0  # + 0.0 turns -0.0 at zero current into 0.0
    dx_p_dt = i / battery.Q_p_C + 0.0
    # P8 heat: reaction, ohmic and reversible (signed, never forced to zero)
    q_reversible = -i * T * beta
    q_cell = i * (dv_n + dv_p) + i * i * battery.R_ohm_ohm + q_reversible
    cells = battery.N_s * battery.N_p
    margins = {
        "current_A": min(i - limits.i_min_A, limits.i_max_A - i),
        "voltage_V": _band(v, (limits.v_min_V, limits.v_max_V)),
        "x_n_mean": _band(x_n, limits.x_n_range),
        "x_p_mean": _band(x_p, limits.x_p_range),
        "x_n_surface": _band(x_n_s, limits.x_n_range),
        "x_p_surface": _band(x_p_s, limits.x_p_range),
        "x_n_center": _band(x_n_c, limits.x_n_range),
        "x_p_center": _band(x_p_c, limits.x_p_range),
    }
    margins["x_mean"] = min(margins["x_n_mean"], margins["x_p_mean"])
    margins["x_surface"] = min(margins["x_n_surface"], margins["x_p_surface"])
    margins["x_center"] = min(margins["x_n_center"], margins["x_p_center"])
    # P4 single cell to pack, applied once
    return BatteryResponse(
        v_cell_V=v,
        I_B_A=battery.N_p * i,
        V_B_V=battery.N_s * v,
        P_B_W=cells * i * v,
        Q_B_W=cells * q_cell,
        dx_n_dt=dx_n_dt,
        dx_p_dt=dx_p_dt,
        constraint_margins=margins,
        i_A=i,
        T_B_K=T,
        x_n_surface=x_n_s,
        x_p_surface=x_p_s,
        x_n_center=x_n_c,
        x_p_center=x_p_c,
        U_n_V=U_n,
        U_p_V=U_p,
        dv_n_V=dv_n,
        dv_p_V=dv_p,
        beta_V_K=beta,
        q_cell_W=q_cell,
        q_reversible_cell_W=q_reversible,
    )


def battery_response(i_A: float, state: PowerState, T_B_K: float, parameters: PowerParameters) -> BatteryResponse:
    """Battery response to a trial cell current ``i_A`` (positive on discharge), design 5.3.

    Evaluates P10, P6, P7, P5, P8 and P4 in that order at the state's lithium fractions and the Thermal battery
    temperature. Pure: it integrates nothing, latches nothing and leaves the inputs unchanged. Raises
    :class:`PowerInputError` when the temperature lies outside ``battery.limits.T_range_K`` or a surface fraction
    leaves (0, 1); material-range excursions are reported through negative ``constraint_margins``.
    """

    if not isinstance(state, PowerState):
        raise TypeError(f"state must be PowerState, got {type(state).__name__}")
    if not isinstance(parameters, PowerParameters):
        raise TypeError(f"parameters must be PowerParameters, got {type(parameters).__name__}")
    i = _finite(i_A, "battery_response.i_A", PowerInputError)
    T = _positive(T_B_K, "battery_response.T_B_K", PowerInputError)
    _check_temperature(T, parameters.battery, "battery_response.T_B_K")
    return _cell_response(i, state.x_n, state.x_p, T, parameters.battery)


# ----------------------------------------------------------------------------------------------------------------------
# current solve (P11) and allocation (P1, P3, design 4.5 and 5.5)
# ----------------------------------------------------------------------------------------------------------------------


class _NumericalFailure(Exception):
    """Bracket or root-finding failure; reported as valid=False, never as a supply shortfall."""


@dataclass
class _Outcome:
    kind: str  # "zero", "root", "curtailed" or "shortfall"
    response: BatteryResponse | None
    info: dict[str, Any]


def _linear_limit(direction: float, x_n: float, x_p: float, T: float, battery: BatteryParameters) -> tuple[float, str]:
    """Distance from zero current to the first current, surface or centre bound along ``direction`` (+1 or -1).

    P6 and the centre relation are linear in the current at fixed temperature, so these bounds are exact.
    """

    limits = battery.limits
    candidates = [(limits.i_max_A if direction > 0 else -limits.i_min_A, "current")]
    _, _, a_n, a_p = _surface_slopes(T, battery)
    lines = (
        ("x_n_surface", x_n, -a_n, limits.x_n_range),
        ("x_p_surface", x_p, a_p, limits.x_p_range),
        ("x_n_center", x_n, 1.5 * a_n, limits.x_n_range),
        ("x_p_center", x_p, -1.5 * a_p, limits.x_p_range),
    )
    for name, start, slope, (low, high) in lines:
        rate = direction * slope
        if rate > 0.0:
            candidates.append((max(0.0, (high - start) / rate), name))
        elif rate < 0.0:
            candidates.append((max(0.0, (start - low) / -rate), name))
    distance, name = min(candidates, key=lambda item: item[0])
    return distance * (1.0 - _INTERIOR_SHRINK), name


def _evaluator(state: PowerState, T: float, parameters: PowerParameters) -> Callable[[float], BatteryResponse]:
    def evaluate(i: float) -> BatteryResponse:
        try:
            return battery_response(i, state, T, parameters)
        except PowerInputError as exc:
            raise _NumericalFailure(f"battery evaluation failed inside the allowed interval: {exc}") from None

    return evaluate


def _brent(function: Callable[[float], float], a: float, b: float, xtol: float, what: str) -> float:
    low, high = (a, b) if a <= b else (b, a)
    try:
        root, report = brentq(function, low, high, xtol=xtol, maxiter=200, full_output=True, disp=False)
    except (ValueError, RuntimeError) as exc:
        raise _NumericalFailure(f"{what}: Brent root finding failed on [{low!r}, {high!r}] A: {exc}") from None
    if not report.converged:
        raise _NumericalFailure(f"{what}: Brent root finding did not converge on [{low!r}, {high!r}] A "
                                f"({report.flag})")
    return float(root)


def _nudge(
    evaluate: Callable[[float], BatteryResponse],
    x: float,
    toward: float,
    xtol: float,
    accept: Callable[[BatteryResponse], bool],
) -> tuple[float, BatteryResponse]:
    """Move ``x`` toward ``toward`` (whose response is acceptable) until the response is acceptable."""

    response = evaluate(x)
    if accept(response):
        return x, response
    step = math.copysign(max(xtol, 4.0 * _EPS * abs(x)), toward - x)
    for _ in range(200):
        if abs(toward - x) <= abs(step):
            break
        x += step
        response = evaluate(x)
        if accept(response):
            return x, response
        step *= 2.0
    return toward, evaluate(toward)


def _search(target_W: float, state: PowerState, T: float, parameters: PowerParameters) -> _Outcome:
    """Solve P11 ``N_s N_p i v(i) = target`` from zero current toward discharge (target > 0) or charge (target < 0).

    The allowed interval runs from zero current to the first current, surface, centre or voltage bound. The first
    root inside it is bracketed on a scan and refined with Brent's method. Without a root, the extreme port power over
    the whole allowed interval decides: a discharge that cannot reach the target is a confirmed shortfall; a charge
    that cannot absorb the surplus uses the allowed charging current (curtailment).
    """

    numerics = parameters.numerics
    evaluate = _evaluator(state, T, parameters)
    response0 = evaluate(0.0)
    if target_W == 0.0:
        return _Outcome("zero", response0, {"i_A": 0.0})
    direction = 1.0 if target_W > 0.0 else -1.0

    def met(response: BatteryResponse) -> bool:
        residual = response.P_B_W - target_W
        return residual >= 0.0 if direction > 0 else residual <= 0.0

    linear_end, end_constraint = _linear_limit(direction, state.x_n, state.x_p, T, parameters.battery)
    points: list[tuple[float, BatteryResponse]] = [(0.0, response0)]
    bracket: tuple[tuple[float, BatteryResponse], tuple[float, BatteryResponse]] | None = None
    if linear_end > 0.0:
        count = numerics.current_scan_points
        for index in range(1, count):
            current = direction * linear_end * index / (count - 1)
            response = evaluate(current)
            if response.constraint_margins["voltage_V"] < 0.0:
                previous = points[-1][0]
                limit = _brent(lambda value: evaluate(value).constraint_margins["voltage_V"], previous, current,
                               numerics.current_xtol_A, "voltage bound")
                limit, response = _nudge(evaluate, limit, previous, numerics.current_xtol_A,
                                         lambda item: item.constraint_margins["voltage_V"] >= 0.0)
                points.append((limit, response))
                end_constraint = "voltage"
                if met(response):
                    bracket = (points[-2], points[-1])
                break
            points.append((current, response))
            if met(response):
                bracket = (points[-2], points[-1])
                break
    allowed_end = points[-1][0] if bracket is None else None
    info: dict[str, Any] = {"direction": "discharge" if direction > 0 else "charge", "end_constraint": end_constraint}

    if bracket is None:
        info["allowed_end_A"] = allowed_end
        best_i, best = _extreme(points, direction, evaluate, numerics.current_xtol_A)
        info["extreme_i_A"] = best_i
        info["extreme_P_B_W"] = best.P_B_W
        if met(best):
            earlier = [point for point in points if abs(point[0]) < abs(best_i)]
            bracket = (earlier[-1], (best_i, best))
        elif direction > 0:
            if target_W - best.P_B_W <= numerics.power_residual_tol_W:
                info["i_A"] = best_i
                return _Outcome("root", best, info)
            return _Outcome("shortfall", None, info)
        else:
            end_i, end_response = points[-1]
            info["i_A"] = end_i
            return _Outcome("curtailed", end_response, info)

    (a, _), (b, response_b) = bracket
    if response_b.P_B_W == target_W:
        root, response = b, response_b
    else:
        root = _brent(lambda value: evaluate(value).P_B_W - target_W, a, b, numerics.current_xtol_A,
                      "P11 current")
        response = evaluate(root)
        if direction < 0 and response.P_B_W < target_W:
            # keep P_B >= target on charge so the actual solar output never exceeds P_pv_max
            root, response = _nudge(evaluate, root, a, numerics.current_xtol_A,
                                    lambda item: item.P_B_W >= target_W)
    residual = response.P_B_W - target_W
    if abs(residual) > numerics.power_residual_tol_W:
        raise _NumericalFailure(f"P11 power residual {residual!r} W exceeds numerics.power_residual_tol_W at "
                                f"i={root!r} A")
    info["i_A"] = root
    info["P11_residual_W"] = residual
    return _Outcome("root", response, info)


def _extreme(
    points: list[tuple[float, BatteryResponse]],
    direction: float,
    evaluate: Callable[[float], BatteryResponse],
    xtol: float,
) -> tuple[float, BatteryResponse]:
    """Largest discharge power or most negative charge power over the scanned allowed interval, refined locally."""

    def score(response: BatteryResponse) -> float:
        return direction * response.P_B_W

    index = max(range(len(points)), key=lambda k: score(points[k][1]))
    best_i, best = points[index]
    low = points[max(index - 1, 0)][0]
    high = points[min(index + 1, len(points) - 1)][0]
    if low == high:
        return best_i, best
    bounds = (min(low, high), max(low, high))
    try:
        refined = minimize_scalar(lambda value: -score(evaluate(value)), bounds=bounds, method="bounded",
                                  options={"xatol": xtol})
    except (ValueError, RuntimeError) as exc:
        raise _NumericalFailure(f"port power extreme search failed on {bounds} A: {exc}") from None
    if refined.success:
        candidate = evaluate(float(refined.x))
        if score(candidate) > score(best):
            return float(refined.x), candidate
    return best_i, best


def _identity_check(inputs: PowerInputs, state: PowerState, parameters: PowerParameters) -> None:
    if inputs.run_id != state.run_id:
        raise PowerInputError(f"PowerInputs.run_id={inputs.run_id!r} differs from PowerState.run_id={state.run_id!r}")
    if inputs.instance_id != state.instance_id:
        raise PowerInputError(
            f"PowerInputs.instance_id={inputs.instance_id!r} differs from PowerState.instance_id={state.instance_id!r}"
        )
    if inputs.instance_id != parameters.instance_id:
        raise PowerInputError(
            f"PowerInputs.instance_id={inputs.instance_id!r} differs from the parameter instance "
            f"{parameters.instance_id!r}"
        )
    if inputs.time_s != state.time_s:
        raise PowerInputError(f"PowerInputs.time_s={inputs.time_s!r} differs from PowerState.time_s={state.time_s!r}")


def solve_power_allocation(inputs: PowerInputs, state: PowerState, parameters: PowerParameters) -> PowerResult:
    """Pure same-instant Power evaluation: P2, the P11 current, controller rules, P3 and P1 (design 5.5).

    A connected load draws ``P_need = P_request / eta_D``; a disconnected load draws nothing while the array may still
    charge the battery. Surplus solar that the battery cannot absorb is curtailed (``P_pv < P_pv_max``). A discharge
    that cannot meet the need anywhere in the allowed current interval returns ``event_required=True`` with reason
    ``supply_shortfall``; a trial state already beyond a mean-fraction or zero-current voltage bound returns
    ``device_boundary``. Input errors and numerical failures return ``valid=False``. The protection state is never
    changed here; ``can_supply_request`` reports whether the current request could be supplied.
    """

    CALL_STATS.solve_calls += 1
    if not isinstance(inputs, PowerInputs):
        raise TypeError(f"inputs must be PowerInputs, got {type(inputs).__name__}")
    if not isinstance(state, PowerState):
        raise TypeError(f"state must be PowerState, got {type(state).__name__}")
    if not isinstance(parameters, PowerParameters):
        raise TypeError(f"parameters must be PowerParameters, got {type(parameters).__name__}")

    battery = parameters.battery
    T = inputs.T_B_K
    diagnostics: dict[str, Any] = {"load_connected": state.load_connected, "trip_latched": state.trip_latched,
                                   "P_request_W": inputs.P_request_W, "T_B_K": T}

    def empty(code: str, detail: str, *, valid: bool, solar: SolarPowerResult | None) -> PowerResult:
        diagnostics["reason_code"] = code
        return PowerResult(
            run_id=inputs.run_id, instance_id=inputs.instance_id, time_s=inputs.time_s,
            P_pv_W=None, P_load_W=None, Q_B_W=None, Q_D_W=None, dx_n_dt=None, dx_p_dt=None, battery=None,
            valid=valid, event_required=valid, can_supply_request=False, reason=f"{code}: {detail}",
            solar=solar, P_bus_W=None, diagnostics=diagnostics,
        )

    try:
        _identity_check(inputs, state, parameters)
        solar = solar_power(inputs.environment, parameters)
    except PowerInputError as exc:
        return empty("invalid_input", str(exc), valid=False, solar=None)
    try:
        _check_temperature(T, battery, "PowerInputs.T_B_K")
    except PowerInputError as exc:
        return empty("temperature_out_of_range", str(exc), valid=False, solar=solar)

    P_pv_max = solar.P_pv_max_W
    eta = parameters.eta_D
    P_need_request = inputs.P_request_W / eta
    diagnostics.update({"P_pv_max_W": P_pv_max, "P_need_request_W": P_need_request})

    # a trial state already beyond a mean-fraction or zero-current voltage bound crossed a device boundary
    limits = battery.limits
    for name, value, bounds in (("x_n", state.x_n, limits.x_n_range), ("x_p", state.x_p, limits.x_p_range)):
        if not _within(value, bounds):
            return empty("device_boundary", f"PowerState.{name}={value!r} lies outside the material range {bounds}",
                         valid=True, solar=solar)
    try:
        response0 = battery_response(0.0, state, T, parameters)
    except PowerInputError as exc:
        return empty("numerical_failure", str(exc), valid=False, solar=solar)
    diagnostics["zero_current_voltage_V"] = response0.v_cell_V
    if response0.constraint_margins["voltage_V"] < 0.0:
        return empty(
            "device_boundary",
            f"zero-current cell voltage {response0.v_cell_V!r} V lies outside [{limits.v_min_V!r}, {limits.v_max_V!r}] V",
            valid=True, solar=solar,
        )

    try:
        if state.load_connected:
            P_need = P_need_request
            target = P_need - P_pv_max
            outcome = _search(target, state, T, parameters)
            can_supply = outcome.kind != "shortfall"
        else:
            P_need = 0.0
            target = -P_pv_max
            outcome = _search(target, state, T, parameters)
            request_target = P_need_request - P_pv_max
            if request_target <= 0.0:
                can_supply = True
            else:
                can_supply = _search(request_target, state, T, parameters).kind != "shortfall"
    except _NumericalFailure as exc:
        return empty("numerical_failure", str(exc), valid=False, solar=solar)

    diagnostics.update({"P_need_W": P_need, "target_P_B_W": target, "search": outcome.info})
    if outcome.kind == "shortfall":
        return empty(
            "supply_shortfall",
            f"the largest battery port power in the allowed discharge interval is "
            f"{outcome.info['extreme_P_B_W']!r} W, below the required {target!r} W (interval end "
            f"{outcome.info['allowed_end_A']!r} A set by {outcome.info['end_constraint']})",
            valid=True, solar=solar,
        )

    response = outcome.response
    if target > 0.0:
        # discharge: the array delivers P_pv_max, the bus receives what the array and battery deliver
        P_pv = P_pv_max
        P_bus = P_pv + response.P_B_W
    elif target == 0.0:
        P_pv = P_pv_max
        P_bus = P_need
    else:
        # charge or curtailment: the bus receives P_need, P1 fixes the actual solar output
        P_bus = P_need
        P_pv = P_need - response.P_B_W
    P_load = eta * P_bus
    Q_D = (1.0 - eta) * P_bus
    curtailed = outcome.kind == "curtailed"
    diagnostics["curtailed_W"] = P_pv_max - P_pv if curtailed else 0.0
    if curtailed:
        code = "charge_limited"
        detail = (f": charging held at {response.i_A!r} A per cell by the {outcome.info['end_constraint']} bound, "
                  f"actual solar output {P_pv!r} W of {P_pv_max!r} W available")
    else:
        code = "supplied" if state.load_connected else "load_disconnected"
        detail = ""
    diagnostics["reason_code"] = code
    return PowerResult(
        run_id=inputs.run_id, instance_id=inputs.instance_id, time_s=inputs.time_s,
        P_pv_W=P_pv, P_load_W=P_load, Q_B_W=response.Q_B_W, Q_D_W=Q_D,
        dx_n_dt=response.dx_n_dt, dx_p_dt=response.dx_p_dt, battery=response,
        valid=True, event_required=False, can_supply_request=can_supply, reason=code + detail,
        solar=solar, P_bus_W=P_bus, diagnostics=diagnostics,
    )


# ----------------------------------------------------------------------------------------------------------------------
# accepted events (design 4.5, 5.6)
# ----------------------------------------------------------------------------------------------------------------------


def apply_power_event(
    state: PowerState, event: PowerEvent | Sequence[PowerEvent], decision: PowerResult
) -> PowerState:
    """Update the protection state for accepted events at one instant (design 5.6); ``x_n`` and ``x_p`` are kept.

    ``stop`` disconnects the load; ``supply_loss`` disconnects and latches, and needs a decision that confirmed a
    supply shortfall over the allowed discharge interval (``valid=True``, ``event_required=True``, reason code
    ``supply_shortfall``). A ``device_boundary`` decision (a trial state past a fraction or zero-current voltage
    bound) says nothing about supply capacity and is rejected for ``supply_loss``; the caller re-allocates instead
    (design 4.5). ``start`` connects and clears the latch only when
    ``decision.can_supply_request`` is true, otherwise the load stays as it was. Several events at one instant may be
    passed together: a stop or supply loss then takes priority over a start, which is recorded as handled without
    connecting. Already handled command ids are not executed again. Trial events (``accepted=False``) and invalid
    decisions are rejected with :class:`PowerInputError`.
    """

    if not isinstance(state, PowerState):
        raise TypeError(f"state must be PowerState, got {type(state).__name__}")
    if not isinstance(decision, PowerResult):
        raise TypeError(f"decision must be PowerResult, got {type(decision).__name__}")
    events = (event,) if isinstance(event, PowerEvent) else tuple(event)
    if not events:
        raise PowerInputError("apply_power_event: no event given")
    for item in events:
        if not isinstance(item, PowerEvent):
            raise TypeError(f"event must be PowerEvent, got {type(item).__name__}")
    ids = [item.command_id for item in events]
    if len(set(ids)) != len(ids):
        raise PowerInputError(f"apply_power_event: duplicate command ids {ids}")
    for item in events:
        if not item.accepted:
            raise PowerInputError(f"PowerEvent {item.command_id!r}: accepted=False; a trial event cannot change the "
                                  "protection state")
    if not decision.valid:
        raise PowerInputError(f"decision: valid=False ({decision.reason}); an input or numerical error cannot drive a "
                              "protection event")
    for record, name in ((decision, "decision"),) + tuple((item, f"PowerEvent {item.command_id!r}") for item in events):
        for key in ("run_id", "instance_id", "time_s"):
            if getattr(record, key) != getattr(state, key):
                raise PowerInputError(
                    f"{name}.{key}={getattr(record, key)!r} differs from PowerState.{key}={getattr(state, key)!r}"
                )

    pending = [item for item in events if item.command_id not in state.handled_command_ids]
    for item in pending:
        if item.kind == "supply_loss" and not (
            decision.event_required and not decision.can_supply_request
            and decision.reason_code == "supply_shortfall"
        ):
            raise PowerInputError(
                f"PowerEvent {item.command_id!r}: supply_loss needs a decision that confirmed a supply shortfall over "
                f"the allowed discharge interval (event_required=True, reason code 'supply_shortfall'), got "
                f"event_required={decision.event_required!r}, reason {decision.reason!r}"
            )
    load_connected = state.load_connected
    trip_latched = state.trip_latched
    kinds = {item.kind for item in pending}
    if "stop" in kinds or "supply_loss" in kinds:
        load_connected = False
        if "supply_loss" in kinds:
            trip_latched = True
    elif "start" in kinds and decision.can_supply_request:
        load_connected = True
        trip_latched = False
    return PowerState(
        run_id=state.run_id,
        instance_id=state.instance_id,
        time_s=state.time_s,
        x_n=state.x_n,
        x_p=state.x_p,
        load_connected=load_connected,
        trip_latched=trip_latched,
        handled_command_ids=state.handled_command_ids + tuple(item.command_id for item in pending),
    )


# ----------------------------------------------------------------------------------------------------------------------
# illustrative example parameters
# ----------------------------------------------------------------------------------------------------------------------

_EXAMPLE_STATUS = (
    "illustrative test values for the SDTwin thermal tests; not a selected, qualified or measured device. The SPM "
    "geometry and kinetics are of the order of published NMC and graphite cells, the open-circuit potentials are "
    "simple monotone polynomials chosen for these tests, not fitted material curves."
)
_EXAMPLE_SOURCE = "illustrative test value, not a selected device (sdtwin_sim.power_stand_in.example_power_records)"


def example_power_records() -> tuple[dict[str, Any], dict[str, Any]]:
    """Illustrative ``(asset_record, scene_record)`` for :func:`load_power_parameters`; fresh copies on each call.

    The values are test values, not a selected device. The pack is 8 series by 6 parallel cells of about 2.8 Ah usable
    each (about 0.5 kWh) and the array gives about 0.73 kW at normal incidence, sized for a computing load of a few
    hundred watts. The scene starts at mid charge with the load connected.
    """

    negative = {
        "radius_m": 6.0e-6,
        "active_fraction": 0.75,
        "electrode_area_m2": 0.06,
        "thickness_m": 85.0e-6,
        "c_max_mol_m3": 31000.0,
        "D_ref_m2_s": 3.3e-14,
        "I0_ref_A": 2.5,
        "E_D_J_mol": 30300.0,
        "E_I_J_mol": 35000.0,
        "b_V": [0.65, -1.6, 2.0, -0.95],
        "d_V_K": [1.2e-4, -3.0e-4, 1.5e-4, 0.0],
        "source": _EXAMPLE_SOURCE,
    }
    positive = {
        "radius_m": 5.0e-6,
        "active_fraction": 0.665,
        "electrode_area_m2": 0.06,
        "thickness_m": 75.0e-6,
        "c_max_mol_m3": 63000.0,
        "D_ref_m2_s": 1.0e-14,
        "I0_ref_A": 3.0,
        "E_D_J_mol": 25000.0,
        "E_I_J_mol": 17500.0,
        "b_V": [4.6, -1.3, 0.9, -0.8],
        "d_V_K": [-0.6e-4, 0.4e-4, 0.0, 0.0],
        "source": _EXAMPLE_SOURCE,
    }
    x_n_100, x_p_100, x_n_initial = 0.90, 0.27, 0.60
    Q_n = _electrode_charge_C(negative["active_fraction"], negative["electrode_area_m2"], negative["thickness_m"],
                              negative["c_max_mol_m3"])
    Q_p = _electrode_charge_C(positive["active_fraction"], positive["electrode_area_m2"], positive["thickness_m"],
                              positive["c_max_mol_m3"])
    x_p_initial = x_p_100 + (x_n_100 - x_n_initial) * Q_n / Q_p  # same lithium inventory as the SOC 100 point
    asset_record = {
        "data_status": _EXAMPLE_STATUS,
        "solar": {
            "asset_id": "example.solar_array",
            "asset_version": "test-1",
            "source": _EXAMPLE_SOURCE,
            "area_m2": 1.8,
            "efficiency": 0.30,
            "normal_body": [0.0, 0.0, 1.0],
        },
        "battery": {
            "asset_id": "example.battery_pack",
            "asset_version": "test-1",
            "source": _EXAMPLE_SOURCE,
            "parameter_level": "cell",
            "N_s": 8,
            "N_p": 6,
            "R_ohm_ohm": 0.025,
            "T_ref_K": 298.15,
            "electrodes": {"n": negative, "p": positive},
            "x_n_0": 0.03,
            "x_n_100": x_n_100,
            "x_p_100": x_p_100,
            "limits": {
                "i_min_A": -3.0,
                "i_max_A": 6.0,
                "v_min_V": 3.0,
                "v_max_V": 4.2,
                "x_n_range": [0.01, 0.95],
                "x_p_range": [0.20, 0.95],
                "T_range_K": [253.15, 333.15],
            },
        },
        "pdu": {
            "asset_id": "example.pdu",
            "asset_version": "test-1",
            "source": _EXAMPLE_SOURCE,
            "eta_D": 0.95,
            "covered_wiring": "PDU01 conversion and the PDU01 to Compute01 harness; battery and array harness "
                              "resistance is not included (battery ohmic resistance is in R_ohm_ohm)",
        },
    }
    scene_record = {
        "instance_id": "Sat01",
        "asset_refs": {
            "solar": {"asset_id": "example.solar_array", "asset_version": "test-1"},
            "battery": {"asset_id": "example.battery_pack", "asset_version": "test-1"},
            "pdu": {"asset_id": "example.pdu", "asset_version": "test-1"},
        },
        "links": {"P_pv_W": "SolarArray01", "P_load_W": "Compute01", "Q_B_W": "Battery01", "Q_D_W": "PDU01"},
        "overrides": {},
        "initial_state": {
            "time_s": 0.0,
            "x_n": x_n_initial,
            "x_p": x_p_initial,
            "T_B_K": 293.15,
            "load_connected": True,
            "trip_latched": False,
        },
        "numerics": {
            "rtol": 1e-6,
            "atol_x": 1e-9,
            "atol_T_K": 1e-6,
            "current_xtol_A": 1e-12,
            "power_residual_tol_W": 1e-6,
            "event_time_tol_s": 1e-3,
            "max_step_s": 60.0,
            "environment_step_s": 10.0,
            "output_step_s": 60.0,
            "current_scan_points": 32,
            "inventory_rtol": 1e-9,
        },
    }
    return asset_record, scene_record


def example_power_parameters() -> PowerParameters:
    """:class:`PowerParameters` from :func:`example_power_records`; illustrative test values, not a selected device."""

    asset_record, scene_record = example_power_records()
    return load_power_parameters(asset_record, scene_record)
