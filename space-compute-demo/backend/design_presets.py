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
    # Hull configuration — one of gen_twin_satellite.py's ARCHITECTURES.
    # Each preset is a genuinely different satellite SHAPE, not a rescale.
    architecture: str = "truss"
    # Geometry knobs only — `version` is owned by the live engine state.
    solar_clusters_per_side: int
    radiator_long: float
    radiator_ratio: float
    workload_profile: str
    # Accelerator cards fitted (drives payload power AND compute throughput).
    gpu_count: int = 8
    # Battery capacity is DERIVED from config.battery_material × battery_size
    # (see state_engine._batt_capacity_wh) — no separate Wh field.
    platform_power_w: float

    def geometry_patch(self) -> dict:
        return {
            "architecture": self.architecture,
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
        tagline="H200 · 5-cluster wings · white-paint radiators",
        description=(
            "The reference orbital data-center loadout: eight H200s on "
            "five-cluster silicon wings (+24 % power margin) with white-paint "
            "radiators sized for the mixed inference/training duty cycle."
        ),
        config=SatelliteConfig(
            gpu="H200", solar_material="Si", solar_size="M",
            radiator_material="WhitePaint", radiator_size="Standard",
            battery_material="LiIon", battery_size="L",),
        architecture="truss",
        solar_clusters_per_side=5, radiator_long=1.9, radiator_ratio=2.5,
        workload_profile="chat_serving", gpu_count=8,
        platform_power_w=600.0,
    ),
    DesignPreset(
        id="redwire",
        name="Redwire Serving Node",
        tagline="8x H200 · flat payload bay · frontier 405B serving",
        description=(
            "A dedicated LLM-serving node on a one-panel-wide Redwire "
            "payload bay: the bay's own row of discrete GPU modules runs "
            "Llama-405B as one tensor-parallel group, a long flat GaAs "
            "ribbon extends off each bay-edge lug coplanar with the deck, "
            "and a single OSR radiator booms off the +Z face."
        ),
        config=SatelliteConfig(
            gpu="H200", solar_material="GaAs", solar_size="M",
            radiator_material="OSR", radiator_size="Standard",
            battery_material="LiS", battery_size="M",),
        architecture="redwire",
        solar_clusters_per_side=4, radiator_long=1.75, radiator_ratio=1.3,
        workload_profile="frontier", gpu_count=8,
        platform_power_w=700.0,
    ),
    DesignPreset(
        id="compute_max",
        name="Compute Max",
        tagline="12x B200 · twin-truss tower · OSR wide radiators",
        description=(
            "Maximum on-orbit FLOPS: TWO backbone segments stacked into a "
            "24-slot tower carrying twelve B200s, perovskite wings on the "
            "joint, and oversized OSR radiators for sustained training "
            "(graphite's solar absorptivity would eat the margin in daylight)."
        ),
        config=SatelliteConfig(
            gpu="B200", solar_material="Perovskite", solar_size="L",
            radiator_material="OSR", radiator_size="Wide",
            battery_material="LiIon", battery_size="XL",),
        architecture="twin_truss",
        solar_clusters_per_side=8, radiator_long=2.6, radiator_ratio=2.0,
        workload_profile="training", gpu_count=12,
        platform_power_w=800.0,
    ),
    DesignPreset(
        id="eco_light",
        name="Eco Light",
        tagline="4x H200 · LUMID smallsat hull · integrated cross panels",
        description=(
            "Minimum launch mass and CAPEX on the LUMID smallsat bus: four "
            "integrated perovskite cross panels and slim radiators, flying a "
            "low-duty housekeeping workload with occasional batch jobs."
        ),
        config=SatelliteConfig(
            gpu="H200", solar_material="Perovskite", solar_size="S",
            radiator_material="WhitePaint", radiator_size="Compact",
            battery_material="LiFePO4", battery_size="M",),
        architecture="lumid",
        solar_clusters_per_side=2, radiator_long=1.75, radiator_ratio=3.0,
        workload_profile="low_duty", gpu_count=4,
        platform_power_w=450.0,
    ),
    DesignPreset(
        id="thermal_guard",
        name="Thermal Guard",
        tagline="H200 · dish comms hull · OSR radiators",
        description=(
            "Built for spiky target-of-opportunity tasking: a parabolic-dish "
            "comms hull with windmill wings, plus optical-solar-reflector "
            "radiators sized so burst heat stays flat without freezing the "
            "bus through eclipse."
        ),
        config=SatelliteConfig(
            gpu="H200", solar_material="GaAs", solar_size="M",
            radiator_material="OSR", radiator_size="Wide",
            battery_material="LiIon", battery_size="M",),
        architecture="dish",
        solar_clusters_per_side=3, radiator_long=1.8, radiator_ratio=1.5,
        workload_profile="burst", gpu_count=8,
        platform_power_w=600.0,
    ),
    DesignPreset(
        id="wide_wing",
        name="Wide Wing",
        tagline="B200 · ISS-style ribbon wings · standard radiators",
        description=(
            "Power-rich survey platform: two 24 m single-row blanket wings "
            "harvest enough for continuous B200 inference plus battery "
            "margin for long eclipse seasons."
        ),
        config=SatelliteConfig(
            gpu="B200", solar_material="Perovskite", solar_size="XL",
            radiator_material="OSR", radiator_size="Standard",
            battery_material="SolidState", battery_size="M",),
        architecture="blanket",
        solar_clusters_per_side=8, radiator_long=1.85, radiator_ratio=2.5,
        workload_profile="code_rag", gpu_count=8,
        platform_power_w=650.0,
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
        _GPU_TABLE, _SOLAR_MAT_TABLE, _RAD_MAT_TABLE, _BATT_MAT_TABLE,
        _batt_capacity_wh, _solar_area_m2, _radiator_area_m2,
        workload_profile_stats,
    )

    geom = TwinGeometry(**p.geometry_patch())
    gpu = _GPU_TABLE[p.config.gpu]
    s_mat = _SOLAR_MAT_TABLE[p.config.solar_material]
    r_mat = _RAD_MAT_TABLE[p.config.radiator_material]

    solar_area = _solar_area_m2(geom)               # active cell area, m²
    radiator_area = _radiator_area_m2(geom)         # emitting area (both faces), m²
    radiator_material_area = radiator_area / 2.0    # physical panel area for mass

    peak_solar_w = s_mat["efficiency"] * solar_area * 1361.0
    compute_pflops = gpu["pflops"] * p.gpu_count
    battery_capacity_wh = _batt_capacity_wh(p.config)
    b_mat = _BATT_MAT_TABLE[p.config.battery_material]
    mass_kg = (300.0
               + solar_area * s_mat["density_kg_m2"]
               + radiator_material_area * r_mat["density_kg_m2"]
               + battery_capacity_wh / b_mat["density_wh_kg"])   # pack mass
    profile = workload_profile_stats(p.workload_profile)

    return {
        **p.model_dump(),
        # Capacity is derived (no longer a preset field) — expose it so the
        # gallery card + frontend DesignPresetInfo keep working.
        "battery_capacity_wh": round(battery_capacity_wh),
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
