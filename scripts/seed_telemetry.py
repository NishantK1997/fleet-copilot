import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Company,
    ComplianceResult,
    Device,
    DiskVolume,
    Employee,
    InstalledSoftware,
    NetworkInterface,
    TelemetrySnapshot,
)
from app.database.session import SessionLocal


COMPANY_NAMES = {
    "acme-001": "Acme",
    "globex-002": "Globex",
    "initech-003": "Initech",
}


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def resolve_dataset_path() -> Path:
    candidates = [
        os.getenv("DATASET_PATH"),
        "data/device-telemetry-dataset.ndjson",
        "device-telemetry-dataset.ndjson",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    raise FileNotFoundError("Could not find device-telemetry-dataset.ndjson")


def get_or_create_company(db: Session, company_id: str) -> Company:
    company = db.get(Company, company_id)
    if company:
        return company
    company = Company(id=company_id, name=COMPANY_NAMES.get(company_id, company_id))
    db.add(company)
    return company


def get_or_create_employee(db: Session, employee_id: str, company_id: str) -> Employee:
    employee = db.get(Employee, (employee_id, company_id))
    if employee:
        return employee
    employee = Employee(employee_id=employee_id, company_id=company_id)
    db.add(employee)
    return employee


def upsert_device(db: Session, row: dict[str, Any]) -> Device:
    identity = row.get("device_identity") or {}
    company_id = row["company_id"]
    device_id = row["device_id"]
    device = db.get(Device, (device_id, company_id))
    values = {
        "employee_id": row.get("employee_id"),
        "serial_number": identity.get("serial_number"),
        "model_name": identity.get("model_name"),
        "model_identifier": identity.get("model_identifier"),
        "processor": identity.get("processor"),
        "hardware_uuid": identity.get("hardware_uuid"),
        "total_memory_label": identity.get("total_memory"),
    }
    if device:
        for key, value in values.items():
            setattr(device, key, value)
        return device

    device = Device(device_id=device_id, company_id=company_id, **values)
    db.add(device)
    return device


def snapshot_exists(db: Session, device_id: str, collected_at: datetime) -> bool:
    statement = select(TelemetrySnapshot.id).where(
        TelemetrySnapshot.device_id == device_id,
        TelemetrySnapshot.collected_at == collected_at,
    )
    return db.execute(statement).first() is not None


def build_snapshot(row: dict[str, Any], collected_at: datetime) -> TelemetrySnapshot:
    os_info = row.get("os") or {}
    memory = row.get("memory") or {}
    battery = row.get("battery") or {}
    return TelemetrySnapshot(
        device_id=row["device_id"],
        company_id=row["company_id"],
        collected_at=collected_at,
        agent_version=row.get("agent_version"),
        os_platform=os_info.get("platform"),
        os_product_name=os_info.get("product_name"),
        os_product_version=os_info.get("product_version"),
        os_build_version=os_info.get("build_version"),
        os_architecture=os_info.get("architecture"),
        os_kernel_name=os_info.get("kernel_name"),
        os_kernel_release=os_info.get("kernel_release"),
        os_hostname=os_info.get("hostname"),
        ram_bytes=memory.get("ram_bytes"),
        total_memory_bytes=memory.get("total_memory_bytes"),
        used_memory_bytes=memory.get("used_memory_bytes"),
        free_memory_bytes=memory.get("free_memory_bytes"),
        page_size_bytes=memory.get("page_size_bytes"),
        battery_present=battery.get("battery_present"),
        battery_charging_status=battery.get("charging_status"),
        battery_percentage=battery.get("percentage"),
        battery_condition=battery.get("condition"),
        battery_cycle_count=battery.get("cycle_count"),
        battery_full_charge_capacity=battery.get("full_charge_capacity"),
        raw_payload=row,
    )


def add_child_rows(db: Session, snapshot: TelemetrySnapshot, row: dict[str, Any]) -> Counter:
    counts: Counter[str] = Counter()

    for volume in row.get("disk_volumes") or []:
        db.add(
            DiskVolume(
                snapshot=snapshot,
                company_id=row["company_id"],
                device_id=row["device_id"],
                volume_name=volume.get("volume_name"),
                file_system=volume.get("file_system"),
                mount_point=volume.get("mount_point"),
                size_bytes=volume.get("size_bytes"),
                available_bytes=volume.get("available_bytes"),
                encrypted=volume.get("encrypted"),
            )
        )
        counts["disk_volumes"] += 1

    for interface in row.get("network") or []:
        db.add(
            NetworkInterface(
                snapshot=snapshot,
                company_id=row["company_id"],
                device_id=row["device_id"],
                address=interface.get("address"),
                family=interface.get("family"),
                interface_name=interface.get("interface_name"),
                internal=interface.get("internal"),
                mac=interface.get("mac"),
            )
        )
        counts["network_interfaces"] += 1

    for software in row.get("installed_software") or []:
        db.add(
            InstalledSoftware(
                snapshot=snapshot,
                company_id=row["company_id"],
                device_id=row["device_id"],
                name=software.get("name") or "Unknown",
                version=software.get("version"),
                publisher=software.get("publisher"),
            )
        )
        counts["installed_software"] += 1

    for compliance in row.get("compliance_results") or []:
        db.add(
            ComplianceResult(
                snapshot=snapshot,
                company_id=row["company_id"],
                device_id=row["device_id"],
                check_id=compliance.get("check_id") or "unknown",
                status=compliance.get("status") or "unknown",
                severity=compliance.get("severity") or "unknown",
            )
        )
        counts["compliance_results"] += 1

    return counts


def table_count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def validation_summary(db: Session) -> dict[str, int]:
    return {
        "companies": table_count(db, Company),
        "employees": table_count(db, Employee),
        "devices": table_count(db, Device),
        "telemetry_snapshots": table_count(db, TelemetrySnapshot),
        "disk_volumes": table_count(db, DiskVolume),
        "network_interfaces": table_count(db, NetworkInterface),
        "installed_software": table_count(db, InstalledSoftware),
        "compliance_results": table_count(db, ComplianceResult),
    }


def seed_telemetry(dataset_path: Path) -> dict[str, Any]:
    processed = 0
    inserted_snapshots = 0
    skipped_snapshots = 0
    inserted_children: Counter[str] = Counter()

    with SessionLocal() as db:
        with dataset_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                try:
                    company_id = row["company_id"]
                    employee_id = row["employee_id"]
                    device_id = row["device_id"]
                    collected_at = parse_timestamp(row["collected_at"])
                except KeyError as exc:
                    raise ValueError(f"Missing required field {exc} on line {line_number}") from exc

                get_or_create_company(db, company_id)
                get_or_create_employee(db, employee_id, company_id)
                upsert_device(db, row)
                db.flush()

                if snapshot_exists(db, device_id, collected_at):
                    skipped_snapshots += 1
                    processed += 1
                    continue

                snapshot = build_snapshot(row, collected_at)
                db.add(snapshot)
                inserted_children.update(add_child_rows(db, snapshot, row))
                inserted_snapshots += 1
                processed += 1

                if processed % 100 == 0:
                    db.commit()

        db.commit()
        summary = validation_summary(db)

    return {
        "dataset_path": str(dataset_path),
        "processed_records": processed,
        "inserted_snapshots": inserted_snapshots,
        "skipped_existing_snapshots": skipped_snapshots,
        "inserted_child_rows": dict(inserted_children),
        "summary": summary,
    }


def main() -> None:
    result = seed_telemetry(resolve_dataset_path())
    print(json.dumps(result, indent=2, sort_keys=True))

    summary = result["summary"]
    expected = {
        "companies": 3,
        "devices": 25,
        "telemetry_snapshots": 750,
    }
    failures = {
        key: {"expected": value, "actual": summary.get(key)}
        for key, value in expected.items()
        if summary.get(key) != value
    }
    if failures:
        raise SystemExit(f"Telemetry seed validation failed: {json.dumps(failures, sort_keys=True)}")


if __name__ == "__main__":
    main()
