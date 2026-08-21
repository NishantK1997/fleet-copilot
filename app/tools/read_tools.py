from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.config_policies import load_policies
from app.services.analytics import AnalyticsService, InsightDetectionInput
from app.services.telemetry import TelemetryReadService
from app.tools.schemas import (
    BatteryRiskDevicesInput,
    ComplianceFailuresInput,
    DeviceDetailsInput,
    DeviceMetricHistoryInput,
    FleetSummaryInput,
    LowDiskDevicesInput,
    MemoryPressureDevicesInput,
    SearchDevicesInput,
    SearchTelemetryInput,
    SoftwareInventoryInput,
    ToolResult,
)


def _service(db: Session, context: TenantContext) -> TelemetryReadService:
    return TelemetryReadService(db=db, context=context)


def get_fleet_summary(db: Session, context: TenantContext, payload: FleetSummaryInput | None = None) -> ToolResult:
    return _service(db, context).get_fleet_summary(payload or FleetSummaryInput())


def search_devices(db: Session, context: TenantContext, payload: SearchDevicesInput) -> ToolResult:
    return _service(db, context).search_devices(payload)


def get_device_details(db: Session, context: TenantContext, payload: DeviceDetailsInput) -> ToolResult:
    return _service(db, context).get_device_details(payload)


def get_device_metric_history(db: Session, context: TenantContext, payload: DeviceMetricHistoryInput) -> ToolResult:
    return _service(db, context).get_device_metric_history(payload)


def get_low_disk_devices(db: Session, context: TenantContext, payload: LowDiskDevicesInput | None = None) -> ToolResult:
    policy = load_policies().read_tools
    default_payload = LowDiskDevicesInput(
        threshold_percent=policy.low_disk_percent,
        min_ratio=policy.persistent_ratio,
    )
    return _service(db, context).get_low_disk_devices(payload or default_payload)


def get_memory_pressure_devices(db: Session, context: TenantContext, payload: MemoryPressureDevicesInput | None = None) -> ToolResult:
    policy = load_policies().read_tools
    default_payload = MemoryPressureDevicesInput(
        used_percent_threshold=policy.memory_used_percent,
        min_ratio=policy.persistent_ratio,
    )
    return _service(db, context).get_memory_pressure_devices(payload or default_payload)


def get_battery_risk_devices(db: Session, context: TenantContext, payload: BatteryRiskDevicesInput | None = None) -> ToolResult:
    policy = load_policies().read_tools
    default_payload = BatteryRiskDevicesInput(
        cycle_count_threshold=policy.battery_cycle_count,
        capacity_below=policy.battery_capacity_low,
    )
    return _service(db, context).get_battery_risk_devices(payload or default_payload)


def get_compliance_failures(db: Session, context: TenantContext, payload: ComplianceFailuresInput | None = None) -> ToolResult:
    return _service(db, context).get_compliance_failures(payload or ComplianceFailuresInput())


def search_software_inventory(db: Session, context: TenantContext, payload: SoftwareInventoryInput) -> ToolResult:
    return _service(db, context).search_software_inventory(payload)


def search_telemetry(db: Session, context: TenantContext, payload: SearchTelemetryInput) -> ToolResult:
    return _service(db, context).search_telemetry(payload)


def detect_insights(db: Session, context: TenantContext, payload: InsightDetectionInput | None = None) -> ToolResult:
    return AnalyticsService(db=db, context=context).detect_insights(payload)


READ_TOOLS = {
    "get_fleet_summary": get_fleet_summary,
    "search_devices": search_devices,
    "get_device_details": get_device_details,
    "get_device_metric_history": get_device_metric_history,
    "get_low_disk_devices": get_low_disk_devices,
    "get_memory_pressure_devices": get_memory_pressure_devices,
    "get_battery_risk_devices": get_battery_risk_devices,
    "get_compliance_failures": get_compliance_failures,
    "search_software_inventory": search_software_inventory,
    "search_telemetry": search_telemetry,
    "detect_insights": detect_insights,
}
