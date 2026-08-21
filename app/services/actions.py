from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.database.models import (
    ActionProposal,
    Notification,
    RemediationTicket,
    ReplacementRequest,
    UpgradeOrder,
)
from app.database.repositories.proposals import ActionProposalRepository
from app.guardrails.authorization import TenantIsolationError
from app.services.audit import write_audit_log
from app.services.proposals import ActionProposalInput, ProposalService


class ActionExecutionResult(BaseModel):
    proposal_id: int
    action_type: str
    proposal_status: str
    operational_table: str | None = None
    operational_id: int | None = None
    message: str


class ActionApprovalService:
    def __init__(self, db: Session, context: TenantContext):
        self.db = db
        self.context = context

    def get_proposal(self, proposal_id: int) -> ActionProposal:
        return ActionProposalRepository(self.db, self.context).require(proposal_id)

    def reject(self, proposal_id: int) -> ActionExecutionResult:
        proposal = self.get_proposal(proposal_id)
        if proposal.status != "PENDING_APPROVAL":
            raise ValueError(f"Only PENDING_APPROVAL proposals can be rejected; current status is {proposal.status}.")
        proposal.status = "REJECTED"
        proposal.updated_at = datetime.now(timezone.utc)
        write_audit_log(
            self.db,
            self.context,
            event_type="action_proposal_rejected",
            status="REJECTED",
            tool_name="reject_proposal",
            resource_type=proposal.action_type,
            resource_id=str(proposal.id),
            arguments=proposal.proposed_arguments,
            evidence=proposal.evidence,
            result={"proposal_id": proposal.id},
        )
        self.db.commit()
        return ActionExecutionResult(
            proposal_id=proposal.id,
            action_type=proposal.action_type,
            proposal_status="REJECTED",
            message="Proposal rejected. No operational action was created.",
        )

    def approve_and_execute(self, proposal_id: int) -> ActionExecutionResult:
        proposal = self.get_proposal(proposal_id)
        if proposal.status != "PENDING_APPROVAL":
            raise ValueError(f"Only PENDING_APPROVAL proposals can be approved; current status is {proposal.status}.")

        try:
            payload = ActionProposalInput(**proposal.proposed_arguments)
            decision = ProposalService(self.db, self.context)._check_evidence(payload)
            if not decision.allowed:
                proposal.status = "FAILED"
                proposal.updated_at = datetime.now(timezone.utc)
                write_audit_log(
                    self.db,
                    self.context,
                    event_type="action_execution_failed",
                    status="FAILED",
                    tool_name="approve_proposal",
                    resource_type=proposal.action_type,
                    resource_id=str(proposal.id),
                    arguments=proposal.proposed_arguments,
                    evidence=proposal.evidence,
                    result={"reason": decision.reason},
                )
                self.db.commit()
                return ActionExecutionResult(
                    proposal_id=proposal.id,
                    action_type=proposal.action_type,
                    proposal_status="FAILED",
                    message=f"Proposal evidence no longer passes policy: {decision.reason}",
                )

            operational_table, operational_id = self._execute(payload)
            now = datetime.now(timezone.utc)
            proposal.status = "EXECUTED"
            proposal.approved_at = now
            proposal.executed_at = now
            proposal.updated_at = now
            write_audit_log(
                self.db,
                self.context,
                event_type="action_executed",
                status="EXECUTED",
                tool_name=proposal.action_type,
                resource_type=operational_table,
                resource_id=str(operational_id),
                arguments=proposal.proposed_arguments,
                evidence=proposal.evidence,
                result={"proposal_id": proposal.id, "operational_id": operational_id},
            )
            self.db.commit()
            return ActionExecutionResult(
                proposal_id=proposal.id,
                action_type=proposal.action_type,
                proposal_status="EXECUTED",
                operational_table=operational_table,
                operational_id=operational_id,
                message="Proposal approved and executed.",
            )
        except TenantIsolationError:
            raise
        except Exception as exc:
            proposal.status = "FAILED"
            proposal.updated_at = datetime.now(timezone.utc)
            write_audit_log(
                self.db,
                self.context,
                event_type="action_execution_failed",
                status="FAILED",
                tool_name=proposal.action_type,
                resource_type=proposal.action_type,
                resource_id=str(proposal.id),
                arguments=proposal.proposed_arguments,
                evidence=proposal.evidence,
                result={"error": str(exc)},
            )
            self.db.commit()
            raise

    def _execute(self, payload: ActionProposalInput) -> tuple[str, int]:
        if payload.action_type == "create_upgrade_order":
            if not payload.device_id or not payload.component or not payload.spec:
                raise ValueError("Upgrade order proposal is missing required arguments.")
            row = UpgradeOrder(
                company_id=self.context.company_id,
                device_id=payload.device_id,
                component=payload.component,
                spec=payload.spec,
                reason=payload.reason,
                status="OPEN",
                created_by=self.context.user_id,
            )
            self.db.add(row)
            self.db.flush()
            return "upgrade_orders", row.id

        if payload.action_type == "open_remediation_ticket":
            if not payload.device_id or not payload.check_id or not payload.note:
                raise ValueError("Remediation ticket proposal is missing required arguments.")
            row = RemediationTicket(
                company_id=self.context.company_id,
                device_id=payload.device_id,
                check_id=payload.check_id,
                note=payload.note,
                status="OPEN",
                created_by=self.context.user_id,
            )
            self.db.add(row)
            self.db.flush()
            return "remediation_tickets", row.id

        if payload.action_type == "flag_device_for_replacement":
            if not payload.device_id:
                raise ValueError("Replacement proposal is missing device_id.")
            row = ReplacementRequest(
                company_id=self.context.company_id,
                device_id=payload.device_id,
                reason=payload.reason,
                status="OPEN",
                created_by=self.context.user_id,
            )
            self.db.add(row)
            self.db.flush()
            return "replacement_requests", row.id

        if payload.action_type == "notify_employee":
            if not payload.employee_id or not payload.message:
                raise ValueError("Notification proposal is missing employee_id or message.")
            row = Notification(
                company_id=self.context.company_id,
                employee_id=payload.employee_id,
                device_id=payload.device_id,
                message=payload.message,
                status="QUEUED",
                created_by=self.context.user_id,
            )
            self.db.add(row)
            self.db.flush()
            return "notifications", row.id

        raise ValueError(f"Unsupported action type: {payload.action_type}")
