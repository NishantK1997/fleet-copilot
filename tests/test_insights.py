from fastapi.security import HTTPAuthorizationCredentials

from app.api.auth import login
from app.api.chat import ChatRequest, chat
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.session import SessionLocal
from app.services.analytics import AnalyticsService, InsightDetectionInput
from app.tools.read_tools import detect_insights


def context_for(db, email: str = "admin@acme.example", password: str = "AcmeAdmin123!"):
    token = login(LoginRequest(email=email, password=password), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def test_detects_all_four_acme_insight_types():
    with SessionLocal() as db:
        context = context_for(db)
        result = detect_insights(db, context, InsightDetectionInput(limit_per_type=10))
        types = {row["insight_type"] for row in result.data}
        assert {"low_disk", "memory_pressure", "battery_risk", "compliance_drift"}.issubset(types)
        assert result.evidence


def test_disk_memory_battery_and_compliance_have_evidence():
    with SessionLocal() as db:
        context = context_for(db)
        service = AnalyticsService(db=db, context=context)
        groups = [
            service.detect_low_disk(InsightDetectionInput(include_types=["low_disk"])),
            service.detect_memory_pressure(InsightDetectionInput(include_types=["memory_pressure"])),
            service.detect_battery_risk(InsightDetectionInput(include_types=["battery_risk"])),
            service.detect_compliance_drift(InsightDetectionInput(include_types=["compliance_drift"])),
        ]
        for insights in groups:
            assert insights
            assert all(insight.evidence for insight in insights)
            assert all(insight.time_window_start and insight.time_window_end for insight in insights)


def test_insights_are_tenant_scoped():
    with SessionLocal() as db:
        acme = context_for(db, "admin@acme.example", "AcmeAdmin123!")
        globex = context_for(db, "admin@globex.example", "GlobexAdmin123!")
        acme_result = detect_insights(db, acme, InsightDetectionInput(include_types=["low_disk"], limit_per_type=10))
        globex_result = detect_insights(db, globex, InsightDetectionInput(include_types=["low_disk"], limit_per_type=10))

        acme_devices = {row["device_id"] for row in acme_result.data}
        globex_devices = {row["device_id"] for row in globex_result.data}
        assert acme_devices
        assert globex_devices
        assert acme_devices.isdisjoint(globex_devices)


def test_agent_routes_trend_questions_to_insights():
    with SessionLocal() as db:
        context = context_for(db)
        response = chat(ChatRequest(message="Show me disk and compliance trend insights"), db, context)
        assert response.tool_calls[0]["tool"] == "detect_insights"
        assert response.evidence
        assert response.answer
