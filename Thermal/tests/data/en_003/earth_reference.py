# -*- coding: utf-8 -*-
"""Independent references for EN-003 (Earth albedo and infrared inputs). No code from sdtwin_sim or thermal is used.

1. ``plate_sphere_view_factor``: closed-form view factor from a differential plate to a sphere, with the plate normal
   tilted by ``lam`` from the direction to the sphere centre (catalogue of radiation view factors, J. R. Howell,
   configuration "differential planar element to sphere, element tilted"; also Gilmore, Spacecraft Thermal Control
   Handbook, Earth view factor of a tilted plate). With ``H = r / R``:
     lam <= acos(1/H):              F = cos(lam) / H^2
     acos(1/H) < lam < pi-acos(1/H): F = 1/2 - asin(sqrt(H^2-1) / (H sin lam)) / pi
                                      + [cos(lam) acos(-sqrt(H^2-1) cot lam) - sqrt(H^2-1) sqrt(1 - H^2 cos^2 lam)] / (pi H^2)
     lam >= pi-acos(1/H):           F = 0
2. ``CapQuadrature``: midpoint quadrature over the visible spherical cap of the Earth parameterised by the GEOCENTRIC
   angle ``psi`` from the sub-satellite point and the azimuth ``phi`` (Earth-surface elements dA = R^2 dcos(psi) dphi),
   integrand cos(theta_plate) cos(theta_earth) / (pi d^2), and for the albedo factor the extra weight
   max(0, cos(solar zenith angle of the element)). This differs from the module, which integrates over nadir angles on
   the satellite's sky; both are exact forms of the same integral, so agreement tests the module and not a shared code.
3. ``monte_carlo_cap``: area-uniform random points on the visible cap, the same integrand, for a stochastic cross-check
   of the deterministic reference.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq


def adaptive_cap_factors(position_m, normal_gcrs, sun_dir_gcrs, earth_radius_m, *, rtol=1e-8):
    """Independent geocentric integral resolving plate and terminator boundaries.

    At each geocentric ring both plate incidence and solar zenith cosine are of
    the form a + b*cos(phi) + c*sin(phi). Split at their exact zeros, integrate
    the positive product on each interval by Gauss quadrature, then adapt in
    geocentric angle. This avoids a uniform mesh missing a narrow illuminated
    crescent. It shares no numerical implementation with the sky-grid provider.
    """
    r = float(np.linalg.norm(position_m))
    R = float(earth_radius_m)
    basis = _local_basis(np.asarray(position_m))
    n = basis @ np.asarray(normal_gcrs)
    sun = basis @ np.asarray(sun_dir_gcrs)
    end = math.acos(R / r)
    gx, gw = np.polynomial.legendre.leggauss(16)

    def roots(coeff):
        a, b, c = coeff
        amp = math.hypot(b, c)
        if amp == 0 or abs(a) >= amp:
            return []
        phase, angle = math.atan2(c, b), math.acos(-a / amp)
        return [(phase - angle) % (2 * math.pi), (phase + angle) % (2 * math.pi)]

    def coefficients(psi):
        sp, cp = math.sin(psi), math.cos(psi)
        distance = math.sqrt((r - R) ** 2 + 2 * r * R * (1 - cp))
        plate = (n[2] * (R * cp - r) / distance, R * sp * n[0] / distance, R * sp * n[1] / distance)
        solar = (sun[2] * cp, sun[0] * sp, sun[1] * sp)
        weight = max(0., r * cp - R) * R * R * sp / (math.pi * distance ** 3)
        return plate, solar, weight

    def ring(psi, albedo):
        plate, solar, weight = coefficients(psi)
        coeffs = (plate, solar) if albedo else (plate,)
        edges = sorted([0., 2 * math.pi] + [x for c in coeffs for x in roots(c)])
        total = 0.
        for lo, hi in zip(edges[:-1], edges[1:]):
            mid, half = (lo + hi) / 2, (hi - lo) / 2
            if any(a + b * math.cos(mid) + c * math.sin(mid) <= 0 for a, b, c in coeffs):
                continue
            phi = mid + half * gx
            value = np.ones_like(phi)
            for a, b, c in coeffs:
                value *= np.maximum(0., a + b * np.cos(phi) + c * np.sin(phi))
            total += half * float(gw @ value)
        return total * weight

    points = list(np.linspace(0, end, 33))
    # Ring tangencies mark the onset of a partial visible or illuminated arc.
    grid = np.linspace(0, end, 129)
    for component in (0, 1):
        for sign in (-1, 1):
            def boundary(x):
                a, b, c = coefficients(x)[component]
                return a + sign * math.hypot(b, c)
            for lo, hi in zip(grid[:-1], grid[1:]):
                if boundary(lo) * boundary(hi) < 0:
                    points.append(brentq(boundary, lo, hi, xtol=1e-14))
    points = sorted(set(points))[1:-1]
    values, errors = [], []
    for albedo in (False, True):
        value, error = quad(ring, 0, end, args=(albedo,), points=points,
                            epsabs=1e-18, epsrel=rtol, limit=400)
        values.append(value)
        errors.append(error)
    return (*values, *errors)


def plate_sphere_view_factor(H: float, lam: np.ndarray | float) -> np.ndarray:
    """Analytic view factor from a plate at ``H = r/R`` sphere radii, normal tilted ``lam`` rad from the nadir."""

    lam = np.asarray(lam, dtype=float)
    if H <= 1.0:
        raise ValueError("H must exceed 1")
    s = math.sqrt(H * H - 1.0)
    c = math.acos(1.0 / H)
    out = np.zeros_like(lam)
    full = lam <= c
    out[full] = np.cos(lam[full]) / (H * H)
    part = (lam > c) & (lam < math.pi - c)
    lp = lam[part]
    sin_l, cos_l = np.sin(lp), np.cos(lp)
    arg1 = np.clip(s / (H * sin_l), -1.0, 1.0)
    arg2 = np.clip(-s * cos_l / sin_l, -1.0, 1.0)
    root = np.sqrt(np.clip(1.0 - H * H * cos_l * cos_l, 0.0, None))
    out[part] = 0.5 - np.arcsin(arg1) / math.pi + (cos_l * np.arccos(arg2) - s * root) / (math.pi * H * H)
    return out


def _local_basis(position_m: np.ndarray) -> np.ndarray:
    """Rows: e1, e2, up (orthonormal, up = position direction)."""

    up = position_m / np.linalg.norm(position_m)
    trial = np.array([0.0, 0.0, 1.0]) if abs(up[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(trial, up)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    return np.vstack([e1, e2, up])


class CapQuadrature:
    """Geocentric midpoint quadrature of the visible cap for one orbit radius (template reused at every position).

    The template is built in a local frame whose z axis is the local vertical of the satellite; at a position the
    plate normal and the Sun direction are expressed in that frame, so one template serves the whole circular orbit.
    """

    def __init__(self, orbit_radius_m: float, earth_radius_m: float, n_psi: int, n_phi: int) -> None:
        r, R = float(orbit_radius_m), float(earth_radius_m)
        self.r, self.R, self.n_psi, self.n_phi = r, R, int(n_psi), int(n_phi)
        psi_max = math.acos(R / r)
        edges = np.linspace(0.0, psi_max, self.n_psi + 1)
        psi = 0.5 * (edges[:-1] + edges[1:])
        dcos = np.cos(edges[:-1]) - np.cos(edges[1:])            # exact cell area / (R^2 dphi)
        dphi = 2.0 * math.pi / self.n_phi
        phi = (np.arange(self.n_phi) + 0.5) * dphi
        P, F = np.meshgrid(psi, phi, indexing="ij")
        e = np.stack([np.sin(P) * np.cos(F), np.sin(P) * np.sin(F), np.cos(P)], axis=-1).reshape(-1, 3)
        dA = (R * R * dcos * dphi)[:, None].repeat(self.n_phi, axis=1).reshape(-1)
        d = R * e - np.array([0.0, 0.0, r])                         # satellite to element
        dist = np.linalg.norm(d, axis=1)
        dhat = d / dist[:, None]
        cos_earth = np.clip(-(e * dhat).sum(axis=1), 0.0, None)     # element normal against the line of sight
        self.e_local = e
        self.dhat_local = dhat
        self.weight = cos_earth * dA / (math.pi * dist * dist)
        self.cap_area_m2 = 2.0 * math.pi * R * R * (1.0 - R / r)

    def factors(self, position_m: np.ndarray, normals_gcrs: np.ndarray, sun_dir_gcrs: np.ndarray):
        """(F, F_alb) for each row of ``normals_gcrs`` at ``position_m``; Sun direction from Earth, unit."""

        position_m = np.asarray(position_m, dtype=float)
        if abs(np.linalg.norm(position_m) - self.r) > 1e-6 * self.r:
            raise ValueError("position radius differs from the template orbit radius")
        basis = _local_basis(position_m)
        normals = np.atleast_2d(np.asarray(normals_gcrs, dtype=float)) @ basis.T
        sun = basis @ np.asarray(sun_dir_gcrs, dtype=float)
        lit = np.clip(self.e_local @ sun, 0.0, None)
        cos_plate = np.clip(self.dhat_local @ normals.T, 0.0, None)  # (N, k)
        F = self.weight @ cos_plate
        F_alb = (self.weight * lit) @ cos_plate
        return F, F_alb


def monte_carlo_cap(position_m, normal_gcrs, sun_dir_gcrs, earth_radius_m: float, n: int, seed: int):
    """Monte Carlo estimates (F, F_alb) and their standard errors for one plate (area-uniform cap sampling)."""

    rng = np.random.default_rng(seed)
    position_m = np.asarray(position_m, dtype=float)
    r = float(np.linalg.norm(position_m))
    R = float(earth_radius_m)
    basis = _local_basis(position_m)
    normal = basis @ np.asarray(normal_gcrs, dtype=float)
    sun = basis @ np.asarray(sun_dir_gcrs, dtype=float)
    cos_psi = rng.uniform(R / r, 1.0, n)
    sin_psi = np.sqrt(1.0 - cos_psi * cos_psi)
    phi = rng.uniform(0.0, 2.0 * math.pi, n)
    e = np.stack([sin_psi * np.cos(phi), sin_psi * np.sin(phi), cos_psi], axis=1)
    d = R * e - np.array([0.0, 0.0, r])
    dist = np.linalg.norm(d, axis=1)
    dhat = d / dist[:, None]
    cos_earth = np.clip(-(e * dhat).sum(axis=1), 0.0, None)
    cos_plate = np.clip(dhat @ normal, 0.0, None)
    area = 2.0 * math.pi * R * R * (1.0 - R / r)
    g = cos_plate * cos_earth / (math.pi * dist * dist) * area
    g_alb = g * np.clip(e @ sun, 0.0, None)
    return (float(g.mean()), float(g.std(ddof=1) / math.sqrt(n)),
            float(g_alb.mean()), float(g_alb.std(ddof=1) / math.sqrt(n)))
