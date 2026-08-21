from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.database.models import ActionProposal
from app.database.repositories.tenant import TenantRepository


class ActionProposalRepository(TenantRepository[ActionProposal]):
    def __init__(self, db: Session, context: TenantContext):
        super().__init__(db, context, ActionProposal)

    def get(self, proposal_id: int) -> ActionProposal | None:
        return self.one_or_none(ActionProposal.id == proposal_id)

    def require(self, proposal_id: int) -> ActionProposal:
        return self.require_one(ActionProposal.id == proposal_id, resource_name="action proposal")
