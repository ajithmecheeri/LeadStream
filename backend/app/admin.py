"""Make an account super admin, or take it back. The only way to become admin: there is no API for it.

    python -m app.admin you@example.com            # make super admin
    python -m app.admin you@example.com --revoke   # back to a job seeker

The new role is in the next access token, so sign out and in again (or wait for the token to refresh).
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.db import dispose_engine, sessionmaker
from app.modules.users.models import AuditEvent, User


async def set_role(email: str, role: str) -> str:
    async with sessionmaker()() as db, db.begin():
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            return f"No account with the email {email}"
        if user.role == role:
            return f"{email} is already {'the super admin' if role == 'super_admin' else 'a job seeker'}"
        user.role = role
        db.add(AuditEvent(user_id=user.id, actor="cli", event=f"role_set_{role}", entity="user"))
        return f"{email} is now {'the super admin' if role == 'super_admin' else 'a job seeker'}. Sign out and in again."


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("email")
    p.add_argument("--revoke", action="store_true", help="make the account a job seeker again")
    args = p.parse_args()
    try:
        message = await set_role(args.email.strip(), "job_seeker" if args.revoke else "super_admin")
    finally:
        await dispose_engine()
    print(message)
    return 1 if message.startswith("No account") else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
