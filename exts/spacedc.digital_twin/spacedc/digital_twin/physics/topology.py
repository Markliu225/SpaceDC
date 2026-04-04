"""
============================================================
  topology.py - Lightweight constellation topology helpers
============================================================

  Stores user-authored inter-satellite links and builds simple
  preset topologies for visual orchestration inside Omniverse.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


TOPOLOGY_PRESET_KEYS = ("ring", "chain", "star", "mesh")


@dataclass(frozen=True)
class TopologyLink:
    source_catalog_number: str
    target_catalog_number: str

    @property
    def key(self) -> tuple[str, str]:
        return tuple(sorted((self.source_catalog_number, self.target_catalog_number)))


def canonicalize_link(source_catalog_number: str, target_catalog_number: str) -> Optional[TopologyLink]:
    source = str(source_catalog_number or "").strip()
    target = str(target_catalog_number or "").strip()
    if not source or not target or source == target:
        return None
    a, b = sorted((source, target))
    return TopologyLink(a, b)


def add_link(links: list[TopologyLink], source_catalog_number: str, target_catalog_number: str) -> tuple[list[TopologyLink], bool]:
    link = canonicalize_link(source_catalog_number, target_catalog_number)
    if not link:
        return list(links), False
    if any(existing.key == link.key for existing in links):
        return list(links), False
    return list(links) + [link], True


def remove_link(links: list[TopologyLink], source_catalog_number: str, target_catalog_number: str) -> tuple[list[TopologyLink], bool]:
    link = canonicalize_link(source_catalog_number, target_catalog_number)
    if not link:
        return list(links), False
    remaining = [existing for existing in links if existing.key != link.key]
    return remaining, len(remaining) != len(links)


def preset_links(satellites, preset_key: str) -> list[TopologyLink]:
    sat_ids = [sat.catalog_number for sat in satellites if sat.catalog_number]
    if len(sat_ids) < 2:
        return []

    links: list[TopologyLink] = []
    if preset_key == "ring":
        for idx in range(len(sat_ids)):
            link = canonicalize_link(sat_ids[idx], sat_ids[(idx + 1) % len(sat_ids)])
            if link:
                links.append(link)
    elif preset_key == "chain":
        for idx in range(len(sat_ids) - 1):
            link = canonicalize_link(sat_ids[idx], sat_ids[idx + 1])
            if link:
                links.append(link)
    elif preset_key == "star":
        hub = sat_ids[0]
        for sat_id in sat_ids[1:]:
            link = canonicalize_link(hub, sat_id)
            if link:
                links.append(link)
    elif preset_key == "mesh":
        for idx, sat_id in enumerate(sat_ids):
            for other_id in sat_ids[idx + 1:]:
                link = canonicalize_link(sat_id, other_id)
                if link:
                    links.append(link)
    return dedupe_links(links)


def dedupe_links(links: list[TopologyLink]) -> list[TopologyLink]:
    seen: set[tuple[str, str]] = set()
    unique: list[TopologyLink] = []
    for link in links:
        if link.key in seen:
            continue
        seen.add(link.key)
        unique.append(link)
    return unique


def resolve_satellite_reference(reference: str, constellation) -> Optional[str]:
    if not constellation:
        return None

    raw = str(reference or "").strip()
    if not raw:
        return None
    folded = raw.casefold()

    for sat in constellation.satellites:
        candidates = {
            sat.catalog_number,
            sat.safe_id,
            sat.safe_id.replace("Sat_", "", 1),
            sat.name,
            sat.label,
        }
        for candidate in candidates:
            if candidate and str(candidate).strip().casefold() == folded:
                return sat.catalog_number

    for sat in constellation.satellites:
        haystacks = (
            sat.catalog_number,
            sat.safe_id,
            sat.name,
            sat.label,
        )
        if any(folded in str(value).casefold() for value in haystacks if value):
            return sat.catalog_number

    return None


def available_satellite_text(constellation, limit: int = 8) -> str:
    if not constellation or not constellation.satellites:
        return "Load a constellation to author topology links."
    labels = [f"{sat.catalog_number}:{sat.name}" for sat in constellation.satellites[:limit]]
    suffix = " ..." if len(constellation.satellites) > limit else ""
    return "Sats: " + ", ".join(labels) + suffix


def link_summary_text(links: list[TopologyLink], constellation, limit: int = 6) -> str:
    if not links:
        return "No active links."

    by_id = constellation.by_catalog_number if constellation else {}
    rows: list[str] = []
    for link in links[:limit]:
        left = by_id.get(link.source_catalog_number)
        right = by_id.get(link.target_catalog_number)
        if left and right:
            rows.append(f"{left.name} ↔ {right.name}")
        else:
            rows.append(f"{link.source_catalog_number} ↔ {link.target_catalog_number}")
    if len(links) > limit:
        rows.append(f"... +{len(links) - limit} more")
    return " | ".join(rows)
