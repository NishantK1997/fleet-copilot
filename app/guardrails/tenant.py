from typing import Protocol

from sqlalchemy import Select

from app.auth.dependencies import TenantContext


class TenantScopedModel(Protocol):
    company_id: str


def tenant_filter(model: type[TenantScopedModel], context: TenantContext):
    return model.company_id == context.company_id


def apply_tenant_scope(statement: Select, model: type[TenantScopedModel], context: TenantContext) -> Select:
    return statement.where(tenant_filter(model, context))
