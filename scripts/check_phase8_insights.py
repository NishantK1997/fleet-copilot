import sys
from pathlib import Path

from fastapi.security import HTTPAuthorizationCredentials

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.auth import login
from app.api.chat import ChatRequest, chat
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.session import SessionLocal
from app.services.analytics import AnalyticsService, InsightDetectionInput
from app.tools.read_tools import detect_insights


def build_context(db, email: str, password: str):
    token = login(LoginRequest(email=email, password=password), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def main() -> None:
    with SessionLocal() as db:
        context = build_context(db, "admin@acme.example", "AcmeAdmin123!")
        service = AnalyticsService(db=db, context=context)

        disk = service.detect_low_disk(InsightDetectionInput(include_types=["low_disk"]))
        assert disk and all(item.evidence for item in disk)
        print("low disk insight: PASS")

        memory = service.detect_memory_pressure(InsightDetectionInput(include_types=["memory_pressure"]))
        assert memory and all(item.evidence for item in memory)
        print("memory pressure insight: PASS")

        battery = service.detect_battery_risk(InsightDetectionInput(include_types=["battery_risk"]))
        assert battery and all(item.evidence for item in battery)
        print("battery risk insight: PASS")

        compliance = service.detect_compliance_drift(InsightDetectionInput(include_types=["compliance_drift"]))
        assert compliance and all(item.evidence for item in compliance)
        print("compliance drift insight: PASS")

        result = detect_insights(db, context)
        assert result.evidence
        print("detect_insights tool: PASS")

        response = chat(ChatRequest(message="Show me fleet insights and compliance drift"), db, context)
        assert response.tool_calls[0]["tool"] == "detect_insights"
        assert response.evidence
        print("agent insight routing: PASS")


if __name__ == "__main__":
    main()
