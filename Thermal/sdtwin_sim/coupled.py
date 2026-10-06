"""Coupled procedure of thermal design chapters 7 and 8 and Power design chapters 7 and 8.

The coupled ordinary differential equation has one continuous state vector: the six node temperatures in NODE_ORDER
(K) and, when Power is enabled, the two lithium fractions ``x_n`` and ``x_p`` (dimensionless). A SciPy ``OdeSolver``
class (``RK45`` by default, ``Radau`` for disparate time scales) is stepped manually with ``rtol``, per-component
``atol`` (temperatures in K, lithium fractions dimensionless) and ``max_step``.

Every right-hand-side evaluation is a trial (thermal design 5.6, 6.3 and chapter 7; Power design 6.3 and chapter 7).
It builds a ThermalState for the trial temperatures, takes the synchronized ``orbit_input``, ``earth_flux`` and
``PowerEnvironment`` of that instant from an :class:`EnvironmentProvider`, prepares the surface environment, evaluates
Power with the trial lithium fractions and ``T_B_K`` equal to the trial temperature of B (a thermal-only run reads
``prescribed_ports(time_s)`` instead) and calls ``thermal_derivative``. Only states accepted by the solver are stored;
a rejected step leaves no record.

Integration is split at eclipse boundaries (located from Orbit's ``eclipse_fraction``), at load start and stop
commands, at declared input discontinuities and at located Power events, so no step spans a boundary and nothing is
averaged across one. A Power result with ``valid=False`` stops the run with a reported error: :class:`CoupledRunError`
carries the archive of every accepted state. ``event_required=True`` in a trial starts a bisection that locates the
boundary within ``event_time_tol_s``; the state there is accepted and Power decides again with it. A confirmed supply
shortfall (reason code ``supply_shortfall``) is the only boundary with a protection rule (Power design 4.5): the
``supply_loss`` event is applied with ``apply_power_event`` and the decision of that instant, Power is recomputed at the
same instant and integration continues. Any other boundary decision (for example ``device_boundary``, a state past a
fraction or zero-current voltage bound) has no protection rule and no valid operating state beyond it; the run stops
at the last accepted state inside the bound with a ``device_boundary`` record and no event is applied.

Charge limiting (Power reason ``charge_limited``) is a device boundary but not a protection event (Power design 4.6,
5.5 and chapter 7): after every accepted step the Power reason at the accepted end state is compared with the one at the
start; on a change the crossing is located on the step's dense output within ``event_time_tol_s``, the step is ended
there and the solver restarts from that instant. Start and end times of charge limiting are archived in
``limit_events`` next to the eclipse boundaries and the applied Power events. Every accepted state is checked against
the declared node temperature ranges; excursions are listed in ``range_warnings`` (thermal design 5.4). Outputs are
sampled on the accepted solution at ``output_step_s``, independent of the internal steps.

The procedure never calls Orbit's ``power_considering_thermal`` and writes temperatures only from the integrated
thermal state.
"""

from __future__ import annotations

import bisect
import itertools
import json
import math
import platform
import time
import warnings
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

import numpy as np
import scipy
from numpy.typing import ArrayLike, NDArray
from scipy.integrate import DOP853, RK23, RK45, Radau
from scipy.interpolate import CubicHermiteSpline, CubicSpline
from scipy.spatial.transform import Rotation, Slerp

from ntu_space_dynamics import eclipse_fraction as _orbit_eclipse_fraction
from ntu_space_dynamics import sun_intensity as _orbit_sun_intensity
from ntu_space_dynamics.time import ensure_utc, seconds_since
from thermal import ThermalInputs, ThermalParameters, ThermalRangeWarning, ThermalState, prepare_surface_environment, thermal_derivative
from thermal.types import EXPOSED_NODES, NODE_ORDER, PATH_ORDER

from . import power_stand_in
from .earth_flux import earth_flux_record

__all__ = [
    "ARCHIVE_FORMAT",
    "ECLIPSE_PHASES",
    "EVALUATION_CONTEXTS",
    "LITHIUM_ORDER",
    "PORT_ORDER",
    "SUPPORTED_METHODS",
    "CoupledArchive",
    "CoupledConfigurationError",
    "CoupledError",
    "CoupledRunError",
    "EarthFluxModel",
    "EclipseBoundary",
    "EnvironmentProvider",
    "EnvironmentProviderError",
    "EnvironmentSample",
    "LoadCommand",
    "PowerCoupling",
    "SolverSettings",
    "TrialRecord",
    "eclipse_entry_exit_times",
    "find_eclipse_boundaries",
    "run_coupled",
]

# Order of the four Power ports in archives (thermal design 5.1, Power design table 5).
PORT_ORDER: tuple[str, ...] = ("P_pv_W", "P_load_W", "Q_B_W", "Q_D_W")
# Order of the two Power state components that follow the six temperatures in the state vector.
LITHIUM_ORDER: tuple[str, ...] = ("x_n", "x_p")
# SciPy OdeSolver classes accepted; RK45 is the design baseline and Radau the implicit option of table 8.
SUPPORTED_METHODS: tuple[str, ...] = ("RK45", "Radau", "RK23", "DOP853")
# Illumination phases: full Sun (fraction 1), partial (0 < fraction < 1) and umbra (fraction 0).
ECLIPSE_PHASES: tuple[str, ...] = ("sunlit", "penumbra", "umbra")
# Contexts in which the coupled model is evaluated; the statistics count each separately.
EVALUATION_CONTEXTS: tuple[str, ...] = ("integration", "event_location", "boundary", "output", "energy_audit")
ARCHIVE_FORMAT = "sdtwin.coupled_archive/1"

_METHOD_CLASSES = {"RK45": RK45, "Radau": Radau, "RK23": RK23, "DOP853": DOP853}
_SETTINGS_FROM_NUMERICS = (
    "rtol",
    "atol_x",
    "atol_T_K",
    "max_step_s",
    "event_time_tol_s",
    "environment_step_s",
    "output_step_s",
)
_N_NODES = len(NODE_ORDER)
_B_INDEX = NODE_ORDER.index("B")
_RADAU_COLLOCATION_TIMES = 3
_CACHE_SIZE = 2048
_GAP_ULPS = 64
_MAX_UNCONFIRMED_SEARCHES = 1000
_QUATERNION_SAMPLE_TOLERANCE = 1e-6
_GAUSS_POINTS = 3
# Power reason code of a continuous charging curtailment (Power design 5.5); its start and end are located and archived.
_CHARGE_LIMITED = "charge_limited"
_SUPPLY_SHORTFALL = "supply_shortfall"
_T1_TERMS = ("Q_env_S_W", "Q_env_R_W", "P_pv_W", "P_load_W", "Q_B_W", "Q_D_W", "Q_emit_S_W", "Q_emit_R_W")
_T1_SIGNS = np.array([1.0, 1.0, -1.0, 1.0, 1.0, 1.0, -1.0, -1.0])
_NAN = float("nan")


# ----------------------------------------------------------------------------------------------------------------------
# errors and internal signals
# ----------------------------------------------------------------------------------------------------------------------


class CoupledError(ValueError):
    """Base class of the errors raised by the coupled procedure."""


class CoupledConfigurationError(CoupledError):
    """Invalid run configuration found before integration; the message names the record and the field."""


class EnvironmentProviderError(CoupledError):
    """Invalid orbit, attitude, Sun, irradiance or Earth-flux input of an :class:`EnvironmentProvider`."""


class CoupledRunError(CoupledError):
    """The run stopped with a reported error; ``archive`` holds every accepted state up to the stop."""

    def __init__(self, message: str, archive: CoupledArchive) -> None:
        super().__init__(message)
        self.archive = archive


class _EvaluationError(CoupledError):
    """A trial evaluation met an unusable value; the run stops and reports it."""


class _PowerSignal(Exception):
    """Internal: a trial Power result that cannot provide ports or derivatives."""

    def __init__(self, time_s: float, state: ArrayLike, result: Any, context: str) -> None:
        super().__init__(f"Power result at time_s={time_s!r}: {getattr(result, 'reason', '?')}")
        self.time_s = time_s
        self.state = np.array(state, dtype=float)
        self.result = result
        self.context = context
        # Last accepted (time_s, state) of the solver step that raised the signal; set by _CoupledRun._step.
        self.restart: tuple[float, NDArray[np.float64]] | None = None


class _PowerEventSignal(_PowerSignal):
    """``valid=True`` with ``event_required=True``: the boundary must be located and accepted first."""


class _PowerInvalidSignal(_PowerSignal):
    """``valid=False``: an input or numerical error that is reported and stops the run."""


class _StopRun(Exception):
    """Internal: the run stops with the error record ``record``."""

    def __init__(self, record: dict[str, Any]) -> None:
        super().__init__(record.get("message", "run stopped"))
        self.record = record


# ----------------------------------------------------------------------------------------------------------------------
# validation and conversion helpers
# ----------------------------------------------------------------------------------------------------------------------


def _number(value: Any, where: str, error: type[Exception] = CoupledConfigurationError) -> float:
    if isinstance(value, np.ndarray):
        if value.ndim != 0:
            raise error(f"{where} must be a finite number, got an array of shape {value.shape}")
        value = value.item()
    if isinstance(value, (bool, np.bool_)):
        raise error(f"{where} must be a finite number, got the boolean {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise error(f"{where} must be a finite number, got {value!r}") from None
    if not math.isfinite(number):
        raise error(f"{where} must be finite, got {number!r}")
    return number


def _positive(value: Any, where: str, error: type[Exception] = CoupledConfigurationError) -> float:
    number = _number(value, where, error)
    if number <= 0.0:
        raise error(f"{where} must be > 0, got {number!r}")
    return number


def _nonnegative(value: Any, where: str, error: type[Exception] = CoupledConfigurationError) -> float:
    number = _number(value, where, error)
    if number < 0.0:
        raise error(f"{where} must be >= 0, got {number!r}")
    return number


def _text(value: Any, where: str, error: type[Exception] = CoupledConfigurationError) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{where} must be a non-empty string, got {value!r}")
    return value


def _readonly(array: NDArray[Any]) -> NDArray[Any]:
    array.setflags(write=False)
    return array


def _vector(value: Any, length: int, where: str, error: type[Exception]) -> NDArray[np.float64]:
    """Read-only float copy of a finite vector of shape ``(length,)``."""

    try:
        array = np.array(value, dtype=float)
    except (TypeError, ValueError):
        raise error(f"{where} must be a numeric array of shape ({length},), got {value!r}") from None
    if array.shape != (length,):
        raise error(f"{where} must have shape ({length},), got shape {array.shape}")
    if not np.all(np.isfinite(array)):
        raise error(f"{where} must contain only finite values, got {array.tolist()!r}")
    return _readonly(array)


def _increasing_times(value: Any, where: str, error: type[Exception]) -> NDArray[np.float64]:
    try:
        times = np.array(value, dtype=float)
    except (TypeError, ValueError):
        raise error(f"{where} must be a one-dimensional numeric array of times in s") from None
    if times.ndim != 1 or times.size < 2:
        raise error(f"{where} must be a one-dimensional array with at least two times, got shape {times.shape}")
    if not np.all(np.isfinite(times)):
        raise error(f"{where} must contain only finite times")
    if np.any(np.diff(times) <= 0.0):
        raise error(f"{where} must be strictly increasing")
    return times


def _phase(fraction: float) -> str:
    """Illumination phase of a visible solar-disc fraction."""

    if fraction >= 1.0:
        return "sunlit"
    if fraction <= 0.0:
        return "umbra"
    return "penumbra"


def _next_float(value: float) -> float:
    return math.nextafter(value, math.inf)


def _previous_float(value: float) -> float:
    return math.nextafter(value, -math.inf)


def _gap_tolerance(value: float) -> float:
    """Intervals shorter than this are instants: no solver step is attempted across them."""

    return _GAP_ULPS * math.ulp(max(abs(value), 1.0))


def _callable_name(function: Any) -> str:
    name = getattr(function, "__qualname__", None) or getattr(function, "__name__", None)
    if name is None:
        return repr(function)
    module = getattr(function, "__module__", None)
    return f"{module}.{name}" if module else str(name)


def _optional_float(value: Any) -> float:
    if value is None or isinstance(value, (bool, np.bool_)):
        return _NAN
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _NAN
    return number


def _plain(value: Any) -> Any:
    """JSON-ready copy: mappings, lists, finite numbers (NaN and infinities become None), strings and booleans."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, ModuleType):
        return value.__name__
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value) if not item.name.startswith("_")}
    if callable(value):
        return _callable_name(value)
    return repr(value)


def _software() -> dict[str, str]:
    try:
        from importlib.metadata import version

        orbit = version("ntu-space-dynamics")
    except Exception:  # noqa: BLE001  (an unknown version is recorded, not fatal)
        orbit = "unknown"
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "ntu_space_dynamics": orbit,
        "coupled_module": __name__,
    }


# ----------------------------------------------------------------------------------------------------------------------
# settings, commands and the Power coupling
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SolverSettings:
    """Numerical settings of the coupled ODE (thermal design table 8; Power design table 7).

    ``method`` is a SciPy ``OdeSolver`` class name, ``"RK45"`` by default and ``"Radau"`` for disparate time scales.
    ``rtol`` is dimensionless, ``atol_T_K`` is the temperature absolute tolerance in K and ``atol_x`` the absolute
    tolerance of the lithium fractions (required when Power is enabled). ``max_step_s`` bounds every step,
    ``output_step_s`` is the output spacing on the accepted solution, ``environment_step_s`` the spacing at which the
    eclipse phase is scanned before bisection, ``event_time_tol_s`` the width within which a Power boundary is located
    and ``first_step_s`` the optional initial step of each solver started at a segment boundary. These are scene-level
    settings; apart from the method none has a default.
    """

    method: str = "RK45"
    rtol: float
    atol_T_K: float
    max_step_s: float
    output_step_s: float
    environment_step_s: float
    event_time_tol_s: float
    atol_x: float | None = None
    first_step_s: float | None = None

    def __post_init__(self) -> None:
        error = CoupledConfigurationError
        if not isinstance(self.method, str) or self.method not in SUPPORTED_METHODS:
            raise error(f"SolverSettings.method must be one of {SUPPORTED_METHODS}, got {self.method!r}")
        rtol = _positive(self.rtol, "SolverSettings.rtol", error)
        floor = 100.0 * float(np.finfo(float).eps)
        if rtol < floor:
            raise error(f"SolverSettings.rtol must be >= {floor!r} (SciPy would raise it silently), got {rtol!r}")
        object.__setattr__(self, "rtol", rtol)
        for name in ("atol_T_K", "max_step_s", "output_step_s", "environment_step_s", "event_time_tol_s"):
            object.__setattr__(self, name, _positive(getattr(self, name), f"SolverSettings.{name}", error))
        for name in ("atol_x", "first_step_s"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _positive(value, f"SolverSettings.{name}", error))

    @classmethod
    def from_power_numerics(
        cls, numerics: Any, *, method: str = "RK45", first_step_s: float | None = None
    ) -> SolverSettings:
        """Settings taken from Power ``parameters.numerics``, the shared numerical configuration of Power table 7."""

        missing = [name for name in _SETTINGS_FROM_NUMERICS if not hasattr(numerics, name)]
        if missing:
            raise CoupledConfigurationError(f"Power numerics {type(numerics).__name__} has no field(s) {missing}")
        values = {name: getattr(numerics, name) for name in _SETTINGS_FROM_NUMERICS}
        return cls(method=method, first_step_s=first_step_s, **values)

    def as_dict(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True)
class LoadCommand:
    """One-time ``start`` or ``stop`` command of the computing load at ``time_s`` (Power design 4.5, 5.6).

    ``supply_loss`` is not a command: the procedure generates it when Power confirms a physical boundary.
    """

    time_s: float
    kind: str
    command_id: str

    def __post_init__(self) -> None:
        error = CoupledConfigurationError
        command_id = _text(self.command_id, "LoadCommand.command_id", error)
        object.__setattr__(self, "time_s", _number(self.time_s, f"LoadCommand {command_id!r}.time_s", error))
        if self.kind not in ("start", "stop"):
            raise error(
                f"LoadCommand {command_id!r}.kind must be 'start' or 'stop', got {self.kind!r}; supply_loss is "
                "generated at a confirmed Power boundary, not commanded"
            )


@dataclass(frozen=True, kw_only=True)
class PowerCoupling:
    """Power side of a coupled run (Power design 5.5, 5.6, 6.3).

    ``parameters`` and ``initial_state`` are the Power ``PowerParameters`` and ``PowerState`` (run, instance and time
    of the state must match the run). ``request_W`` is the computing load request ``P_request_W``, a constant or a
    callable of ``time_s``; declare its discontinuities through ``run_coupled(boundaries_s=...)``. ``commands`` are the
    load start and stop commands. ``interface`` provides ``PowerInputs``, ``PowerState``, ``PowerEvent``,
    ``PowerEnvironment``, ``solve_power_allocation`` and ``apply_power_event`` (the stand-in by default); ``solve`` and
    ``apply_event`` replace the two functions, for example to inject a Power result in a test.
    """

    parameters: Any
    initial_state: Any
    request_W: float | Callable[[float], float]
    commands: Sequence[LoadCommand] = ()
    solve: Callable[..., Any] | None = None
    apply_event: Callable[..., Any] | None = None
    interface: Any = power_stand_in

    def __post_init__(self) -> None:
        error = CoupledConfigurationError
        required = ("PowerInputs", "PowerState", "PowerEvent", "PowerEnvironment", "solve_power_allocation",
                    "apply_power_event")
        missing = [name for name in required if not hasattr(self.interface, name)]
        if missing:
            raise error(f"PowerCoupling.interface {_callable_name(self.interface)} has no {missing}")
        if not callable(self.request_W):
            object.__setattr__(self, "request_W", _nonnegative(self.request_W, "PowerCoupling.request_W", error))
        commands = tuple(self.commands)
        for index, command in enumerate(commands):
            if not isinstance(command, LoadCommand):
                raise error(f"PowerCoupling.commands[{index}] must be a LoadCommand, got {type(command).__name__}")
        ids = [command.command_id for command in commands]
        repeated = sorted({item for item in ids if ids.count(item) > 1})
        if repeated:
            raise error(f"PowerCoupling.commands repeat command_id(s) {repeated}; each command has a unique id")
        object.__setattr__(self, "commands", commands)
        solve = self.interface.solve_power_allocation if self.solve is None else self.solve
        apply_event = self.interface.apply_power_event if self.apply_event is None else self.apply_event
        for name, function in (("solve", solve), ("apply_event", apply_event)):
            if not callable(function):
                raise error(f"PowerCoupling.{name} must be callable, got {function!r}")
        object.__setattr__(self, "solve", solve)
        object.__setattr__(self, "apply_event", apply_event)


# ----------------------------------------------------------------------------------------------------------------------
# environment provider
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class EarthFluxModel:
    """Earth albedo and infrared configuration of an :class:`EnvironmentProvider` (thermal design 5.3, 9.4).

    ``albedo`` (Bond albedo fraction), ``olr_W_m2`` (outgoing longwave radiation at the Earth's surface) and
    ``solar_constant_W_m2`` (solar irradiance used for the reflected light) are required; ``earth_radius_m`` and the
    quadrature ``resolution`` are passed to :func:`sdtwin_sim.earth_flux.earth_flux_record`. A teaching case that
    switches albedo and infrared off uses :meth:`disabled` with the recorded reason; a missing value is never taken as
    zero.
    """

    albedo: float | None = None
    olr_W_m2: float | None = None
    solar_constant_W_m2: float | None = None
    earth_radius_m: float = 6378137.0
    resolution: tuple[int, int] = (240, 360)
    disabled_reason: str | None = None

    def __post_init__(self) -> None:
        error = EnvironmentProviderError
        values = {"albedo": self.albedo, "olr_W_m2": self.olr_W_m2, "solar_constant_W_m2": self.solar_constant_W_m2}
        if self.disabled_reason is not None:
            _text(self.disabled_reason, "EarthFluxModel.disabled_reason", error)
            given = [name for name, value in values.items() if value is not None]
            if given:
                raise error(
                    f"EarthFluxModel gives {given} together with disabled_reason; a disabled Earth flux carries no "
                    "albedo or infrared values"
                )
        else:
            missing = [name for name, value in values.items() if value is None]
            if missing:
                raise error(
                    f"EarthFluxModel is missing {missing}; Earth albedo and infrared are environment data that must "
                    "be configured, or switched off explicitly with EarthFluxModel.disabled(reason) (design 5.3, 9.4)"
                )
            albedo = _number(self.albedo, "EarthFluxModel.albedo", error)
            if not 0.0 <= albedo <= 1.0:
                raise error(f"EarthFluxModel.albedo must lie in [0, 1], got {albedo!r}")
            object.__setattr__(self, "albedo", albedo)
            object.__setattr__(self, "olr_W_m2", _nonnegative(self.olr_W_m2, "EarthFluxModel.olr_W_m2", error))
            object.__setattr__(
                self,
                "solar_constant_W_m2",
                _nonnegative(self.solar_constant_W_m2, "EarthFluxModel.solar_constant_W_m2", error),
            )
        radius = _positive(self.earth_radius_m, "EarthFluxModel.earth_radius_m", error)
        object.__setattr__(self, "earth_radius_m", radius)
        try:
            pair = tuple(self.resolution)
        except TypeError:
            raise error(f"EarthFluxModel.resolution must be a pair of integers, got {self.resolution!r}") from None
        if len(pair) != 2 or any(isinstance(item, bool) or not isinstance(item, (int, np.integer)) for item in pair):
            raise error(f"EarthFluxModel.resolution must be a pair of integers, got {self.resolution!r}")
        if min(pair) < 4:
            raise error(f"EarthFluxModel.resolution entries must be >= 4, got {pair!r}")
        object.__setattr__(self, "resolution", (int(pair[0]), int(pair[1])))

    @classmethod
    def disabled(cls, reason: str) -> EarthFluxModel:
        """Zero albedo and infrared with the recorded teaching simplification ``reason`` (design 9.4)."""

        return cls(disabled_reason=reason)

    @property
    def enabled(self) -> bool:
        return self.disabled_reason is None

    def as_dict(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True)
class EnvironmentSample:
    """Synchronized environment of one instant (thermal design 5.3, 6.1; Power design 5.1).

    ``orbit_input`` and ``earth_flux`` are the mappings of ``prepare_surface_environment``, ``surface_environment`` is
    its result, ``power_environment`` the Power ``PowerEnvironment`` built from the same orbit and attitude result and
    ``illumination_fraction`` the visible solar-disc fraction that classifies the eclipse phase.
    """

    time_s: float
    orbit_input: Mapping[str, Any]
    earth_flux: Mapping[str, Any]
    surface_environment: Mapping[str, Any]
    power_environment: Any
    illumination_fraction: float

    @property
    def G_W_m2(self) -> float:
        return float(self.orbit_input["G_W_m2"])

    @property
    def phase(self) -> str:
        return _phase(self.illumination_fraction)


@dataclass(frozen=True)
class EclipseBoundary:
    """One change of illumination phase located to adjacent floating-point times.

    ``time_left_s`` is the last instant of ``phase_before`` and ``time_right_s`` the first instant of ``phase_after``;
    ``time_s`` is ``time_right_s``.
    """

    time_left_s: float
    time_right_s: float
    phase_before: str
    phase_after: str

    def __post_init__(self) -> None:
        error = CoupledConfigurationError
        for name in ("phase_before", "phase_after"):
            if getattr(self, name) not in ECLIPSE_PHASES:
                raise error(f"EclipseBoundary.{name} must be one of {ECLIPSE_PHASES}, got {getattr(self, name)!r}")
        if self.phase_before == self.phase_after:
            raise error(f"EclipseBoundary phases must differ, got {self.phase_before!r} twice")
        left = _number(self.time_left_s, "EclipseBoundary.time_left_s", error)
        right = _number(self.time_right_s, "EclipseBoundary.time_right_s", error)
        if not left < right:
            raise error(f"EclipseBoundary.time_left_s {left!r} must be below time_right_s {right!r}")
        object.__setattr__(self, "time_left_s", left)
        object.__setattr__(self, "time_right_s", right)

    @property
    def time_s(self) -> float:
        return self.time_right_s

    @property
    def kind(self) -> str:
        return f"{self.phase_before}_to_{self.phase_after}"

    @property
    def is_eclipse_entry(self) -> bool:
        return self.phase_before == "sunlit"

    @property
    def is_eclipse_exit(self) -> bool:
        return self.phase_after == "sunlit"

    def as_dict(self) -> dict[str, Any]:
        return {
            "time_s": self.time_s,
            "time_left_s": self.time_left_s,
            "time_right_s": self.time_right_s,
            "phase_before": self.phase_before,
            "phase_after": self.phase_after,
            "kind": self.kind,
        }


class EnvironmentProvider:
    """Synchronized ``orbit_input``, ``earth_flux`` and ``PowerEnvironment`` of a run at any ``time_s``.

    Build it with :meth:`from_orbit` (Orbit ephemeris, attitude quaternions and Sun positions; ``G`` from Orbit's
    ``sun_intensity(include_eclipse=True)`` and eclipse phases from Orbit's ``eclipse_fraction``) or with
    :meth:`from_callables` (analytic ``position(t)``, ``sun_position(t)``, ``quaternion(t)`` and ``G(t)``). Vectors
    are GCRS in m, the quaternion is the active body-to-GCRS rotation in SciPy xyzw order and ``G`` already includes
    the eclipse; it is passed through unchanged. Samples are cached by time, so trials and prescribed ports at one
    instant share one environment.
    """

    def __init__(
        self,
        *,
        run_id: str,
        epoch: datetime,
        parameters: ThermalParameters,
        position: Callable[[float], ArrayLike],
        sun_position: Callable[[float], ArrayLike],
        quaternion: Callable[[float], ArrayLike],
        irradiance: Callable[[float, NDArray[np.float64], NDArray[np.float64]], float],
        eclipse_model: str,
        eclipse_function: Callable[[float], float] | None,
        earth_flux: EarthFluxModel | Callable[..., Mapping[str, Any]],
        time_range_s: tuple[float, float],
        description: Mapping[str, Any],
        power_interface: Any = None,
    ) -> None:
        error = EnvironmentProviderError
        self.run_id = _text(run_id, "EnvironmentProvider.run_id", error)
        try:
            self.epoch = ensure_utc(epoch)
        except (TypeError, ValueError) as exc:
            raise error(f"EnvironmentProvider.epoch must be a timezone-aware UTC datetime: {exc}") from None
        if not isinstance(parameters, ThermalParameters):
            raise error(f"EnvironmentProvider.parameters must be ThermalParameters, got {type(parameters).__name__}")
        self.parameters = parameters
        self.surface_ids = tuple(surface.surface_id for surface in parameters.surfaces)
        for name, function in (("position", position), ("sun_position", sun_position), ("quaternion", quaternion),
                               ("irradiance", irradiance)):
            if not callable(function):
                raise error(f"EnvironmentProvider.{name} must be callable, got {function!r}")
        if eclipse_model not in ("orbit", "callable", "irradiance"):
            raise error(f"EnvironmentProvider eclipse model {eclipse_model!r} is not known")
        if eclipse_model == "callable" and not callable(eclipse_function):
            raise error(f"EnvironmentProvider.eclipse_fraction must be callable, got {eclipse_function!r}")
        if not isinstance(earth_flux, EarthFluxModel) and not callable(earth_flux):
            raise error(
                "EnvironmentProvider.earth_flux must be an EarthFluxModel or a callable "
                f"(run_id, time_s, position_m, sun_position_m, quaternion_xyzw, parameters), got {earth_flux!r}"
            )
        low, high = time_range_s
        if not low < high:
            raise error(f"EnvironmentProvider time range must be increasing, got {time_range_s!r}")
        self._position = position
        self._sun_position = sun_position
        self._quaternion = quaternion
        self._irradiance = irradiance
        self._eclipse_model = eclipse_model
        self._eclipse_function = eclipse_function
        self.earth_flux = earth_flux
        self.time_range_s = (float(low), float(high))
        self.power_interface = power_stand_in if power_interface is None else power_interface
        if not hasattr(self.power_interface, "PowerEnvironment"):
            raise error(f"EnvironmentProvider power interface {self.power_interface!r} has no PowerEnvironment")
        self._description = dict(description)
        self._cache: OrderedDict[float, EnvironmentSample] = OrderedDict()

    # ------------------------------------------------------------------------------------------------------- builders

    @classmethod
    def from_orbit(
        cls,
        *,
        run_id: str,
        epoch: datetime,
        parameters: ThermalParameters,
        ephemeris: Any,
        attitude: Any,
        sun_positions_m: ArrayLike,
        earth_flux: EarthFluxModel | Callable[..., Mapping[str, Any]],
        sun_times_s: ArrayLike | None = None,
        power_interface: Any = None,
    ) -> EnvironmentProvider:
        """Provider from an Orbit ``Ephemeris``, an ``AttitudeEphemeris`` and Earth-to-Sun positions.

        ``ephemeris`` must be GCRS (transform TEME with ``ntu_space_dynamics.transform_ephemeris`` first); positions
        are interpolated with cubic Hermite polynomials that use the ephemeris velocities. ``attitude.times_s`` are
        seconds from ``epoch`` and its body-to-GCRS quaternions are interpolated by spherical linear interpolation.
        ``sun_positions_m`` (n, 3) are GCRS Earth-to-Sun vectors at the ephemeris times, or at ``sun_times_s`` (seconds
        from ``epoch``) when given, interpolated with a cubic spline. ``G`` is Orbit's ``sun_intensity`` with
        ``include_eclipse=True`` and the eclipse phases come from Orbit's ``eclipse_fraction``; no value is
        extrapolated outside the common time range of the three inputs.
        """

        error = EnvironmentProviderError
        try:
            epoch_utc = ensure_utc(epoch)
        except (TypeError, ValueError) as exc:
            raise error(f"from_orbit: epoch must be a timezone-aware UTC datetime: {exc}") from None
        for name in ("times", "positions_m", "velocities_m_s", "frame"):
            if not hasattr(ephemeris, name):
                raise error(f"from_orbit: ephemeris has no field {name!r} ({type(ephemeris).__name__} given)")
        if ephemeris.frame != "GCRS":
            raise error(
                f"from_orbit: ephemeris.frame is {ephemeris.frame!r}; transform it to GCRS with "
                "ntu_space_dynamics.transform_ephemeris first, relabelling is not a frame transformation"
            )
        try:
            orbit_times = seconds_since(ephemeris.times, epoch_utc)
        except (TypeError, ValueError) as exc:
            raise error(f"from_orbit: ephemeris.times cannot be referred to the epoch: {exc}") from None
        orbit_times = _increasing_times(orbit_times, "from_orbit: ephemeris times", error)
        positions = np.array(ephemeris.positions_m, dtype=float)
        velocities = np.array(ephemeris.velocities_m_s, dtype=float)
        shape = (orbit_times.size, 3)
        if positions.shape != shape or velocities.shape != shape:
            raise error(
                f"from_orbit: ephemeris positions and velocities must have shape {shape}, got {positions.shape} and "
                f"{velocities.shape}"
            )
        if not (np.all(np.isfinite(positions)) and np.all(np.isfinite(velocities))):
            raise error("from_orbit: ephemeris positions and velocities must be finite")
        position_spline = CubicHermiteSpline(orbit_times, positions, velocities, axis=0)

        for name in ("times_s", "quaternions_xyzw"):
            if not hasattr(attitude, name):
                raise error(f"from_orbit: attitude has no field {name!r} ({type(attitude).__name__} given)")
        attitude_times = _increasing_times(attitude.times_s, "from_orbit: attitude.times_s", error)
        quaternions = np.array(attitude.quaternions_xyzw, dtype=float)
        if quaternions.shape != (attitude_times.size, 4) or not np.all(np.isfinite(quaternions)):
            raise error(
                f"from_orbit: attitude.quaternions_xyzw must be finite with shape {(attitude_times.size, 4)}, "
                f"got {quaternions.shape}"
            )
        norms = np.linalg.norm(quaternions, axis=1)
        worst = int(np.argmax(np.abs(norms - 1.0)))
        if abs(norms[worst] - 1.0) > _QUATERNION_SAMPLE_TOLERANCE:
            raise error(
                f"from_orbit: attitude quaternion {worst} at {attitude_times[worst]!r} s has norm {norms[worst]!r}; "
                f"body-to-GCRS quaternions must be unit within {_QUATERNION_SAMPLE_TOLERANCE:g}"
            )
        slerp = Slerp(attitude_times, Rotation.from_quat(quaternions))

        sun_values = np.array(sun_positions_m, dtype=float)
        if sun_times_s is None:
            sun_times = orbit_times
            label = "the ephemeris times"
        else:
            sun_times = _increasing_times(sun_times_s, "from_orbit: sun_times_s", error)
            label = "sun_times_s"
        if sun_values.shape != (sun_times.size, 3) or not np.all(np.isfinite(sun_values)):
            raise error(
                f"from_orbit: sun_positions_m must be finite with shape {(sun_times.size, 3)} at {label}, "
                f"got {sun_values.shape}"
            )
        sun_spline = CubicSpline(sun_times, sun_values, axis=0)

        low = max(orbit_times[0], attitude_times[0], sun_times[0])
        high = min(orbit_times[-1], attitude_times[-1], sun_times[-1])
        if not low < high:
            raise error(
                f"from_orbit: ephemeris [{orbit_times[0]!r}, {orbit_times[-1]!r}] s, attitude "
                f"[{attitude_times[0]!r}, {attitude_times[-1]!r}] s and Sun [{sun_times[0]!r}, {sun_times[-1]!r}] s "
                "have no common time range"
            )

        def position(time_s: float) -> NDArray[np.float64]:
            return position_spline(time_s)

        def sun_position(time_s: float) -> NDArray[np.float64]:
            return sun_spline(time_s)

        def quaternion(time_s: float) -> NDArray[np.float64]:
            return slerp([time_s]).as_quat()[0]

        def irradiance(time_s: float, r: NDArray[np.float64], s: NDArray[np.float64]) -> float:
            return _orbit_sun_intensity(r, s, include_eclipse=True)

        description = {
            "mode": "orbit_ephemeris",
            "irradiance": "ntu_space_dynamics.sun_intensity(include_eclipse=True)",
            "eclipse_phases": "ntu_space_dynamics.eclipse_fraction, conical umbra and penumbra",
            "position_interpolation": "cubic Hermite polynomials with the ephemeris velocities",
            "attitude_interpolation": "spherical linear interpolation of the body-to-GCRS quaternions",
            "sun_interpolation": "cubic spline of the Earth-to-Sun vectors",
            "ephemeris": {
                "frame": ephemeris.frame,
                "samples": int(orbit_times.size),
                "first_s": float(orbit_times[0]),
                "last_s": float(orbit_times[-1]),
                "max_spacing_s": float(np.max(np.diff(orbit_times))),
            },
            "attitude": {
                "samples": int(attitude_times.size),
                "first_s": float(attitude_times[0]),
                "last_s": float(attitude_times[-1]),
                "max_spacing_s": float(np.max(np.diff(attitude_times))),
            },
            "sun": {
                "samples": int(sun_times.size),
                "first_s": float(sun_times[0]),
                "last_s": float(sun_times[-1]),
            },
        }
        return cls(
            run_id=run_id,
            epoch=epoch_utc,
            parameters=parameters,
            position=position,
            sun_position=sun_position,
            quaternion=quaternion,
            irradiance=irradiance,
            eclipse_model="orbit",
            eclipse_function=None,
            earth_flux=earth_flux,
            time_range_s=(float(low), float(high)),
            description=description,
            power_interface=power_interface,
        )

    @classmethod
    def from_callables(
        cls,
        *,
        run_id: str,
        epoch: datetime,
        parameters: ThermalParameters,
        position: Callable[[float], ArrayLike],
        sun_position: Callable[[float], ArrayLike],
        quaternion: Callable[[float], ArrayLike],
        G: Callable[[float], float],
        earth_flux: EarthFluxModel | Callable[..., Mapping[str, Any]],
        eclipse_fraction: Callable[[float], float] | None = None,
        time_range_s: tuple[float, float] | None = None,
        power_interface: Any = None,
    ) -> EnvironmentProvider:
        """Provider from analytic functions of ``time_s``, for idealized orbits such as the finite-element cases.

        ``position(t)`` and ``sun_position(t)`` return GCRS vectors in m (Earth to satellite, Earth to Sun),
        ``quaternion(t)`` the active body-to-GCRS unit quaternion (xyzw) and ``G(t)`` the solar irradiance in W/m^2
        that already includes the eclipse. Eclipse phases come from ``eclipse_fraction(t)`` (visible solar-disc fraction
        in [0, 1]) when given, otherwise from ``G(t) > 0``; the boundaries must be those of ``G``. ``time_range_s``
        optionally limits the valid times.
        """

        error = EnvironmentProviderError
        for name, function in (("position", position), ("sun_position", sun_position), ("quaternion", quaternion),
                               ("G", G)):
            if not callable(function):
                raise error(f"from_callables: {name} must be callable, got {function!r}")
        if eclipse_fraction is not None and not callable(eclipse_fraction):
            raise error(f"from_callables: eclipse_fraction must be callable or None, got {eclipse_fraction!r}")
        if time_range_s is None:
            low, high = -math.inf, math.inf
        else:
            try:
                low_value, high_value = time_range_s
            except (TypeError, ValueError):
                raise error(f"from_callables: time_range_s must be a pair (low, high), got {time_range_s!r}") from None
            low = _number(low_value, "from_callables: time_range_s[0]", error)
            high = _number(high_value, "from_callables: time_range_s[1]", error)

        def irradiance(time_s: float, r: NDArray[np.float64], s: NDArray[np.float64]) -> float:
            return G(time_s)

        description = {
            "mode": "analytic_callables",
            "position": _callable_name(position),
            "sun_position": _callable_name(sun_position),
            "quaternion": _callable_name(quaternion),
            "irradiance": f"caller G(t): {_callable_name(G)}",
            "eclipse_phases": (
                f"caller eclipse_fraction(t): {_callable_name(eclipse_fraction)}"
                if eclipse_fraction is not None
                else "G(t) > 0 is sunlit, G(t) = 0 is umbra"
            ),
        }
        return cls(
            run_id=run_id,
            epoch=epoch,
            parameters=parameters,
            position=position,
            sun_position=sun_position,
            quaternion=quaternion,
            irradiance=irradiance,
            eclipse_model="callable" if eclipse_fraction is not None else "irradiance",
            eclipse_function=eclipse_fraction,
            earth_flux=earth_flux,
            time_range_s=(low, high),
            description=description,
            power_interface=power_interface,
        )

    # ------------------------------------------------------------------------------------------------------- sampling

    def sample(self, time_s: float) -> EnvironmentSample:
        """Synchronized environment at ``time_s`` (cached by time)."""

        t = _number(time_s, "EnvironmentProvider.sample time_s", EnvironmentProviderError)
        cached = self._cache.get(t)
        if cached is not None:
            self._cache.move_to_end(t)
            return cached
        self._check_time(t)
        position, sun = self._geometry(t)
        quaternion = _vector(
            self._quaternion(t), 4, f"EnvironmentProvider quaternion at time_s={t!r}", EnvironmentProviderError
        )
        irradiance = self._G(t, position, sun)
        fraction = self._fraction(t, position, sun, irradiance)
        orbit_input = MappingProxyType(
            {
                "run_id": self.run_id,
                "time_s": t,
                "epoch": self.epoch,
                "position_m": position,
                "sun_position_m": sun,
                "frame": "GCRS",
                "quaternion_xyzw": quaternion,
                "G_W_m2": irradiance,
            }
        )
        flux = self._earth_flux_record(t, position, sun, quaternion)
        surface = prepare_surface_environment(orbit_input, flux, self.parameters)
        power_environment = self.power_interface.PowerEnvironment(
            G_W_m2=irradiance,
            position_m=position,
            sun_position_m=sun,
            quaternion_xyzw=quaternion,
            frame="GCRS",
        )
        sample = EnvironmentSample(
            time_s=t,
            orbit_input=orbit_input,
            earth_flux=MappingProxyType(dict(flux)),
            surface_environment=MappingProxyType(surface),
            power_environment=power_environment,
            illumination_fraction=fraction,
        )
        self._cache[t] = sample
        if len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return sample

    def illumination_fraction(self, time_s: float) -> float:
        """Visible solar-disc fraction at ``time_s`` (1 sunlit, 0 umbra) that defines the eclipse phase."""

        t = _number(time_s, "EnvironmentProvider.illumination_fraction time_s", EnvironmentProviderError)
        self._check_time(t)
        if self._eclipse_model == "callable":
            return self._fraction(t, None, None, None)
        position, sun = self._geometry(t)
        return self._fraction(t, position, sun, None)

    def eclipse_phase(self, time_s: float) -> str:
        """``"sunlit"``, ``"penumbra"`` or ``"umbra"`` at ``time_s``."""

        return _phase(self.illumination_fraction(time_s))

    def describe(self) -> dict[str, Any]:
        """Plain description of the provider for the run provenance."""

        earth = self.earth_flux.as_dict() if isinstance(self.earth_flux, EarthFluxModel) else {
            "callable": _callable_name(self.earth_flux)
        }
        return _plain(
            {
                **self._description,
                "run_id": self.run_id,
                "epoch_utc": self.epoch,
                "frame": "GCRS",
                "time_range_s": list(self.time_range_s),
                "earth_flux": earth,
                "surface_ids": list(self.surface_ids),
                "power_environment": _callable_name(self.power_interface.PowerEnvironment),
            }
        )

    # -------------------------------------------------------------------------------------------------------- private

    def _check_time(self, t: float) -> None:
        low, high = self.time_range_s
        if not low <= t <= high:
            raise EnvironmentProviderError(
                f"time_s={t!r} lies outside the environment data range [{low!r}, {high!r}] s; nothing is extrapolated"
            )

    def _geometry(self, t: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        error = EnvironmentProviderError
        position = _vector(self._position(t), 3, f"EnvironmentProvider position at time_s={t!r}", error)
        sun = _vector(self._sun_position(t), 3, f"EnvironmentProvider sun_position at time_s={t!r}", error)
        return position, sun

    def _G(self, t: float, position: NDArray[np.float64], sun: NDArray[np.float64]) -> float:
        return _nonnegative(
            self._irradiance(t, position, sun), f"EnvironmentProvider G_W_m2 at time_s={t!r}", EnvironmentProviderError
        )

    def _fraction(
        self,
        t: float,
        position: NDArray[np.float64] | None,
        sun: NDArray[np.float64] | None,
        irradiance: float | None,
    ) -> float:
        if self._eclipse_model == "orbit":
            value = _orbit_eclipse_fraction(position, sun)
        elif self._eclipse_model == "callable":
            value = self._eclipse_function(t)  # type: ignore[misc]
        else:
            if irradiance is None:
                irradiance = self._G(t, position, sun)  # type: ignore[arg-type]
            value = 1.0 if irradiance > 0.0 else 0.0
        fraction = _number(value, f"EnvironmentProvider eclipse fraction at time_s={t!r}", EnvironmentProviderError)
        if not 0.0 <= fraction <= 1.0:
            raise EnvironmentProviderError(
                f"EnvironmentProvider eclipse fraction at time_s={t!r} must lie in [0, 1], got {fraction!r}"
            )
        return fraction

    def _earth_flux_record(
        self,
        t: float,
        position: NDArray[np.float64],
        sun: NDArray[np.float64],
        quaternion: NDArray[np.float64],
    ) -> Mapping[str, Any]:
        model = self.earth_flux
        if not isinstance(model, EarthFluxModel):
            record = model(self.run_id, t, position, sun, quaternion, self.parameters)
            if not isinstance(record, Mapping):
                raise EnvironmentProviderError(
                    f"earth_flux callable {_callable_name(model)} must return a mapping at time_s={t!r}, "
                    f"got {type(record).__name__}"
                )
            return record
        if model.enabled:
            return earth_flux_record(
                self.run_id,
                t,
                position,
                sun,
                quaternion,
                self.parameters,
                albedo=model.albedo,
                olr_W_m2=model.olr_W_m2,
                solar_constant_W_m2=model.solar_constant_W_m2,
                earth_radius_m=model.earth_radius_m,
                resolution=model.resolution,
            )
        zeros = _readonly(np.zeros(len(self.surface_ids)))
        return {
            "run_id": self.run_id,
            "time_s": t,
            "surface_ids": self.surface_ids,
            "albedo_W_m2": zeros,
            "infrared_W_m2": zeros,
        }


# ----------------------------------------------------------------------------------------------------------------------
# eclipse boundaries
# ----------------------------------------------------------------------------------------------------------------------


def find_eclipse_boundaries(
    source: EnvironmentProvider | Callable[[float], float],
    t0_s: float,
    t1_s: float,
    *,
    scan_step_s: float,
) -> tuple[EclipseBoundary, ...]:
    """Locate every change of illumination phase on ``[t0_s, t1_s]``.

    ``source`` is an :class:`EnvironmentProvider` (its ``illumination_fraction``, from Orbit's ``eclipse_fraction`` in
    an orbit provider) or a callable returning the visible solar-disc fraction at a time. The phase (sunlit,
    penumbra, umbra) is scanned every ``scan_step_s`` and each change is bisected to adjacent floating-point times, so
    no evaluation on one side of a boundary sees the other side. A phase that begins and ends within one scan step is
    not seen; choose ``scan_step_s`` below the shortest phase.
    """

    if isinstance(source, EnvironmentProvider):
        fraction_of = source.illumination_fraction
    elif callable(source):
        fraction_of = source
    else:
        raise CoupledConfigurationError(
            f"find_eclipse_boundaries: source must be an EnvironmentProvider or a callable, got {source!r}"
        )
    t0 = _number(t0_s, "find_eclipse_boundaries t0_s")
    t1 = _number(t1_s, "find_eclipse_boundaries t1_s")
    step = _positive(scan_step_s, "find_eclipse_boundaries scan_step_s")
    if not t0 < t1:
        raise CoupledConfigurationError(f"find_eclipse_boundaries needs t0_s < t1_s, got {t0!r} and {t1!r}")

    def phase(moment: float) -> str:
        value = _number(fraction_of(moment), f"illumination fraction at time_s={moment!r}")
        if not 0.0 <= value <= 1.0:
            raise CoupledConfigurationError(
                f"illumination fraction at time_s={moment!r} must lie in [0, 1], got {value!r}"
            )
        return _phase(value)

    count = math.floor((t1 - t0) / step)
    grid = [t0 + index * step for index in range(count + 1)]
    grid = [moment for moment in grid if moment < t1]
    grid.append(t1)
    boundaries: list[EclipseBoundary] = []
    previous_time, previous_phase = grid[0], phase(grid[0])
    for moment in grid[1:]:
        current = phase(moment)
        if current != previous_phase:
            boundaries.extend(_bisect_transitions(phase, previous_time, previous_phase, moment, current))
        previous_time, previous_phase = moment, current
    return tuple(boundaries)


def _bisect_transitions(
    phase: Callable[[float], str], a: float, phase_a: str, b: float, phase_b: str
) -> list[EclipseBoundary]:
    """All phase changes between ``a`` and ``b`` (phases differ), each bisected to adjacent floats."""

    found: list[EclipseBoundary] = []
    while phase_a != phase_b:
        low, high, phase_high = a, b, phase_b
        while True:
            middle = low + 0.5 * (high - low)
            if not low < middle < high:
                break
            phase_middle = phase(middle)
            if phase_middle == phase_a:
                low = middle
            else:
                high, phase_high = middle, phase_middle
        found.append(EclipseBoundary(low, high, phase_a, phase_high))
        a, phase_a = high, phase_high
    return found


def eclipse_entry_exit_times(
    source: EnvironmentProvider | Callable[[float], float],
    t0_s: float,
    t1_s: float,
    *,
    scan_step_s: float,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Eclipse entry times (first instant that is not sunlit) and exit times (first sunlit instant) on the interval."""

    boundaries = find_eclipse_boundaries(source, t0_s, t1_s, scan_step_s=scan_step_s)
    entries = tuple(boundary.time_s for boundary in boundaries if boundary.is_eclipse_entry)
    exits = tuple(boundary.time_s for boundary in boundaries if boundary.is_eclipse_exit)
    return entries, exits


# ----------------------------------------------------------------------------------------------------------------------
# trial records and the archive
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class TrialRecord:
    """One evaluation of the coupled model passed to ``trial_hook`` (diagnostics only, never stored by the run).

    ``context`` is one of EVALUATION_CONTEXTS, ``outcome`` is ``"ok"``, ``"event_required"``, ``"invalid"`` or
    ``"error"``, ``state`` a read-only copy of the evaluated state vector and ``thermal_state`` the trial ThermalState
    when it could be built.
    """

    run_id: str
    time_s: float
    context: str
    outcome: str
    solver_id: int
    state: NDArray[np.float64]
    thermal_state: ThermalState | None
    power_reason: str | None


@dataclass(frozen=True, eq=False, repr=False)
class CoupledArchive:
    """Archive of one coupled run (thermal design 9.4; Power design 9.4).

    The output series are samples of the accepted solution at ``output_step_s``: ``time_s`` (n,), ``temperature_K``
    and ``dT_dt_K_s`` (n, 6) in NODE_ORDER, ``ports_W`` (the four Power ports by name), ``q_W`` (n, 5) in PATH_ORDER,
    ``Q_env_W`` and ``Q_emit_W`` (n, 2) in EXPOSED_NODES order and ``lithium`` (``x_n``, ``x_p``) when Power is
    enabled. ``accepted`` holds every accepted state and ``steps`` every accepted step; ``events`` (applied Power
    events), ``limit_events`` (located starts and ends of charge limiting, not protection events), ``segments`` and
    ``eclipse_boundaries`` record the boundaries. ``range_warnings`` lists temperatures outside the declared node ranges,
    both excursions of accepted states (``source="accepted_states"``) and output samples (``source="output_sample"``).
    ``status`` is ``"completed"`` or ``"stopped"`` with ``error``.
    """

    run_id: str
    epoch: datetime
    status: str
    error: Mapping[str, Any] | None
    t_start_s: float
    t_end_s: float
    time_s: NDArray[np.float64]
    temperature_K: NDArray[np.float64]
    dT_dt_K_s: NDArray[np.float64]
    ports_W: Mapping[str, NDArray[np.float64]]
    q_W: NDArray[np.float64]
    Q_env_W: NDArray[np.float64]
    Q_emit_W: NDArray[np.float64]
    lithium: Mapping[str, NDArray[np.float64]] | None
    power_diagnostics: Mapping[str, Any] | None
    environment: Mapping[str, Any]
    sample_valid: NDArray[np.bool_]
    accepted: Mapping[str, Any]
    steps: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    limit_events: tuple[Mapping[str, Any], ...]
    eclipse_boundaries: tuple[EclipseBoundary, ...]
    segments: tuple[Mapping[str, Any], ...]
    solver_settings: Mapping[str, Any]
    statistics: Mapping[str, Any]
    energy_audit: Mapping[str, Any] | None
    provenance: Mapping[str, Any]
    instance_map: Mapping[str, Any]
    range_warnings: tuple[Mapping[str, Any], ...]
    notes: tuple[str, ...]
    final_thermal_state: ThermalState | None
    final_power_state: Any
    _solution: Any = field(default=None, repr=False)

    def __repr__(self) -> str:
        return (
            f"CoupledArchive(run_id={self.run_id!r}, status={self.status!r}, t=[{self.t_start_s!r}, "
            f"{self.t_end_s!r}] s, samples={self.time_s.size}, accepted_states={len(self.accepted['time_s'])}, "
            f"events={len(self.events)}, limit_events={len(self.limit_events)})"
        )

    @property
    def node_order(self) -> tuple[str, ...]:
        return NODE_ORDER

    @property
    def path_order(self) -> tuple[str, ...]:
        return PATH_ORDER

    @property
    def exposed_node_order(self) -> tuple[str, ...]:
        return EXPOSED_NODES

    @property
    def port_order(self) -> tuple[str, ...]:
        return PORT_ORDER

    def node_temperature_K(self, node: str) -> NDArray[np.float64]:
        """Output temperatures of one node (``"S"``, ``"J"``, ``"C"``, ``"B"``, ``"D"`` or ``"R"``)."""

        if node not in NODE_ORDER:
            raise KeyError(f"node must be one of {NODE_ORDER}, got {node!r}")
        return self.temperature_K[:, NODE_ORDER.index(node)]

    def state_at(self, time_s: ArrayLike) -> NDArray[np.float64]:
        """State vector on the accepted solution at ``time_s`` (scalar or one-dimensional), interpolated only."""

        if self._solution is None:
            raise RuntimeError("this archive carries no accepted solution")
        times = np.asarray(time_s, dtype=float)
        if times.ndim == 0:
            return self._solution.locate(float(times))[0]
        if times.ndim != 1:
            raise ValueError("time_s must be a scalar or a one-dimensional array")
        return np.array([self._solution.locate(float(moment))[0] for moment in times])

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON-ready copy of the archive; NaN and infinities become ``None``."""

        final_state = None
        if self.final_thermal_state is not None:
            final_state = {
                "time_s": self.final_thermal_state.time_s,
                "temperature_K": self.final_thermal_state.temperature_K,
            }
            if self.final_power_state is not None:
                final_state.update(
                    {
                        "x_n": getattr(self.final_power_state, "x_n", None),
                        "x_p": getattr(self.final_power_state, "x_p", None),
                        "load_connected": getattr(self.final_power_state, "load_connected", None),
                        "trip_latched": getattr(self.final_power_state, "trip_latched", None),
                        "handled_command_ids": getattr(self.final_power_state, "handled_command_ids", None),
                    }
                )
        return _plain(
            {
                "format": ARCHIVE_FORMAT,
                "run_id": self.run_id,
                "epoch_utc": self.epoch,
                "status": self.status,
                "error": self.error,
                "t_start_s": self.t_start_s,
                "t_end_s": self.t_end_s,
                "node_order": NODE_ORDER,
                "path_order": PATH_ORDER,
                "exposed_node_order": EXPOSED_NODES,
                "port_order": PORT_ORDER,
                "lithium_order": LITHIUM_ORDER if self.lithium is not None else (),
                "instance_map": self.instance_map,
                "time_s": self.time_s,
                "temperature_K": self.temperature_K,
                "dT_dt_K_s": self.dT_dt_K_s,
                "ports_W": self.ports_W,
                "q_W": self.q_W,
                "Q_env_W": self.Q_env_W,
                "Q_emit_W": self.Q_emit_W,
                "lithium": self.lithium,
                "power_diagnostics": self.power_diagnostics,
                "environment": self.environment,
                "sample_valid": self.sample_valid,
                "accepted": self.accepted,
                "steps": self.steps,
                "events": self.events,
                "limit_events": self.limit_events,
                "eclipse_boundaries": [boundary.as_dict() for boundary in self.eclipse_boundaries],
                "segments": self.segments,
                "solver_settings": self.solver_settings,
                "statistics": self.statistics,
                "energy_audit": self.energy_audit,
                "range_warnings": self.range_warnings,
                "notes": self.notes,
                "final_state": final_state,
                "provenance": self.provenance,
            }
        )

    def to_json(self, path: str | Path) -> Path:
        """Write :meth:`as_dict` as UTF-8 JSON to ``path`` (parent folders are created) and return the path."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.as_dict(), ensure_ascii=False, allow_nan=False), encoding="utf-8")
        return target.resolve()


# ----------------------------------------------------------------------------------------------------------------------
# internal records of the runner
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Protection:
    """Discrete Power protection state; changed only by apply_power_event at an accepted boundary."""

    load_connected: bool
    trip_latched: bool
    handled_command_ids: tuple[str, ...]
    since_s: float


class _LinearDense:
    """Linear interpolant of an event bridge (one explicit Euler step of at most ``event_time_tol_s``)."""

    def __init__(self, t_old: float, t_new: float, y_old: NDArray[np.float64], y_new: NDArray[np.float64]) -> None:
        self.t_old = t_old
        self.t_new = t_new
        self.y_old = y_old
        self.y_new = y_new

    def __call__(self, t: float) -> NDArray[np.float64]:
        if self.t_new == self.t_old:
            return self.y_new.copy()
        weight = (t - self.t_old) / (self.t_new - self.t_old)
        return self.y_old + weight * (self.y_new - self.y_old)


@dataclass(eq=False)
class _Piece:
    """One accepted step (solver step or event bridge) with its dense output."""

    t_old: float
    t_new: float
    y_old: NDArray[np.float64]
    y_new: NDArray[np.float64]
    dense: Any
    protection: int
    kind: str
    solver_id: int
    attempts: int


@dataclass(eq=False)
class _SolverCounter:
    solver_id: int
    context: str
    calls: int = 0
    times: list[float] = field(default_factory=list)


@dataclass(eq=False)
class _Cut:
    start: float
    end: float
    reasons: list[str]
    commands: list[LoadCommand]


@dataclass(eq=False)
class _Segment:
    start: float
    end: float
    start_reasons: list[str]
    end_reasons: list[str]
    commands: list[LoadCommand]


@dataclass(frozen=True, eq=False)
class _Evaluation:
    derivative: NDArray[np.float64]
    thermal: Any
    power: Any
    ports: tuple[float, ...]
    sample: EnvironmentSample
    request_W: float | None


class _PiecewiseSolution:
    """Accepted solution: dense outputs of the accepted steps; instants between steps carry the state unchanged."""

    def __init__(
        self,
        t_start: float,
        y_start: NDArray[np.float64],
        initial_protection: int,
        pieces: list[_Piece],
        y_final: NDArray[np.float64],
        final_protection: int,
    ) -> None:
        self.t_start = t_start
        self.y_start = y_start
        self.initial_protection = initial_protection
        self.pieces = list(pieces)
        self.starts = [piece.t_old for piece in self.pieces]
        self.y_final = y_final
        self.final_protection = final_protection

    def locate(self, t: float) -> tuple[NDArray[np.float64], int]:
        """State and protection index at ``t``; right-continuous at boundary instants."""

        index = bisect.bisect_right(self.starts, t) - 1
        if index < 0:
            return self.y_start.copy(), self.initial_protection
        piece = self.pieces[index]
        if t <= piece.t_new:
            if t == piece.t_old:
                return piece.y_old.copy(), piece.protection
            if t == piece.t_new:
                return piece.y_new.copy(), piece.protection
            return np.array(piece.dense(t), dtype=float), piece.protection
        if index + 1 < len(self.pieces):
            following = self.pieces[index + 1]
            return following.y_old.copy(), following.protection
        return self.y_final.copy(), self.final_protection


class _Statistics:
    def __init__(self) -> None:
        self.evaluations: Counter[str] = Counter()
        self.power_calls: Counter[str] = Counter()
        self.accepted: Counter[str] = Counter()
        self.bridge_steps = 0
        self.rejected_error_control = 0
        self.event_aborted_attempts = 0
        self.discarded_search_steps = 0
        self.discarded_search_rejections = 0
        self.solver_instances = 0
        self.construction_evaluations = 0
        self.event_searches = 0
        self.located_events = 0
        self.unconfirmed_event_searches = 0
        self.bisection_iterations = 0
        self.applied_events = 0
        self.attempt_count_anomalies = 0
        self.limit_searches = 0
        self.limit_bisection_iterations = 0
        self.limit_splits = 0
        self.limit_reason_reuses = 0


def _merge_cuts(cuts: list[_Cut]) -> list[_Cut]:
    """Sorted cuts with overlapping or touching ones merged into one instant interval."""

    merged: list[_Cut] = []
    for cut in sorted(cuts, key=lambda item: (item.start, item.end)):
        if merged and cut.start <= merged[-1].end + _gap_tolerance(merged[-1].end):
            last = merged[-1]
            merged[-1] = _Cut(
                min(last.start, cut.start), max(last.end, cut.end), last.reasons + cut.reasons,
                last.commands + cut.commands,
            )
        else:
            merged.append(_Cut(cut.start, cut.end, list(cut.reasons), list(cut.commands)))
    return merged


def _output_grid(start: float, stop: float, step: float) -> NDArray[np.float64]:
    """``start + k step`` up to ``stop``, with ``stop`` always included; independent of the internal steps."""

    if stop <= start:
        return np.array([start])
    count = math.floor((stop - start) / step + 1e-9)
    times = start + step * np.arange(count + 1, dtype=float)
    times = times[times <= stop]
    if times.size == 0 or stop - times[-1] > 1e-9 * step:
        times = np.append(times, stop)
    else:
        times[-1] = stop
    return times


# ----------------------------------------------------------------------------------------------------------------------
# the runner
# ----------------------------------------------------------------------------------------------------------------------


class _CoupledRun:
    """State of one coupled run; see :func:`run_coupled`."""

    def __init__(
        self,
        parameters: ThermalParameters,
        initial_state: ThermalState,
        environment: EnvironmentProvider,
        t_end_s: float,
        settings: SolverSettings | None,
        power: PowerCoupling | None,
        prescribed_ports: Callable[[float], Mapping[str, float]] | None,
        boundaries_s: Sequence[Any],
        energy_audit: bool,
        trial_hook: Callable[[TrialRecord], None] | None,
        provenance: Mapping[str, Any] | None,
    ) -> None:
        error = CoupledConfigurationError
        if not isinstance(parameters, ThermalParameters):
            raise error(f"parameters must be ThermalParameters, got {type(parameters).__name__}")
        if not isinstance(initial_state, ThermalState):
            raise error(
                f"initial_state must be a ThermalState (all initial temperatures enter ThermalState, design 9.4), "
                f"got {type(initial_state).__name__}"
            )
        if not isinstance(environment, EnvironmentProvider):
            raise error(f"environment must be an EnvironmentProvider, got {type(environment).__name__}")
        self.parameters = parameters
        self.run_id = initial_state.run_id
        self.provider = environment
        if environment.run_id != self.run_id:
            raise error(f"environment.run_id {environment.run_id!r} differs from initial_state.run_id {self.run_id!r}")
        if environment.parameters is not parameters and environment.parameters != parameters:
            raise error("environment.parameters differ from parameters; the surfaces of both must be the same record")
        self.t_start = initial_state.time_s
        self.t_end = _number(t_end_s, "t_end_s")
        if not self.t_end > self.t_start:
            raise error(f"t_end_s {self.t_end!r} must exceed initial_state.time_s {self.t_start!r}")
        low, high = environment.time_range_s
        if self.t_start < low or self.t_end > high:
            raise error(
                f"the run [{self.t_start!r}, {self.t_end!r}] s is not covered by the environment data range "
                f"[{low!r}, {high!r}] s"
            )
        if (power is None) == (prescribed_ports is None):
            raise error(
                "give exactly one of power (a coupled Power run) or prescribed_ports (a thermal-only run with "
                "prescribed P_pv_W, P_load_W, Q_B_W and Q_D_W)"
            )
        self.power = power
        self.prescribed_ports = prescribed_ports
        self.instance_id: str | None = None
        y0 = np.array(initial_state.temperature_K, dtype=float)
        if power is not None:
            settings = self._check_power(power, settings)
            state = power.initial_state
            y0 = np.concatenate([y0, [_number(state.x_n, "power.initial_state.x_n"),
                                      _number(state.x_p, "power.initial_state.x_p")]])
            initial_protection = _Protection(
                bool(state.load_connected), bool(state.trip_latched), tuple(state.handled_command_ids), self.t_start
            )
            self.commands = tuple(sorted(power.commands, key=lambda command: command.time_s))
        else:
            if not callable(prescribed_ports):
                raise error(
                    f"prescribed_ports must be callable (time_s -> mapping of the four ports), got {prescribed_ports!r}"
                )
            if settings is None:
                raise error("settings are required for a thermal-only run (no Power numerics to take them from)")
            if not isinstance(settings, SolverSettings):
                raise error(f"settings must be SolverSettings, got {type(settings).__name__}")
            initial_protection = _Protection(False, False, (), self.t_start)
            self.commands = ()
        self.settings: SolverSettings = settings
        self.method_class = _METHOD_CLASSES[settings.method]
        self.n_state = y0.size
        atol = [settings.atol_T_K] * _N_NODES
        if power is not None:
            atol += [settings.atol_x] * len(LITHIUM_ORDER)
        self.atol = np.array(atol, dtype=float)
        self.y0 = _readonly(y0)
        self.declared = self._read_boundaries(boundaries_s)
        if not isinstance(energy_audit, (bool, np.bool_)):
            raise error(f"energy_audit must be True or False, got {energy_audit!r}")
        self.energy_audit = bool(energy_audit)
        if trial_hook is not None and not callable(trial_hook):
            raise error(f"trial_hook must be callable or None, got {trial_hook!r}")
        self.trial_hook = trial_hook
        if provenance is not None and not isinstance(provenance, Mapping):
            raise error(f"provenance must be a mapping or None, got {type(provenance).__name__}")
        self.caller_provenance = {} if provenance is None else provenance

        self.stats = _Statistics()
        self.protections: list[_Protection] = [initial_protection]
        self._protection_index = 0
        self._initial_protection_index = 0
        self.pieces: list[_Piece] = []
        self.points: list[tuple[float, NDArray[np.float64], str, int]] = []
        self.events: list[dict[str, Any]] = []
        self.limit_events: list[dict[str, Any]] = []
        self.segment_records: list[dict[str, Any]] = []
        self.eclipse_boundaries: tuple[EclipseBoundary, ...] = ()
        self.notes: list[str] = []
        self.range_warnings: list[dict[str, Any]] = []
        declared_ranges = parameters.provenance["temperature_range_K"]
        self._ranges: tuple[tuple[float, float], ...] = tuple(
            (float(declared_ranges[node][0]), float(declared_ranges[node][1])) for node in NODE_ORDER
        )
        self._open_excursions: dict[str, dict[str, Any]] = {}
        # Last Power reason known at an accepted state (None before the first usable decision).
        self._limit_reason_text: str | None = None
        # Reason of the latest usable Power result: (time_s, protection index, state, reason).
        self._last_power_reason: tuple[float, int, NDArray[np.float64], str] | None = None
        self._solvers: list[Any] = []
        self._solver_sequence = 0
        self._supply_losses = 0
        self._last_evaluation: tuple[float, str] = (self.t_start, "initial")
        self.t_accepted = self.t_start
        self.y_accepted = self.y0.copy()
        self.accepted_state: ThermalState | None = None

    # ---------------------------------------------------------------------------------------------- configuration

    def _check_power(self, power: PowerCoupling, settings: SolverSettings | None) -> SolverSettings:
        error = CoupledConfigurationError
        if not isinstance(power, PowerCoupling):
            raise error(f"power must be a PowerCoupling, got {type(power).__name__}")
        parameters = power.parameters
        self.instance_id = _text(getattr(parameters, "instance_id", None), "power.parameters.instance_id")
        state = power.initial_state
        for name in ("run_id", "instance_id", "time_s", "x_n", "x_p", "load_connected", "trip_latched",
                     "handled_command_ids"):
            if not hasattr(state, name):
                raise error(f"power.initial_state has no field {name!r} ({type(state).__name__} given)")
        if state.run_id != self.run_id:
            raise error(f"power.initial_state.run_id {state.run_id!r} differs from the run {self.run_id!r}")
        if state.instance_id != self.instance_id:
            raise error(
                f"power.initial_state.instance_id {state.instance_id!r} differs from the Power parameters instance "
                f"{self.instance_id!r}"
            )
        if state.time_s != self.t_start:
            raise error(f"power.initial_state.time_s {state.time_s!r} differs from the run start {self.t_start!r}")
        links = getattr(parameters, "links", None)
        if not isinstance(links, Mapping):
            raise error("power.parameters.links must map the four ports to instance ids")
        thermal_ports = self.parameters.instance_map["ports"]
        for port in PORT_ORDER:
            if links.get(port) != thermal_ports[port]:
                raise error(
                    f"Power port {port} is linked to {links.get(port)!r} but the thermal instance map takes it from "
                    f"{thermal_ports[port]!r}; array position alone must not connect a value to the wrong device "
                    "(thermal design 5.1)"
                )
        numerics = getattr(parameters, "numerics", None)
        if settings is None:
            settings = SolverSettings.from_power_numerics(numerics)
        else:
            if not isinstance(settings, SolverSettings):
                raise error(f"settings must be SolverSettings, got {type(settings).__name__}")
            for name in _SETTINGS_FROM_NUMERICS:
                if not hasattr(numerics, name):
                    raise error(f"power.parameters.numerics has no field {name!r}")
                if getattr(settings, name) != float(getattr(numerics, name)):
                    raise error(
                        f"SolverSettings.{name}={getattr(settings, name)!r} differs from power.parameters.numerics."
                        f"{name}={getattr(numerics, name)!r}; the coupled ODE has one shared numerical configuration "
                        "(Power design table 7); build the settings with SolverSettings.from_power_numerics or change "
                        "the Power numerics"
                    )
        if settings.atol_x is None:
            raise error("SolverSettings.atol_x is required when Power is enabled (lithium fraction tolerance)")
        handled = set(state.handled_command_ids)
        for command in power.commands:
            if not self.t_start <= command.time_s < self.t_end:
                raise error(
                    f"LoadCommand {command.command_id!r} at {command.time_s!r} s lies outside the run "
                    f"[{self.t_start!r}, {self.t_end!r}) s"
                )
            if command.command_id in handled:
                raise error(f"LoadCommand {command.command_id!r} is already in power.initial_state.handled_command_ids")
        return settings

    def _read_boundaries(self, boundaries_s: Sequence[Any]) -> list[tuple[float, str]]:
        if isinstance(boundaries_s, (str, bytes)) or not isinstance(boundaries_s, Sequence):
            raise CoupledConfigurationError(f"boundaries_s must be a sequence of times, got {boundaries_s!r}")
        declared = []
        for index, item in enumerate(boundaries_s):
            if isinstance(item, (tuple, list)):
                if len(item) != 2:
                    raise CoupledConfigurationError(
                        f"boundaries_s[{index}] must be a time or (time, label), got {item!r}"
                    )
                moment = _number(item[0], f"boundaries_s[{index}] time")
                label = _text(item[1], f"boundaries_s[{index}] label")
            else:
                moment = _number(item, f"boundaries_s[{index}]")
                label = "input discontinuity"
            declared.append((moment, f"declared:{label}"))
        return sorted(declared, key=lambda entry: entry[0])

    # --------------------------------------------------------------------------------------------------- driving

    def run(self) -> CoupledArchive:
        started = time.perf_counter()
        error: dict[str, Any] | None = None
        cause: BaseException | None = None
        try:
            with warnings.catch_warnings():
                # Trial states are not results: their range warnings are not emitted (outputs record them).
                warnings.simplefilter("ignore", ThermalRangeWarning)
                self._integrate()
        except _StopRun as stop:
            error, cause = stop.record, stop.__cause__
        except _PowerInvalidSignal as signal:
            error = self._invalid_record(signal.time_s, signal.context, signal.result, signal.state)
        except _PowerEventSignal as signal:
            error = self._record(
                "event_unhandled", signal.time_s, signal.context,
                f"Power required an event outside an integration step: {getattr(signal.result, 'reason', '?')}",
                state=signal.state,
            )
        except Exception as exc:  # noqa: BLE001  (every other trial failure is reported and stops the run)
            moment, context = self._last_evaluation
            error = self._record(
                "evaluation_error", moment, context, f"{type(exc).__name__}: {exc}", exception_type=type(exc).__name__
            )
            cause = exc
        archive = self._archive("completed" if error is None else "stopped", error, started)
        if error is not None:
            raise CoupledRunError(
                f"coupled run {self.run_id!r} stopped at time_s={error.get('time_s')!r}: {error.get('message')}",
                archive,
            ) from cause
        return archive

    def _integrate(self) -> None:
        t = self.t_start
        y = self.y0.copy()
        self._accept_point(t, y, "initial")
        for index, segment in enumerate(self._plan()):
            if segment.start > t:
                t = segment.start
                self._accept_point(t, y, "segment_start")
            self._instant(t, y, segment.commands, segment.start_reasons)
            if index == 0:
                self._initial_protection_index = self._protection_index
            self._track_limit(t, y, "run_start" if index == 0 else "boundary", segment.start_reasons)
            protection = self.protections[self._protection_index]
            record = {
                "index": index,
                "start_s": t,
                "end_s": segment.end,
                "start_reasons": list(segment.start_reasons),
                "end_reasons": list(segment.end_reasons),
                "commands": [command.command_id for command in segment.commands],
                "load_connected_at_start": protection.load_connected if self.power is not None else None,
                "trip_latched_at_start": protection.trip_latched if self.power is not None else None,
                "integrated": False,
            }
            self.segment_records.append(record)
            if segment.end - t > _gap_tolerance(segment.end):
                t, y = self._integrate_segment(t, y, segment.end)
                record["integrated"] = True
            record["reached_s"] = t
        if t < self.t_end:
            t = self.t_end
            self._accept_point(t, y, "final")

    def _plan(self) -> list[_Segment]:
        """Segments between eclipse boundaries, command instants and declared discontinuities.

        Located Power events and located charge-limit boundaries split these segments further during integration.
        """

        boundaries = find_eclipse_boundaries(
            self.provider, self.t_start, self.t_end, scan_step_s=self.settings.environment_step_s
        )
        self.eclipse_boundaries = boundaries
        cuts = [_Cut(item.time_left_s, item.time_right_s, [f"eclipse:{item.kind}"], []) for item in boundaries]
        start, end = self.t_start, self.t_end
        start_reasons, end_reasons = ["run_start"], ["run_end"]
        initial_commands: list[LoadCommand] = []
        for moment, label in self.declared:
            if moment == self.t_start:
                start = _next_float(moment)
                start_reasons.append(label)
            elif moment == self.t_end:
                end = _previous_float(moment)
                end_reasons.append(label)
            elif self.t_start < moment < self.t_end:
                cuts.append(_Cut(_previous_float(moment), _next_float(moment), [label], []))
            else:
                self.notes.append(f"{label} at {moment!r} s lies outside the run and is not used")
        for command in self.commands:
            label = f"command:{command.kind}:{command.command_id}"
            if command.time_s == self.t_start:
                initial_commands.append(command)
                start_reasons.append(label)
            else:
                cuts.append(_Cut(command.time_s, command.time_s, [label], [command]))
        segments: list[_Segment] = []
        segment_start, reasons, commands = start, start_reasons, initial_commands
        for cut in _merge_cuts(cuts):
            if cut.start <= segment_start:
                segment_start = max(segment_start, cut.end)
                reasons = reasons + cut.reasons
                commands = commands + cut.commands
                continue
            segments.append(_Segment(segment_start, min(cut.start, end), reasons, list(cut.reasons), commands))
            segment_start, reasons, commands = cut.end, list(cut.reasons), list(cut.commands)
        segments.append(_Segment(segment_start, end, reasons, end_reasons, commands))
        return segments

    def _integrate_segment(self, t: float, y: NDArray[np.float64], end: float) -> tuple[float, NDArray[np.float64]]:
        """Integrate one segment; located Power events and charge-limit boundaries split it further."""

        first_step = self.settings.first_step_s
        while end - t > _gap_tolerance(end):
            try:
                solver, counter = self._new_solver(t, y, end, "integration", first_step)
            except _PowerEventSignal as signal:
                self.stats.event_aborted_attempts += 1
                t, y = self._locate_event(t, y, signal, end)
                self._track_limit(t, y, "event_restart", ["power_event"])
                first_step = None
                continue
            first_step = None
            split: tuple[float, NDArray[np.float64]] | None = None
            try:
                while solver.status == "running":
                    split = self._commit_tracked(self._step(solver, counter, "integration"), split=True)
                    if split is not None:
                        break
            except _PowerEventSignal as signal:
                self.stats.event_aborted_attempts += 1
                restart = signal.restart or (float(solver.t), np.array(solver.y, dtype=float))
                t, y = self._locate_event(restart[0], restart[1], signal, end)
                self._track_limit(t, y, "event_restart", ["power_event"])
                continue
            if split is not None:
                # The step ended at the located charge-limit boundary: a new solver starts there.
                t, y = split
                continue
            t, y = float(solver.t), np.array(solver.y, dtype=float)
        return t, y

    def _new_solver(
        self, t: float, y: NDArray[np.float64], end: float, context: str, first_step: float | None
    ) -> tuple[Any, _SolverCounter]:
        solver_id = self._solver_sequence
        self._solver_sequence += 1
        counter = _SolverCounter(solver_id, context)
        protection = self._protection_index

        def fun(time_value: float, state: NDArray[np.float64]) -> NDArray[np.float64]:
            moment = float(time_value)
            counter.calls += 1
            counter.times.append(moment)
            return self._evaluate(moment, state, protection, context, solver_id)

        options: dict[str, Any] = {"rtol": self.settings.rtol, "atol": self.atol, "max_step": self.settings.max_step_s}
        if first_step is not None:
            options["first_step"] = min(first_step, end - t)
        self.stats.solver_instances += 1
        try:
            solver = self.method_class(fun, t, np.array(y, dtype=float), end, **options)
        finally:
            self.stats.construction_evaluations += counter.calls
        self._solvers.append(solver)
        return solver, counter

    def _step(self, solver: Any, counter: _SolverCounter, context: str) -> _Piece:
        """One accepted step of ``solver``; the attempts behind it are derived from its function evaluations."""

        t_old = float(solver.t)
        y_old = np.array(solver.y, dtype=float)
        counter.calls = 0
        counter.times = []
        try:
            message = solver.step()
            if solver.status == "failed":
                raise _StopRun(
                    self._record(
                        "solver_failure", t_old, context,
                        f"{self.settings.method} step from time_s={t_old!r} failed: {message}", state=y_old,
                    )
                )
            t_new = float(solver.t)
            attempts = self._attempts(counter.calls, counter.times, t_old, t_new)
            dense = solver.dense_output()  # DOP853 evaluates the model here as well
        except _PowerEventSignal as signal:
            # Nothing of this step is stored; the search restarts from the last accepted state.
            signal.restart = (t_old, y_old)
            raise
        return _Piece(t_old, t_new, y_old, np.array(solver.y, dtype=float), dense, self._protection_index, context,
                      counter.solver_id, attempts)

    def _attempts(self, calls: int, times: list[float], t_old: float, t_new: float) -> int:
        if self.settings.method == "Radau":
            # Each attempt evaluates the three collocation times t + c_i h (Newton iterations repeat them).
            after = sorted(moment for moment in times if moment > t_old)
            if not after:
                self.stats.attempt_count_anomalies += 1
                return 1
            tolerance = 4.0 * math.ulp(max(abs(t_new), 1.0)) + 1e-12 * (t_new - t_old)
            clusters = 1 + sum(1 for first, second in itertools.pairwise(after) if second - first > tolerance)
            attempts, remainder = divmod(clusters, _RADAU_COLLOCATION_TIMES)
            if remainder or attempts < 1:
                self.stats.attempt_count_anomalies += 1
                attempts = max(1, round(clusters / _RADAU_COLLOCATION_TIMES))
            return attempts
        # An explicit Runge-Kutta attempt costs n_stages evaluations: stages 2 to n_stages and the end derivative.
        stages = self.method_class.n_stages
        attempts, remainder = divmod(calls, stages)
        if remainder or attempts < 1:
            self.stats.attempt_count_anomalies += 1
            attempts = max(1, round(calls / stages))
        return attempts

    def _commit(self, piece: _Piece) -> None:
        self.pieces.append(piece)
        if piece.kind == "event_bridge":
            self.stats.bridge_steps += 1
        else:
            self.stats.accepted[piece.kind] += 1
            self.stats.rejected_error_control += piece.attempts - 1
        self._accept_point(piece.t_new, piece.y_new, piece.kind)

    def _accept_point(self, t: float, y: NDArray[np.float64], kind: str) -> None:
        # The accepted ThermalState of design 6.3: only an accepted step creates it.
        self.accepted_state = ThermalState(self.run_id, t, y[:_N_NODES])
        state = np.array(y, dtype=float)
        self.points.append((t, state, kind, self._protection_index))
        self.t_accepted, self.y_accepted = t, state
        self._check_ranges(t, state, kind)

    def _check_ranges(self, t: float, state: NDArray[np.float64], kind: str) -> None:
        """Report accepted temperatures outside the declared node ranges (thermal design 5.4).

        Trial states are not results and stay silent; every accepted state is a result. One record per excursion of a
        node: it opens at the first accepted state outside the range and is extended until a state is back inside.
        """

        for index, node in enumerate(NODE_ORDER):
            value = float(state[index])
            low, high = self._ranges[index]
            entry = self._open_excursions.get(node)
            if low <= value <= high:
                if entry is not None:
                    entry["returned_s"] = t
                    del self._open_excursions[node]
                continue
            distance = low - value if value < low else value - high
            if entry is None:
                entry = {
                    "source": "accepted_states",
                    "time_s": t,
                    "node": node,
                    "value_K": value,
                    "range_K": (low, high),
                    "accepted_kind": kind,
                    "last_time_s": t,
                    "extreme_value_K": value,
                    "extreme_time_s": t,
                    "accepted_states": 1,
                    "returned_s": None,
                    "message": (
                        f"accepted state at time_s={t!r}: node {node} temperature {value!r} K is outside the declared "
                        f"range [{low!r}, {high!r}] K of its constant capacitance, resistance and optical properties "
                        "(design 5.4); last_time_s, extreme_value_K and returned_s give the extent of the excursion"
                    ),
                }
                self.range_warnings.append(entry)
                self._open_excursions[node] = entry
                continue
            entry["last_time_s"] = t
            entry["accepted_states"] += 1
            extreme = entry["extreme_value_K"]
            if distance > (low - extreme if extreme < low else extreme - high):
                entry["extreme_value_K"] = value
                entry["extreme_time_s"] = t

    # ------------------------------------------------------------------------------------------ charge-limit times

    @staticmethod
    def _reason_code(reason: str | None) -> str | None:
        return None if reason is None else reason.split(":", 1)[0].strip()

    def _limit_reason(self, t: float, y: NDArray[np.float64], context: str) -> str | None:
        """Power reason at an accepted (or dense-output) state with the current protection; None when unusable."""

        cached = self._last_power_reason
        if (cached is not None and cached[0] == t and cached[1] == self._protection_index
                and np.array_equal(cached[2], y)):
            self.stats.limit_reason_reuses += 1
            return cached[3]
        result = self._power_decision(t, y, context)
        if not result.valid or result.event_required:
            return None
        return str(getattr(result, "reason", ""))

    def _record_limit(
        self,
        t: float,
        y: NDArray[np.float64],
        reason: str,
        previous: str | None,
        source: str,
        segmented: bool,
        details: dict[str, Any],
    ) -> None:
        """Archive a start or end of charge limiting; not a protection event, apply_power_event is not called."""

        limited = self._reason_code(reason) == _CHARGE_LIMITED
        entry = {
            "time_s": t,
            "kind": "charge_limit_start" if limited else "charge_limit_end",
            "source": source,
            "protection_event": False,
            "segmented": segmented,
            "reason": reason,
            "previous_reason": previous,
            "state": [float(value) for value in y],
        }
        entry.update(details)
        self.limit_events.append(entry)
        self._limit_reason_text = reason

    def _track_limit(self, t: float, y: NDArray[np.float64], source: str, reasons: Sequence[str]) -> None:
        """Compare the Power reason at an accepted boundary instant with the last known one and record a change."""

        if self.power is None:
            return
        reason = self._limit_reason(t, y, "boundary")
        if reason is None:
            return
        previous = self._limit_reason_text
        limited = self._reason_code(reason) == _CHARGE_LIMITED
        was_limited = self._reason_code(previous) == _CHARGE_LIMITED
        if limited != was_limited:
            self._record_limit(
                t, y, reason, previous, source, True,
                {"instant_reasons": list(reasons), "bracket_s": [t, t], "bisection_iterations": 0, "located": True},
            )
        else:
            self._limit_reason_text = reason

    def _limit_crossing(
        self, piece: _Piece
    ) -> tuple[float, NDArray[np.float64], str, str, dict[str, Any]] | None:
        """Located change of charge limiting inside an accepted step, or None.

        The Power reason at the step end is compared with the last known one; on a change the crossing is bisected on
        the step's dense output to within ``event_time_tol_s`` (Power design 4.6 and table 7). Returns the first
        instant with the new reason, the state there, its reason, the reason at the step end and the search record.
        """

        if self.power is None:
            return None
        new_reason = self._limit_reason(piece.t_new, piece.y_new, "boundary")
        previous = self._limit_reason_text
        if new_reason is None:
            return None
        was_limited = self._reason_code(previous) == _CHARGE_LIMITED
        if previous is None or (self._reason_code(new_reason) == _CHARGE_LIMITED) == was_limited:
            self._limit_reason_text = new_reason
            return None
        self.stats.limit_searches += 1
        tolerance = self.settings.event_time_tol_s
        low, high = piece.t_old, piece.t_new
        high_state, high_reason = piece.y_new, new_reason
        iterations = 0
        while high - low > tolerance:
            middle = low + 0.5 * (high - low)
            if middle - low <= _gap_tolerance(middle):
                break
            iterations += 1
            state = np.array(piece.dense(middle), dtype=float)
            reason = self._limit_reason(middle, state, "event_location")
            if reason is not None and (self._reason_code(reason) == _CHARGE_LIMITED) == was_limited:
                low = middle
            else:
                high, high_state, high_reason = middle, state, reason
        self.stats.limit_bisection_iterations += iterations
        located = high_reason is not None
        if not located:
            # An unusable Power decision inside the step: the change is recorded at the step end.
            high, high_state, high_reason = piece.t_new, piece.y_new, new_reason
        search = {"bracket_s": [low, high], "bisection_iterations": iterations, "located": located}
        return high, np.array(high_state, dtype=float), high_reason, new_reason, search

    def _commit_tracked(self, piece: _Piece, split: bool) -> tuple[float, NDArray[np.float64]] | None:
        """Commit an accepted step after checking it for a start or end of charge limiting.

        With ``split`` (integration steps) the step is ended at the located crossing, which becomes an accepted state,
        and the instant and state are returned so that a new solver restarts there (Power design chapter 7: device
        boundaries set the segmentation times). Without it (steps of an event search) the crossing is only recorded.
        """

        crossing = self._limit_crossing(piece)
        if crossing is None:
            self._commit(piece)
            return None
        moment, state, reason, end_reason, search = crossing
        previous = self._limit_reason_text
        restart = None
        if split:
            if moment < piece.t_new:
                piece = _Piece(piece.t_old, moment, piece.y_old, state, piece.dense, piece.protection, piece.kind,
                               piece.solver_id, piece.attempts)
                end_reason = reason
            restart = (piece.t_new, piece.y_new.copy())
            self.stats.limit_splits += 1
        self._commit(piece)
        self._record_limit(moment, state, reason, previous, "located", split, search)
        self._limit_reason_text = end_reason
        return restart

    # --------------------------------------------------------------------------------------------- Power events

    def _instant(self, t: float, y: NDArray[np.float64], commands: list[LoadCommand], reasons: list[str]) -> None:
        """Boundary instant: Power decision with the accepted state, events and recomputation (Power design 6.3)."""

        if self.power is None:
            return
        decision = self._power_decision(t, y, "boundary")
        if not decision.valid:
            raise _StopRun(self._invalid_record(t, "boundary", decision, y))
        events: list[Any] = []
        sources: list[str] = []
        if decision.event_required:
            if not self._is_shortfall(decision):
                raise _StopRun(self._boundary_record(t, "boundary", decision, y, {"instant_reasons": list(reasons)}))
            events.append(self._supply_loss(t))
            sources.append("boundary_decision")
        interface = self.power.interface
        for command in commands:
            events.append(
                interface.PowerEvent(
                    kind=command.kind,
                    command_id=command.command_id,
                    accepted=True,
                    run_id=self.run_id,
                    instance_id=self.instance_id,
                    time_s=t,
                )
            )
            sources.append("command")
        if events:
            self._apply_events(t, y, events, decision, sources, {"instant_reasons": list(reasons)})

    def _is_shortfall(self, decision: Any) -> bool:
        """A boundary decision with a protection rule: confirmed supply shortfall (Power design 4.5, 5.5)."""

        return self._reason_code(getattr(decision, "reason", None)) == _SUPPLY_SHORTFALL

    def _boundary_record(
        self, t: float, context: str, decision: Any, state: NDArray[np.float64], details: dict[str, Any]
    ) -> dict[str, Any]:
        reason = getattr(decision, "reason", None)
        return self._record(
            "device_boundary", t, context,
            f"Power reached a boundary at which it forms no valid operating state ({reason}); supply_loss applies only "
            "to a confirmed supply shortfall (Power design 4.5, 5.5), no protection rule covers this boundary and the "
            "run stops at the last accepted state inside it",
            state=state, power_reason=reason, **details,
        )

    def _supply_loss(self, t: float) -> Any:
        self._supply_losses += 1
        return self.power.interface.PowerEvent(
            kind="supply_loss",
            command_id=f"supply_loss-{self._supply_losses:04d}@{t!r}",
            accepted=True,
            run_id=self.run_id,
            instance_id=self.instance_id,
            time_s=t,
        )

    def _apply_events(
        self,
        t: float,
        y: NDArray[np.float64],
        events: list[Any],
        decision: Any,
        sources: list[str],
        details: dict[str, Any],
    ) -> None:
        """apply_power_event at an accepted instant, then Power is recomputed at the same instant."""

        before = self.protections[self._protection_index]
        state = self._power_state(t, y, before)
        payload = events[0] if len(events) == 1 else tuple(events)
        kinds = [event.kind for event in events]
        try:
            updated = self.power.apply_event(state, payload, decision)
        except Exception as exc:
            raise _StopRun(
                self._record("event_rejected", t, "boundary", f"apply_power_event rejected {kinds}: {exc}", state=y)
            ) from exc
        if getattr(updated, "x_n", None) != state.x_n or getattr(updated, "x_p", None) != state.x_p:
            raise _StopRun(
                self._record("event_rejected", t, "boundary",
                             f"apply_power_event changed the lithium fractions for {kinds}; they must be kept", state=y)
            )
        after = _Protection(
            bool(updated.load_connected), bool(updated.trip_latched), tuple(updated.handled_command_ids), t
        )
        self.protections.append(after)
        self._protection_index = len(self.protections) - 1
        recomputed = self._power_decision(t, y, "boundary")
        if not recomputed.valid:
            raise _StopRun(self._invalid_record(t, "boundary", recomputed, y))
        if recomputed.event_required:
            raise _StopRun(
                self._record(
                    "event_unresolved", t, "boundary",
                    f"Power still requires an event after applying {kinds}: {getattr(recomputed, 'reason', '?')}; "
                    "the declared protection rule cannot resolve this boundary",
                    state=y, power_reason=getattr(recomputed, "reason", None),
                )
            )
        summary = {
            "valid": bool(decision.valid),
            "event_required": bool(decision.event_required),
            "can_supply_request": bool(getattr(decision, "can_supply_request", False)),
            "reason": getattr(decision, "reason", None),
        }
        result = {name: _optional_float(getattr(recomputed, name, None)) for name in PORT_ORDER}
        result["reason"] = getattr(recomputed, "reason", None)
        for event, source in zip(events, sources, strict=True):
            entry = {
                "time_s": t,
                "kind": event.kind,
                "command_id": event.command_id,
                "source": source,
                "decision": summary,
                "before": {"load_connected": before.load_connected, "trip_latched": before.trip_latched},
                "after": {"load_connected": after.load_connected, "trip_latched": after.trip_latched},
                "recomputed": result,
                "state": [float(value) for value in y],
            }
            entry.update(details)
            self.events.append(entry)
        self.stats.applied_events += len(events)

    def _locate_event(
        self, t_n: float, y_n: NDArray[np.float64], signal: _PowerEventSignal, end: float
    ) -> tuple[float, NDArray[np.float64]]:
        """Bisection for the Power boundary after a trial required an event (Power design 5.5, 6.3).

        Sub-integrations from the last accepted state that see no event are accepted; those that do are discarded.
        The final interval of at most ``event_time_tol_s`` is bridged with one explicit Euler step and the decision is
        evaluated there. A confirmed supply shortfall accepts the bridged state and applies the supply-loss event at
        that instant; any other boundary decision stops the run at the last state inside the bound (Power design 4.5).
        """

        self.stats.event_searches += 1
        tolerance = self.settings.event_time_tol_s
        low, y_low = t_n, y_n
        high = min(max(signal.time_s, t_n), end)
        iterations = 0
        while high - low > tolerance:
            middle = low + 0.5 * (high - low)
            if middle - low <= _gap_tolerance(middle):
                break
            iterations += 1
            pieces = self._sub_integrate(low, y_low, middle)
            if not pieces:
                high = middle
            else:
                for piece in pieces:
                    self._commit_tracked(piece, split=False)
                low, y_low = middle, pieces[-1].y_new
        self.stats.bisection_iterations += iterations
        search = {
            "bracket_s": [low, high],
            "bisection_iterations": iterations,
            "trial_time_s": signal.time_s,
            "trial_reason": getattr(signal.result, "reason", None),
        }
        try:
            rate = self._evaluate(low, y_low, self._protection_index, "event_location")
        except _PowerEventSignal:
            # The accepted state itself requires the event: the boundary is at ``low``.
            search["bracket_s"] = [low, low]
            decision = self._power_decision(low, y_low, "boundary")
            if not decision.valid:
                raise _StopRun(self._invalid_record(low, "boundary", decision, y_low)) from None
            return self._accept_located(low, y_low, decision, search)
        y_high = y_low + (high - low) * rate if high > low else y_low
        # Decision with the boundary state (design 6.3: accept the state there, then decide). A bridged state past a
        # bound without a protection rule is not accepted: the run stops at ``low``, the last state inside the bound.
        decision = self._power_decision(high, y_high, "boundary")
        if not decision.valid:
            raise _StopRun(self._invalid_record(high, "boundary", decision, y_high))
        if decision.event_required and not self._is_shortfall(decision):
            raise _StopRun(self._boundary_record(low, "event_location", decision, y_low, search))
        if high > low:
            self._commit_tracked(
                _Piece(low, high, y_low.copy(), y_high, _LinearDense(low, high, y_low.copy(), y_high.copy()),
                       self._protection_index, "event_bridge", -1, 1),
                split=False,
            )
        if decision.event_required:
            return self._accept_located(high, y_high, decision, search)
        self.stats.unconfirmed_event_searches += 1
        if high <= t_n:
            raise _StopRun(
                self._record(
                    "event_location_stalled", t_n, "event_location",
                    "Power required an event only in trial evaluations at the accepted instant itself (for example "
                    "Jacobian perturbations) while the accepted state needs none; the run cannot advance",
                    state=y_n, power_reason=search["trial_reason"],
                )
            )
        if self.stats.unconfirmed_event_searches > _MAX_UNCONFIRMED_SEARCHES:
            raise _StopRun(
                self._record(
                    "event_location_failed", high, "event_location",
                    f"more than {_MAX_UNCONFIRMED_SEARCHES} event searches ended without a confirmed boundary",
                    state=y_high,
                )
            )
        return high, y_high

    def _sub_integrate(
        self, t: float, y: NDArray[np.float64], end: float
    ) -> list[_Piece] | None:
        """Integrate from an accepted state to ``end``; None when a trial on the way requires an event."""

        pieces: list[_Piece] = []
        try:
            solver, counter = self._new_solver(t, y, end, "event_location", None)
            while solver.status == "running":
                pieces.append(self._step(solver, counter, "event_location"))
        except _PowerEventSignal:
            self.stats.event_aborted_attempts += 1
            self.stats.discarded_search_steps += len(pieces)
            self.stats.discarded_search_rejections += sum(piece.attempts - 1 for piece in pieces)
            return None
        return pieces

    def _accept_located(
        self, t: float, y: NDArray[np.float64], decision: Any, search: dict[str, Any]
    ) -> tuple[float, NDArray[np.float64]]:
        if not self._is_shortfall(decision):
            raise _StopRun(self._boundary_record(t, "event_location", decision, y, search))
        self.stats.located_events += 1
        self._apply_events(t, y, [self._supply_loss(t)], decision, ["located"], search)
        return t, y

    # ------------------------------------------------------------------------------------------------- evaluation

    def _request(self, t: float) -> float:
        request = self.power.request_W
        value = request(t) if callable(request) else request
        return _nonnegative(value, f"P_request_W at time_s={t!r}", _EvaluationError)

    def _power_state(self, t: float, y: NDArray[np.float64], protection: _Protection) -> Any:
        return self.power.interface.PowerState(
            run_id=self.run_id,
            instance_id=self.instance_id,
            time_s=t,
            x_n=float(y[_N_NODES]),
            x_p=float(y[_N_NODES + 1]),
            load_connected=protection.load_connected,
            trip_latched=protection.trip_latched,
            handled_command_ids=protection.handled_command_ids,
        )

    def _call_power(
        self, t: float, y: NDArray[np.float64], protection: _Protection, sample: EnvironmentSample, request: float,
        context: str,
    ) -> Any:
        """solve_power_allocation with the trial lithium fractions and T_B_K = trial temperature of B."""

        interface = self.power.interface
        environment = sample.power_environment
        if self.provider.power_interface is not interface:
            # Same orbit and attitude result, recorded with the Power interface of this coupling.
            orbit = sample.orbit_input
            environment = interface.PowerEnvironment(
                G_W_m2=orbit["G_W_m2"],
                position_m=orbit["position_m"],
                sun_position_m=orbit["sun_position_m"],
                quaternion_xyzw=orbit["quaternion_xyzw"],
                frame=orbit["frame"],
            )
        inputs = interface.PowerInputs(
            run_id=self.run_id,
            instance_id=self.instance_id,
            time_s=t,
            environment=environment,
            P_request_W=request,
            T_B_K=float(y[_B_INDEX]),
        )
        state = self._power_state(t, y, protection)
        self.stats.power_calls[context] += 1
        result = self.power.solve(inputs, state, self.power.parameters)
        for name in ("valid", "event_required"):
            if not hasattr(result, name):
                raise _EvaluationError(f"Power result at time_s={t!r} has no field {name!r} ({type(result).__name__})")
        for name, expected in (("run_id", self.run_id), ("time_s", t)):
            value = getattr(result, name, expected)
            if value != expected:
                raise _EvaluationError(
                    f"Power result {name} {value!r} differs from the trial {name} {expected!r}; the environment and "
                    "the four ports must share one instant"
                )
        return result

    def _power_decision(self, t: float, y: NDArray[np.float64], context: str) -> Any:
        """Power evaluation at an accepted instant with the current protection state."""

        self._last_evaluation = (t, context)
        sample = self.provider.sample(t)
        result = self._call_power(t, y, self.protections[self._protection_index], sample, self._request(t), context)
        if result.valid and not result.event_required:
            self._last_power_reason = (
                t, self._protection_index, np.array(y, dtype=float), str(getattr(result, "reason", ""))
            )
        if self.trial_hook is not None:
            outcome = "invalid" if not result.valid else ("event_required" if result.event_required else "ok")
            self.trial_hook(
                TrialRecord(self.run_id, t, context, outcome, -1, _readonly(np.array(y, dtype=float)), None,
                            getattr(result, "reason", None))
            )
        return result

    def _result_values(self, result: Any, t: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
        values = []
        for name in (*PORT_ORDER, "dx_n_dt", "dx_p_dt"):
            value = getattr(result, name, None)
            if value is None:
                raise _EvaluationError(
                    f"Power result at time_s={t!r} is valid and needs no event but carries no {name}"
                )
            values.append(_number(value, f"Power result {name} at time_s={t!r}", _EvaluationError))
        return tuple(values[: len(PORT_ORDER)]), tuple(values[len(PORT_ORDER):])

    def _prescribed(self, t: float) -> tuple[float, ...]:
        ports = self.prescribed_ports(t)  # type: ignore[misc]
        where = f"prescribed_ports({t!r})"
        if not isinstance(ports, Mapping):
            raise _EvaluationError(f"{where} must return a mapping with {PORT_ORDER}, got {type(ports).__name__}")
        missing = [name for name in PORT_ORDER if name not in ports]
        if missing:
            raise _EvaluationError(f"{where} is missing port(s) {missing}")
        unknown = [str(name) for name in ports if name not in PORT_ORDER]
        if unknown:
            raise _EvaluationError(f"{where} has unknown port(s) {unknown}; the ports are {PORT_ORDER}")
        return tuple(_number(ports[name], f"{where}[{name!r}]", _EvaluationError) for name in PORT_ORDER)

    def _evaluate(
        self,
        t: float,
        y: NDArray[np.float64],
        protection: int,
        context: str,
        solver_id: int = -1,
        details: bool = False,
    ) -> Any:
        """One trial of the coupled model: ThermalState, environment, Power or prescribed ports, thermal_derivative."""

        self.stats.evaluations[context] += 1
        self._last_evaluation = (t, context)
        outcome = "ok"
        thermal_state = None
        power_result = None
        try:
            thermal_state = ThermalState(self.run_id, t, y[:_N_NODES])
            sample = self.provider.sample(t)
            request = None
            if self.power is not None:
                request = self._request(t)
                power_result = self._call_power(t, y, self.protections[protection], sample, request, context)
                if not power_result.valid:
                    outcome = "invalid"
                    raise _PowerInvalidSignal(t, y, power_result, context)
                if power_result.event_required:
                    outcome = "event_required"
                    raise _PowerEventSignal(t, y, power_result, context)
                ports, rates = self._result_values(power_result, t)
                self._last_power_reason = (
                    t, protection, np.array(y, dtype=float), str(getattr(power_result, "reason", ""))
                )
            else:
                ports, rates = self._prescribed(t), ()
            inputs = ThermalInputs(self.run_id, t, sample.surface_environment, *ports)
            evaluation = thermal_derivative(thermal_state, inputs, self.parameters)
            derivative = np.empty(self.n_state)
            derivative[:_N_NODES] = evaluation.dT_dt_K_s
            derivative[_N_NODES:] = rates
        except _PowerSignal:
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            if self.trial_hook is not None:
                self.trial_hook(
                    TrialRecord(self.run_id, t, context, outcome, solver_id, _readonly(np.array(y, dtype=float)),
                                thermal_state, getattr(power_result, "reason", None))
                )
        if details:
            return _Evaluation(derivative, evaluation, power_result, ports, sample, request)
        return derivative

    # ---------------------------------------------------------------------------------------------- error records

    def _record(self, kind: str, t: float, context: str, message: str, **extra: Any) -> dict[str, Any]:
        record = {"kind": kind, "time_s": t, "context": context, "message": message,
                  "last_accepted_time_s": self.t_accepted}
        for key, value in extra.items():
            record[key] = value.tolist() if isinstance(value, np.ndarray) else value
        return record

    def _invalid_record(self, t: float, context: str, result: Any, state: ArrayLike) -> dict[str, Any]:
        reason = getattr(result, "reason", None)
        return self._record(
            "power_invalid", t, context,
            f"Power returned valid=False ({reason}); the input or numerical error is reported, no physical-boundary "
            "protection is applied and the run stops (thermal design 5.6, Power design 5.5)",
            state=np.array(state, dtype=float), power_reason=reason,
        )

    # ------------------------------------------------------------------------------------------------- the archive

    def _archive(self, status: str, error: dict[str, Any] | None, started: float) -> CoupledArchive:
        solution = _PiecewiseSolution(
            self.t_start, self.y0.copy(), self._initial_protection_index, self.pieces, self.y_accepted.copy(),
            self._protection_index,
        )
        outputs = self._sample_outputs(solution)
        audit = self._energy_audit() if self.energy_audit and self.pieces else None
        if self.range_warnings:
            warnings.warn(
                f"run {self.run_id!r}: {len(self.range_warnings)} record(s) of accepted-state excursions or output "
                "samples with temperatures outside the declared ranges of the node constants; see "
                "archive.range_warnings (design 5.4)",
                ThermalRangeWarning,
                stacklevel=4,
            )
        final_thermal = ThermalState(self.run_id, self.t_accepted, self.y_accepted[:_N_NODES])
        final_power = None
        if self.power is not None:
            final_power = self._power_state(self.t_accepted, self.y_accepted, self.protections[self._protection_index])
        accepted = {
            "time_s": np.array([point[0] for point in self.points]),
            "state": np.array([point[1] for point in self.points]),
            "kind": tuple(point[2] for point in self.points),
        }
        if self.power is not None:
            accepted["load_connected"] = np.array([self.protections[point[3]].load_connected for point in self.points])
            accepted["trip_latched"] = np.array([self.protections[point[3]].trip_latched for point in self.points])
        steps = {
            "t_old_s": np.array([piece.t_old for piece in self.pieces], dtype=float),
            "t_new_s": np.array([piece.t_new for piece in self.pieces], dtype=float),
            "kind": tuple(piece.kind for piece in self.pieces),
            "solver_id": np.array([piece.solver_id for piece in self.pieces], dtype=int),
            "attempts": np.array([piece.attempts for piece in self.pieces], dtype=int),
        }
        statistics = self._statistics(outputs, time.perf_counter() - started)
        notes = list(self.notes)
        if isinstance(self.provider.earth_flux, EarthFluxModel) and not self.provider.earth_flux.enabled:
            notes.append(f"Earth albedo and infrared switched off: {self.provider.earth_flux.disabled_reason}")
        notes.append(
            "ThermalRangeWarning is not emitted for trial states; every accepted state is checked against the declared "
            "node ranges and excursions, like out-of-range output samples, are recorded in range_warnings"
        )
        return CoupledArchive(
            run_id=self.run_id,
            epoch=self.provider.epoch,
            status=status,
            error=MappingProxyType(dict(error)) if error is not None else None,
            t_start_s=self.t_start,
            t_end_s=self.t_end,
            time_s=outputs["time_s"],
            temperature_K=outputs["temperature_K"],
            dT_dt_K_s=outputs["dT_dt_K_s"],
            ports_W=MappingProxyType(outputs["ports_W"]),
            q_W=outputs["q_W"],
            Q_env_W=outputs["Q_env_W"],
            Q_emit_W=outputs["Q_emit_W"],
            lithium=MappingProxyType(outputs["lithium"]) if outputs["lithium"] is not None else None,
            power_diagnostics=(
                MappingProxyType(outputs["power_diagnostics"]) if outputs["power_diagnostics"] is not None else None
            ),
            environment=MappingProxyType(outputs["environment"]),
            sample_valid=outputs["sample_valid"],
            accepted=MappingProxyType(self._frozen_arrays(accepted)),
            steps=MappingProxyType(self._frozen_arrays(steps)),
            events=tuple(MappingProxyType(entry) for entry in self.events),
            limit_events=tuple(MappingProxyType(entry) for entry in self.limit_events),
            eclipse_boundaries=self.eclipse_boundaries,
            segments=tuple(MappingProxyType(entry) for entry in self.segment_records),
            solver_settings=MappingProxyType(self.settings.as_dict()),
            statistics=MappingProxyType(statistics),
            energy_audit=MappingProxyType(audit) if audit is not None else None,
            provenance=MappingProxyType(self._provenance()),
            instance_map=MappingProxyType(_plain(self.parameters.instance_map)),
            range_warnings=tuple(MappingProxyType(entry) for entry in self.range_warnings),
            notes=tuple(notes),
            final_thermal_state=final_thermal,
            final_power_state=final_power,
            _solution=solution,
        )

    @staticmethod
    def _frozen_arrays(record: dict[str, Any]) -> dict[str, Any]:
        for value in record.values():
            if isinstance(value, np.ndarray):
                value.setflags(write=False)
        return record

    def _sample_outputs(self, solution: _PiecewiseSolution) -> dict[str, Any]:
        """Samples of the accepted solution at ``output_step_s``, evaluated with the coupled model."""

        times = _output_grid(self.t_start, self.t_accepted, self.settings.output_step_s)
        count = times.size
        temperature = np.full((count, _N_NODES), _NAN)
        derivative = np.full((count, _N_NODES), _NAN)
        flows = np.full((count, len(PATH_ORDER)), _NAN)
        absorbed = np.full((count, len(EXPOSED_NODES)), _NAN)
        emitted = np.full((count, len(EXPOSED_NODES)), _NAN)
        ports = {name: np.full(count, _NAN) for name in PORT_ORDER}
        irradiance = np.full(count, _NAN)
        illumination = np.full(count, _NAN)
        valid = np.zeros(count, dtype=bool)
        power = self.power is not None
        if power:
            x_n = np.full(count, _NAN)
            x_p = np.full(count, _NAN)
            diagnostics: dict[str, Any] = {
                name: np.full(count, _NAN)
                for name in ("P_request_W", "P_pv_max_W", "P_bus_W", "I_B_A", "V_B_V", "v_cell_V", "P_B_W", "SOC")
            }
            diagnostics["load_connected"] = np.zeros(count, dtype=bool)
            diagnostics["trip_latched"] = np.zeros(count, dtype=bool)
            reasons: list[str | None] = [None] * count
            soc = getattr(getattr(self.power.parameters, "battery", None), "soc", None)
        for index, moment in enumerate(times):
            moment = float(moment)
            state, protection = solution.locate(moment)
            temperature[index] = state[:_N_NODES]
            if power:
                x_n[index], x_p[index] = state[_N_NODES], state[_N_NODES + 1]
                flags = self.protections[protection]
                diagnostics["load_connected"][index] = flags.load_connected
                diagnostics["trip_latched"][index] = flags.trip_latched
                if callable(soc):
                    diagnostics["SOC"][index] = _optional_float(soc(float(state[_N_NODES])))
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ThermalRangeWarning)
                try:
                    evaluation = self._evaluate(moment, state, protection, "output", details=True)
                except _PowerSignal as signal:
                    evaluation = None
                    message = f"output sample at {moment!r} s: Power result {getattr(signal.result, 'reason', '?')}"
                    self.notes.append(message)
                    if power:
                        reasons[index] = getattr(signal.result, "reason", None)
                except Exception as exc:  # noqa: BLE001  (a failed output sample is recorded, not fatal)
                    evaluation = None
                    self.notes.append(
                        f"output sample at {moment!r} s could not be evaluated: {type(exc).__name__}: {exc}"
                    )
            for item in caught:
                if issubclass(item.category, ThermalRangeWarning):
                    self.range_warnings.append(
                        {"source": "output_sample", "time_s": moment, "message": str(item.message)}
                    )
                else:
                    warnings.warn_explicit(item.message, item.category, item.filename, item.lineno)
            if evaluation is None:
                continue
            valid[index] = True
            thermal = evaluation.thermal
            derivative[index] = thermal.dT_dt_K_s
            flows[index] = thermal.q_W
            absorbed[index] = thermal.Q_env_W
            emitted[index] = thermal.Q_emit_W
            for name, value in zip(PORT_ORDER, evaluation.ports, strict=True):
                ports[name][index] = value
            irradiance[index] = evaluation.sample.G_W_m2
            illumination[index] = evaluation.sample.illumination_fraction
            if power:
                result = evaluation.power
                solar = getattr(result, "solar", None)
                battery = getattr(result, "battery", None)
                diagnostics["P_request_W"][index] = _optional_float(evaluation.request_W)
                diagnostics["P_pv_max_W"][index] = _optional_float(getattr(solar, "P_pv_max_W", None))
                diagnostics["P_bus_W"][index] = _optional_float(getattr(result, "P_bus_W", None))
                for name in ("I_B_A", "V_B_V", "v_cell_V", "P_B_W"):
                    diagnostics[name][index] = _optional_float(getattr(battery, name, None))
                reasons[index] = getattr(result, "reason", None)
        lithium = None
        power_diagnostics = None
        if power:
            lithium = {"x_n": _readonly(x_n), "x_p": _readonly(x_p)}
            power_diagnostics = {name: _readonly(value) for name, value in diagnostics.items()}
            power_diagnostics["reason"] = tuple(reasons)
        return {
            "time_s": _readonly(times),
            "temperature_K": _readonly(temperature),
            "dT_dt_K_s": _readonly(derivative),
            "ports_W": {name: _readonly(value) for name, value in ports.items()},
            "q_W": _readonly(flows),
            "Q_env_W": _readonly(absorbed),
            "Q_emit_W": _readonly(emitted),
            "lithium": lithium,
            "power_diagnostics": power_diagnostics,
            "environment": {
                "G_W_m2": _readonly(irradiance),
                "illumination_fraction": _readonly(illumination),
            },
            "sample_valid": _readonly(valid),
        }

    def _energy_audit(self) -> dict[str, Any]:
        """T1 closure over the run: sum C_i (T_i(end) - T_i(start)) against the integral of the T1 right side.

        The right side is evaluated with the coupled model at three Gauss-Legendre nodes of every accepted step on its
        dense output; the boundaries are step ends, so each integrand is smooth on its step.
        """

        nodes, weights = np.polynomial.legendre.leggauss(_GAUSS_POINTS)
        capacitance = np.array(self.parameters.C_J_K, dtype=float)
        term_parts: list[list[float]] = [[] for _ in _T1_TERMS]
        stored_rate_parts: list[float] = []
        worst_pointwise = 0.0
        failures = 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ThermalRangeWarning)
            for piece in self.pieces:
                width = piece.t_new - piece.t_old
                if width <= 0.0:
                    continue
                for node, weight in zip(nodes, weights, strict=True):
                    moment = piece.t_old + 0.5 * width * (1.0 + float(node))
                    state = np.array(piece.dense(moment), dtype=float)
                    try:
                        evaluation = self._evaluate(moment, state, piece.protection, "energy_audit", details=True)
                    except _PowerSignal:
                        failures += 1
                        continue
                    except Exception:  # noqa: BLE001  (counted; the audit reports it)
                        failures += 1
                        continue
                    thermal = evaluation.thermal
                    p_pv, p_load, q_b, q_d = evaluation.ports
                    values = np.array([thermal.Q_env_W[0], thermal.Q_env_W[1], p_pv, p_load, q_b, q_d,
                                       thermal.Q_emit_W[0], thermal.Q_emit_W[1]])
                    factor = 0.5 * width * float(weight)
                    for part, value in zip(term_parts, values, strict=True):
                        part.append(factor * float(value))
                    stored_rate = float(np.dot(capacitance, thermal.dT_dt_K_s))
                    stored_rate_parts.append(factor * stored_rate)
                    right_side = float(np.dot(_T1_SIGNS, values))
                    scale = float(np.sum(np.abs(values)))
                    mismatch = abs(stored_rate - right_side)
                    worst_pointwise = max(worst_pointwise, mismatch / scale if scale > 0.0 else mismatch)
        terms = {name: math.fsum(part) for name, part in zip(_T1_TERMS, term_parts, strict=True)}
        right_side_integral = math.fsum(sign * terms[name] for name, sign in zip(_T1_TERMS, _T1_SIGNS, strict=True))
        gross = math.fsum(abs(value) for value in terms.values())
        start = np.array(self.y0[:_N_NODES], dtype=float)
        end = np.array(self.y_accepted[:_N_NODES], dtype=float)
        stored = math.fsum(float(c) * (float(b) - float(a)) for c, a, b in zip(capacitance, start, end, strict=True))
        content = math.fsum(float(c) * float(a) for c, a in zip(capacitance, start, strict=True))
        residual = stored - right_side_integral
        return {
            "method": (
                f"{_GAUSS_POINTS}-point Gauss-Legendre quadrature on the dense output of every accepted step; T1 right "
                "side Q_env,S + Q_env,R - P_pv + P_load + Q_B + Q_D - Q_emit,S - Q_emit,R from the coupled model; "
                "stored change sum C_i (T_i(end) - T_i(start)) from the accepted states"
            ),
            "interval_s": [self.t_start, self.t_accepted],
            "stored_energy_change_J": stored,
            "integral_sum_C_dT_dt_J": math.fsum(stored_rate_parts),
            "integral_T1_right_side_J": right_side_integral,
            "terms_J": terms,
            "gross_throughput_J": gross,
            "stored_energy_content_J": content,
            "residual_J": residual,
            "relative_residual": abs(residual) / gross if gross > 0.0 else abs(residual),
            "residual_relative_to_energy_content": abs(residual) / content,
            "max_pointwise_relative_T1_mismatch": worst_pointwise,
            "failed_nodes": failures,
            "accepted_steps": len(self.pieces),
        }

    def _statistics(self, outputs: dict[str, Any], wall_time_s: float) -> dict[str, Any]:
        stats = self.stats
        if self.settings.method == "Radau":
            rule = (
                "Radau: each attempt evaluates the three collocation times t + c_i h; attempts per accepted step are "
                "the distinct evaluation times after the step start divided by three; rejected = attempts - 1"
            )
        else:
            rule = (
                f"{self.settings.method}: each attempt costs n_stages = {self.method_class.n_stages} evaluations; "
                "attempts per accepted step are its evaluations divided by n_stages; rejected = attempts - 1"
            )
        rejected_total = (
            stats.rejected_error_control
            + stats.event_aborted_attempts
            + stats.discarded_search_steps
            + stats.discarded_search_rejections
        )
        return {
            "accepted_steps": sum(stats.accepted.values()),
            "accepted_steps_by_context": {
                name: stats.accepted.get(name, 0) for name in ("integration", "event_location")
            },
            "bridge_steps": stats.bridge_steps,
            "accepted_states": len(self.points),
            "rejected_steps": stats.rejected_error_control,
            "event_aborted_attempts": stats.event_aborted_attempts,
            "discarded_event_search_steps": stats.discarded_search_steps,
            "discarded_event_search_rejections": stats.discarded_search_rejections,
            "rejected_steps_total": rejected_total,
            "rejected_step_rule": rule,
            "attempt_count_anomalies": stats.attempt_count_anomalies,
            "function_evaluations": sum(stats.evaluations.values()),
            "function_evaluations_by_context": {name: stats.evaluations.get(name, 0) for name in EVALUATION_CONTEXTS},
            "solver_construction_evaluations": stats.construction_evaluations,
            "power_calls": sum(stats.power_calls.values()),
            "power_calls_by_context": {name: stats.power_calls.get(name, 0) for name in EVALUATION_CONTEXTS},
            "solver_instances": stats.solver_instances,
            "solver_nfev": int(sum(solver.nfev for solver in self._solvers)),
            "solver_njev": int(sum(solver.njev for solver in self._solvers)),
            "solver_nlu": int(sum(solver.nlu for solver in self._solvers)),
            "segments": len(self.segment_records),
            "eclipse_boundaries": len(self.eclipse_boundaries),
            "event_searches": stats.event_searches,
            "located_events": stats.located_events,
            "unconfirmed_event_searches": stats.unconfirmed_event_searches,
            "bisection_iterations": stats.bisection_iterations,
            "applied_events": stats.applied_events,
            "charge_limit_transitions": len(self.limit_events),
            "charge_limit_searches": stats.limit_searches,
            "charge_limit_bisection_iterations": stats.limit_bisection_iterations,
            "charge_limit_splits": stats.limit_splits,
            "charge_limit_reason_reuses": stats.limit_reason_reuses,
            "range_excursions_accepted_states": sum(
                1 for entry in self.range_warnings if entry.get("source") == "accepted_states"
            ),
            "output_samples": int(outputs["time_s"].size),
            "invalid_output_samples": int(np.count_nonzero(~outputs["sample_valid"])),
            "wall_time_s": wall_time_s,
        }

    def _provenance(self) -> dict[str, Any]:
        thermal_values = {
            "C_J_K": dict(zip(NODE_ORDER, (float(value) for value in self.parameters.C_J_K), strict=True)),
            "R_K_W": dict(zip(PATH_ORDER, (float(value) for value in self.parameters.R_K_W), strict=True)),
            "surfaces": [_plain(surface) for surface in self.parameters.surfaces],
        }
        power = None
        if self.power is not None:
            parameters = self.power.parameters
            state = self.power.initial_state
            request = self.power.request_W
            power = {
                "interface": _callable_name(self.power.interface),
                "solve": _callable_name(self.power.solve),
                "apply_event": _callable_name(self.power.apply_event),
                "instance_id": self.instance_id,
                "parameters_provenance": _plain(getattr(parameters, "provenance", None)),
                "resolved_parameters": {
                    name: _plain(getattr(parameters, name, None))
                    for name in ("solar", "battery", "eta_D", "links", "numerics")
                },
                "initial_state": {
                    "time_s": state.time_s,
                    "x_n": state.x_n,
                    "x_p": state.x_p,
                    "load_connected": state.load_connected,
                    "trip_latched": state.trip_latched,
                    "handled_command_ids": list(state.handled_command_ids),
                },
                "request_W": _callable_name(request) if callable(request) else request,
                "commands": [
                    {"time_s": command.time_s, "kind": command.kind, "command_id": command.command_id}
                    for command in self.commands
                ],
            }
        return _plain(
            {
                "procedure": {
                    "module": __name__,
                    "design": (
                        "thermal design chapters 7 and 8 with table 8; Power design chapters 7 and 8 with table 7"
                    ),
                    "state_vector": list(NODE_ORDER) + (list(LITHIUM_ORDER) if self.power is not None else []),
                    "segmentation": (
                        "eclipse boundaries from the environment provider, load commands, declared input "
                        "discontinuities, located Power events and located starts and ends of charge limiting "
                        "(a step that crosses one is ended at the crossing and the solver restarts there)"
                    ),
                    "event_location": (
                        "bisection of sub-integrations from the last accepted state to within event_time_tol_s, the "
                        "final interval bridged by one explicit Euler step"
                    ),
                    "orbit_power_considering_thermal": "not called; temperatures come only from the integrated state",
                },
                "thermal_parameters": self.parameters.provenance_as_dict(),
                "thermal_values": thermal_values,
                "environment": self.provider.describe(),
                "power": power,
                "prescribed_ports": (
                    _callable_name(self.prescribed_ports) if self.prescribed_ports is not None else None
                ),
                "declared_boundaries": [{"time_s": moment, "label": label} for moment, label in self.declared],
                "caller": self.caller_provenance,
                "software": _software(),
            }
        )


# ----------------------------------------------------------------------------------------------------------------------
# public entry point
# ----------------------------------------------------------------------------------------------------------------------


def run_coupled(
    parameters: ThermalParameters,
    initial_state: ThermalState,
    environment: EnvironmentProvider,
    t_end_s: float,
    *,
    settings: SolverSettings | None = None,
    power: PowerCoupling | None = None,
    prescribed_ports: Callable[[float], Mapping[str, float]] | None = None,
    boundaries_s: Sequence[float | tuple[float, str]] = (),
    energy_audit: bool = False,
    trial_hook: Callable[[TrialRecord], None] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> CoupledArchive:
    """Run the coupled procedure of thermal design chapters 7 and 8 from ``initial_state`` to ``t_end_s``.

    ``initial_state`` gives ``run_id``, the start time and the six initial temperatures; ``environment`` supplies the
    synchronized orbit, attitude, irradiance and Earth-flux inputs of the same run. Give exactly one of ``power`` (a
    :class:`PowerCoupling`; the lithium fractions join the state vector and ``settings`` default to the Power numerics
    with RK45, explicit settings must agree with them) or ``prescribed_ports`` (a thermal-only run: a function of
    ``time_s`` returning ``P_pv_W``, ``P_load_W``, ``Q_B_W`` and ``Q_D_W``; ``settings`` required).
    ``boundaries_s`` lists times (or ``(time, label)`` pairs) where a time-dependent input jumps; integration ends
    one floating-point step before such a time and restarts one step after it. ``energy_audit`` adds the T1 closure
    check to the archive, ``trial_hook`` receives a :class:`TrialRecord` for every evaluation and ``provenance`` is
    stored with the archive (for example the scene assembly).

    Returns the :class:`CoupledArchive`. A Power result with ``valid=False``, an unresolved event or any other trial
    failure raises :class:`CoupledRunError`, whose ``archive`` holds every accepted state up to the stop.
    """

    run = _CoupledRun(
        parameters,
        initial_state,
        environment,
        t_end_s,
        settings,
        power,
        prescribed_ports,
        boundaries_s,
        energy_audit,
        trial_hook,
        provenance,
    )
    return run.run()
