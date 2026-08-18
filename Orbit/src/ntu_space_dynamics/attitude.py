"""Euler/YPR conversions and rigid-body Euler dynamics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.integrate import solve_ivp
from scipy.spatial.transform import Rotation

from .types import AttitudeEphemeris


def ypr_to_euler(
    yaw: float,
    pitch: float,
    roll: float,
    *,
    output_sequence: str = "XYZ",
    degrees: bool = False,
) -> NDArray[np.float64]:
    """Convert aerospace intrinsic yaw-pitch-roll (Z-Y-X) to another Euler sequence.

    Uppercase sequences are intrinsic and lowercase sequences are extrinsic,
    matching :class:`scipy.spatial.transform.Rotation`.
    """

    if len(output_sequence) != 3:
        raise ValueError("output_sequence must contain three axes")
    rotation = Rotation.from_euler("ZYX", [yaw, pitch, roll], degrees=degrees)
    return rotation.as_euler(output_sequence, degrees=degrees)


def euler_to_dcm(
    angles: ArrayLike, sequence: str = "XYZ", *, degrees: bool = False
) -> NDArray[np.float64]:
    """Return the active direction cosine matrix for an Euler sequence."""

    values = np.asarray(angles, dtype=float)
    if values.shape != (3,):
        raise ValueError("angles must have shape (3,)")
    return Rotation.from_euler(sequence, values, degrees=degrees).as_matrix()


TorqueFunction = Callable[[float, NDArray[np.float64], NDArray[np.float64]], ArrayLike]


@dataclass
class EulerDynamics:
    """Propagate a rigid body's quaternion and body angular velocity."""

    inertia_kg_m2: ArrayLike
    torque_body_nm: TorqueFunction | ArrayLike = (0.0, 0.0, 0.0)
    relative_tolerance: float = 1e-10
    absolute_tolerance: float = 1e-12

    def __post_init__(self) -> None:
        inertia = np.asarray(self.inertia_kg_m2, dtype=float)
        if inertia.shape == (3,):
            inertia = np.diag(inertia)
        if inertia.shape != (3, 3) or not np.allclose(inertia, inertia.T):
            raise ValueError("inertia_kg_m2 must be a symmetric (3,3) matrix or 3-vector")
        if np.min(np.linalg.eigvalsh(inertia)) <= 0.0:
            raise ValueError("inertia tensor must be positive definite")
        self.inertia_kg_m2 = inertia
        self._inverse_inertia = np.linalg.inv(inertia)
        if not callable(self.torque_body_nm):
            torque = np.asarray(self.torque_body_nm, dtype=float)
            if torque.shape != (3,):
                raise ValueError("constant torque must have shape (3,)")
            self.torque_body_nm = torque

    def _torque(self, time_s: float, quaternion: np.ndarray, rate: np.ndarray) -> np.ndarray:
        if callable(self.torque_body_nm):
            value = self.torque_body_nm(time_s, quaternion, rate)
        else:
            value = self.torque_body_nm
        result = np.asarray(value, dtype=float)
        if result.shape != (3,):
            raise ValueError("torque function must return shape (3,)")
        return result

    def derivative(self, time_s: float, state: ArrayLike) -> NDArray[np.float64]:
        values = np.asarray(state, dtype=float)
        if values.shape != (7,):
            raise ValueError("attitude state must be [qx,qy,qz,qw,wx,wy,wz]")
        quaternion = values[:4] / np.linalg.norm(values[:4])
        rate = values[4:]
        qx, qy, qz, qw = quaternion
        wx, wy, wz = rate
        quaternion_derivative = 0.5 * np.array(
            [
                qw * wx + qy * wz - qz * wy,
                qw * wy + qz * wx - qx * wz,
                qw * wz + qx * wy - qy * wx,
                -qx * wx - qy * wy - qz * wz,
            ]
        )
        angular_momentum = self.inertia_kg_m2 @ rate
        rate_derivative = self._inverse_inertia @ (
            self._torque(time_s, quaternion, rate) - np.cross(rate, angular_momentum)
        )
        return np.concatenate((quaternion_derivative, rate_derivative))

    def propagate(
        self,
        initial_quaternion_xyzw: ArrayLike,
        initial_angular_velocity_body_rad_s: ArrayLike,
        times_s: ArrayLike,
    ) -> AttitudeEphemeris:
        quaternion = np.asarray(initial_quaternion_xyzw, dtype=float)
        rate = np.asarray(initial_angular_velocity_body_rad_s, dtype=float)
        times = np.asarray(times_s, dtype=float)
        if quaternion.shape != (4,) or np.linalg.norm(quaternion) == 0.0:
            raise ValueError("initial_quaternion_xyzw must be a non-zero 4-vector")
        if rate.shape != (3,):
            raise ValueError("initial angular velocity must have shape (3,)")
        if times.ndim != 1 or len(times) == 0 or np.any(np.diff(times) <= 0.0):
            raise ValueError("times_s must be a non-empty strictly increasing array")
        if times[0] < 0.0:
            raise ValueError("times_s must start at or after zero")
        initial = np.concatenate((quaternion / np.linalg.norm(quaternion), rate))
        if times[-1] == 0.0:
            return AttitudeEphemeris(times, initial[:4][None, :], initial[4:][None, :])
        solution = solve_ivp(
            self.derivative,
            (0.0, float(times[-1])),
            initial,
            method="DOP853",
            t_eval=times,
            rtol=self.relative_tolerance,
            atol=self.absolute_tolerance,
        )
        if not solution.success:
            raise RuntimeError(f"attitude integration failed: {solution.message}")
        quaternions = solution.y[:4].T
        quaternions /= np.linalg.norm(quaternions, axis=1)[:, None]
        return AttitudeEphemeris(times, quaternions, solution.y[4:].T)

