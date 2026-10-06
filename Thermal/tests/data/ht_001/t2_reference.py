"""Independent reference for HT-001: exact rational T2 and T5 written from the design report, and a read counter.

Nothing in this file imports the thermal package. Node and path names are written from design 1.4, 4.2 and table 6.
Temperatures and resistance inputs are converted to the exact fractions of the binary floating-point numbers that the
module receives, so a comparison measures only the rounding of the module's own arithmetic. The read counter is an
ndarray view that logs every element index read, used to count how often each path is evaluated in one call.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Any, Self

import numpy as np

NODES = ("S", "J", "C", "B", "D", "R")  # design 1.4, table 6: S, J, C, B, D, R
PATHS = ("SR", "JC", "CR", "BR", "DR")  # design 4.2, table 6: SR, JC, CR, BR, DR


def ends(path: str) -> tuple[str, str]:
    """First and second node of a path, read from the letters of its name (design 5.5)."""

    if len(path) != 2 or path[0] not in NODES or path[1] not in NODES:
        raise ValueError(f"not a path name: {path!r}")
    return path[0], path[1]


def degree() -> dict[str, int]:
    """Number of paths ending at each node."""

    count = {node: 0 for node in NODES}
    for path in PATHS:
        for node in ends(path):
            count[node] += 1
    return count


def exact(value: Any) -> Fraction:
    """Exact rational value of a float (or of a decimal string such as '0.5')."""

    if isinstance(value, str):
        return Fraction(value)
    return Fraction(float(value))


def t5_resistance(connection: Mapping[str, Any]) -> Fraction:
    """Second line of T5, R = l / (kappa A) + R_contact, or a supplied equivalent total (design 4.5)."""

    if "equivalent_total_resistance_K_W" in connection:
        total = exact(connection["equivalent_total_resistance_K_W"])
        if connection["includes_contact"]:
            return total
        return total + exact(connection["contact_resistance_K_W"])
    conduction = exact(connection["length_m"]) / (exact(connection["conductivity_W_mK"]) * exact(connection["area_m2"]))
    return conduction + exact(connection["contact_resistance_K_W"])


def t2_flows(temperature_K: Mapping[str, Any], resistance_K_W: Mapping[str, Fraction]) -> dict[str, Fraction]:
    """T2 for every path, q_ij = (T_i - T_j) / R_ij, in exact arithmetic and in design path order."""

    flows = {}
    for path in PATHS:
        first, second = ends(path)
        flows[path] = (exact(temperature_K[first]) - exact(temperature_K[second])) / resistance_K_W[path]
    return flows


def relative_error(value: Any, reference: Fraction) -> float:
    """|value - reference| / |reference| in exact arithmetic.

    A zero reference needs an exact zero: the error is 0.0 for value 0 and infinity otherwise. A non-finite value
    has infinite error.
    """

    number = float(value)
    if not np.isfinite(number):
        return float("inf")
    difference = abs(Fraction(number) - reference)
    if reference == 0:
        return 0.0 if difference == 0 else float("inf")
    return float(difference / abs(reference))


class ReadCounter(np.ndarray):
    """1-D float array view that appends to ``log`` every element index it is read at.

    Indexing by an integer, slice, index array or mask logs the covered indices; a ufunc applied to the whole array
    logs every index once. The values returned are those of a plain ndarray, so results are unchanged.
    """

    def __new__(cls, values: Any, log: list[int]) -> Self:
        obj = np.array(values, dtype=float).view(cls)
        obj._log = log
        return obj

    def __array_finalize__(self, obj: Any) -> None:
        self._log = getattr(obj, "_log", None)

    def __getitem__(self, key: Any) -> Any:
        plain = self.view(np.ndarray)
        if self._log is not None:
            covered = np.arange(plain.shape[0])[key]
            self._log.extend(int(index) for index in np.atleast_1d(covered))
        return plain[key]

    def __array_ufunc__(self, ufunc: Any, method: str, *inputs: Any, **kwargs: Any) -> Any:
        plain_inputs = []
        for item in inputs:
            if isinstance(item, ReadCounter):
                if item._log is not None:
                    item._log.extend(range(item.view(np.ndarray).shape[0]))
                plain_inputs.append(item.view(np.ndarray))
            else:
                plain_inputs.append(item)
        return getattr(ufunc, method)(*plain_inputs, **kwargs)
