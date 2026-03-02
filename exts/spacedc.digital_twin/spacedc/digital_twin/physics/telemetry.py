"""
============================================================
  telemetry.py — Telemetry log system
  Migrated from: js/telemetry.js
============================================================
"""
from __future__ import annotations
from typing import List, Tuple
from collections import deque

# ── Preset telemetry log messages ───────────────────────────
LOGS: List[Tuple[str, str]] = [
    ("ok",   "Solar tracking nominal. Sun angle <3°."),
    ("info", "Station-keeping ΔV=0.2m/s done."),
    ("ok",   "GPU T=84°C. Cold plate ΔT=8°C."),
    ("info", "Downlink: Tokyo→Svalbard. 12Gbps."),
    ("warn", "Cosmic ray DIMM-07. ECC corrected."),
    ("ok",   "BMS: 480 cells balanced. SOH=99.8%."),
    ("info", "LLM batch queued. 847 jobs pending."),
    ("ok",   "ADCS 0.01° off-nadir. RWA OK."),
    ("info", "SSO dawn-dusk geometry. β=2.3°."),
    ("ok",   "Laser: 12Gbps Tenerife. BER=1e-12."),
    ("ok",   "VCHP conductance adj. post-eclipse."),
    ("warn", "Wing-D 82°C. Within TML."),
    ("ok",   "Radiator P3 NH₃ 4.2kg/s nominal."),
    ("info", "Orbit decay +0.1km cold-gas thrust."),
]

MAX_LOG_ENTRIES = 60


class TelemetryLogger:
    """
    Ring-buffer telemetry log that replaces the DOM-based logger.
    UI panels can subscribe to ``on_log`` callback.
    """

    def __init__(self):
        self._entries: deque = deque(maxlen=MAX_LOG_ENTRIES)
        self._callbacks: list = []

    def add_log(self, level: str, msg: str, met_seconds: float = 0.0):
        """
        Append a log entry.
        ``level``: 'ok' | 'info' | 'warn' | 'danger'
        """
        h = int(met_seconds // 3600)
        m = int((met_seconds % 3600) // 60)
        s = int(met_seconds % 60)
        timestamp = f"[{h:03d}:{m:02d}:{s:02d}]"
        entry = {"level": level, "timestamp": timestamp, "msg": msg}
        self._entries.append(entry)
        for cb in self._callbacks:
            cb(entry)

    def subscribe(self, callback):
        """Register a callback ``fn(entry_dict)`` for new logs."""
        self._callbacks.append(callback)

    def unsubscribe(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    @property
    def entries(self) -> list:
        return list(self._entries)

    def format_met(self, met_seconds: float) -> str:
        """Format MET as T+HHH:MM:SS string."""
        h = int(met_seconds // 3600)
        m = int((met_seconds % 3600) // 60)
        s = int(met_seconds % 60)
        return f"T+{h:03d}:{m:02d}:{s:02d}"
