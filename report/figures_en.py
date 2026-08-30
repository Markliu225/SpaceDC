"""English edition of the report diagrams.  Reuses the drawing primitives of
figures.py and writes to report/figures_en/.   Run: python figures_en.py"""
from __future__ import annotations

import os
import matplotlib.pyplot as plt

import figures as F
from figures import _box, _line, _arrow, FILL_ROOT, FILL_L1, INK, LINE, tree

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "figures_en")
os.makedirs(OUT, exist_ok=True)
F.OUT = OUT                                   # _finish() reads the module global at call time
plt.rcParams["font.family"] = ["Segoe UI", "Arial", "DejaVu Sans", "sans-serif"]


def architecture():
    W, H = 15.6, 9.6
    fig, ax = plt.subplots(figsize=(W * 0.85, H * 0.85))
    band_x, band_w = 1.05, 10.9
    label_w = 0.75

    def band(y, h, title, fill, edge):
        _box(ax, band_x, y, band_w, h, "", fill=fill, edge=edge, lw=1.4, rounded=False)
        _box(ax, 0.2, y, label_w, h, "", fill=edge, edge=edge, rounded=False)
        ax.text(0.2 + label_w / 2, y + h / 2, title, rotation=90, ha="center",
                va="center", fontsize=10, color="white", fontweight="bold")

    ay, ah = 7.15, 2.25
    band(ay, ah, "APPLICATION", "#EEF4FB", "#2E5A88")
    tiles = [("Constellation Configuration and Evaluation",
              ["Orbit and constellation designer", "Fleet situation and coverage", "Ground station visibility"]),
             ("Compute Satellite Digital Twin",
              ["Real-time 3D twin viewport", "Configurator and design library", "Telemetry curves and alarms"]),
             ("Compute Task Effectiveness Validation",
              ["Builder wizard and preview", "Workload profile fit assessment", "Lockstep design comparison"])]
    tw = (band_w - 0.3 * 4) / 3
    for i, (t, items) in enumerate(tiles):
        x = band_x + 0.3 + i * (tw + 0.3)
        _box(ax, x, ay + 0.15, tw, ah - 0.3, "", fill="#FFFFFF", edge="#2E5A88")
        ax.text(x + tw / 2, ay + ah - 0.4, t, ha="center", va="center", fontsize=8.2,
                fontweight="bold", color=INK)
        for j, it in enumerate(items):
            _box(ax, x + 0.18, ay + ah - 1.0 - j * 0.48, tw - 0.36, 0.4, it, fs=7.5)

    sy, sh = 3.55, 3.25
    band(sy, sh, "SERVICE", "#FDF3EA", "#B85C1E")
    groups = [("Simulation Engine Service",
               ["1 Hz real-time stepping", "Fixed-order model calls", "Snapshot and read-time refresh", "Comparison session"]),
              ("Simulation Control Service",
               ["Configuration and geometry", "Design and build commands", "Workload and attitude", "Mission and constellation"]),
              ("Data Exchange Service",
               ["WebSocket broadcast", "REST interface", "Renderer state polling", "Unified message envelope"]),
              ("3D Rendering Service",
               ["RTX real-time rendering", "USD stage and session layer", "WebRTC streaming", "Scene and selection extensions"])]
    gw = (band_w - 0.3 * 5) / 4
    for i, (t, items) in enumerate(groups):
        x = band_x + 0.3 + i * (gw + 0.3)
        _box(ax, x, sy + 0.15, gw, sh - 0.3, "", fill="#FFFFFF", edge="#B85C1E")
        ax.text(x + gw / 2, sy + sh - 0.38, t, ha="center", va="center", fontsize=8.2,
                fontweight="bold", color=INK)
        for j, it in enumerate(items):
            _box(ax, x + 0.15, sy + sh - 1.05 - j * 0.55, gw - 0.3, 0.44, it, fs=7)

    cy, ch = 0.2, 3.05
    band(cy, ch, "COMPUTATION", "#EEF7EE", "#2F6B3A")
    cols = [("Orbit", ["SGP4 propagation", "Ground track\nconversion", "Sun position\nand eclipse", "Walker constellation"]),
            ("Communication", ["Ground station\nvisibility", "Access windows\nand downlink", "Band catalog"]),
            ("Computing", ["GPU hardware catalog", "Typed workload\nschedules", "DVFS power law", "LLM inference model"]),
            ("Power", ["Solar array power", "Cell efficiency\nand temperature", "Battery state\nof charge"]),
            ("Thermal", ["Radiator emission", "Environmental\nheat flux", "Lumped thermal node", "GPU die and\nthrottling"])]
    cw = (band_w - 0.25 * 6) / 5
    for i, (t, items) in enumerate(cols):
        x = band_x + 0.25 + i * (cw + 0.25)
        _box(ax, x, cy + 0.12, cw, ch - 0.24, "", fill="#FFFFFF", edge="#2F6B3A")
        ax.text(x + cw / 2, cy + ch - 0.33, t, ha="center", va="center", fontsize=8.5,
                fontweight="bold", color=INK)
        for j, it in enumerate(items):
            _box(ax, x + 0.12, cy + ch - 0.92 - j * 0.52, cw - 0.24, 0.42, it, fs=6.8)

    axx, aw = 13.0, 2.45
    _box(ax, axx, 0.2, aw, 9.2, "", fill="#F7EEF7", edge="#7A3E7A", lw=1.4, rounded=False)
    ax.text(axx + aw / 2, 9.05, "3D Asset Library", ha="center", va="center", fontsize=9.5,
            fontweight="bold", color=INK)
    for j, it in enumerate(["Parametric satellite\ngenerator", "Six hull architectures", "USD stage library",
                            "Geometry parameter store", "Offline software renderer", "Design thumbnail cache"]):
        _box(ax, axx + 0.2, 8.2 - j * 0.85, aw - 0.4, 0.62, it, fs=7.5)

    mid = band_x + band_w / 2
    _arrow(ax, mid - 0.25, sy + sh, mid - 0.25, ay, lw=1.4)
    _arrow(ax, mid + 0.25, ay, mid + 0.25, sy + sh, lw=1.4)
    ax.text(mid + 0.45, (ay + sy + sh) / 2, "commands down, state broadcast and video stream up",
            fontsize=7.2, va="center", color=LINE)
    _arrow(ax, mid - 0.25, sy, mid - 0.25, cy + ch, lw=1.4)
    _arrow(ax, mid + 0.25, cy + ch, mid + 0.25, sy, lw=1.4)
    ax.text(mid + 0.45, (sy + cy + ch) / 2, "every physics step calls all models in fixed order",
            fontsize=7.2, va="center", color=LINE)
    _arrow(ax, band_x + band_w, 5.4, axx, 5.4, lw=1.4)
    _arrow(ax, axx, 4.7, band_x + band_w, 4.7, lw=1.4)
    ax.text((band_x + band_w + axx) / 2, 5.62, "geometry", fontsize=7, ha="center", color=LINE)
    ax.text((band_x + band_w + axx) / 2, 4.32, "USD model", fontsize=7, ha="center", color=LINE)
    F._finish(fig, ax, "fig_architecture.png", W, H)


def usage_flow():
    W, H = 15.0, 9.2
    fig, ax = plt.subplots(figsize=(W * 0.82, H * 0.82))
    lanes = ["Situation Display and\nSimulation Management", "Data Exchange", "Simulation Engine", "3D Rendering and 3D Assets"]
    lw_ = W / 4
    for i, name in enumerate(lanes):
        x = i * lw_
        fill = ["#EEF4FB", "#EEF7EE", "#FDF3EA", "#F7EEF7"][i]
        _box(ax, x + 0.08, 0.1, lw_ - 0.16, H - 0.2, "", fill=fill, edge="#C9CFD6", rounded=False)
        ax.text(x + lw_ / 2, H - 0.45, name, ha="center", va="center", fontsize=8.5, fontweight="bold")

    def node(lane, y, text, h=0.62, w=None, fill="#FFFFFF"):
        w = w or (lw_ - 0.6)
        x = lane * lw_ + (lw_ - w) / 2
        _box(ax, x, y - h / 2, w, h, text, fs=7.4, fill=fill)
        return (x, x + w, y)

    a1 = node(0, 7.6, "Edit scenario: builder wizard,\nconfigurator, design library,\norbit designer", h=0.9)
    a2 = node(1, 7.6, "Receive REST or WebSocket\ncommand, parse the envelope", h=0.9)
    a3 = node(2, 7.6, "Command response: update\nconfiguration, geometry,\nworkload profile, orbit preset", h=0.9)
    a4 = node(3, 7.6, "Regenerate USD model on\ngeometry change, bump version,\nrenderer reloads", h=0.9)
    b1 = node(0, 6.3, "Start simulation")
    b3 = node(2, 6.3, "Initialization: restore geometry,\nassemble entities, start\nstepping coroutine", h=0.9)
    c3 = node(2, 5.0, "Real-time stepping: orbit,\nlighting, power, workload,\nbattery, thermal, alarms", h=0.9)
    c2 = node(1, 5.0, "State broadcast at 1 Hz,\nrenderer polls at 5 Hz", h=0.75)
    c1 = node(0, 5.0, "Telemetry curves, status cards\nand event stream refresh", h=0.75)
    c4 = node(3, 5.0, "Project state to USD per frame,\nRTX render, WebRTC stream", h=0.75)
    d1 = node(0, 3.6, "Runtime operations: attitude,\ndeployment, comparison,\nground station", h=0.9)
    d3 = node(2, 3.6, "Comparison session: offline\nvariant engines advance\nin lockstep", h=0.9)
    e3 = node(2, 2.35, "Simulation ends or user pauses")
    e1 = node(0, 2.35, "Browser shows 3D viewport\nand all analysis tabs", h=0.75)
    f = node(2, 1.25, "End", fill=FILL_ROOT, w=2.0)

    def arr(p, q):
        if p[0] < q[0]:
            _arrow(ax, p[1], p[2], q[0], q[2])
        else:
            _arrow(ax, p[0], p[2], q[1], q[2])

    def varr(p, q):
        xm = (p[0] + p[1]) / 2
        _arrow(ax, xm, p[2] - 0.45, xm, q[2] + 0.45)

    arr(a1, a2); arr(a2, a3); arr(a3, a4)
    varr(a1, b1); arr(b1, b3); varr(b3, c3)
    arr(c3, c2); arr(c2, c1); arr(c3, c4)
    varr(c1, d1); arr(d1, d3); varr(d3, e3); varr(d1, e1); varr(e3, f)
    xc4 = (c4[0] + c4[1]) / 2
    xe1 = (e1[0] + e1[1]) / 2
    ax.plot([xc4, xc4, xe1], [c4[2] - 0.4, 0.5, 0.5], color=LINE, lw=1.2, zorder=2)
    _arrow(ax, xe1, 0.5, xe1, e1[2] - 0.4)
    ax.text((xc4 + xe1) / 2, 0.68, "WebRTC video stream back to the browser viewport", fontsize=7.5,
            color=LINE, ha="center")
    F._finish(fig, ax, "fig_usage_flow.png", W, H)


def tick_flow():
    steps = [
        "Read simulation time t; take the current configuration, geometry and workload profile",
        "Propagate the constellation and the tracked satellite, giving TEME position and velocity",
        "Ground track, sunlight, Sun vector, visible solar disc fraction, ground station elevation",
        "Solar array power: area, efficiency, attitude incidence, Sun distance, temperature derating, deployment",
        "Take the current workload block; solve the GPU operating point and realized draw per card-type group",
        "Integrate battery state of charge, charging taxed by the round-trip loss",
        "Thermal balance integration: dissipation and environmental flux in, radiator emission out",
        "Downlink visibility and data rate",
        "Design margin check and alarm evaluation",
        "Build and broadcast the state snapshot; the comparison session advances one step",
    ]
    W = 8.6
    h_box, gap = 0.62, 0.32
    H = 1.6 + len(steps) * (h_box + gap) + 1.0
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    y = H - 0.4
    _box(ax, W / 2 - 1.3, y - 0.5, 2.6, 0.5, "Begin one physics step", fill=FILL_ROOT, fs=8.5, bold=True)
    prev_y = y - 0.5
    for s in steps:
        y = prev_y - gap
        _box(ax, 0.4, y - h_box, W - 0.8, h_box, s, fs=7.6)
        _arrow(ax, W / 2, prev_y, W / 2, y)
        prev_y = y - h_box
    y = prev_y - gap
    _box(ax, W / 2 - 1.6, y - 0.5, 3.2, 0.5, "Wait for the next 1 Hz heartbeat", fill=FILL_ROOT, fs=8.5, bold=True)
    _arrow(ax, W / 2, prev_y, W / 2, y)
    F._finish(fig, ax, "fig_tick_flow.png", W, H)


def coupling_loop():
    W, H = 12.0, 5.2
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    nodes = [
        (0.4, 3.5, "Orbit and lighting\nposition, sunlight,\nSun vector"),
        (3.3, 3.5, "Solar array and battery\ngenerated power,\nstate of charge"),
        (6.2, 3.5, "GPU payload\npower budget, frequency,\nthroughput"),
        (9.1, 3.5, "Radiator and structure\ndissipation, environment\nflux, temperature"),
    ]
    bw, bh = 2.5, 1.1
    for x, y, t in nodes:
        _box(ax, x, y, bw, bh, t, fs=7.8, fill=FILL_L1)
    for i in range(3):
        _arrow(ax, nodes[i][0] + bw, 4.05, nodes[i + 1][0], 4.05, lw=1.4)
    for i, lb in enumerate(["sunlight and incidence", "available power", "realized draw is heat"]):
        xm = (nodes[i][0] + bw + nodes[i + 1][0]) / 2
        ax.text(xm, 4.78, lb, ha="center", fontsize=7.2, color=LINE)
    _arrow(ax, 9.1 + bw / 2, 3.5, 9.1 + bw / 2, 2.4, lw=1.4)
    _line(ax, 9.1 + bw / 2, 2.4, 6.2 + bw / 2, 2.4, lw=1.4)
    _arrow(ax, 6.2 + bw / 2, 2.4, 6.2 + bw / 2, 3.5, lw=1.4)
    ax.text(7.65 + 1.45, 2.05, "structure temperature is the cold-plate temperature and caps the GPU power budget",
            ha="center", fontsize=7.6, color=INK)
    _line(ax, 9.1 + bw - 0.3, 3.5, 9.1 + bw - 0.3, 1.3, lw=1.1)
    _line(ax, 9.1 + bw - 0.3, 1.3, 3.3 + bw / 2, 1.3, lw=1.1)
    _arrow(ax, 3.3 + bw / 2, 1.3, 3.3 + bw / 2, 3.5, lw=1.1)
    ax.text(6.3, 0.95, "structure temperature derates the solar cell efficiency", ha="center", fontsize=7.6, color=INK)
    _box(ax, 0.4, 0.3, 2.5, 0.55, "loop closes once per step", fill=FILL_ROOT, fs=7.6, bold=True)
    F._finish(fig, ax, "fig_coupling_loop.png", W, H)


def model_hierarchy():
    W, H = 12.4, 5.0
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    rows = [
        (3.6, "Concept\nmodels", ["Compute satellite", "Satellite constellation", "Ground station and target"], "#FBE9DD"),
        (2.0, "Algorithm\nmodels", ["Orbit and eclipse", "Power and storage", "Thermal balance", "GPU inference\nperformance", "Visibility and links"], "#E4E1F2"),
        (0.4, "Entity\nmodels", ["Satellite entity and\npayload components", "Constellation entity", "Ground station entity"], "#E3E7EC"),
    ]
    for y, title, items, fill in rows:
        _box(ax, 0.3, y, W - 0.6, 1.15, "", fill="#F4F5F7", edge=LINE, rounded=False)
        _box(ax, 0.45, y + 0.2, 1.7, 0.75, title, fill=fill, fs=8.5, bold=True)
        n = len(items)
        avail = W - 0.6 - 2.2
        iw = min(2.6, (avail - 0.2 * (n - 1)) / n)
        x0 = 2.4 + (avail - (n * iw + 0.2 * (n - 1))) / 2
        for i, it in enumerate(items):
            _box(ax, x0 + i * (iw + 0.2), y + 0.2, iw, 0.75, it, fs=7.6, fill=fill)
    for y in (3.6, 2.0):
        _arrow(ax, W / 2, y - 0.03, W / 2, y - 0.42, lw=1.6)
    F._finish(fig, ax, "fig_model_hierarchy.png", W, H)


def entity_flow():
    steps = [
        ("Start", True),
        ("Entity initialization: platform constants, slot payloads,\ngeometry areas, initial charge and temperature", False),
        ("Orbit propagation and lighting determination", False),
        ("Solve power generation and workload operating point", False),
        ("Integrate battery and thermal node", False),
        ("Die temperature above throttle target?", "dec"),
        ("Shrink the power budget, record the throttle alarm", False),
        ("Write back state and advance to the next step", False),
        ("End of simulation", True),
    ]
    W = 8.2
    hb, gap = 0.6, 0.3
    H = 1.0 + len(steps) * (hb + gap) + 0.4
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    y = H - 0.3
    prev = None
    for text, kind in steps:
        y_top = y
        if kind == "dec":
            cx, cy = W / 2, y_top - hb / 2
            ax.add_patch(plt.Polygon([(cx - 2.8, cy), (cx, cy + hb / 2 + 0.05), (cx + 2.8, cy),
                                      (cx, cy - hb / 2 - 0.05)], closed=True, fc="#FFFFFF", ec=LINE))
            ax.text(cx, cy, text, ha="center", va="center", fontsize=7.8)
            ax.text(cx + 2.9, cy + 0.15, "no", fontsize=7.5, color=LINE)
            ax.text(cx + 0.12, cy - hb / 2 - 0.25, "yes", fontsize=7.5, color=LINE)
        elif kind is True:
            _box(ax, W / 2 - 1.2, y_top - hb, 2.4, hb, text, fill=FILL_ROOT, fs=8.5, bold=True)
        else:
            _box(ax, 0.5, y_top - hb, W - 1.0, hb, text, fs=7.6)
        if prev is not None:
            _arrow(ax, W / 2, prev, W / 2, y_top + (0.05 if kind == "dec" else 0))
        prev = y_top - hb - (0.05 if kind == "dec" else 0)
        y = prev - gap
    y_dec = H - 0.3 - 5 * (hb + gap) - hb / 2
    y_wb = H - 0.3 - 7 * (hb + gap) - hb / 2
    _line(ax, W / 2 + 2.8, y_dec, W - 0.25, y_dec)
    _line(ax, W - 0.25, y_dec, W - 0.25, y_wb)
    _arrow(ax, W - 0.25, y_wb, W - 0.5, y_wb)
    y_orb = H - 0.3 - 2 * (hb + gap) - hb / 2
    _line(ax, 0.5, y_wb, 0.25, y_wb)
    _line(ax, 0.25, y_wb, 0.25, y_orb)
    _arrow(ax, 0.25, y_orb, 0.5, y_orb)
    F._finish(fig, ax, "fig_entity_flow.png", W, H)


def time_cascade():
    W, H = 13.0, 3.6
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    items = [
        ("Physics step\n1 Hz", "engine advances simulation\ntime and integrates state"),
        ("Read-time refresh\nper read", "geometry recomputed from\nsim time plus wall-clock fraction"),
        ("Renderer polling\n5 Hz", "fetch state, update anchor\nand easing targets"),
        ("Frame callback\nabout 30 fps", "exponential easing to target,\nextrapolated constellation phase"),
        ("Display extrapolation\nrefresh rate", "browser smooths the\n1 Hz steps"),
    ]
    bw, bh = 2.2, 1.0
    x = 0.3
    for i, (t, d) in enumerate(items):
        _box(ax, x, 2.0, bw, bh, t, fill=FILL_L1, fs=7.8, bold=True)
        ax.text(x + bw / 2, 1.4, d, ha="center", va="center", fontsize=6.8, color=INK)
        if i < len(items) - 1:
            _arrow(ax, x + bw, 2.5, x + bw + 0.35, 2.5, lw=1.3)
        x += bw + 0.35
    ax.text(W / 2, 0.55, "one authoritative clock; every other time is a downsampled or smoothed view of it",
            ha="center", fontsize=8, color=INK)
    F._finish(fig, ax, "fig_time_cascade.png", W, H)


def main():
    architecture()
    tree("fig_system_tree.png", "Orbital Compute Data Center" + chr(10) + "Digital Twin Platform", [
        ("Simulation Model\nSubsystem", ["Computation models", "Model standard interface", "Entity models", "Payload component models"]),
        ("Simulation Engine\nSubsystem", ["Model initialization", "Real-time stepping", "Command response", "State output", "Comparison simulation"]),
        ("Data Exchange\nSubsystem", ["WebSocket broadcast", "REST interface", "Renderer polling interface", "Data entity contract"]),
        ("Situation Display and\nSimulation Management", ["Overview page", "Satellite twin page", "Satellite builder wizard", "Orbit and ground station\nworkbench", "Comparison panel"]),
        ("3D Rendering\nSubsystem", ["Render host application", "Scene extension", "Selection extension", "Messaging extension", "Streaming layer"]),
        ("3D Asset\nSubsystem", ["Parametric model generator", "Hull architecture library", "USD stage library", "Offline software renderer"]),
    ], col_w=2.75, gap=0.25, g_h=0.8, root_h=0.85, leaf_h=0.58, fs_leaf=7.4, fs_group=8, fs_root=9.5)
    tree("fig_model_subsystem.png", "Simulation Model Subsystem", [
        ("Computation Model\nModule", ["Orbit propagation", "Ground track and\ncoordinate conversion", "Sun position and eclipse",
                                       "Ground station visibility", "Solar array power", "Battery state of charge", "Thermal balance",
                                       "GPU workload and power", "LLM inference performance", "Design margin check", "Ground station analytics"]),
        ("Model Standard\nInterface Module", ["Initialization", "Step advance", "Command response", "State output"]),
        ("Entity Model\nModule", ["Compute satellite entity", "Constellation entity", "Ground station entity"]),
        ("Payload Component\nModule", ["Solar array", "Battery", "Radiator", "GPU payload", "Communications"]),
    ], col_w=3.1, gap=0.35, g_h=0.8, leaf_h=0.6, fs_leaf=7.8, fs_group=8.5)
    tree("fig_engine_subsystem.png", "Simulation Engine Subsystem", [
        ("Model\nInitialization", ["Geometry restore", "Entity assembly", "Parameter table loading"]),
        ("Real-time\nStepping", ["1 Hz heartbeat coroutine", "Fixed-order model calls", "State integration", "Alarm evaluation"]),
        ("Command\nResponse", ["Configuration and geometry", "Design and build", "Workload and attitude", "Mission and constellation"]),
        ("State\nOutput", ["State snapshot", "Read-time kinematics\nrefresh", "Broadcast callback"]),
        ("Comparison\nSimulation", ["Consistent snapshot", "Offline variant engines", "Lockstep session", "Preview engine"]),
    ], col_w=2.8, gap=0.3, g_h=0.8, leaf_h=0.6, fs_leaf=7.6, fs_group=8.5)
    tree("fig_comm_subsystem.png", "Data Exchange Subsystem", [
        ("WebSocket\nBroadcast Module", ["Connection management", "Command dispatch", "State broadcast", "Acknowledgement and error"]),
        ("REST Interface\nModule", ["State read", "Configuration and geometry", "Design and build", "Orbit and ground station", "Comparison and mission"]),
        ("Renderer Polling\nInterface", ["State polling", "Selection report", "Scene-ready notification"]),
        ("Data Entity\nContract", ["State packet", "Satellite state", "Satellite configuration", "Twin geometry"]),
    ], col_w=3.1, gap=0.35, g_h=0.8, leaf_h=0.6, fs_leaf=7.8, fs_group=8.5)
    tree("fig_ui_subsystem.png", "Situation Display and Simulation Management Subsystem", [
        ("Overview\nPage", ["3D Earth and constellation", "Telemetry parameter cards", "Constellation preset switch", "Event stream"]),
        ("Orbit and Ground\nStation Workbench", ["Design tab", "Coverage tab", "Solar histogram tab", "Band comparison tab"]),
        ("Satellite Twin\nPage", ["3D twin viewport", "Satellite configurator", "Design library", "Telemetry strip"]),
        ("Satellite Builder\nWizard", ["Platform selection", "Structure design", "Payload design", "Workload profile"]),
        ("Comparison\nPanel", ["Dimension selection", "Candidate values", "Live value table"]),
    ], col_w=2.8, gap=0.3, g_h=0.8, leaf_h=0.6, fs_leaf=7.6, fs_group=8.5)
    tree("fig_render_subsystem.png", "3D Rendering Subsystem", [
        ("Render Host\nApplication", ["RTX renderer", "USD stage and session layer", "Frame event stream", "WebRTC streaming layer"]),
        ("Scene\nExtension", ["State polling", "Stage switching", "Per-frame drive", "Model hot reload"]),
        ("Selection\nExtension", ["Component pick events", "Selection report"]),
        ("Messaging\nExtension", ["Browser to renderer\ndata channel"]),
        ("Setup\nExtension", ["Initial stage open", "Window layout"]),
    ], col_w=2.8, gap=0.3, g_h=0.8, leaf_h=0.6, fs_leaf=7.6, fs_group=8.5)
    tree("fig_asset_subsystem.png", "3D Asset Subsystem", [
        ("Parametric Model\nGenerator", ["Backbone and rack slots", "Solar array clusters", "Radiator panels", "Blades and GPU color tags"]),
        ("Hull Architecture\nLibrary", ["Single truss", "Twin-truss tower", "Blanket wing", "Cross-wing smallsat", "Windmill-wing comms bus", "Flat payload bay"]),
        ("USD Stage\nLibrary", ["Overview stage", "Satellite close-up stage", "Earth and star field", "Lights and cameras"]),
        ("Offline Software\nRenderer", ["GL-free rasterization", "Design thumbnails", "Geometry check renders"]),
    ], col_w=3.1, gap=0.35, g_h=0.8, leaf_h=0.6, fs_leaf=7.8, fs_group=8.5)
    usage_flow()
    tick_flow()
    coupling_loop()
    model_hierarchy()
    entity_flow()
    time_cascade()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
