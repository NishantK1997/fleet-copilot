from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.graph import run_agent
from app.auth.dependencies import TenantContext, get_tenant_context
from app.database.session import get_db
from app.tools.schemas import Evidence


router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    answer: str
    tool_calls: list[dict[str, Any]]
    tool_summaries: list[str]
    tool_results: list[dict[str, Any]]
    evidence: list[Evidence]


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
) -> ChatResponse:
    state = run_agent(payload.message, db, context)
    return ChatResponse(
        answer=state.get("final_answer", ""),
        tool_calls=state.get("tool_calls", []),
        tool_summaries=[result.summary for result in state.get("tool_results", [])],
        tool_results=[result.model_dump(mode="json") for result in state.get("tool_results", [])],
        evidence=state.get("evidence", []),
    )
