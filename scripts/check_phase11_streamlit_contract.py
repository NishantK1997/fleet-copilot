import sys
from pathlib import Path

from fastapi.security import HTTPAuthorizationCredentials

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.actions import reject_action_proposal
from app.api.auth import login
from app.api.chat import ChatRequest, chat
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.session import SessionLocal


def context_for(db):
    auth = login(LoginRequest(email="admin@acme.example", password="AcmeAdmin123!"), db)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth.access_token)
    user = get_current_user(credentials=credentials, db=db)
    return auth, get_tenant_context(credentials=credentials, user=user)


def main() -> None:
    with SessionLocal() as db:
        auth, context = context_for(db)
        assert auth.access_token and auth.user.company_id == "acme-001"
        print("login contract: PASS")

        summary = chat(ChatRequest(message="Give me fleet summary"), db, context)
        assert summary.answer and summary.evidence and summary.tool_results
        print("chat/evidence contract: PASS")

        proposal_response = chat(ChatRequest(message="Open a remediation ticket for 1LYSSFD074BB os up to date"), db, context)
        proposal_result = next(result for result in proposal_response.tool_results if result["tool"] == "propose_action")
        proposal_id = proposal_result["data"]["proposal_id"]
        assert proposal_id and proposal_result["data"]["status"] == "PENDING_APPROVAL"
        print("pending proposal contract: PASS")

        rejected = reject_action_proposal(proposal_id, db, context)
        assert rejected.proposal_status == "REJECTED"
        print("approve/reject endpoint contract: PASS")


if __name__ == "__main__":
    main()
