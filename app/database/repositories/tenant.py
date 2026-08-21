from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.guardrails.authorization import TenantIsolationError
from app.guardrails.tenant import apply_tenant_scope


ModelT = TypeVar("ModelT")


class TenantRepository(Generic[ModelT]):
    def __init__(self, db: Session, context: TenantContext, model: type[ModelT]):
        self.db = db
        self.context = context
        self.model = model

    def scoped(self, statement: Select | None = None) -> Select:
        statement = statement if statement is not None else select(self.model)
        return apply_tenant_scope(statement, self.model, self.context)

    def one_or_none(self, *filters: Any) -> ModelT | None:
        statement = self.scoped().where(*filters)
        return self.db.scalar(statement)

    def require_one(self, *filters: Any, resource_name: str = "resource") -> ModelT:
        value = self.one_or_none(*filters)
        if value is None:
            raise TenantIsolationError(f"{resource_name} not found for authenticated tenant")
        return value

    def list(self, *filters: Any) -> list[ModelT]:
        statement = self.scoped().where(*filters)
        return list(self.db.scalars(statement).all())
