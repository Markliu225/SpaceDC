"""Satellite ASSETS — the vendor platforms the builder picks between.

A design preset (design_presets.py) is a finished satellite someone else
already specced. An *asset* is the bare platform you start from: which hull
flies, how many payload slots it has, and the loadout it ships with. The Twin
page's satellite builder walks

    1. pick an asset  →  2. structure design (power / thermal / orbit)
    →  3. payload design (a GPU per slot)  →  4. workload  →  Run

and POSTs the result to /satellite_build, which applies all four steps
atomically (config + geometry + per-slot loadout + job schedule).

Each asset maps onto one of gen_twin_satellite.py's hull ARCHITECTURES — a
genuinely different satellite shape, not a rescale — and ships the loadout of
the audited design preset built on that hull, so a freshly-picked platform
closes the engine's power / thermal / eclipse checks before the user touches
anything.

  asset     hull        slots  ships as
  spacex    truss         12   Balanced LEO-DC (baseline)
  redwire   redwire        7   Redwire Serving Node
  sophia    lumid          6   Eco Light
  ada       dish           8   Thermal Guard
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from models import GpuType, SatelliteConfig, TwinGeometry


class SatelliteAsset(BaseModel):
    id: str
    name: str
    vendor: str
    tagline: str
    description: str
    # Hull configuration — one of gen_twin_satellite.py's ARCHITECTURES.
    architecture: str
    # Payload bay: how many cards the platform can physically carry, how the
    # builder should group them, and what to call each slot. len(slot_labels)
    # == slot_count, and the ORDER matches the USD slot order the generator
    # walks (rack-major for the truss hulls), so slot 5 in the UI is slot 5
    # in the 3D model.
    slot_count: int
    slot_group_size: int
    slot_group_label: str
    slot_labels: list[str]
    # Loadout the platform ships with (the audited preset for this hull).
    config: SatelliteConfig
    solar_clusters_per_side: int
    radiator_long: float
    radiator_ratio: float
    workload_profile: str
    default_gpu: GpuType
    # Slots populated out of the crate — the rest ship empty.
    default_gpu_count: int
    platform_power_w: float

    def geometry_patch(self) -> dict:
        return {
            "architecture": self.architecture,
            "solar_clusters_per_side": self.solar_clusters_per_side,
            "radiator_long": self.radiator_long,
            "radiator_ratio": self.radiator_ratio,
        }

    def default_slots(self) -> list[Optional[str]]:
        """Factory loadout as a slot list: the first `default_gpu_count` slots
        fitted with `default_gpu`, the rest empty."""
        return [self.default_gpu if i < self.default_gpu_count else None
                for i in range(self.slot_count)]


def _rack_labels() -> list[str]:
    """The 12 truss slots in gen_twin_satellite.RACKS order: four quadrant
    racks (upper/lower × ±Y), three shelves each."""
    return [f"{rack}·{i + 1}"
            for rack in ("U+Y", "U−Y", "L+Y", "L−Y")
            for i in range(3)]


ASSETS: dict[str, SatelliteAsset] = {a.id: a for a in [
    SatelliteAsset(
        id="spacex",
        name="SpaceX Compute Bus",
        vendor="SpaceX",
        tagline="Single-truss spine · 12 rack slots · silicon wings",
        description=(
            "The workhorse platform: a vertical truss spine with a thruster "
            "module at each end and four quadrant racks of three open shelves "
            "— twelve slots, the largest payload bay in the catalog. Sun-"
            "tracking silicon wings deploy along ±Y, radiators along ±Z."
        ),
        architecture="truss",
        slot_count=12, slot_group_size=3, slot_group_label="Rack",
        slot_labels=_rack_labels(),
        config=SatelliteConfig(
            gpu="H100", solar_material="Si", solar_size="M",
            radiator_material="WhitePaint", radiator_size="Standard",
            battery_material="LiIon", battery_size="L"),
        solar_clusters_per_side=5, radiator_long=1.9, radiator_ratio=2.5,
        workload_profile="chat_serving",
        default_gpu="H100", default_gpu_count=8,
        platform_power_w=600.0,
    ),
    SatelliteAsset(
        id="redwire",
        name="Redwire Payload Bay",
        vendor="Redwire",
        tagline="Flat bay · 7 GPU modules · roll-out GaAs ribbon",
        description=(
            "A one-panel-wide flat payload bay carrying its own row of seven "
            "discrete GPU modules along the sun face. The wings are a flexible "
            "roll-out ribbon that reels out of the bay edges coplanar with the "
            "deck; a single OSR radiator booms off the +Z face."
        ),
        architecture="redwire",
        slot_count=7, slot_group_size=7, slot_group_label="Bay row",
        slot_labels=[f"M{i + 1}" for i in range(7)],
        config=SatelliteConfig(
            gpu="H200", solar_material="GaAs", solar_size="M",
            radiator_material="OSR", radiator_size="Standard",
            battery_material="LiS", battery_size="M"),
        solar_clusters_per_side=4, radiator_long=1.75, radiator_ratio=1.3,
        workload_profile="frontier",
        default_gpu="H200", default_gpu_count=7,
        platform_power_w=700.0,
    ),
    SatelliteAsset(
        id="sophia",
        name="Sophia Space TILE",
        vendor="Sophia Space",
        tagline="1 m² tile · solar face + radiating back · no fans",
        description=(
            "TILE — Thermal Integrated LEO Edge: a one-square-metre, ~1 cm "
            "thick panel that is the whole data center. Solar cells cover the "
            "sunlit face, the processors sit inside, and the anti-sun face "
            "radiates their heat straight to space — no fans, no coolant "
            "loops. Tiles aggregate: one hosted on someone else's bus, ~40 as "
            "a companion-orbit cluster, thousands for a full orbital DC."
        ),
        architecture="lumid",
        slot_count=6, slot_group_size=3, slot_group_label="Tile row",
        slot_labels=[f"T{i + 1}" for i in range(6)],
        config=SatelliteConfig(
            gpu="H100", solar_material="Perovskite", solar_size="S",
            radiator_material="WhitePaint", radiator_size="Compact",
            battery_material="LiFePO4", battery_size="M"),
        solar_clusters_per_side=2, radiator_long=1.75, radiator_ratio=3.0,
        workload_profile="low_duty",
        default_gpu="H100", default_gpu_count=4,
        platform_power_w=450.0,
    ),
    SatelliteAsset(
        id="ada",
        name="Ada Space Compute Node",
        vendor="Ada Space",
        tagline="Networked smallsat · twin wings · 100 Gbps laser mesh",
        description=(
            "The Three-Body Computing Constellation bus: a compact "
            "intelligent-networked smallsat that computes on orbit instead of "
            "downlinking raw data — on-board AI accelerators, a space-based "
            "model, and gimballed laser terminals meshing the whole ring at up "
            "to 100 Gbps. Flies a sun-synchronous plane, twelve to a launch, "
            "with max-span radiators for burst tasking."
        ),
        architecture="dish",
        slot_count=8, slot_group_size=4, slot_group_label="Bank",
        slot_labels=[f"B{i + 1}" for i in range(8)],
        config=SatelliteConfig(
            gpu="H200", solar_material="GaAs", solar_size="M",
            radiator_material="OSR", radiator_size="Wide",
            battery_material="LiIon", battery_size="M"),
        solar_clusters_per_side=3, radiator_long=3.0, radiator_ratio=1.5,
        workload_profile="burst",
        default_gpu="H200", default_gpu_count=8,
        platform_power_w=600.0,
    ),
]}

_BY_ARCHITECTURE: dict[str, str] = {a.architecture: a.id for a in ASSETS.values()}


def get_asset(asset_id: str) -> SatelliteAsset | None:
    return ASSETS.get(asset_id)


def asset_for_architecture(architecture: str) -> str:
    """Which catalogued platform flies this hull — "" for the hulls that only
    design presets use (twin_truss, blanket)."""
    return _BY_ARCHITECTURE.get(architecture, "")


def asset_summary(a: SatelliteAsset) -> dict:
    """Asset + the headline stats of its factory loadout, using the engine's
    own area / mass formulas so the builder card and the physics agree."""
    # Local import — state_engine imports models like we do; keeping it inside
    # the function avoids any module-init order surprises (design_presets.py
    # does the same).
    from state_engine import (
        _GPU_TABLE, _SOLAR_MAT_TABLE, _RAD_MAT_TABLE, _BATT_MAT_TABLE,
        _batt_capacity_wh, _solar_area_m2, _radiator_area_m2,
    )

    geom = TwinGeometry(**a.geometry_patch())
    gpu = _GPU_TABLE[a.default_gpu]
    s_mat = _SOLAR_MAT_TABLE[a.config.solar_material]
    r_mat = _RAD_MAT_TABLE[a.config.radiator_material]
    b_mat = _BATT_MAT_TABLE[a.config.battery_material]

    solar_area = _solar_area_m2(geom)
    radiator_area = _radiator_area_m2(geom)          # both faces
    battery_capacity_wh = _batt_capacity_wh(a.config)
    mass_kg = (300.0
               + solar_area * s_mat["density_kg_m2"]
               + (radiator_area / 2.0) * r_mat["density_kg_m2"]
               + battery_capacity_wh / b_mat["density_wh_kg"])

    return {
        **a.model_dump(),
        "battery_capacity_wh": round(battery_capacity_wh),
        "stats": {
            "solar_area_m2": round(solar_area, 1),
            "radiator_area_m2": round(radiator_area, 1),
            "peak_solar_w": round(s_mat["efficiency"] * solar_area * 1361.0),
            "compute_pflops": round(gpu["pflops"] * a.default_gpu_count, 1),
            "mass_kg": round(mass_kg),
            "gpu_tdp_w": gpu["tdp_w"],
            "radiator_emissivity": r_mat["emissivity"],
        },
        "preview_url": f"/satellite_assets/{a.id}/preview.png",
    }


def list_summaries() -> list[dict]:
    return [asset_summary(a) for a in ASSETS.values()]
