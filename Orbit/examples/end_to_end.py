"""End-to-end orbit, Sun, power, attitude, access, and plotting example."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from ntu_space_dynamics import (
    AttitudeEphemeris,
    ClassicalElements,
    Ephemeris,
    EulerDynamics,
    GroundTarget,
    HighPrecisionPropagator,
    NadirSensor,
    OrbitState,
    SolarPanel,
    ThermalPowerResult,
    access_interpolation,
    eclipse_fraction,
    oe_to_rv,
    power_considering_thermal,
    sun_beta_angle,
    sun_intensity,
    sun_position_ephemeris,
)


PALETTE = {
    "blue": "#0F4D92",
    "red": "#B64342",
    "teal": "#42949E",
    "violet": "#9A4D8E",
    "gold": "#D99A24",
    "neutral": "#767676",
    "dark": "#272727",
    "light_blue": "#DCEAF7",
    "light_gold": "#F5E7C8",
}


def _configure_plot_style() -> None:
    """Apply a compact publication-style theme with editable vector text."""

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans"],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 7.5,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "axes.linewidth": 0.8,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "legend.frameon": False,
            "legend.fontsize": 6.5,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "savefig.dpi": 300,
            "grid.color": "#D8D8D8",
            "grid.linewidth": 0.6,
            "grid.alpha": 0.65,
        }
    )


def _panel_label(axis: plt.Axes, label: str) -> None:
    axis.text(
        -0.10,
        1.04,
        label,
        transform=axis.transAxes,
        fontsize=9.5,
        fontweight="bold",
        ha="left",
        va="bottom",
    )


def _finish_axis(axis: plt.Axes, *, xlabel: bool = False) -> None:
    axis.grid(True, axis="both")
    axis.margins(x=0.0)
    if xlabel:
        axis.set_xlabel("Elapsed time (h)")


def plot_timeseries(
    ephemeris: Ephemeris,
    beta_deg: np.ndarray,
    illumination: np.ndarray,
    power: ThermalPowerResult,
    attitude: AttitudeEphemeris,
    output_dir: Path,
    *,
    dpi: int = 300,
) -> tuple[Path, ...]:
    """Plot all state histories and export PNG, PDF, SVG, and compressed TIFF."""

    _configure_plot_style()
    output_dir.mkdir(parents=True, exist_ok=True)
    elapsed_hours = ephemeris.elapsed_seconds / 3600.0
    position_km = ephemeris.positions_m / 1000.0
    velocity_km_s = ephemeris.velocities_m_s / 1000.0
    radius_km = np.linalg.norm(position_km, axis=1)
    speed_km_s = np.linalg.norm(velocity_km_s, axis=1)
    angular_rate_deg_s = np.rad2deg(attitude.angular_velocity_body_rad_s)

    fig, axes = plt.subplots(
        4,
        2,
        figsize=(7.2, 10.2),
        sharex=True,
        constrained_layout=True,
    )
    component_colors = (PALETTE["blue"], PALETTE["red"], PALETTE["teal"])

    axis = axes[0, 0]
    for index, (label, color) in enumerate(zip(("x", "y", "z"), component_colors)):
        axis.plot(elapsed_hours, position_km[:, index], color=color, lw=1.35, label=label)
    axis.plot(elapsed_hours, radius_km, color=PALETTE["dark"], lw=1.8, label="Radius")
    axis.set_title("GCRS position")
    axis.set_ylabel("Position (km)")
    axis.legend(ncol=4, loc="upper right")
    _panel_label(axis, "a")
    _finish_axis(axis)

    axis = axes[0, 1]
    for index, (label, color) in enumerate(zip(("vx", "vy", "vz"), component_colors)):
        axis.plot(elapsed_hours, velocity_km_s[:, index], color=color, lw=1.35, label=label)
    axis.plot(elapsed_hours, speed_km_s, color=PALETTE["dark"], lw=1.8, label="Speed")
    axis.set_title("GCRS velocity")
    axis.set_ylabel("Velocity (km/s)")
    axis.legend(ncol=4, loc="upper right")
    _panel_label(axis, "b")
    _finish_axis(axis)

    axis = axes[1, 0]
    axis.plot(elapsed_hours, beta_deg, color=PALETTE["violet"], lw=1.8)
    beta_span = float(np.ptp(beta_deg))
    beta_padding = max(0.05, 0.15 * beta_span)
    beta_baseline = float(beta_deg.min() - beta_padding)
    axis.fill_between(
        elapsed_hours,
        beta_baseline,
        beta_deg,
        color=PALETTE["violet"],
        alpha=0.10,
    )
    axis.axhline(beta_deg[0], color=PALETTE["neutral"], lw=0.8, ls="--")
    axis.set_ylim(beta_baseline, float(beta_deg.max() + beta_padding))
    axis.set_title("Sun beta angle")
    axis.set_ylabel("Beta angle (deg)")
    _panel_label(axis, "c")
    _finish_axis(axis)

    axis = axes[1, 1]
    axis.plot(elapsed_hours, illumination, color=PALETTE["gold"], lw=1.8)
    axis.fill_between(
        elapsed_hours,
        0.0,
        illumination,
        color=PALETTE["light_gold"],
        alpha=0.8,
    )
    axis.set_ylim(-0.03, 1.05)
    axis.set_title("Solar-disc visibility")
    axis.set_ylabel("Illumination fraction")
    if np.all(illumination > 0.999):
        axis.text(
            0.98,
            0.10,
            "No eclipse in interval",
            transform=axis.transAxes,
            color=PALETTE["neutral"],
            ha="right",
            va="bottom",
        )
    _panel_label(axis, "d")
    _finish_axis(axis)

    axis = axes[2, 0]
    axis.plot(
        elapsed_hours,
        power.incident_power_w,
        color=PALETTE["neutral"],
        lw=1.2,
        ls="--",
        label="Incident",
    )
    axis.plot(
        elapsed_hours,
        power.electrical_power_w,
        color=PALETTE["blue"],
        lw=1.8,
        label="Electrical",
    )
    axis.fill_between(
        elapsed_hours,
        0.0,
        power.electrical_power_w,
        color=PALETTE["light_blue"],
        alpha=0.55,
    )
    axis.set_title("Solar-array power")
    axis.set_ylabel("Power (W)")
    axis.legend(loc="best")
    _panel_label(axis, "e")
    _finish_axis(axis)

    axis = axes[2, 1]
    axis.plot(elapsed_hours, power.temperature_k, color=PALETTE["red"], lw=1.8)
    axis.fill_between(
        elapsed_hours,
        power.temperature_k.min(),
        power.temperature_k,
        color=PALETTE["red"],
        alpha=0.10,
    )
    axis.set_title("Panel temperature")
    axis.set_ylabel("Temperature (K)")
    _panel_label(axis, "f")
    _finish_axis(axis)

    axis = axes[3, 0]
    quaternion_colors = (
        PALETTE["blue"],
        PALETTE["red"],
        PALETTE["teal"],
        PALETTE["violet"],
    )
    for index, (label, color) in enumerate(
        zip(("qx", "qy", "qz", "qw"), quaternion_colors)
    ):
        axis.plot(
            elapsed_hours,
            attitude.quaternions_xyzw[:, index],
            color=color,
            lw=1.35,
            label=label,
        )
    axis.set_ylim(-1.05, 1.05)
    axis.set_title("Body-to-inertial quaternion")
    axis.set_ylabel("Quaternion component")
    axis.legend(ncol=4, loc="upper right")
    _panel_label(axis, "g")
    _finish_axis(axis, xlabel=True)

    axis = axes[3, 1]
    for index, (label, color) in enumerate(zip(("ωx", "ωy", "ωz"), component_colors)):
        axis.plot(
            elapsed_hours,
            angular_rate_deg_s[:, index],
            color=color,
            lw=1.35,
            label=label,
        )
    axis.set_title("Body angular velocity")
    axis.set_ylabel("Angular rate (deg/s)")
    axis.legend(ncol=3, loc="upper right")
    _panel_label(axis, "h")
    _finish_axis(axis, xlabel=True)

    fig.suptitle(
        "End-to-end spacecraft dynamics and power forecast",
        fontsize=11,
        fontweight="bold",
    )
    base = output_dir / "end_to_end_timeseries"
    outputs = tuple(
        base.with_suffix(suffix) for suffix in (".png", ".pdf", ".svg", ".tiff")
    )
    fig.savefig(outputs[0], dpi=dpi, bbox_inches="tight", facecolor="white")
    fig.savefig(outputs[1], bbox_inches="tight", facecolor="white")
    fig.savefig(outputs[2], bbox_inches="tight", facecolor="white")
    fig.savefig(
        outputs[3],
        dpi=600,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"compression": "tiff_lzw"},
    )
    plt.close(fig)
    return outputs


def build_argument_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=3.0, help="forecast duration")
    parser.add_argument("--step-s", type=float, default=60.0, help="output sampling step")
    parser.add_argument(
        "--gravity-degree",
        type=int,
        default=70,
        help="EGM2008 degree/order used by HPOP (2-120)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "outputs" / "end_to_end",
        help="figure output directory",
    )
    parser.add_argument("--dpi", type=int, default=300, help="PNG resolution")
    return parser


def main() -> None:
    args = build_argument_parser().parse_args()
    if args.hours <= 0.0 or args.step_s <= 0.0 or args.dpi <= 0:
        raise ValueError("hours, step-s, and dpi must be positive")

    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    elements = ClassicalElements.from_degrees(
        7_000_000.0, 0.001, 97.5, 20.0, 0.0, 0.0, epoch
    )
    position, velocity = oe_to_rv(elements)
    initial = OrbitState(epoch, position, velocity)

    propagator = HighPrecisionPropagator(
        gravity_degree=args.gravity_degree,
        gravity_order=args.gravity_degree,
        area_to_mass_m2_kg=0.01,
        include_third_body=True,
        include_relativity=True,
    )
    ephemeris = propagator.propagate_grid(
        initial,
        epoch + timedelta(hours=args.hours),
        step_s=args.step_s,
    )

    sun_positions = np.vstack(
        [sun_position_ephemeris(time) for time in ephemeris.times]
    )
    beta_deg = np.array(
        [
            sun_beta_angle(position, velocity, sun, degrees=True)
            for position, velocity, sun in zip(
                ephemeris.positions_m,
                ephemeris.velocities_m_s,
                sun_positions,
            )
        ]
    )
    illumination = np.array(
        [
            eclipse_fraction(satellite, sun)
            for satellite, sun in zip(ephemeris.positions_m, sun_positions)
        ]
    )
    irradiance = np.array(
        [
            sun_intensity(satellite, sun)
            for satellite, sun in zip(ephemeris.positions_m, sun_positions)
        ]
    )

    # This example assumes ideal Sun tracking, hence incidence cosine = 1.
    panel = SolarPanel(area_m2=2.0, efficiency_reference=0.30)
    power = power_considering_thermal(
        ephemeris.elapsed_seconds,
        irradiance,
        np.ones(len(ephemeris)),
        panel,
    )

    attitude = EulerDynamics([12.0, 15.0, 18.0]).propagate(
        [0.0, 0.0, 0.0, 1.0],
        [0.001, 0.002, 0.003],
        ephemeris.elapsed_seconds,
    )

    access = access_interpolation(
        ephemeris,
        GroundTarget.from_degrees(30.0, 120.0, name="Shanghai"),
        NadirSensor.from_degrees(35.0, minimum_elevation_deg=5.0),
        scan_step_s=20.0,
        boundary_tolerance_s=0.1,
    )
    figure_paths = plot_timeseries(
        ephemeris,
        beta_deg,
        illumination,
        power,
        attitude,
        args.output_dir,
        dpi=args.dpi,
    )

    radius_km = np.linalg.norm(ephemeris.positions_m, axis=1) / 1000.0
    speed_km_s = np.linalg.norm(ephemeris.velocities_m_s, axis=1) / 1000.0
    print(f"forecast: {ephemeris.times[0].isoformat()} -> {ephemeris.times[-1].isoformat()}")
    print(f"states: {len(ephemeris)}, step: {args.step_s:g} s")
    print(f"radius range: {radius_km.min():.3f}..{radius_km.max():.3f} km")
    print(f"speed range: {speed_km_s.min():.6f}..{speed_km_s.max():.6f} km/s")
    print(f"beta range: {beta_deg.min():.3f}..{beta_deg.max():.3f} deg")
    print(f"illumination range: {illumination.min():.6f}..{illumination.max():.6f}")
    print(
        "electrical power range: "
        f"{power.electrical_power_w.min():.1f}..{power.electrical_power_w.max():.1f} W"
    )
    print(
        "panel temperature range: "
        f"{power.temperature_k.min():.2f}..{power.temperature_k.max():.2f} K"
    )
    print(f"final quaternion [x,y,z,w]: {attitude.quaternions_xyzw[-1]}")
    print(
        "final body rate [x,y,z]: "
        f"{np.rad2deg(attitude.angular_velocity_body_rad_s[-1])} deg/s"
    )
    print(f"access windows: {len(access.windows)}")
    for window in access.windows:
        print(
            f"access: {window.start.isoformat()} -> {window.end.isoformat()} "
            f"({window.duration_s:.1f} s)"
        )
    for path in figure_paths:
        print(f"figure: {path.resolve()}")


if __name__ == "__main__":
    main()
