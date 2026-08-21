from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import TenantContext
from app.database.models import (
    ComplianceResult,
    Device,
    DiskVolume,
    InstalledSoftware,
    TelemetrySnapshot,
)
from app.database.repositories.devices import DeviceRepository
from app.guardrails.authorization import TenantIsolationError
from app.tools.schemas import (
    BatteryRiskDevicesInput,
    ComplianceFailuresInput,
    DeviceDetailsInput,
    DeviceMetricHistoryInput,
    Evidence,
    FleetSummaryInput,
    LowDiskDevicesInput,
    MemoryPressureDevicesInput,
    SearchDevicesInput,
    SearchTelemetryInput,
    SoftwareInventoryInput,
    ToolResult,
)


def _version_key(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    parts: list[int] = []
    for token in value.replace("-", " ").replace("_", " ").replace(".", " ").split():
        if token.isdigit():
            parts.append(int(token))
    return tuple(parts)


def _is_version_lt(left: str | None, right: str | None) -> bool:
    return _version_key(left) < _version_key(right)


def _pct(part: int | None, whole: int | None) -> float | None:
    if part is None or whole in (None, 0):
        return None
    return round((part / whole) * 100, 2)


def _latest_snapshot_subquery(context: TenantContext):
    return (
        select(
            TelemetrySnapshot.device_id.label("device_id"),
            func.max(TelemetrySnapshot.collected_at).label("latest_collected_at"),
        )
        .where(TelemetrySnapshot.company_id == context.company_id)
        .group_by(TelemetrySnapshot.device_id)
        .subquery()
    )


def _snapshot_evidence(
    snapshot: TelemetrySnapshot,
    metric: str,
    value: Any,
    *,
    source: str = "telemetry_snapshots",
    unit: str | None = None,
    explanation: str | None = None,
) -> Evidence:
    return Evidence(
        device_id=snapshot.device_id,
        snapshot_id=snapshot.id,
        collected_at=snapshot.collected_at,
        source=source,
        metric_or_check=metric,
        value=value,
        unit=unit,
        explanation=explanation,
    )


@dataclass
class TelemetryReadService:
    db: Session
    context: TenantContext

    def get_fleet_summary(self, payload: FleetSummaryInput) -> ToolResult:
        device_count = self.db.scalar(
            select(func.count()).select_from(Device).where(Device.company_id == self.context.company_id)
        ) or 0
        snapshot_count = self.db.scalar(
            select(func.count()).select_from(TelemetrySnapshot).where(TelemetrySnapshot.company_id == self.context.company_id)
        ) or 0
        os_rows = self.db.execute(
            select(TelemetrySnapshot.os_product_name, TelemetrySnapshot.os_product_version, func.count(func.distinct(TelemetrySnapshot.device_id)))
            .where(TelemetrySnapshot.company_id == self.context.company_id)
            .group_by(TelemetrySnapshot.os_product_name, TelemetrySnapshot.os_product_version)
        ).all()
        data: dict[str, Any] = {
            "company_id": self.context.company_id,
            "device_count": device_count,
            "snapshot_count": snapshot_count,
            "os_distribution": [
                {"product_name": name, "product_version": version, "device_count": count}
                for name, version, count in os_rows
            ],
        }
        evidence = [
            Evidence(
                source="devices",
                metric_or_check="device_count",
                value=device_count,
                unit="devices",
                explanation="Count is scoped to authenticated tenant.",
            ),
            Evidence(
                source="telemetry_snapshots",
                metric_or_check="snapshot_count",
                value=snapshot_count,
                unit="snapshots",
                explanation="Count is scoped to authenticated tenant.",
            ),
        ]
        if payload.include_compliance:
            compliance_rows = self.db.execute(
                select(ComplianceResult.check_id, ComplianceResult.status, ComplianceResult.severity, func.count())
                .where(ComplianceResult.company_id == self.context.company_id)
                .group_by(ComplianceResult.check_id, ComplianceResult.status, ComplianceResult.severity)
            ).all()
            data["compliance"] = [
                {"check_id": check, "status": status, "severity": severity, "count": count}
                for check, status, severity, count in compliance_rows
            ]
        return ToolResult(tool="get_fleet_summary", summary=f"{device_count} devices and {snapshot_count} snapshots found.", data=data, evidence=evidence)

    def search_devices(self, payload: SearchDevicesInput) -> ToolResult:
        latest = _latest_snapshot_subquery(self.context)
        statement = (
            select(Device, TelemetrySnapshot)
            .join(TelemetrySnapshot, and_(TelemetrySnapshot.device_id == Device.device_id, TelemetrySnapshot.company_id == Device.company_id))
            .join(latest, and_(latest.c.device_id == TelemetrySnapshot.device_id, latest.c.latest_collected_at == TelemetrySnapshot.collected_at))
            .where(Device.company_id == self.context.company_id)
            .order_by(Device.device_id)
        )
        rows = self.db.execute(statement).all()
        results = []
        evidence = []
        for device, snapshot in rows:
            if payload.os_platform and snapshot.os_platform != payload.os_platform:
                continue
            if payload.os_product_version and snapshot.os_product_version != payload.os_product_version:
                continue
            if payload.os_product_version_lt and not _is_version_lt(snapshot.os_product_version, payload.os_product_version_lt):
                continue
            if payload.architecture and snapshot.os_architecture != payload.architecture:
                continue
            if payload.model_name and device.model_name != payload.model_name:
                continue
            if payload.processor_contains and payload.processor_contains.lower() not in (device.processor or "").lower():
                continue
            if payload.employee_id and device.employee_id != payload.employee_id:
                continue
            if payload.agent_version and snapshot.agent_version != payload.agent_version:
                continue
            results.append(self._device_row(device, snapshot))
            evidence.append(_snapshot_evidence(snapshot, "latest_device_state", snapshot.collected_at.isoformat()))
            if len(results) >= payload.limit:
                break
        return ToolResult(tool="search_devices", summary=f"{len(results)} devices matched.", data=results, evidence=evidence)

    def get_device_details(self, payload: DeviceDetailsInput) -> ToolResult:
        DeviceRepository(self.db, self.context).require(payload.device_id)
        snapshot = self._latest_snapshot(payload.device_id)
        if snapshot is None:
            raise TenantIsolationError("device snapshot not found for authenticated tenant")
        snapshot = self.db.scalar(
            select(TelemetrySnapshot)
            .where(TelemetrySnapshot.id == snapshot.id, TelemetrySnapshot.company_id == self.context.company_id)
            .options(
                selectinload(TelemetrySnapshot.disk_volumes),
                selectinload(TelemetrySnapshot.network_interfaces),
                selectinload(TelemetrySnapshot.installed_software),
                selectinload(TelemetrySnapshot.compliance_results),
            )
        )
        assert snapshot is not None
        data = {
            "device_id": snapshot.device_id,
            "employee_id": snapshot.raw_payload.get("employee_id"),
            "collected_at": snapshot.collected_at.isoformat(),
            "agent_version": snapshot.agent_version,
            "os": {
                "platform": snapshot.os_platform,
                "product_name": snapshot.os_product_name,
                "product_version": snapshot.os_product_version,
                "architecture": snapshot.os_architecture,
                "hostname": snapshot.os_hostname,
            },
            "memory": {
                "total_memory_bytes": snapshot.total_memory_bytes,
                "used_memory_bytes": snapshot.used_memory_bytes,
                "used_percent": _pct(snapshot.used_memory_bytes, snapshot.total_memory_bytes),
            },
            "battery": {
                "present": snapshot.battery_present,
                "condition": snapshot.battery_condition,
                "cycle_count": snapshot.battery_cycle_count,
                "full_charge_capacity": snapshot.battery_full_charge_capacity,
            },
            "disk_volumes": [
                {
                    "volume_name": volume.volume_name,
                    "mount_point": volume.mount_point,
                    "available_bytes": volume.available_bytes,
                    "size_bytes": volume.size_bytes,
                    "available_percent": _pct(volume.available_bytes, volume.size_bytes),
                    "encrypted": volume.encrypted,
                }
                for volume in snapshot.disk_volumes
            ],
            "compliance_results": [
                {"check_id": result.check_id, "status": result.status, "severity": result.severity}
                for result in snapshot.compliance_results
            ],
            "installed_software_count": len(snapshot.installed_software),
        }
        return ToolResult(
            tool="get_device_details",
            summary=f"Latest details for {snapshot.device_id}.",
            data=data,
            evidence=[_snapshot_evidence(snapshot, "latest_device_details", snapshot.collected_at.isoformat())],
        )

    def get_device_metric_history(self, payload: DeviceMetricHistoryInput) -> ToolResult:
        DeviceRepository(self.db, self.context).require(payload.device_id)
        snapshots = self._snapshots(payload.device_id, limit=payload.limit)
        data = []
        evidence = []
        for snapshot in snapshots:
            row: dict[str, Any] = {"snapshot_id": snapshot.id, "collected_at": snapshot.collected_at.isoformat(), "device_id": snapshot.device_id}
            if payload.metric == "memory":
                row.update(
                    total_memory_bytes=snapshot.total_memory_bytes,
                    used_memory_bytes=snapshot.used_memory_bytes,
                    used_percent=_pct(snapshot.used_memory_bytes, snapshot.total_memory_bytes),
                )
                evidence.append(_snapshot_evidence(snapshot, "memory_used_percent", row["used_percent"], unit="%"))
            elif payload.metric == "battery":
                row.update(
                    condition=snapshot.battery_condition,
                    cycle_count=snapshot.battery_cycle_count,
                    full_charge_capacity=snapshot.battery_full_charge_capacity,
                    percentage=snapshot.battery_percentage,
                )
                evidence.append(_snapshot_evidence(snapshot, "battery_cycle_count", snapshot.battery_cycle_count))
            elif payload.metric == "disk":
                volumes = self.db.scalars(select(DiskVolume).where(DiskVolume.snapshot_id == snapshot.id)).all()
                row["volumes"] = [
                    {
                        "mount_point": volume.mount_point,
                        "available_bytes": volume.available_bytes,
                        "size_bytes": volume.size_bytes,
                        "available_percent": _pct(volume.available_bytes, volume.size_bytes),
                    }
                    for volume in volumes
                ]
                if row["volumes"]:
                    evidence.append(_snapshot_evidence(snapshot, "disk_available_percent", row["volumes"][0]["available_percent"], source="disk_volumes", unit="%"))
            else:
                checks = self.db.scalars(select(ComplianceResult).where(ComplianceResult.snapshot_id == snapshot.id)).all()
                row["checks"] = [{"check_id": check.check_id, "status": check.status, "severity": check.severity} for check in checks]
                evidence.append(_snapshot_evidence(snapshot, "compliance_results", len(checks), source="compliance_results", unit="checks"))
            data.append(row)
        return ToolResult(tool="get_device_metric_history", summary=f"{len(data)} {payload.metric} snapshots returned.", data=data, evidence=evidence)

    def get_low_disk_devices(self, payload: LowDiskDevicesInput) -> ToolResult:
        rows = self.db.execute(
            select(TelemetrySnapshot, DiskVolume)
            .join(DiskVolume, DiskVolume.snapshot_id == TelemetrySnapshot.id)
            .where(TelemetrySnapshot.company_id == self.context.company_id)
        ).all()
        grouped: dict[str, list[tuple[TelemetrySnapshot, DiskVolume, float]]] = defaultdict(list)
        for snapshot, volume in rows:
            available_pct = _pct(volume.available_bytes, volume.size_bytes)
            if available_pct is not None:
                grouped[snapshot.device_id].append((snapshot, volume, available_pct))
        data = []
        evidence = []
        for device_id, values in grouped.items():
            low = [(snapshot, volume, pct) for snapshot, volume, pct in values if pct < payload.threshold_percent]
            ratio = len(low) / len(values) if values else 0
            if ratio >= payload.min_ratio:
                latest_snapshot, _latest_volume, latest_pct = sorted(values, key=lambda item: item[0].collected_at)[-1]
                data.append(
                    {
                        "device_id": device_id,
                        "low_snapshot_count": len(low),
                        "total_snapshot_count": len(values),
                        "low_ratio": round(ratio, 3),
                        "latest_available_percent": latest_pct,
                    }
                )
                evidence.extend(
                    _snapshot_evidence(snapshot, "disk_available_percent", pct, source="disk_volumes", unit="%")
                    for snapshot, _volume, pct in low[:3]
                )
            if len(data) >= payload.limit:
                break
        return ToolResult(tool="get_low_disk_devices", summary=f"{len(data)} devices met low disk criteria.", data=data, evidence=evidence)

    def get_memory_pressure_devices(self, payload: MemoryPressureDevicesInput) -> ToolResult:
        snapshots = self.db.scalars(select(TelemetrySnapshot).where(TelemetrySnapshot.company_id == self.context.company_id)).all()
        grouped: dict[str, list[tuple[TelemetrySnapshot, float]]] = defaultdict(list)
        for snapshot in snapshots:
            used_pct = _pct(snapshot.used_memory_bytes, snapshot.total_memory_bytes)
            if used_pct is not None:
                grouped[snapshot.device_id].append((snapshot, used_pct))
        data = []
        evidence = []
        for device_id, values in grouped.items():
            pressured = [(snapshot, pct) for snapshot, pct in values if pct >= payload.used_percent_threshold]
            ratio = len(pressured) / len(values) if values else 0
            if ratio >= payload.min_ratio:
                latest_snapshot, latest_pct = sorted(values, key=lambda item: item[0].collected_at)[-1]
                data.append(
                    {
                        "device_id": device_id,
                        "pressure_snapshot_count": len(pressured),
                        "total_snapshot_count": len(values),
                        "pressure_ratio": round(ratio, 3),
                        "latest_used_percent": latest_pct,
                    }
                )
                evidence.extend(_snapshot_evidence(snapshot, "memory_used_percent", pct, unit="%") for snapshot, pct in pressured[:3])
            if len(data) >= payload.limit:
                break
        return ToolResult(tool="get_memory_pressure_devices", summary=f"{len(data)} devices met memory pressure criteria.", data=data, evidence=evidence)

    def get_battery_risk_devices(self, payload: BatteryRiskDevicesInput) -> ToolResult:
        latest = _latest_snapshot_subquery(self.context)
        snapshots = self.db.scalars(
            select(TelemetrySnapshot)
            .join(latest, and_(latest.c.device_id == TelemetrySnapshot.device_id, latest.c.latest_collected_at == TelemetrySnapshot.collected_at))
            .where(TelemetrySnapshot.company_id == self.context.company_id)
            .order_by(TelemetrySnapshot.device_id)
        ).all()
        data = []
        evidence = []
        for snapshot in snapshots:
            reasons = []
            if snapshot.battery_condition and snapshot.battery_condition.lower() != "normal":
                reasons.append(f"condition={snapshot.battery_condition}")
            if snapshot.battery_cycle_count is not None and snapshot.battery_cycle_count >= payload.cycle_count_threshold:
                reasons.append(f"cycle_count={snapshot.battery_cycle_count}")
            if snapshot.battery_full_charge_capacity is not None and snapshot.battery_full_charge_capacity < payload.capacity_below:
                reasons.append(f"capacity={snapshot.battery_full_charge_capacity}")
            if reasons:
                data.append(
                    {
                        "device_id": snapshot.device_id,
                        "condition": snapshot.battery_condition,
                        "cycle_count": snapshot.battery_cycle_count,
                        "full_charge_capacity": snapshot.battery_full_charge_capacity,
                        "reasons": reasons,
                    }
                )
                evidence.append(_snapshot_evidence(snapshot, "battery_risk", reasons))
            if len(data) >= payload.limit:
                break
        return ToolResult(tool="get_battery_risk_devices", summary=f"{len(data)} devices met battery risk criteria.", data=data, evidence=evidence)

    def get_compliance_failures(self, payload: ComplianceFailuresInput) -> ToolResult:
        if payload.device_id:
            DeviceRepository(self.db, self.context).require(payload.device_id)
        statement = (
            select(ComplianceResult, TelemetrySnapshot)
            .join(TelemetrySnapshot, TelemetrySnapshot.id == ComplianceResult.snapshot_id)
            .where(ComplianceResult.company_id == self.context.company_id, ComplianceResult.status == "fail")
            .order_by(desc(TelemetrySnapshot.collected_at), ComplianceResult.device_id)
        )
        if payload.severity:
            statement = statement.where(ComplianceResult.severity == payload.severity)
        if payload.check_id:
            statement = statement.where(ComplianceResult.check_id == payload.check_id)
        if payload.device_id:
            statement = statement.where(ComplianceResult.device_id == payload.device_id)
        rows = self.db.execute(statement).all()
        if payload.latest_only:
            seen = set()
            filtered = []
            for result, snapshot in rows:
                key = (result.device_id, result.check_id)
                if key in seen:
                    continue
                seen.add(key)
                filtered.append((result, snapshot))
            rows = filtered
        rows = rows[: payload.limit]
        data = [
            {
                "device_id": result.device_id,
                "check_id": result.check_id,
                "severity": result.severity,
                "status": result.status,
                "snapshot_id": snapshot.id,
                "collected_at": snapshot.collected_at.isoformat(),
            }
            for result, snapshot in rows
        ]
        evidence = [
            _snapshot_evidence(snapshot, result.check_id, result.status, source="compliance_results", explanation=f"{result.severity} severity")
            for result, snapshot in rows
        ]
        return ToolResult(tool="get_compliance_failures", summary=f"{len(data)} compliance failures returned.", data=data, evidence=evidence)

    def search_software_inventory(self, payload: SoftwareInventoryInput) -> ToolResult:
        latest = _latest_snapshot_subquery(self.context)
        statement = (
            select(InstalledSoftware, TelemetrySnapshot)
            .join(TelemetrySnapshot, TelemetrySnapshot.id == InstalledSoftware.snapshot_id)
            .join(latest, and_(latest.c.device_id == TelemetrySnapshot.device_id, latest.c.latest_collected_at == TelemetrySnapshot.collected_at))
            .where(InstalledSoftware.company_id == self.context.company_id)
            .order_by(InstalledSoftware.name, InstalledSoftware.device_id)
        )
        if payload.name_contains:
            statement = statement.where(InstalledSoftware.name.ilike(f"%{payload.name_contains}%"))
        if payload.version:
            statement = statement.where(InstalledSoftware.version == payload.version)
        if payload.publisher_contains:
            statement = statement.where(InstalledSoftware.publisher.ilike(f"%{payload.publisher_contains}%"))
        rows = self.db.execute(statement.limit(payload.limit)).all()
        data = [
            {
                "device_id": software.device_id,
                "name": software.name,
                "version": software.version,
                "publisher": software.publisher,
                "snapshot_id": snapshot.id,
                "collected_at": snapshot.collected_at.isoformat(),
            }
            for software, snapshot in rows
        ]
        evidence = [
            _snapshot_evidence(snapshot, "installed_software", software.name, source="installed_software")
            for software, snapshot in rows
        ]
        return ToolResult(tool="search_software_inventory", summary=f"{len(data)} software inventory rows returned.", data=data, evidence=evidence)

    def search_telemetry(self, payload: SearchTelemetryInput) -> ToolResult:
        model, allowed = self._search_resource(payload.resource)
        if payload.field not in allowed:
            raise ValueError(f"Field '{payload.field}' is not allowed for resource '{payload.resource}'")
        column = allowed[payload.field]
        statement = select(model).where(model.company_id == self.context.company_id)
        statement = self._apply_operator(statement, column, payload.operator, payload.value).limit(payload.limit)
        rows = list(self.db.scalars(statement).all())
        data = [self._model_to_dict(row, payload.field) for row in rows]
        evidence = [
            Evidence(
                device_id=getattr(row, "device_id", None),
                snapshot_id=getattr(row, "snapshot_id", getattr(row, "id", None) if isinstance(row, TelemetrySnapshot) else None),
                collected_at=getattr(row, "collected_at", None),
                source=model.__tablename__,
                metric_or_check=payload.field,
                value=getattr(row, payload.field),
            )
            for row in rows
        ]
        return ToolResult(tool="search_telemetry", summary=f"{len(data)} {payload.resource} rows matched.", data=data, evidence=evidence)

    def _latest_snapshot(self, device_id: str) -> TelemetrySnapshot | None:
        return self.db.scalar(
            select(TelemetrySnapshot)
            .where(TelemetrySnapshot.company_id == self.context.company_id, TelemetrySnapshot.device_id == device_id)
            .order_by(desc(TelemetrySnapshot.collected_at))
            .limit(1)
        )

    def _snapshots(self, device_id: str, limit: int) -> list[TelemetrySnapshot]:
        return list(
            self.db.scalars(
                select(TelemetrySnapshot)
                .where(TelemetrySnapshot.company_id == self.context.company_id, TelemetrySnapshot.device_id == device_id)
                .order_by(desc(TelemetrySnapshot.collected_at))
                .limit(limit)
            ).all()
        )

    def _device_row(self, device: Device, snapshot: TelemetrySnapshot) -> dict[str, Any]:
        return {
            "device_id": device.device_id,
            "employee_id": device.employee_id,
            "model_name": device.model_name,
            "processor": device.processor,
            "agent_version": snapshot.agent_version,
            "os_platform": snapshot.os_platform,
            "os_product_name": snapshot.os_product_name,
            "os_product_version": snapshot.os_product_version,
            "architecture": snapshot.os_architecture,
            "latest_snapshot_id": snapshot.id,
            "latest_collected_at": snapshot.collected_at.isoformat(),
        }

    def _search_resource(self, resource: str):
        resources = {
            "devices": (
                Device,
                {
                    "device_id": Device.device_id,
                    "employee_id": Device.employee_id,
                    "model_name": Device.model_name,
                    "processor": Device.processor,
                },
            ),
            "snapshots": (
                TelemetrySnapshot,
                {
                    "device_id": TelemetrySnapshot.device_id,
                    "agent_version": TelemetrySnapshot.agent_version,
                    "os_platform": TelemetrySnapshot.os_platform,
                    "os_product_version": TelemetrySnapshot.os_product_version,
                    "battery_condition": TelemetrySnapshot.battery_condition,
                    "battery_cycle_count": TelemetrySnapshot.battery_cycle_count,
                },
            ),
            "compliance": (
                ComplianceResult,
                {
                    "device_id": ComplianceResult.device_id,
                    "check_id": ComplianceResult.check_id,
                    "status": ComplianceResult.status,
                    "severity": ComplianceResult.severity,
                },
            ),
            "software": (
                InstalledSoftware,
                {
                    "device_id": InstalledSoftware.device_id,
                    "name": InstalledSoftware.name,
                    "version": InstalledSoftware.version,
                    "publisher": InstalledSoftware.publisher,
                },
            ),
        }
        return resources[resource]

    def _apply_operator(self, statement: Select, column, operator: str, value: str | int | float | bool) -> Select:
        if operator == "eq":
            return statement.where(column == value)
        if operator == "contains":
            return statement.where(column.ilike(f"%{value}%"))
        if operator == "lt":
            return statement.where(column < value)
        if operator == "lte":
            return statement.where(column <= value)
        if operator == "gt":
            return statement.where(column > value)
        if operator == "gte":
            return statement.where(column >= value)
        raise ValueError(f"Unsupported operator '{operator}'")

    def _model_to_dict(self, row: Any, field: str) -> dict[str, Any]:
        output = {
            "source": row.__tablename__ if hasattr(row, "__tablename__") else row.__class__.__tablename__,
            "id": getattr(row, "id", None),
            "device_id": getattr(row, "device_id", None),
            "company_id": getattr(row, "company_id", None),
            field: getattr(row, field),
        }
        if hasattr(row, "collected_at"):
            output["collected_at"] = row.collected_at.isoformat()
        if hasattr(row, "snapshot_id"):
            output["snapshot_id"] = row.snapshot_id
        return output
