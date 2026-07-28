"""One-time bootstrap: promote a single existing account to SUPER_ADMIN. Only
runs when no SUPER_ADMIN exists yet — after that, ownership moves exclusively
through the in-app "Transfer Super Admin" action (user_service.transfer_super_admin),
which atomically demotes the old holder so there is never a moment with zero or
two Super Admins.

Usage: uv run python -m scripts.bootstrap_super_admin your@email.com
"""

import asyncio
import sys

from lib.prisma_client import db
from prisma.enums import Role


async def main(email: str) -> None:
    await db.connect()
    try:
        existing = await db.user.find_first(where={"role": Role.SUPER_ADMIN})
        if existing:
            print(f"A Super Admin already exists ({existing.email}). Use the in-app "
                  f"transfer action instead — refusing to create a second one.")
            return

        user = await db.user.find_unique(where={"email": email})
        if not user:
            print(f"No user found with email {email}")
            return

        await db.user.update(where={"id": user.id}, data={"role": Role.SUPER_ADMIN})
        print(f"{email} is now the Super Admin.")
    finally:
        await db.disconnect()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python -m scripts.bootstrap_super_admin <email>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
