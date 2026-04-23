# Asset Pipeline

Per execution book §12.

## Flow

```
assets_raw/{internal,public,vendor}/
    │
    ▼  (Asset Converter for OBJ/FBX/glTF, CAD Converter for STEP/SolidWorks/etc.)
assets_usd/
    │
    ▼  (structure normalization — naming, units, pivot, materials)
    │
    ▼  (Asset Validator — stage/layer/geometry/materials rules)
    │
    ▼  (Scene Optimizer — LOD, merge, prune)
    │
    ▼
usd/
    ├── root.usd                (main stage)
    ├── environment.usd         (earth, orbit, sun, stars)
    ├── satellite_base.usd      (structure)
    ├── satellite_payload.usd   (variant: H100/H200/B200/MI300X)
    ├── ground_station.usd
    ├── task_scene.usd          (maritime area, detection overlays)
    ├── camera_paths.usd
    └── overlay.usd             (labels, highlights)
```

## Categories to collect

See [../assets_raw/MANIFEST.md](../assets_raw/MANIFEST.md) (populated by research agent).

1. Satellite platform / main bus
2. Deployable solar arrays
3. Thermal radiator panels
4. High-gain antennas
5. Ground station
6. GPU hardware modules (approximate / custom-built)

## License rules

- MUST be CC0, CC-BY, public domain, MIT, or NVIDIA SimReady.
- Non-commercial-only assets NOT allowed (demo may be shown commercially).
- Record every asset's source URL and license in `assets_raw/MANIFEST.md`.

## Validation

All USD output must pass `omni_asset_validator` with default rule set before being referenced from `usd/root.usd`.
