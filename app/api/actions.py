from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext, get_tenant_context
from app.database.models import ActionProposal
from app.database.session import get_db
from app.guardrails.authorization import TenantIsolationError
from app.services.actions import ActionApprovalService, ActionExecutionResult


router = APIRouter(prefix="/actions", tags=["actions"])


class ProposalResponse(BaseModel):
    id: int
    action_type: str
    device_id: str | None
    employee_id: str | None
    proposed_arguments: dict[str, Any]
    reason: str
    evidence: list | dict
    status: str


def _proposal_response(proposal: ActionProposal) -> ProposalResponse:
    return ProposalResponse(
        id=proposal.id,
        action_type=proposal.action_type,
        device_id=proposal.device_id,
        employee_id=proposal.employee_id,
        proposed_arguments=proposal.proposed_arguments,
        reason=proposal.reason,
        evidence=proposal.evidence,
        status=proposal.status,
    )


def _service(db: Session, context: TenantContext) -> ActionApprovalService:
    return ActionApprovalService(db=db, context=context)


@router.get("/{proposal_id}", response_model=ProposalResponse)
def get_action_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
) -> ProposalResponse:
    try:
        proposal = _service(db, context).get_proposal(proposal_id)
    except TenantIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found") from exc
    return _proposal_response(proposal)


@router.post("/{proposal_id}/approve", response_model=ActionExecutionResult)
def approve_action_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
) -> ActionExecutionResult:
    try:
        return _service(db, context).approve_and_execute(proposal_id)
    except TenantIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{proposal_id}/reject", response_model=ActionExecutionResult)
def reject_action_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
) -> ActionExecutionResult:
    try:
        return _service(db, context).reject(proposal_id)
    except TenantIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
