"""Load the fictional demo user from the POC (Kavya Iyer) so the app has something to show.

    python -m app.seed            # create if missing
    python -m app.seed --reset    # delete and recreate

Sign in with demo@example.com / FitFirst-demo-2026
"""

import asyncio
import sys

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import dispose_engine, sessionmaker, set_user
from app.modules.auth import service as auth
from app.modules.auth.schemas import NameParts
from app.modules.candidate.models import CandidateProfile
from app.modules.profiles.models import SearchProfile
from app.modules.users.models import User

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "FitFirst-demo-2026"

CANDIDATE = {
    "headline": "Engineering and product leader, cloud SaaS and payments",
    "summary": "Engineering and product leader with 22 years building cloud SaaS and payments platforms, "
    "most recently leading AI adoption across product engineering.",
    "current_location": "Bengaluru",
    "years_experience": 22,
    "skills": [
        "product development",
        "leadership",
        "aws",
        "azure",
        "microservices",
        "kubernetes",
        "kafka",
        "llm",
        "genai",
        "machine learning",
        "responsible ai",
        "python",
        "java",
        ".net",
        "saas",
        "architecture",
        "pci dss",
        "soc2",
        "iso 27001",
        "agile",
        "devops",
        "observability",
    ],
    "domains": ["fintech", "payments", "banking", "saas", "lending"],
    "notice_days": 90,
    "expected_ctc": "",
}

PROFILES = [
    {
        "name": "VP Engineering",
        "target_roles": [
            "VP Engineering",
            "VP Product Development",
            "SVP Product Engineering",
            "Head of Engineering",
        ],
        "locations": ["Bengaluru", "Hyderabad", "Remote"],
        "work_models": ["Hybrid", "Remote"],
        "min_seniority": 5,
        "excluded_companies": ["Staffing"],
        "threshold": 85,
        "weights": {
            "role": 20,
            "exp": 15,
            "core": 15,
            "cloud": 10,
            "ai": 10,
            "domain": 10,
            "loc": 10,
            "skills": 5,
            "comp": 5,
        },
    },
    {
        "name": "CTO-track",
        "target_roles": ["CTO", "Chief Technology Officer", "SVP Engineering"],
        "locations": ["Bengaluru", "Remote"],
        "work_models": ["Hybrid", "Remote", "On-site"],
        "min_seniority": 7,
        "excluded_companies": [],
        "threshold": 85,
        "weights": {
            "role": 25,
            "exp": 20,
            "core": 10,
            "cloud": 10,
            "ai": 15,
            "domain": 5,
            "loc": 5,
            "skills": 5,
            "comp": 5,
        },
    },
]


async def run(reset: bool = False) -> None:
    async with sessionmaker()() as db, db.begin():
        existing = await db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing and not reset:
            print(f"Demo user already exists: {DEMO_EMAIL}")
            return
        if existing:
            await db.execute(delete(User).where(User.id == existing.id))
            await db.flush()
        names = NameParts(first_name="Kavya", last_name="Iyer (sample)")
        user = await auth.signup(db, DEMO_EMAIL, names, DEMO_PASSWORD, job_locations=["Bengaluru", "Remote"])
        await set_user(db, user.id)
        cand = await db.get(CandidateProfile, user.id)
        for k, v in CANDIDATE.items():
            setattr(cand, k, v)
        for p in PROFILES:
            db.add(SearchProfile(user_id=user.id, **p))
    print(f"Seeded demo user: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"Forwarding address: {auth.forwarding_address(user)}")


# The e2e tests manage Job sources, which is for admins (2026-11-17): a local-only admin account for them.
E2E_ADMIN_EMAIL = "e2e-admin@example.com"
E2E_ADMIN_PASSWORD = "e2e-admin-password-2026"


async def e2e_admin() -> None:
    if get_settings().env != "local":
        return
    async with sessionmaker()() as db, db.begin():
        if await db.scalar(select(User.id).where(User.email == E2E_ADMIN_EMAIL)):
            return
        names = NameParts(first_name="E2E", last_name="Admin")
        user = await auth.signup(db, E2E_ADMIN_EMAIL, names, E2E_ADMIN_PASSWORD, job_locations=["Bengaluru"])
        user.role = "admin"
    print(f"Seeded the e2e admin (local only): {E2E_ADMIN_EMAIL}")


async def main() -> None:
    try:
        await run(reset="--reset" in sys.argv)
        await e2e_admin()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
