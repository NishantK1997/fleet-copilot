from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

from app.api.auth import login
from app.api.chat import ChatRequest, chat
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.models import (
    ActionProposal,
    AuditLog,
    RemediationTicket,
    ReplacementRequest,
    UpgradeOrder,
)
from app.database.session import SessionLocal
from app.guardrails.authorization import TenantIsolationError
from app.services.proposals import ActionProposalInput, ProposalService


def context_for(db, email: str = "admin@acme.example", password: str = "AcmeAdmin123!"):
    token = login(LoginRequest(email=email, password=password), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def action_counts(db):
    return (
        db.scalar(select(func.count()).select_from(UpgradeOrder)),
        db.scalar(select(func.count()).select_from(RemediationTicket)),
        db.scalar(select(func.count()).select_from(ReplacementRequest)),
    )


def test_valid_upgrade_proposal_is_pending_and_has_evidence():
    with SessionLocal() as db:
        context = context_for(db)
        result = ProposalService(db, context).propose_action(
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="MT7PJB7N5LRE",
                component="storage",
                spec="1TB SSD",
                reason="Persistent low disk evidence supports storage upgrade.",
            )
        )
        assert result.created
        assert result.status == "PENDING_APPROVAL"
        assert result.evidence
        proposal = db.get(ActionProposal, result.proposal_id)
        assert proposal is not None
        assert proposal.company_id == "acme-001"
        assert proposal.status == "PENDING_APPROVAL"


def test_weak_evidence_action_is_blocked_and_audited():
    with SessionLocal() as db:
        context = context_for(db)
        before = db.scalar(select(func.count()).select_from(ActionProposal))
        result = ProposalService(db, context).propose_action(
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="1LYSSFD074BB",
                component="storage",
                spec="1TB SSD",
                reason="Weak evidence should be blocked.",
            )
        )
        after = db.scalar(select(func.count()).select_from(ActionProposal))
        assert not result.created
        assert result.refusal_reason
        assert before == after
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.event_type == "action_proposal_blocked", AuditLog.company_id == "acme-001")
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        assert audit is not None


def test_remediation_and_replacement_proposals_require_evidence():
    with SessionLocal() as db:
        context = context_for(db)
        service = ProposalService(db, context)
        ticket = service.propose_action(
            ActionProposalInput(
                action_type="open_remediation_ticket",
                device_id="1LYSSFD074BB",
                check_id="os_up_to_date",
                note="Update OS.",
                reason="Compliance failure is present.",
            )
        )
        replacement = service.propose_action(
            ActionProposalInput(
                action_type="flag_device_for_replacement",
                device_id="7VP16KHV88LM",
                reason="Battery risk is present.",
            )
        )
        assert ticket.created and ticket.evidence
        assert replacement.created and replacement.evidence


def test_cross_tenant_proposal_target_is_blocked():
    with SessionLocal() as db:
        context = context_for(db)
        try:
            ProposalService(db, context).propose_action(
                ActionProposalInput(
                    action_type="create_upgrade_order",
                    device_id="JRZSGXVMKE6M",
                    component="storage",
                    spec="1TB SSD",
                    reason="Globex device should be blocked for Acme.",
                )
            )
        except TenantIsolationError:
            pass
        else:
            raise AssertionError("cross-tenant proposal target was not blocked")


def test_agent_creates_pending_proposal_and_no_operational_action():
    with SessionLocal() as db:
        context = context_for(db)
        before = action_counts(db)
        response = chat(ChatRequest(message="Open a remediation ticket for 1LYSSFD074BB os up to date"), db, context)
        after = action_counts(db)
        assert response.tool_calls[0]["tool"] == "propose_action"
        assert response.evidence
        assert "PENDING_APPROVAL" in response.answer
        assert before == after
