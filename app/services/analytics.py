from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.config_policies import load_policies
from app.database.models import ComplianceResult, DiskVolume, TelemetrySnapshot
from app.tools.schemas import Evidence, ToolResult


InsightType = Literal["low_disk", "memory_pressure", "battery_risk", "compliance_drift"]


class Insight(BaseModel):
    insight_type: InsightType
    finding: str
    explanation: str
    device_id: str | None = None
    check_id: str | None = None
    severity: str
    time_window_start: datetime | None = None
    time_window_end: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)


class InsightDetectionInput(BaseModel):
    include_types: list[InsightType] | None = None
    low_disk_percent: float = Field(default=10, gt=0, le=100)
    memory_used_percent: float = Field(default=85, gt=0, le=100)
    persistent_ratio: float = Field(default=0.5, ge=0, le=1)
    battery_cycle_count: int = Field(default=900, ge=0)
    battery_capacity_low: int = Field(default=5000, ge=0)
    compliance_drift_fail_ratio: float = Field(default=0.25, ge=0, le=1)
    limit_per_type: int = Field(default=10, ge=1, le=100)


def _pct(part: int | None, whole: int | None) -> float | None:
    if part is None or whole in (None, 0):
        return None
    return round((part / whole) * 100, 2)


def _evidence(
    snapshot: TelemetrySnapshot,
    *,
    source: str,
    metric_or_check: str,
    value: Any,
    unit: str | None = None,
    explanation: str | None = None,
) -> Evidence:
    return Evidence(
        device_id=snapshot.device_id,
        snapshot_id=snapshot.id,
        collected_at=snapshot.collected_at,
        source=source,
        metric_or_check=metric_or_check,
        value=value,
        unit=unit,
        explanation=explanation,
    )


@dataclass
class AnalyticsService:
    db: Session
    context: TenantContext

    def detect_insights(self, payload: InsightDetectionInput | None = None) -> ToolResult:
        payload = payload or self.default_input()
        include = set(payload.include_types or ["low_disk", "memory_pressure", "battery_risk", "compliance_drift"])
        insights: list[Insight] = []
        if "low_disk" in include:
            insights.extend(self.detect_low_disk(payload))
        if "memory_pressure" in include:
            insights.extend(self.detect_memory_pressure(payload))
        if "battery_risk" in include:
            insights.extend(self.detect_battery_risk(payload))
        if "compliance_drift" in include:
            insights.extend(self.detect_compliance_drift(payload))

        evidence = [item for insight in insights for item in insight.evidence]
        data = [insight.model_dump(mode="json", exclude={"evidence"}) for insight in insights]
        return ToolResult(
            tool="detect_insights",
            summary=f"{len(insights)} deterministic insights detected.",
            data=data,
            evidence=evidence,
        )

    def default_input(self) -> InsightDetectionInput:
        policy = load_policies().insights
        return InsightDetectionInput(
            low_disk_percent=policy.low_disk_percent,
            memory_used_percent=policy.memory_used_percent,
            persistent_ratio=policy.persistent_ratio,
            battery_cycle_count=policy.battery_cycle_count,
            battery_capacity_low=policy.battery_capacity_low,
            compliance_drift_fail_ratio=policy.compliance_drift_fail_ratio,
        )

    def input_for(self, include_types: list[InsightType]) -> InsightDetectionInput:
        payload = self.default_input()
        payload.include_types = include_types
        return payload

    def detect_low_disk(self, payload: InsightDetectionInput) -> list[Insight]:
        rows = self.db.execute(
            select(TelemetrySnapshot, DiskVolume)
            .join(DiskVolume, DiskVolume.snapshot_id == TelemetrySnapshot.id)
            .where(TelemetrySnapshot.company_id == self.context.company_id)
            .order_by(TelemetrySnapshot.device_id, TelemetrySnapshot.collected_at)
        ).all()
        grouped: dict[str, list[tuple[TelemetrySnapshot, float]]] = defaultdict(list)
        for snapshot, volume in rows:
            available_pct = _pct(volume.available_bytes, volume.size_bytes)
            if available_pct is not None:
                grouped[snapshot.device_id].append((snapshot, available_pct))

        insights = []
        for device_id, values in grouped.items():
            low = [(snapshot, pct) for snapshot, pct in values if pct < payload.low_disk_percent]
            ratio = len(low) / len(values) if values else 0
            if ratio < payload.persistent_ratio:
                continue
            ordered = sorted(values, key=lambda item: item[0].collected_at)
            low_ordered = sorted(low, key=lambda item: item[0].collected_at)
            latest_pct = ordered[-1][1]
            evidence = [
                _evidence(snapshot, source="disk_volumes", metric_or_check="disk_available_percent", value=pct, unit="%")
                for snapshot, pct in low_ordered[:3]
            ]
            insights.append(
                Insight(
                    insight_type="low_disk",
                    finding=f"Device {device_id} is persistently low on disk space.",
                    explanation=f"{len(low)} of {len(values)} snapshots were below {payload.low_disk_percent}% available disk.",
                    device_id=device_id,
                    severity="high" if ratio >= 0.8 else "medium",
                    time_window_start=ordered[0][0].collected_at,
                    time_window_end=ordered[-1][0].collected_at,
                    metrics={
                        "low_snapshot_count": len(low),
                        "total_snapshot_count": len(values),
                        "low_ratio": round(ratio, 3),
                        "latest_available_percent": latest_pct,
                    },
                    evidence=evidence,
                )
            )
            if len(insights) >= payload.limit_per_type:
                break
        return insights

    def detect_memory_pressure(self, payload: InsightDetectionInput) -> list[Insight]:
        snapshots = self.db.scalars(
            select(TelemetrySnapshot)
            .where(TelemetrySnapshot.company_id == self.context.company_id)
            .order_by(TelemetrySnapshot.device_id, TelemetrySnapshot.collected_at)
        ).all()
        grouped: dict[str, list[tuple[TelemetrySnapshot, float]]] = defaultdict(list)
        for snapshot in snapshots:
            used_pct = _pct(snapshot.used_memory_bytes, snapshot.total_memory_bytes)
            if used_pct is not None:
                grouped[snapshot.device_id].append((snapshot, used_pct))

        insights = []
        for device_id, values in grouped.items():
            pressured = [(snapshot, pct) for snapshot, pct in values if pct >= payload.memory_used_percent]
            ratio = len(pressured) / len(values) if values else 0
            if ratio < payload.persistent_ratio:
                continue
            ordered = sorted(values, key=lambda item: item[0].collected_at)
            evidence = [
                _evidence(snapshot, source="telemetry_snapshots", metric_or_check="memory_used_percent", value=pct, unit="%")
                for snapshot, pct in pressured[:3]
            ]
            insights.append(
                Insight(
                    insight_type="memory_pressure",
                    finding=f"Device {device_id} is persistently constrained by RAM.",
                    explanation=f"{len(pressured)} of {len(values)} snapshots were at or above {payload.memory_used_percent}% memory usage.",
                    device_id=device_id,
                    severity="high" if ratio >= 0.8 else "medium",
                    time_window_start=ordered[0][0].collected_at,
                    time_window_end=ordered[-1][0].collected_at,
                    metrics={
                        "pressure_snapshot_count": len(pressured),
                        "total_snapshot_count": len(values),
                        "pressure_ratio": round(ratio, 3),
                        "latest_used_percent": ordered[-1][1],
                    },
                    evidence=evidence,
                )
            )
            if len(insights) >= payload.limit_per_type:
                break
        return insights

    def detect_battery_risk(self, payload: InsightDetectionInput) -> list[Insight]:
        snapshots = self.db.scalars(
            select(TelemetrySnapshot)
            .where(TelemetrySnapshot.company_id == self.context.company_id)
            .order_by(TelemetrySnapshot.device_id, TelemetrySnapshot.collected_at)
        ).all()
        latest_by_device: dict[str, TelemetrySnapshot] = {}
        for snapshot in snapshots:
            latest_by_device[snapshot.device_id] = snapshot

        insights = []
        for device_id, snapshot in latest_by_device.items():
            reasons = []
            if snapshot.battery_condition and snapshot.battery_condition.lower() != "normal":
                reasons.append(f"condition={snapshot.battery_condition}")
            if snapshot.battery_cycle_count is not None and snapshot.battery_cycle_count >= payload.battery_cycle_count:
                reasons.append(f"cycle_count={snapshot.battery_cycle_count}")
            if snapshot.battery_full_charge_capacity is not None and snapshot.battery_full_charge_capacity < payload.battery_capacity_low:
                reasons.append(f"full_charge_capacity={snapshot.battery_full_charge_capacity}")
            if not reasons:
                continue
            evidence = [
                _evidence(snapshot, source="telemetry_snapshots", metric_or_check="battery_risk", value=reasons)
            ]
            insights.append(
                Insight(
                    insight_type="battery_risk",
                    finding=f"Device {device_id} has battery replacement risk.",
                    explanation="Latest battery telemetry crossed one or more configured risk thresholds.",
                    device_id=device_id,
                    severity="high" if snapshot.battery_cycle_count and snapshot.battery_cycle_count >= payload.battery_cycle_count else "medium",
                    time_window_start=snapshot.collected_at,
                    time_window_end=snapshot.collected_at,
                    metrics={
                        "condition": snapshot.battery_condition,
                        "cycle_count": snapshot.battery_cycle_count,
                        "full_charge_capacity": snapshot.battery_full_charge_capacity,
                        "reasons": reasons,
                    },
                    evidence=evidence,
                )
            )
            if len(insights) >= payload.limit_per_type:
                break
        return insights

    def detect_compliance_drift(self, payload: InsightDetectionInput) -> list[Insight]:
        rows = self.db.execute(
            select(ComplianceResult, TelemetrySnapshot)
            .join(TelemetrySnapshot, TelemetrySnapshot.id == ComplianceResult.snapshot_id)
            .where(ComplianceResult.company_id == self.context.company_id)
            .order_by(ComplianceResult.device_id, ComplianceResult.check_id, TelemetrySnapshot.collected_at)
        ).all()
        grouped: dict[tuple[str, str], list[tuple[ComplianceResult, TelemetrySnapshot]]] = defaultdict(list)
        for result, snapshot in rows:
            grouped[(result.device_id, result.check_id)].append((result, snapshot))

        insights = []
        for (device_id, check_id), values in grouped.items():
            statuses = [result.status for result, _snapshot in values]
            fail_count = statuses.count("fail")
            fail_ratio = fail_count / len(statuses) if statuses else 0
            changed = len(set(statuses)) > 1
            if not changed and fail_ratio < payload.compliance_drift_fail_ratio:
                continue
            ordered = sorted(values, key=lambda item: item[1].collected_at)
            failing = [(result, snapshot) for result, snapshot in ordered if result.status == "fail"]
            evidence = [
                _evidence(
                    snapshot,
                    source="compliance_results",
                    metric_or_check=result.check_id,
                    value=result.status,
                    explanation=f"{result.severity} severity",
                )
                for result, snapshot in failing[:3]
            ]
            insights.append(
                Insight(
                    insight_type="compliance_drift",
                    finding=f"Device {device_id} has compliance drift on {check_id}.",
                    explanation=f"{fail_count} of {len(statuses)} snapshots failed; status changed over time: {changed}.",
                    device_id=device_id,
                    check_id=check_id,
                    severity="high" if any(result.severity == "high" for result, _ in values) else "medium",
                    time_window_start=ordered[0][1].collected_at,
                    time_window_end=ordered[-1][1].collected_at,
                    metrics={
                        "fail_count": fail_count,
                        "total_snapshot_count": len(statuses),
                        "fail_ratio": round(fail_ratio, 3),
                        "status_changed": changed,
                    },
                    evidence=evidence,
                )
            )
            if len(insights) >= payload.limit_per_type:
                break
        return insights
