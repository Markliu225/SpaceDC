# One-click launchers

## Prerequisites (one-time)

- Backend deps installed: `backend/.venv/` exists with `uvicorn` etc.
- Web deps installed: `web/node_modules/` exists.
- Kit built once: `C:\Workspace\kit-usd-viewer-template\_build\windows-x86_64\release\space.demo.viewer_streaming.kit.bat` exists.

All three are already true after the Phase 1 + Phase 5 setup.

## Daily use

**Double-click `start_all.bat`** in this folder. It will:

1. Kill any leftover `kit.exe`.
2. Open a console for the FastAPI backend on port **8001**.
3. Open a console for the Vite dev server on port **5173**.
4. Open a PowerShell for the Omniverse Kit streaming app on port **49100**.
5. Wait 20 s, then open `http://localhost:5173` in your default browser.

To stop, close the three service windows — or double-click `stop_all.bat`.

## Alternative views

- `start_all_satellite_closeup.bat` — same as above but Kit frames the satellite's bus + server rack + radiators + antenna for a component close-up.

## Troubleshooting

- **Port already in use** — run `stop_all.bat` first, then `start_all.bat` again.
- **Browser shows "OFFLINE"** — backend window probably errored; check it.
- **3D viewport stays gray / "connecting"** — Kit is still starting (takes ~13 s on first connect after launch). Wait, or reload the page.
- **Earth not visible** — `SPACE_DEMO_USD_ROOT` env var not set; `launch_kit.ps1` should set it automatically. Verify the third window shows `SPACE_DEMO_USD_ROOT = C:\Workspace\SpaceDC\space-compute-demo\usd`.
