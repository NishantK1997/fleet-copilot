from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import TenantContext, get_tenant_context


router = APIRouter(prefix="/tenant", tags=["tenant"])


class TenantEchoRequest(BaseModel):
    company_id: str | None = None


class TenantContextResponse(BaseModel):
    user_id: int
    email: str
    company_id: str
    role: str
    session_id: str


@router.get("/me", response_model=TenantContextResponse)
def tenant_me(context: TenantContext = Depends(get_tenant_context)) -> TenantContextResponse:
    return TenantContextResponse(**context.__dict__)


@router.post("/echo", response_model=TenantContextResponse)
def tenant_echo(
    _payload: TenantEchoRequest,
    context: TenantContext = Depends(get_tenant_context),
) -> TenantContextResponse:
    return TenantContextResponse(**context.__dict__)
