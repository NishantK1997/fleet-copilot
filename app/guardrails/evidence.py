from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.database.models import ComplianceResult, Device, Employee, TelemetrySnapshot
from app.guardrails.authorization import TenantIsolationError
from app.services.analytics import AnalyticsService, InsightDetectionInput, Insight
from app.tools.schemas import Evidence


@dataclass
class EvidenceDecision:
    allowed: bool
    reason: str
    evidence: list[Evidence]


def _require_device(db: Session, context: TenantContext, device_id: str) -> Device:
    device = db.get(Device, (device_id, context.company_id))
    if device is None:
        raise TenantIsolationError("device not found for authenticated tenant")
    return device


def _require_employee(db: Session, context: TenantContext, employee_id: str) -> Employee:
    employee = db.get(Employee, (employee_id, context.company_id))
    if employee is None:
        raise TenantIsolationError("employee not found for authenticated tenant")
    return employee


def _insight_for_device(insights: list[Insight], device_id: str, insight_type: str) -> Insight | None:
    for insight in insights:
        if insight.device_id == device_id and insight.insight_type == insight_type:
            return insight
    return None


def check_upgrade_order_evidence(
    db: Session,
    context: TenantContext,
    *,
    device_id: str,
    component: str,
) -> EvidenceDecision:
    _require_device(db, context, device_id)
    component_text = component.lower()
    service = AnalyticsService(db=db, context=context)

    if component_text in {"storage", "disk", "ssd"}:
        insights = service.detect_low_disk(service.input_for(["low_disk"]))
        insight = _insight_for_device(insights, device_id, "low_disk")
        if insight:
            return EvidenceDecision(True, "Persistent low disk evidence supports a storage upgrade proposal.", insight.evidence)
        return EvidenceDecision(False, "Storage upgrades require persistent low-disk evidence for the target device.", [])

    if component_text in {"memory", "ram"}:
        insights = service.detect_memory_pressure(service.input_for(["memory_pressure"]))
        insight = _insight_for_device(insights, device_id, "memory_pressure")
        if insight:
            return EvidenceDecision(True, "Persistent memory pressure evidence supports a memory upgrade proposal.", insight.evidence)
        return EvidenceDecision(False, "Memory upgrades require persistent RAM pressure evidence for the target device.", [])

    return EvidenceDecision(False, "Unsupported upgrade component. Allowed components are storage/disk/ssd or memory/ram.", [])


def check_remediation_ticket_evidence(
    db: Session,
    context: TenantContext,
    *,
    device_id: str,
    check_id: str,
) -> EvidenceDecision:
    _require_device(db, context, device_id)
    row = db.execute(
        select(ComplianceResult, TelemetrySnapshot)
        .join(TelemetrySnapshot, TelemetrySnapshot.id == ComplianceResult.snapshot_id)
        .where(
            ComplianceResult.company_id == context.company_id,
            ComplianceResult.device_id == device_id,
            ComplianceResult.check_id == check_id,
            ComplianceResult.status == "fail",
        )
        .order_by(desc(TelemetrySnapshot.collected_at))
        .limit(1)
    ).first()
    if not row:
        return EvidenceDecision(False, "Remediation tickets require an actual failing compliance check for the target device.", [])

    result, snapshot = row
    evidence = [
        Evidence(
            device_id=device_id,
            snapshot_id=snapshot.id,
            collected_at=snapshot.collected_at,
            source="compliance_results",
            metric_or_check=result.check_id,
            value=result.status,
            explanation=f"{result.severity} severity",
        )
    ]
    return EvidenceDecision(True, "Failing compliance evidence supports a remediation ticket proposal.", evidence)


def check_replacement_evidence(
    db: Session,
    context: TenantContext,
    *,
    device_id: str,
) -> EvidenceDecision:
    _require_device(db, context, device_id)
    service = AnalyticsService(db=db, context=context)
    insights = service.detect_battery_risk(service.input_for(["battery_risk"]))
    insight = _insight_for_device(insights, device_id, "battery_risk")
    if insight:
        return EvidenceDecision(True, "Battery risk evidence supports a replacement proposal.", insight.evidence)
    return EvidenceDecision(False, "Replacement requests require strong battery replacement-risk evidence for the target device.", [])


def check_notification_evidence(
    db: Session,
    context: TenantContext,
    *,
    employee_id: str,
    device_id: str | None,
) -> EvidenceDecision:
    _require_employee(db, context, employee_id)
    if not device_id:
        return EvidenceDecision(False, "Notifications require a tenant-owned device so the message can be tied to telemetry evidence.", [])
    device = _require_device(db, context, device_id)
    if device.employee_id != employee_id:
        return EvidenceDecision(False, "Notification employee must own the target device.", [])
    snapshot = db.scalar(
        select(TelemetrySnapshot)
        .where(TelemetrySnapshot.company_id == context.company_id, TelemetrySnapshot.device_id == device_id)
        .order_by(desc(TelemetrySnapshot.collected_at))
        .limit(1)
    )
    if snapshot is None:
        return EvidenceDecision(False, "Notification requires latest telemetry evidence for the target device.", [])
    evidence = [
        Evidence(
            device_id=device_id,
            snapshot_id=snapshot.id,
            collected_at=snapshot.collected_at,
            source="telemetry_snapshots",
            metric_or_check="latest_device_state",
            value=snapshot.collected_at.isoformat(),
        )
    ]
    return EvidenceDecision(True, "Latest device telemetry supports a notification proposal.", evidence)
