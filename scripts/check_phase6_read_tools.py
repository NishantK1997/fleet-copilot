import sys
from pathlib import Path

from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.auth import login
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.models import ComplianceResult, Device, TelemetrySnapshot
from app.database.session import SessionLocal
from app.tools.read_tools import (
    get_battery_risk_devices,
    get_compliance_failures,
    get_device_details,
    get_device_metric_history,
    get_fleet_summary,
    get_low_disk_devices,
    get_memory_pressure_devices,
    search_devices,
    search_software_inventory,
    search_telemetry,
)
from app.tools.schemas import (
    ComplianceFailuresInput,
    DeviceDetailsInput,
    DeviceMetricHistoryInput,
    SearchDevicesInput,
    SearchTelemetryInput,
    SoftwareInventoryInput,
)


def build_context(db, email: str, password: str):
    token = login(LoginRequest(email=email, password=password), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def table_counts(db) -> tuple[int, int, int]:
    return (
        db.scalar(select(func.count()).select_from(Device)) or 0,
        db.scalar(select(func.count()).select_from(TelemetrySnapshot)) or 0,
        db.scalar(select(func.count()).select_from(ComplianceResult)) or 0,
    )


def main() -> None:
    with SessionLocal() as db:
        context = build_context(db, "admin@acme.example", "AcmeAdmin123!")
        before = table_counts(db)

        summary = get_fleet_summary(db, context)
        assert summary.data["device_count"] == 10
        assert summary.evidence
        print("get_fleet_summary: PASS")

        devices = search_devices(db, context, SearchDevicesInput(os_product_version_lt="15", limit=5))
        assert all(row["device_id"] for row in devices.data)
        assert devices.evidence
        device_id = devices.data[0]["device_id"]
        print("search_devices: PASS")

        details = get_device_details(db, context, DeviceDetailsInput(device_id=device_id))
        assert details.data["device_id"] == device_id
        assert details.evidence
        print("get_device_details: PASS")

        history = get_device_metric_history(db, context, DeviceMetricHistoryInput(device_id=device_id, metric="memory", limit=3))
        assert len(history.data) == 3
        assert history.evidence
        print("get_device_metric_history: PASS")

        low_disk = get_low_disk_devices(db, context)
        assert isinstance(low_disk.data, list)
        print("get_low_disk_devices: PASS")

        memory = get_memory_pressure_devices(db, context)
        assert isinstance(memory.data, list)
        print("get_memory_pressure_devices: PASS")

        battery = get_battery_risk_devices(db, context)
        assert isinstance(battery.data, list)
        print("get_battery_risk_devices: PASS")

        failures = get_compliance_failures(db, context, ComplianceFailuresInput(severity="medium", limit=10))
        assert failures.evidence
        print("get_compliance_failures: PASS")

        software = search_software_inventory(db, context, SoftwareInventoryInput(name_contains="Chrome", limit=10))
        assert software.evidence
        print("search_software_inventory: PASS")

        fallback = search_telemetry(db, context, SearchTelemetryInput(resource="compliance", field="status", operator="eq", value="fail", limit=10))
        assert fallback.evidence
        print("search_telemetry: PASS")

        after = table_counts(db)
        assert before == after
        print("read tools did not mutate core telemetry tables: PASS")


if __name__ == "__main__":
    main()
