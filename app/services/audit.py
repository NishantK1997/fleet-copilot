from sqlalchemy.orm import Session

from app.auth.dependencies import TenantContext
from app.database.models import AuditLog


def write_audit_log(
    db: Session,
    context: TenantContext,
    *,
    event_type: str,
    status: str,
    tool_name: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    arguments: dict | None = None,
    evidence: list | dict | None = None,
    result: dict | None = None,
) -> AuditLog:
    audit_log = AuditLog(
        company_id=context.company_id,
        user_id=context.user_id,
        session_id=context.session_id,
        event_type=event_type,
        tool_name=tool_name,
        resource_type=resource_type,
        resource_id=resource_id,
        arguments=arguments,
        evidence=evidence,
        result=result,
        status=status,
    )
    db.add(audit_log)
    return audit_log
