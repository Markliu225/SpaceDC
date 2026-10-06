"""Shared test plumbing for the SDTwin thermal test cases.

Every test module declares the case it belongs to with ``pytestmark = pytest.mark.case("PA-001")`` and records its
checks through the ``case_record`` fixture. At the end of the session one evidence file per case is written to
``tests/results/<CASE_ID>.json`` (format in Thermal/IMPLEMENTATION.md). A test that fails or errors outside an
explicit check is recorded as a failed check, so a crash can never read as a pass.
"""
from __future__ import annotations

import json
import hashlib
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

THERMAL_DIR = Path(__file__).resolve().parents[1]
if str(THERMAL_DIR) not in sys.path:
    sys.path.insert(0, str(THERMAL_DIR))

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DATA_DIR = Path(__file__).resolve().parent / "data"


def _environment() -> dict:
    env = {"python": platform.python_version()}
    for name in ("numpy", "scipy", "astropy", "pytest"):
        try:
            module = __import__(name)
            env[name] = getattr(module, "__version__", "unknown")
        except ImportError:
            env[name] = "missing"
    try:
        from importlib.metadata import version

        env["ntu_space_dynamics"] = version("ntu-space-dynamics")
    except Exception:  # noqa: BLE001
        env["ntu_space_dynamics"] = "unknown"
    try:
        from pxr import Usd

        env["usd"] = ".".join(str(v) for v in Usd.GetVersion())
    except Exception:  # noqa: BLE001
        env["usd"] = "missing"
    return env


class CaseRecord:
    """Collects the checks, metrics and Chinese summary of one test case across its test functions."""

    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self.checks: list[dict] = []
        self.metrics: dict = {}
        self.summary_cn = ""
        self.anomalies_cn = ""
        self.status_override: str | None = None

    def check(self, name: str, expected, actual, passed: bool) -> bool:
        self.checks.append({"name": str(name), "expected": str(expected), "actual": str(actual), "passed": bool(passed)})
        return bool(passed)

    def metric(self, key: str, value) -> None:
        self.metrics[key] = value

    def summary(self, text_cn: str) -> None:
        self.summary_cn = text_cn

    def anomalies(self, text_cn: str) -> None:
        self.anomalies_cn = text_cn

    def status(self, status: str) -> None:
        if status not in {"pass", "fail", "partial", "not_run"}:
            raise ValueError(status)
        self.status_override = status

    def resolved_status(self) -> str:
        failed = any(not c["passed"] for c in self.checks)
        if failed:
            return "fail"
        if self.status_override:
            return self.status_override
        return "pass" if self.checks else "not_run"

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": self.resolved_status(),
            "checks": self.checks,
            "metrics": self.metrics,
            "summary_cn": self.summary_cn,
            "anomalies_cn": self.anomalies_cn or "无",
            "environment": _environment(),
        }


_RECORDS: dict[str, CaseRecord] = {}
_EXPECTED: dict[str, set[str]] = {}
_FINISHED: dict[str, set[str]] = {}
_STARTED_UTC = datetime.now(timezone.utc).isoformat()


def pytest_collection_modifyitems(items):
    order = ['PA-001', 'HT-001', 'HT-002', 'DM-001', 'EN-001', 'EN-002', 'EN-003',
             'HT-003', 'EC-001', 'FE-001', 'FE-002', 'FE-003', 'FE-004', 'NI-001', 'NI-002', 'NI-003']
    items.sort(key=lambda item: order.index(_case_id(item)) if _case_id(item) in order else len(order))
    for item in items:
        cid = _case_id(item)
        if cid:
            _EXPECTED.setdefault(cid, set()).add(item.nodeid)


def _write_record(case_id, record):
    data = record.as_dict()
    missing = sorted(_EXPECTED.get(case_id, set()) - _FINISHED.get(case_id, set()))
    if missing or not data['summary_cn']:
        if data['status'] == 'pass':
            data['status'] = 'partial'
        note = '本次测试未形成完整的执行记录或结果摘要。'
        data['anomalies_cn'] = note if data['anomalies_cn'] == '无' else data['anomalies_cn'] + note
    failed = [c['name'] for c in data['checks'] if not c['passed']]
    if failed and data['anomalies_cn'] == '无':
        data['anomalies_cn'] = '本次存在未通过检查，详见检查明细。'
    hashes = {}
    for folder in ('thermal', 'sdtwin_sim', 'tests'):
        for path in sorted((THERMAL_DIR / folder).rglob('*.py')):
            hashes[str(path.relative_to(THERMAL_DIR)).replace('\\', '/')] = hashlib.sha256(path.read_bytes()).hexdigest()
    data['execution'] = {'started_utc': _STARTED_UTC, 'recorded_utc': datetime.now(timezone.utc).isoformat(),
                         'collected_functions': len(_EXPECTED.get(case_id, set())),
                         'finished_functions': len(_FINISHED.get(case_id, set())),
                         'unexecuted_functions': missing, 'source_sha256': hashes}
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f'{case_id}.json').write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def pytest_configure(config):
    config.addinivalue_line("markers", "case(case_id): test case of the SDTwin thermal test report")


def _case_id(item) -> str | None:
    marker = item.get_closest_marker("case")
    return marker.args[0] if marker and marker.args else None


@pytest.fixture
def case_record(request) -> CaseRecord:
    case_id = _case_id(request.node)
    if case_id is None:
        raise RuntimeError("test module must set pytestmark = pytest.mark.case('<CASE_ID>')")
    return _RECORDS.setdefault(case_id, CaseRecord(case_id))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    case_id = _case_id(item)
    if case_id is None or report.when not in {"setup", "call", "teardown"}:
        return
    record = _RECORDS.setdefault(case_id, CaseRecord(case_id))
    if report.failed:
        text = str(report.longreprtext).strip().splitlines()
        tail = " | ".join(text[-6:]) if text else "failed"
        record.check(f"{item.name} {report.when}", "test function completes", tail[:2000], False)
    if report.when == 'teardown':
        _FINISHED.setdefault(case_id, set()).add(item.nodeid)
        if _FINISHED[case_id] == _EXPECTED.get(case_id):
            _write_record(case_id, record)


def pytest_sessionfinish(session, exitstatus):
    if not _RECORDS:
        return
    RESULTS_DIR.mkdir(exist_ok=True)
    for case_id, record in _RECORDS.items():
        _write_record(case_id, record)
