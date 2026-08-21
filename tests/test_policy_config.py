from pathlib import Path

import yaml
from fastapi.security import HTTPAuthorizationCredentials

from app.api.auth import login
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.config_policies import clear_policy_cache, load_policies
from app.database.session import SessionLocal
from app.tools.read_tools import get_low_disk_devices


POLICY_PATH = Path("config/policies.yaml")


def context_for(db):
    token = login(LoginRequest(email="admin@acme.example", password="AcmeAdmin123!"), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def test_policy_yaml_loads_thresholds():
    clear_policy_cache()
    policies = load_policies()
    assert policies.read_tools.low_disk_percent == 10
    assert policies.read_tools.persistent_ratio == 0.5
    assert policies.insights.compliance_drift_fail_ratio == 0.25


def test_read_tool_defaults_change_when_policy_yaml_changes():
    original_text = POLICY_PATH.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(original_text)
        data["read_tools"]["low_disk_percent"] = 1
        POLICY_PATH.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        clear_policy_cache()

        with SessionLocal() as db:
            context = context_for(db)
            result = get_low_disk_devices(db, context)
            assert result.data == []
    finally:
        POLICY_PATH.write_text(original_text, encoding="utf-8")
        clear_policy_cache()
