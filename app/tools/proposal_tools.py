from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.services.proposals import ActionProposalInput, ProposalService
from app.tools.schemas import ToolResult


def propose_action(db: Session, context: TenantContext, payload: ActionProposalInput) -> ToolResult:
    return ProposalService(db=db, context=context).propose_action_tool(payload)
