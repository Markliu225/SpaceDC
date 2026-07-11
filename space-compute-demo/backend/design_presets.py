"""Named single-satellite design presets — the Twin page "design gallery".

Each preset is a COMPLETE satellite design: hardware loadout (GPU, solar /
radiator materials+sizes), deployable geometry (solar cluster count, radiator
shape — drives the regenerated USD model), a workload profile (which job
schedule the GPUs run — see state_engine._WORKLOAD_PROFILES), and platform
constants (battery capacity, bus power). Applying a preset switches ALL of it
atomically: the 3D model regenerates, Kit reloads the layer, and the physics
engine recomputes from the new numbers on the next tick.

The web client lists these via GET /designs (with derived stats + a preview
thumbnail URL) and switches via POST /designs/{id}/apply.
"""
from __future__ import annotations

from pydantic import BaseModel

from models import SatelliteConfig, TwinGeometry


class DesignPreset(BaseModel):
    id: str
    name: str
    tagline: str
    description: str
    config: SatelliteConfig
    # Geometry knobs only — `version` is owned by the live engine state.
    solar_clusters_per_side: int
    radiator_long: float
    radiator_ratio: float
    workload_profile: str
    battery_capacity_wh: float
    platform_power_w: float

    def geometry_patch(self) -> dict:
        return {
            "solar_clusters_per_side": self.solar_clusters_per_side,
            "radiator_long": self.radiator_long,
            "radiator_ratio": self.radiator_ratio,
        }


# The id "custom" is reserved: the engine reports it whenever the user has
# hand-edited config/geometry after (or instead of) applying a preset.
CUSTOM_DESIGN_ID = "custom"

PRESETS: dict[str, DesignPreset] = {p.id: p for p in [
    # Sizing note (all presets): the engine's design check uses
    #   supply = η·A·1361 × 0.95 pointing × 0.5 sunlit  vs  avg demand,
    #   max emit at +60 °C = ε·σ·A_rad·(333.15⁴−250⁴)  vs  peak demand,
    # and one eclipse (~46 min at demand) must fit the battery at ≲65 % DoD.
    # Every preset below closes all three with its own character — margins
    # verified against the running engine in the physics-closure audit.
    DesignPreset(
        id="baseline",
        name="Balanced LEO-DC",
        tagline="H100 · 5-cluster wings · white-paint radiators",
        description=(
            "The reference orbital data-center loadout: eight H100s on "
            "five-cluster silicon wings (+24 % power margin) with white-paint "
            "radiators sized for the mixed inference/training duty cycle."
        ),
        config=SatelliteConfig(
            gpu="H100", solar_material="Si", solar_size="M",
            radiator_material="WhitePaint", radiator_size="Standard",
        ),
        solar_clusters_per_side=5, radiator_long=1.9, radiator_ratio=2.5,
        workload_profile="balanced",
        battery_capacity_wh=7000.0, platform_power_w=600.0,
    ),
    DesignPreset(
        id="compute_max",
        name="Compute Max",
        tagline="B200 · 6-cluster wings · graphite wide radiators",
        description=(
            "Maximum on-orbit FLOPS: eight Blackwell B200s fed by six GaAs "
            "clusters per wing, with oversized graphite radiators to dump "
            "the 8 kW-class payload heat during sustained training runs."
        ),
        config=SatelliteConfig(
            gpu="B200", solar_material="GaAs", solar_size="L",
            radiator_material="Graphite", radiator_size="Wide",
        ),
        solar_clusters_per_side=6, radiator_long=2.6, radiator_ratio=2.0,
        workload_profile="training",
        battery_capacity_wh=10500.0, platform_power_w=800.0,
    ),
    DesignPreset(
        id="eco_light",
        name="Eco Light",
        tagline="H100 · twin-cluster wings · slim radiators",
        description=(
            "Minimum launch mass and CAPEX: two perovskite clusters per side "
            "and slim radiators sized just past the duty cycle, flying a "
            "low-duty housekeeping workload with occasional batch jobs."
        ),
        config=SatelliteConfig(
            gpu="H100", solar_material="Perovskite", solar_size="S",
            radiator_material="WhitePaint", radiator_size="Compact",
        ),
        solar_clusters_per_side=2, radiator_long=1.75, radiator_ratio=3.0,
        workload_profile="low_duty",
        battery_capacity_wh=4600.0, platform_power_w=450.0,
    ),
    DesignPreset(
        id="thermal_guard",
        name="Thermal Guard",
        tagline="H200 · 3-cluster wings · OSR max-area radiators",
        description=(
            "Built for spiky target-of-opportunity bursts: optical solar "
            "reflector radiators at maximum span keep peak-load temperature "
            "flat while H200s sprint through classification bursts."
        ),
        config=SatelliteConfig(
            gpu="H200", solar_material="GaAs", solar_size="M",
            radiator_material="OSR", radiator_size="Wide",
        ),
        solar_clusters_per_side=3, radiator_long=3.0, radiator_ratio=1.5,
        workload_profile="burst",
        battery_capacity_wh=5000.0, platform_power_w=600.0,
    ),
    DesignPreset(
        id="wide_wing",
        name="Wide Wing",
        tagline="MI300X · 8-cluster wings · standard radiators",
        description=(
            "Power-rich survey platform: the full eight-cluster wingspan "
            "harvests enough for continuous MI300X inference plus battery "
            "margin for long eclipse seasons."
        ),
        config=SatelliteConfig(
            gpu="MI300X", solar_material="Perovskite", solar_size="XL",
            radiator_material="OSR", radiator_size="Standard",
        ),
        solar_clusters_per_side=8, radiator_long=1.85, radiator_ratio=2.5,
        workload_profile="balanced",
        battery_capacity_wh=7500.0, platform_power_w=650.0,
    ),
]}


def get_preset(design_id: str) -> DesignPreset | None:
    return PRESETS.get(design_id)


def preset_summary(p: DesignPreset) -> dict:
    """Preset + derived headline stats for the gallery card. Mirrors the
    engine's geometry-area formulas and hardware tables so the card numbers
    match what the physics will report after the switch."""
    # Local import — state_engine imports models like we do; keeping the
    # import inside the function avoids any module-init order surprises.
    from state_engine import (
        _GPU_TABLE, _GPU_CARDS_PER_SAT, _SOLAR_MAT_TABLE, _RAD_MAT_TABLE,
        _solar_area_m2, _radiator_area_m2, workload_profile_stats,
    )

    geom = TwinGeometry(**p.geometry_patch())
    gpu = _GPU_TABLE[p.config.gpu]
    s_mat = _SOLAR_MAT_TABLE[p.config.solar_material]
    r_mat = _RAD_MAT_TABLE[p.config.radiator_material]

    solar_area = _solar_area_m2(geom)               # active cell area, m²
    radiator_area = _radiator_area_m2(geom)         # emitting area (both faces), m²
    radiator_material_area = radiator_area / 2.0    # physical panel area for mass

    peak_solar_w = s_mat["efficiency"] * solar_area * 1361.0
    compute_pflops = gpu["pflops"] * _GPU_CARDS_PER_SAT
    mass_kg = (300.0
               + solar_area * s_mat["density_kg_m2"]
               + radiator_material_area * r_mat["density_kg_m2"])
    profile = workload_profile_stats(p.workload_profile)

    return {
        **p.model_dump(),
        "stats": {
            "solar_area_m2": round(solar_area, 1),
            "radiator_area_m2": round(radiator_area, 1),
            "peak_solar_w": round(peak_solar_w),
            "compute_pflops": round(compute_pflops, 1),
            "mass_kg": round(mass_kg),
            "gpu_tdp_w": gpu["tdp_w"],
            "radiator_emissivity": r_mat["emissivity"],
            "workload_avg_util": profile["avg_util"],
            "workload_label": profile["label"],
        },
        "preview_url": f"/designs/{p.id}/preview.png",
    }


def list_summaries() -> list[dict]:
    return [preset_summary(p) for p in PRESETS.values()]
