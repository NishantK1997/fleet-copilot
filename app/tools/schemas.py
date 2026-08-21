from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    device_id: str | None = None
    snapshot_id: int | None = None
    collected_at: datetime | None = None
    source: str
    metric_or_check: str
    value: Any
    unit: str | None = None
    explanation: str | None = None


class ToolResult(BaseModel):
    tool: str
    summary: str
    data: list[dict[str, Any]] | dict[str, Any]
    evidence: list[Evidence] = Field(default_factory=list)


class FleetSummaryInput(BaseModel):
    include_compliance: bool = True


class SearchDevicesInput(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    os_platform: str | None = None
    os_product_version_lt: str | None = None
    os_product_version: str | None = None
    architecture: str | None = None
    model_name: str | None = None
    processor_contains: str | None = None
    employee_id: str | None = None
    agent_version: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class DeviceDetailsInput(BaseModel):
    device_id: str


class DeviceMetricHistoryInput(BaseModel):
    device_id: str
    metric: Literal["memory", "disk", "battery", "compliance"]
    limit: int = Field(default=30, ge=1, le=750)


class LowDiskDevicesInput(BaseModel):
    threshold_percent: float = Field(default=10, gt=0, le=100)
    min_ratio: float = Field(default=0.5, ge=0, le=1)
    limit: int = Field(default=50, ge=1, le=200)


class MemoryPressureDevicesInput(BaseModel):
    used_percent_threshold: float = Field(default=85, gt=0, le=100)
    min_ratio: float = Field(default=0.5, ge=0, le=1)
    limit: int = Field(default=50, ge=1, le=200)


class BatteryRiskDevicesInput(BaseModel):
    cycle_count_threshold: int = Field(default=900, ge=0)
    capacity_below: int = Field(default=5000, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class ComplianceFailuresInput(BaseModel):
    severity: str | None = None
    check_id: str | None = None
    device_id: str | None = None
    latest_only: bool = True
    limit: int = Field(default=100, ge=1, le=500)


class SoftwareInventoryInput(BaseModel):
    name_contains: str | None = None
    version: str | None = None
    publisher_contains: str | None = None
    limit: int = Field(default=100, ge=1, le=500)


class SearchTelemetryInput(BaseModel):
    resource: Literal["devices", "snapshots", "compliance", "software"]
    field: str
    operator: Literal["eq", "contains", "lt", "lte", "gt", "gte"] = "eq"
    value: str | int | float | bool
    limit: int = Field(default=100, ge=1, le=500)
