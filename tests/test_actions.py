from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

from app.api.actions import approve_action_proposal, get_action_proposal, reject_action_proposal
from app.api.auth import login
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.models import (
    ActionProposal,
    AuditLog,
    Notification,
    RemediationTicket,
    ReplacementRequest,
    UpgradeOrder,
)
from app.database.session import SessionLocal
from app.services.proposals import ActionProposalInput, ProposalService


def context_for(db, email: str = "admin@acme.example", password: str = "AcmeAdmin123!"):
    token = login(LoginRequest(email=email, password=password), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model)) or 0


def proposal(db, context, payload: ActionProposalInput):
    result = ProposalService(db, context).propose_action(payload)
    assert result.created
    return result.proposal_id


def test_reject_pending_proposal_creates_no_operational_row():
    with SessionLocal() as db:
        context = context_for(db)
        proposal_id = proposal(
            db,
            context,
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="MT7PJB7N5LRE",
                component="storage",
                spec="1TB SSD",
                reason="Reject test.",
            ),
        )
        before = count(db, UpgradeOrder)
        result = reject_action_proposal(proposal_id, db, context)
        assert result.proposal_status == "REJECTED"
        assert count(db, UpgradeOrder) == before
        assert db.get(ActionProposal, proposal_id).status == "REJECTED"


def test_approve_upgrade_order_executes_once_and_audits():
    with SessionLocal() as db:
        context = context_for(db)
        proposal_id = proposal(
            db,
            context,
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="MT7PJB7N5LRE",
                component="storage",
                spec="1TB SSD",
                reason="Approve upgrade.",
            ),
        )
        before = count(db, UpgradeOrder)
        result = approve_action_proposal(proposal_id, db, context)
        assert result.proposal_status == "EXECUTED"
        assert result.operational_table == "upgrade_orders"
        assert count(db, UpgradeOrder) == before + 1
        assert db.get(ActionProposal, proposal_id).status == "EXECUTED"
        audit = db.scalar(select(AuditLog).where(AuditLog.event_type == "action_executed").order_by(AuditLog.id.desc()).limit(1))
        assert audit is not None

        try:
            approve_action_proposal(proposal_id, db, context)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("executed proposal was approved twice")


def test_approve_all_action_types():
    with SessionLocal() as db:
        context = context_for(db)
        cases = [
            (
                RemediationTicket,
                "remediation_tickets",
                ActionProposalInput(
                    action_type="open_remediation_ticket",
                    device_id="1LYSSFD074BB",
                    check_id="os_up_to_date",
                    note="Update OS.",
                    reason="Approve remediation.",
                ),
            ),
            (
                ReplacementRequest,
                "replacement_requests",
                ActionProposalInput(
                    action_type="flag_device_for_replacement",
                    device_id="7VP16KHV88LM",
                    reason="Approve replacement.",
                ),
            ),
            (
                Notification,
                "notifications",
                ActionProposalInput(
                    action_type="notify_employee",
                    employee_id="emp-acme-1001",
                    device_id="1LYSSFD074BB",
                    message="Please update your device.",
                    reason="Approve notification.",
                ),
            ),
        ]
        for model, table, payload in cases:
            before = count(db, model)
            proposal_id = proposal(db, context, payload)
            result = approve_action_proposal(proposal_id, db, context)
            assert result.operational_table == table
            assert result.proposal_status == "EXECUTED"
            assert count(db, model) == before + 1


def test_cross_tenant_get_and_approve_are_blocked():
    with SessionLocal() as db:
        acme = context_for(db)
        globex = context_for(db, "admin@globex.example", "GlobexAdmin123!")
        proposal_id = proposal(
            db,
            acme,
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="MT7PJB7N5LRE",
                component="storage",
                spec="1TB SSD",
                reason="Cross tenant block.",
            ),
        )
        for fn in [get_action_proposal, approve_action_proposal, reject_action_proposal]:
            try:
                fn(proposal_id, db, globex)
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError(f"{fn.__name__} allowed cross-tenant access")
