from fastapi import FastAPI

from app.api.actions import router as actions_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.tenant import router as tenant_router
from app.config import get_settings
from app.database.session import check_database_connection


settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(actions_router)
app.include_router(auth_router)
app.include_router(tenant_router)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    check_database_connection()
    return {
        "status": "healthy",
        "database": "connected",
        "environment": settings.environment,
    }
