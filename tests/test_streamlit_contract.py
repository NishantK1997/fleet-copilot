from fastapi.security import HTTPAuthorizationCredentials

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


def test_streamlit_ui_backend_contract_supports_chat_and_proposals():
    with SessionLocal() as db:
        auth, context = context_for(db)
        assert auth.user.email == "admin@acme.example"
        assert auth.user.company_id == "acme-001"

        summary = chat(ChatRequest(message="Give me fleet summary"), db, context)
        assert summary.answer
        assert summary.tool_results
        assert summary.evidence

        proposal = chat(ChatRequest(message="Open a remediation ticket for 1LYSSFD074BB os up to date"), db, context)
        proposal_result = next(result for result in proposal.tool_results if result["tool"] == "propose_action")
        proposal_id = proposal_result["data"]["proposal_id"]
        assert proposal_result["data"]["status"] == "PENDING_APPROVAL"
        assert proposal_id

        rejected = reject_action_proposal(proposal_id, db, context)
        assert rejected.proposal_status == "REJECTED"
