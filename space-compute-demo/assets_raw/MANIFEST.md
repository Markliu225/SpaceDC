# Raw Asset Manifest

Research-only catalog produced 2026-04-22. **No files downloaded yet.** Re-verify every license at download time, especially GrabCAD (personal-use default) and Sketchfab (mixed).

## License rule (re: [../docs/asset_pipeline.md](../docs/asset_pipeline.md))

Accept: CC0 · CC-BY · Public Domain (NASA) · MIT · NVIDIA SimReady · CERN-OHL · ESA Standard Licence.
Reject: GrabCAD personal-use · non-commercial-only · unclear provenance.

---

## Priority download list (fetch first)

| # | Asset | Category | Source | License |
|---|---|---|---|---|
| 1 | NASA SMAP | satellite bus | nasa3d.arc.nasa.gov | Public Domain |
| 2 | NASA ISS (full) | solar wings + radiators | nasa3d.arc.nasa.gov | Public Domain |
| 3 | NASA TDRS | HGA / downlink antenna | nasa3d.arc.nasa.gov | Public Domain |
| 4 | NASA Lucy or Juno | hero-shot solar wings | nasa3d.arc.nasa.gov | Public Domain |
| 5 | NASA DSN dish | ground station antenna | nasa3d.arc.nasa.gov | Public Domain |
| 6 | NVIDIA SimReady warehouse + server rack pack | ground-station building | Omniverse SimReady Library | SimReady Licence |
| 7 | OCP UBB reference CAD | HGX baseboard | opencompute.org | OCP CLA |
| 8 | ESA Sentinel-1 (backup) | alt commercial bus | esa.int 3D models | ESA Standard Licence |

## Full catalog by category

### 1. Satellite platform / main bus
1. **NASA SMAP** — OBJ/BLEND/3DS, Public Domain — *primary, 1MW-bus proxy*
2. NASA Aqua/Terra/Aura EOS — OBJ/3DS, Public Domain
3. NASA Lunar Gateway HALO — OBJ/GLB, Public Domain
4. ESA Sentinel-1 / Sentinel-6 — glTF/OBJ, ESA Standard Licence
5. NASA Hubble — OBJ/BLEND, Public Domain (oversized; StarCloud-like proportions)

### 2. Deployable solar arrays
1. **ISS SAW (from full ISS model)** — OBJ/BLEND, Public Domain — *primary*
2. Juno — three triangular wings, dramatic
3. Lucy — UltraFlex circular arrays
4. ESA Solar Orbiter / Rosetta — flat rectangular deployed arrays

### 3. Thermal radiator panels
1. **ISS HRS panels (within ISS model)** — extract from primary ISS — *primary*
2. JWST sunshield + radiator assembly
3. Libre Space Foundation SatNOGS thermal plates — STEP, CERN-OHL (small scale kit-bash)

> **Gap:** MW-scale radiator panels likely need custom modeling — build tiled flat panel using ISS HRS normal maps as reference.

### 4. High-gain antennas
1. **NASA TDRS** — dual parabolic dishes on booms — *primary*
2. Cassini HGA (4m dish)
3. MRO HGA (3m dish)
4. ESA BepiColombo MPO HGA

### 5. Ground station
1. **NASA DSN 34m/70m dish** — Public Domain — *primary antenna*
2. **NVIDIA SimReady warehouse/industrial building** — *primary building*
3. Libre Space SatNOGS rotator + yagi/dish — accurate engineering CAD, CERN-OHL

### 6. GPU hardware modules (H100 / H200 / B200 / MI300X)

> **Critical gap:** No openly-licensed CAD for these SXM modules exists. All options are approximate.

1. **NVIDIA SimReady DGX / server-rack assets** — closest first-party match, SimReady licence
2. **OCP UBB reference CAD** — accurate 8-GPU baseboard geometry, OCP CLA — *use as accurate base*
3. **Custom-modeled SXM modules** — Blender, from NVIDIA/AMD marketing photography — *required*

Strategy: OCP UBB = accurate baseboard. Place custom low-poly SXM module blocks on top, textured with marketing renders. GrabCAD / Sketchfab GPU uploads are **placeholders only**.

---

## Gaps requiring custom modeling (flagged for Phase 5)

- **MW-scale radiator panel tiles** — no open asset; custom-model flat tiled panel with heat-pipe normal map.
- **H100 / H200 / B200 / MI300X SXM modules** — no open CAD; custom-model.
- **Deployable truss at StarCloud scale** — ISS truss too detailed; simplify or custom-model.
- **Phased-array flat antennas** — if used instead of parabolic, build custom.

---

## Download log

Filled in as files land in `internal/` `public/` `vendor/`. Expected columns:

| File | Downloaded | Source URL | License | SHA256 | Notes |
|------|-----------|-----------|---------|--------|-------|
| _(empty — waiting for approval to start downloading)_ |
