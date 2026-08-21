from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.database.models import Notification, RemediationTicket, ReplacementRequest, UpgradeOrder
from app.database.repositories.tenant import TenantRepository


class UpgradeOrderRepository(TenantRepository[UpgradeOrder]):
    def __init__(self, db: Session, context: TenantContext):
        super().__init__(db, context, UpgradeOrder)


class RemediationTicketRepository(TenantRepository[RemediationTicket]):
    def __init__(self, db: Session, context: TenantContext):
        super().__init__(db, context, RemediationTicket)


class ReplacementRequestRepository(TenantRepository[ReplacementRequest]):
    def __init__(self, db: Session, context: TenantContext):
        super().__init__(db, context, ReplacementRequest)


class NotificationRepository(TenantRepository[Notification]):
    def __init__(self, db: Session, context: TenantContext):
        super().__init__(db, context, Notification)
