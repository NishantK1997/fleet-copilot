from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.database.models import ActionProposal
from app.guardrails.evidence import (
    EvidenceDecision,
    check_notification_evidence,
    check_remediation_ticket_evidence,
    check_replacement_evidence,
    check_upgrade_order_evidence,
)
from app.services.audit import write_audit_log
from app.tools.schemas import Evidence, ToolResult


ActionType = Literal[
    "create_upgrade_order",
    "open_remediation_ticket",
    "flag_device_for_replacement",
    "notify_employee",
]


class ActionProposalInput(BaseModel):
    action_type: ActionType
    device_id: str | None = None
    employee_id: str | None = None
    component: str | None = None
    spec: str | None = None
    check_id: str | None = None
    note: str | None = None
    message: str | None = None
    reason: str = Field(min_length=1, max_length=2000)


class ActionProposalResult(BaseModel):
    created: bool
    proposal_id: int | None = None
    status: str | None = None
    action_type: ActionType
    reason: str
    refusal_reason: str | None = None
    proposed_arguments: dict
    evidence: list[Evidence] = Field(default_factory=list)


class ProposalService:
    def __init__(self, db: Session, context: TenantContext):
        self.db = db
        self.context = context

    def propose_action(self, payload: ActionProposalInput) -> ActionProposalResult:
        decision = self._check_evidence(payload)
        proposed_arguments = self._arguments(payload)

        if not decision.allowed:
            write_audit_log(
                self.db,
                self.context,
                event_type="action_proposal_blocked",
                status="BLOCKED",
                tool_name="propose_action",
                resource_type=payload.action_type,
                resource_id=payload.device_id or payload.employee_id,
                arguments=proposed_arguments,
                result={"reason": decision.reason},
            )
            self.db.commit()
            return ActionProposalResult(
                created=False,
                action_type=payload.action_type,
                reason=payload.reason,
                refusal_reason=decision.reason,
                proposed_arguments=proposed_arguments,
                evidence=decision.evidence,
            )

        proposal = ActionProposal(
            company_id=self.context.company_id,
            user_id=self.context.user_id,
            action_type=payload.action_type,
            device_id=payload.device_id,
            employee_id=payload.employee_id,
            proposed_arguments=proposed_arguments,
            reason=payload.reason,
            evidence=[item.model_dump(mode="json") for item in decision.evidence],
            status="PENDING_APPROVAL",
        )
        self.db.add(proposal)
        self.db.flush()
        write_audit_log(
            self.db,
            self.context,
            event_type="action_proposal_created",
            status="PENDING_APPROVAL",
            tool_name="propose_action",
            resource_type=payload.action_type,
            resource_id=str(proposal.id),
            arguments=proposed_arguments,
            evidence=[item.model_dump(mode="json") for item in decision.evidence],
            result={"proposal_id": proposal.id},
        )
        self.db.commit()
        self.db.refresh(proposal)
        return ActionProposalResult(
            created=True,
            proposal_id=proposal.id,
            status=proposal.status,
            action_type=payload.action_type,
            reason=payload.reason,
            proposed_arguments=proposed_arguments,
            evidence=decision.evidence,
        )

    def propose_action_tool(self, payload: ActionProposalInput) -> ToolResult:
        result = self.propose_action(payload)
        summary = (
            f"Created PENDING_APPROVAL proposal {result.proposal_id} for {result.action_type}."
            if result.created
            else f"Blocked {result.action_type} proposal: {result.refusal_reason}"
        )
        return ToolResult(
            tool="propose_action",
            summary=summary,
            data=result.model_dump(mode="json"),
            evidence=result.evidence,
        )

    def _check_evidence(self, payload: ActionProposalInput) -> EvidenceDecision:
        if payload.action_type == "create_upgrade_order":
            if not payload.device_id or not payload.component or not payload.spec:
                return EvidenceDecision(False, "Upgrade proposals require device_id, component, and spec.", [])
            return check_upgrade_order_evidence(
                self.db,
                self.context,
                device_id=payload.device_id,
                component=payload.component,
            )

        if payload.action_type == "open_remediation_ticket":
            if not payload.device_id or not payload.check_id or not payload.note:
                return EvidenceDecision(False, "Remediation ticket proposals require device_id, check_id, and note.", [])
            return check_remediation_ticket_evidence(
                self.db,
                self.context,
                device_id=payload.device_id,
                check_id=payload.check_id,
            )

        if payload.action_type == "flag_device_for_replacement":
            if not payload.device_id:
                return EvidenceDecision(False, "Replacement proposals require device_id.", [])
            return check_replacement_evidence(self.db, self.context, device_id=payload.device_id)

        if payload.action_type == "notify_employee":
            if not payload.employee_id or not payload.message:
                return EvidenceDecision(False, "Notification proposals require employee_id and message.", [])
            return check_notification_evidence(
                self.db,
                self.context,
                employee_id=payload.employee_id,
                device_id=payload.device_id,
            )

        return EvidenceDecision(False, "Unsupported action type.", [])

    def _arguments(self, payload: ActionProposalInput) -> dict:
        return payload.model_dump(mode="json", exclude_none=True)
