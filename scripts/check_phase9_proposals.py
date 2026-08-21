import sys
from pathlib import Path

from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.auth import login
from app.api.chat import ChatRequest, chat
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.models import ActionProposal, RemediationTicket, ReplacementRequest, UpgradeOrder
from app.database.session import SessionLocal
from app.services.proposals import ActionProposalInput, ProposalService


def context_for(db):
    token = login(LoginRequest(email="admin@acme.example", password="AcmeAdmin123!"), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def operational_counts(db) -> tuple[int, int, int]:
    return (
        db.scalar(select(func.count()).select_from(UpgradeOrder)) or 0,
        db.scalar(select(func.count()).select_from(RemediationTicket)) or 0,
        db.scalar(select(func.count()).select_from(ReplacementRequest)) or 0,
    )


def main() -> None:
    with SessionLocal() as db:
        context = context_for(db)
        service = ProposalService(db, context)
        before = operational_counts(db)

        valid = service.propose_action(
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="MT7PJB7N5LRE",
                component="storage",
                spec="1TB SSD",
                reason="Persistent low disk evidence supports storage upgrade.",
            )
        )
        assert valid.created and valid.status == "PENDING_APPROVAL" and valid.evidence
        print("valid storage upgrade proposal: PASS")

        blocked = service.propose_action(
            ActionProposalInput(
                action_type="create_upgrade_order",
                device_id="1LYSSFD074BB",
                component="storage",
                spec="1TB SSD",
                reason="Try weak evidence storage upgrade.",
            )
        )
        assert not blocked.created and blocked.refusal_reason
        print("weak evidence blocked: PASS")

        ticket = service.propose_action(
            ActionProposalInput(
                action_type="open_remediation_ticket",
                device_id="1LYSSFD074BB",
                check_id="os_up_to_date",
                note="Update OS on failing device.",
                reason="Compliance check is failing.",
            )
        )
        assert ticket.created and ticket.evidence
        print("valid remediation proposal: PASS")

        response = chat(ChatRequest(message="Open a remediation ticket for 1LYSSFD074BB os up to date"), db, context)
        assert response.tool_calls[0]["tool"] == "propose_action"
        assert response.evidence
        print("agent proposal routing: PASS")

        after = operational_counts(db)
        assert before == after
        assert db.scalar(select(func.count()).select_from(ActionProposal)) >= 3
        print("no operational action executed: PASS")


if __name__ == "__main__":
    main()
