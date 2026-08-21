from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

from app.api.auth import login
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.models import ComplianceResult, Device, TelemetrySnapshot
from app.database.session import SessionLocal
from app.guardrails.authorization import TenantIsolationError
from app.tools.read_tools import (
    get_compliance_failures,
    get_device_details,
    get_device_metric_history,
    get_fleet_summary,
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


def context_for(db, email: str, password: str):
    token = login(LoginRequest(email=email, password=password), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def telemetry_counts(db):
    return (
        db.scalar(select(func.count()).select_from(Device)),
        db.scalar(select(func.count()).select_from(TelemetrySnapshot)),
        db.scalar(select(func.count()).select_from(ComplianceResult)),
    )


def test_fleet_summary_is_tenant_scoped():
    with SessionLocal() as db:
        acme = context_for(db, "admin@acme.example", "AcmeAdmin123!")
        globex = context_for(db, "admin@globex.example", "GlobexAdmin123!")
        acme_summary = get_fleet_summary(db, acme)
        globex_summary = get_fleet_summary(db, globex)
        assert acme_summary.data["device_count"] == 10
        assert globex_summary.data["device_count"] == 8
        assert acme_summary.evidence
        assert globex_summary.evidence


def test_search_and_details_return_evidence():
    with SessionLocal() as db:
        context = context_for(db, "admin@acme.example", "AcmeAdmin123!")
        result = search_devices(db, context, SearchDevicesInput(os_product_version_lt="15", limit=10))
        assert result.data
        assert result.evidence

        details = get_device_details(db, context, DeviceDetailsInput(device_id=result.data[0]["device_id"]))
        assert details.data["device_id"] == result.data[0]["device_id"]
        assert details.evidence[0].snapshot_id is not None


def test_cross_tenant_device_details_are_blocked():
    with SessionLocal() as db:
        context = context_for(db, "admin@acme.example", "AcmeAdmin123!")
        globex_device_id = db.scalar(select(Device.device_id).where(Device.company_id == "globex-002"))
        assert globex_device_id is not None
        try:
            get_device_details(db, context, DeviceDetailsInput(device_id=globex_device_id))
        except TenantIsolationError:
            pass
        else:
            raise AssertionError("cross-tenant detail lookup should be blocked")


def test_history_compliance_software_and_fallback_have_evidence():
    with SessionLocal() as db:
        context = context_for(db, "admin@acme.example", "AcmeAdmin123!")
        device_id = db.scalar(select(Device.device_id).where(Device.company_id == "acme-001"))
        assert device_id is not None

        history = get_device_metric_history(db, context, DeviceMetricHistoryInput(device_id=device_id, metric="disk", limit=5))
        failures = get_compliance_failures(db, context, ComplianceFailuresInput(severity="medium", limit=5))
        software = search_software_inventory(db, context, SoftwareInventoryInput(name_contains="Chrome", limit=5))
        fallback = search_telemetry(db, context, SearchTelemetryInput(resource="snapshots", field="device_id", operator="eq", value=device_id, limit=5))

        assert history.evidence
        assert failures.evidence
        assert software.evidence
        assert fallback.evidence


def test_read_tools_do_not_mutate_core_telemetry_tables():
    with SessionLocal() as db:
        context = context_for(db, "admin@acme.example", "AcmeAdmin123!")
        before = telemetry_counts(db)
        get_fleet_summary(db, context)
        search_devices(db, context, SearchDevicesInput(limit=5))
        get_compliance_failures(db, context)
        after = telemetry_counts(db)
        assert before == after
