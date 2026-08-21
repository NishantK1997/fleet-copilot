import json
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.passwords import hash_password, verify_password
from app.config import get_settings
from app.database.models import Company, User
from app.database.session import SessionLocal


DEMO_ADMINS = [
    ("acme-001", "Acme", "admin@acme.example", "acme_admin_password"),
    ("globex-002", "Globex", "admin@globex.example", "globex_admin_password"),
    ("initech-003", "Initech", "admin@initech.example", "initech_admin_password"),
]


def seed_users() -> dict[str, object]:
    settings = get_settings()
    created = 0
    updated = 0
    users: list[dict[str, str]] = []

    with SessionLocal() as db:
        for company_id, company_name, email, password_attr in DEMO_ADMINS:
            company = db.get(Company, company_id)
            if company is None:
                company = Company(id=company_id, name=company_name)
                db.add(company)
                db.flush()

            password = getattr(settings, password_attr)
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    email=email,
                    password_hash=hash_password(password),
                    company_id=company_id,
                    role="admin",
                    is_active=True,
                )
                db.add(user)
                created += 1
            else:
                changed = False
                if user.company_id != company_id:
                    user.company_id = company_id
                    changed = True
                if user.role != "admin":
                    user.role = "admin"
                    changed = True
                if not user.is_active:
                    user.is_active = True
                    changed = True
                if not verify_password(password, user.password_hash):
                    user.password_hash = hash_password(password)
                    changed = True
                if changed:
                    updated += 1

            users.append({"email": email, "company_id": company_id, "role": "admin"})

        db.commit()

    return {"created": created, "updated": updated, "users": users}


def main() -> None:
    print(json.dumps(seed_users(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
