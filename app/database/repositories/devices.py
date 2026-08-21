from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.database.models import Device, Employee, TelemetrySnapshot
from app.database.repositories.tenant import TenantRepository


class DeviceRepository(TenantRepository[Device]):
    def __init__(self, db: Session, context: TenantContext):
        super().__init__(db, context, Device)

    def get(self, device_id: str) -> Device | None:
        return self.one_or_none(Device.device_id == device_id)

    def require(self, device_id: str) -> Device:
        return self.require_one(Device.device_id == device_id, resource_name="device")

    def list_all(self) -> list[Device]:
        return self.list()


class EmployeeRepository(TenantRepository[Employee]):
    def __init__(self, db: Session, context: TenantContext):
        super().__init__(db, context, Employee)

    def get(self, employee_id: str) -> Employee | None:
        return self.one_or_none(Employee.employee_id == employee_id)

    def require(self, employee_id: str) -> Employee:
        return self.require_one(Employee.employee_id == employee_id, resource_name="employee")


class TelemetryRepository(TenantRepository[TelemetrySnapshot]):
    def __init__(self, db: Session, context: TenantContext):
        super().__init__(db, context, TelemetrySnapshot)

    def latest_snapshot_for_device(self, device_id: str) -> TelemetrySnapshot | None:
        statement = (
            self.scoped(select(TelemetrySnapshot))
            .where(TelemetrySnapshot.device_id == device_id)
            .order_by(desc(TelemetrySnapshot.collected_at))
            .limit(1)
        )
        return self.db.scalar(statement)

    def snapshots_for_device(self, device_id: str, limit: int | None = None) -> list[TelemetrySnapshot]:
        statement = (
            self.scoped(select(TelemetrySnapshot))
            .where(TelemetrySnapshot.device_id == device_id)
            .order_by(TelemetrySnapshot.collected_at)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.db.scalars(statement).all())
