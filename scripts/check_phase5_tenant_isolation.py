import sys
from pathlib import Path

from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.auth import login
from app.api.tenant import TenantEchoRequest, tenant_echo
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.models import Device
from app.database.repositories.devices import DeviceRepository
from app.database.session import SessionLocal
from app.guardrails.authorization import TenantIsolationError


def build_context(db, email: str, password: str):
    token = login(LoginRequest(email=email, password=password), db).access_token
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def main() -> None:
    with SessionLocal() as db:
        acme_context = build_context(db, "admin@acme.example", "AcmeAdmin123!")
        forged = tenant_echo(TenantEchoRequest(company_id="globex-002"), acme_context)
        assert forged.company_id == "acme-001"
        print("forged company_id ignored: PASS")

        globex_device_id = db.scalar(select(Device.device_id).where(Device.company_id == "globex-002"))
        assert globex_device_id is not None
        acme_devices = DeviceRepository(db, acme_context).list_all()
        assert acme_devices
        assert {device.company_id for device in acme_devices} == {"acme-001"}
        print("tenant list scoped to acme-001: PASS")

        repo = DeviceRepository(db, acme_context)
        assert repo.get(globex_device_id) is None
        try:
            repo.require(globex_device_id)
        except TenantIsolationError:
            print("cross-tenant device blocked: PASS")
        else:
            raise AssertionError("cross-tenant device lookup was not blocked")


if __name__ == "__main__":
    main()
