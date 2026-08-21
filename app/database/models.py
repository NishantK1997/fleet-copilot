from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="company")
    employees: Mapped[list["Employee"]] = relationship(back_populates="company")
    devices: Mapped[list["Device"]] = relationship(back_populates="company", overlaps="employee,devices")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role in ('admin')", name="ck_users_role"),
        Index("ix_users_company_id", "company_id"),
        Index("ix_users_email", "email", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    company: Mapped["Company"] = relationship(back_populates="users")


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        Index("ix_employees_company_id", "company_id"),
        UniqueConstraint("employee_id", "company_id", name="uq_employees_employee_company"),
    )

    employee_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, primary_key=True)

    company: Mapped["Company"] = relationship(back_populates="employees")
    devices: Mapped[list["Device"]] = relationship(back_populates="employee", overlaps="company,devices")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        ForeignKeyConstraint(["employee_id", "company_id"], ["employees.employee_id", "employees.company_id"]),
        Index("ix_devices_company_id", "company_id"),
        Index("ix_devices_employee_id", "employee_id"),
        UniqueConstraint("device_id", "company_id", name="uq_devices_device_company"),
    )

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, primary_key=True)
    employee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hardware_uuid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_memory_label: Mapped[str | None] = mapped_column(String(64), nullable=True)

    company: Mapped["Company"] = relationship(back_populates="devices", overlaps="employee,devices")
    employee: Mapped["Employee | None"] = relationship(back_populates="devices", overlaps="company,devices")
    snapshots: Mapped[list["TelemetrySnapshot"]] = relationship(back_populates="device", overlaps="company")


class TelemetrySnapshot(Base):
    __tablename__ = "telemetry_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["device_id", "company_id"], ["devices.device_id", "devices.company_id"]),
        UniqueConstraint("device_id", "collected_at", name="uq_telemetry_device_collected_at"),
        Index("ix_telemetry_company_id", "company_id"),
        Index("ix_telemetry_device_id", "device_id"),
        Index("ix_telemetry_collected_at", "collected_at"),
        Index("ix_telemetry_company_device_collected", "company_id", "device_id", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_product_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    os_product_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_build_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_architecture: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_kernel_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_kernel_release: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ram_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_memory_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_memory_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_memory_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    battery_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    battery_charging_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    battery_percentage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    battery_condition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    battery_cycle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    battery_full_charge_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    company: Mapped["Company"] = relationship(overlaps="device,snapshots")
    device: Mapped["Device"] = relationship(back_populates="snapshots", overlaps="company")
    disk_volumes: Mapped[list["DiskVolume"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    network_interfaces: Mapped[list["NetworkInterface"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    installed_software: Mapped[list["InstalledSoftware"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    compliance_results: Mapped[list["ComplianceResult"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")


class DiskVolume(Base):
    __tablename__ = "disk_volumes"
    __table_args__ = (
        Index("ix_disk_volumes_company_id", "company_id"),
        Index("ix_disk_volumes_device_id", "device_id"),
        Index("ix_disk_volumes_snapshot_id", "snapshot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("telemetry_snapshots.id"), nullable=False)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    volume_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mount_point: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    encrypted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    snapshot: Mapped["TelemetrySnapshot"] = relationship(back_populates="disk_volumes")


class NetworkInterface(Base):
    __tablename__ = "network_interfaces"
    __table_args__ = (
        Index("ix_network_interfaces_company_id", "company_id"),
        Index("ix_network_interfaces_device_id", "device_id"),
        Index("ix_network_interfaces_snapshot_id", "snapshot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("telemetry_snapshots.id"), nullable=False)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interface_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    internal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mac: Mapped[str | None] = mapped_column(String(64), nullable=True)

    snapshot: Mapped["TelemetrySnapshot"] = relationship(back_populates="network_interfaces")


class InstalledSoftware(Base):
    __tablename__ = "installed_software"
    __table_args__ = (
        Index("ix_installed_software_company_id", "company_id"),
        Index("ix_installed_software_device_id", "device_id"),
        Index("ix_installed_software_snapshot_id", "snapshot_id"),
        Index("ix_installed_software_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("telemetry_snapshots.id"), nullable=False)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)

    snapshot: Mapped["TelemetrySnapshot"] = relationship(back_populates="installed_software")


class ComplianceResult(Base):
    __tablename__ = "compliance_results"
    __table_args__ = (
        Index("ix_compliance_results_company_id", "company_id"),
        Index("ix_compliance_results_device_id", "device_id"),
        Index("ix_compliance_results_snapshot_id", "snapshot_id"),
        Index("ix_compliance_results_check_id", "check_id"),
        Index("ix_compliance_results_status", "status"),
        Index("ix_compliance_results_severity", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("telemetry_snapshots.id"), nullable=False)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    check_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)

    snapshot: Mapped["TelemetrySnapshot"] = relationship(back_populates="compliance_results")


class ActionProposal(Base):
    __tablename__ = "action_proposals"
    __table_args__ = (
        CheckConstraint(
            "action_type in ('create_upgrade_order', 'open_remediation_ticket', "
            "'flag_device_for_replacement', 'notify_employee')",
            name="ck_action_proposals_action_type",
        ),
        CheckConstraint(
            "status in ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'EXECUTED', 'FAILED')",
            name="ck_action_proposals_status",
        ),
        Index("ix_action_proposals_company_id", "company_id"),
        Index("ix_action_proposals_user_id", "user_id"),
        Index("ix_action_proposals_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposed_arguments: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list | dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_APPROVAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_company_id", "company_id"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_session_id", "session_id"),
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    arguments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UpgradeOrder(TimestampMixin, Base):
    __tablename__ = "upgrade_orders"
    __table_args__ = (
        CheckConstraint("status in ('OPEN', 'CLOSED', 'CANCELLED')", name="ck_upgrade_orders_status"),
        Index("ix_upgrade_orders_company_id", "company_id"),
        Index("ix_upgrade_orders_device_id", "device_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    component: Mapped[str] = mapped_column(String(128), nullable=False)
    spec: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class RemediationTicket(TimestampMixin, Base):
    __tablename__ = "remediation_tickets"
    __table_args__ = (
        CheckConstraint("status in ('OPEN', 'CLOSED', 'CANCELLED')", name="ck_remediation_tickets_status"),
        Index("ix_remediation_tickets_company_id", "company_id"),
        Index("ix_remediation_tickets_device_id", "device_id"),
        Index("ix_remediation_tickets_check_id", "check_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    check_id: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class ReplacementRequest(TimestampMixin, Base):
    __tablename__ = "replacement_requests"
    __table_args__ = (
        CheckConstraint("status in ('OPEN', 'CLOSED', 'CANCELLED')", name="ck_replacement_requests_status"),
        Index("ix_replacement_requests_company_id", "company_id"),
        Index("ix_replacement_requests_device_id", "device_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("status in ('QUEUED', 'SENT', 'FAILED', 'CANCELLED')", name="ck_notifications_status"),
        Index("ix_notifications_company_id", "company_id"),
        Index("ix_notifications_employee_id", "employee_id"),
        Index("ix_notifications_device_id", "device_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    employee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


__all__ = [
    "ActionProposal",
    "AuditLog",
    "Base",
    "Company",
    "ComplianceResult",
    "Device",
    "DiskVolume",
    "Employee",
    "InstalledSoftware",
    "NetworkInterface",
    "Notification",
    "RemediationTicket",
    "ReplacementRequest",
    "TelemetrySnapshot",
    "UpgradeOrder",
    "User",
]
