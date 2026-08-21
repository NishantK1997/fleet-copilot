from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select

from app.api.auth import login
from app.api.tenant import TenantEchoRequest, tenant_echo
from app.auth.dependencies import get_current_user, get_tenant_context
from app.auth.schemas import LoginRequest
from app.database.models import Device
from app.database.repositories.devices import DeviceRepository
from app.database.session import SessionLocal
from app.guardrails.authorization import TenantIsolationError


def login_context(db, email: str, password: str):
    result = login(LoginRequest(email=email, password=password), db)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=result.access_token)
    user = get_current_user(credentials=credentials, db=db)
    return get_tenant_context(credentials=credentials, user=user)


def test_forged_company_id_is_ignored():
    with SessionLocal() as db:
        context = login_context(db, "admin@acme.example", "AcmeAdmin123!")
        response = tenant_echo(TenantEchoRequest(company_id="globex-002"), context)
        assert response.company_id == "acme-001"


def test_cross_tenant_device_is_not_visible():
    with SessionLocal() as db:
        acme_context = login_context(db, "admin@acme.example", "AcmeAdmin123!")
        globex_device_id = db.scalar(select(Device.device_id).where(Device.company_id == "globex-002"))
        assert globex_device_id is not None

        repo = DeviceRepository(db, acme_context)
        assert repo.get(globex_device_id) is None
        try:
            repo.require(globex_device_id)
        except TenantIsolationError:
            pass
        else:
            raise AssertionError("cross-tenant device lookup was not blocked")


def test_tenant_device_listing_only_returns_own_company():
    with SessionLocal() as db:
        acme_context = login_context(db, "admin@acme.example", "AcmeAdmin123!")
        devices = DeviceRepository(db, acme_context).list_all()
        assert devices
        assert {device.company_id for device in devices} == {"acme-001"}
