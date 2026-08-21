import sys
from pathlib import Path

from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.actions import approve_action_proposal, reject_action_proposal
from app.api.auth import login
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.models import RemediationTicket, UpgradeOrder
from app.database.session import SessionLocal
from app.services.proposals import ActionProposalInput, ProposalService


def context_for(db):
    token = login(LoginRequest(email="admin@acme.example", password="AcmeAdmin123!"), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def main() -> None:
    with SessionLocal() as db:
        context = context_for(db)
        proposal_service = ProposalService(db, context)

        reject_candidate = proposal_service.propose_action(
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="MT7PJB7N5LRE",
                component="storage",
                spec="1TB SSD",
                reason="Reject path check.",
            )
        )
        upgrade_before = count(db, UpgradeOrder)
        rejected = reject_action_proposal(reject_candidate.proposal_id, db, context)
        assert rejected.proposal_status == "REJECTED"
        assert count(db, UpgradeOrder) == upgrade_before
        print("reject creates no operational row: PASS")

        approve_candidate = proposal_service.propose_action(
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="MT7PJB7N5LRE",
                component="storage",
                spec="1TB SSD",
                reason="Approve path check.",
            )
        )
        approved = approve_action_proposal(approve_candidate.proposal_id, db, context)
        assert approved.proposal_status == "EXECUTED"
        assert approved.operational_table == "upgrade_orders"
        assert count(db, UpgradeOrder) == upgrade_before + 1
        print("approve creates upgrade order: PASS")

        ticket_candidate = proposal_service.propose_action(
            ActionProposalInput(
                action_type="open_remediation_ticket",
                device_id="1LYSSFD074BB",
                check_id="os_up_to_date",
                note="Update OS.",
                reason="Approval ticket check.",
            )
        )
        tickets_before = count(db, RemediationTicket)
        ticket = approve_action_proposal(ticket_candidate.proposal_id, db, context)
        assert ticket.operational_table == "remediation_tickets"
        assert count(db, RemediationTicket) == tickets_before + 1
        print("approve creates remediation ticket: PASS")


if __name__ == "__main__":
    main()
