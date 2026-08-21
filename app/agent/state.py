from typing import Any, TypedDict

from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.tools.schemas import Evidence, ToolResult


class ToolCall(TypedDict):
    tool: str
    arguments: dict[str, Any]


class AgentState(TypedDict, total=False):
    message: str
    db: Session
    context: TenantContext
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
    evidence: list[Evidence]
    final_answer: str
    unsupported_reason: str | None
