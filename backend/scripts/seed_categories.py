"""One-off/idempotent seed for the 4 taxonomy categories the built-in
lib/prompts.SBL_SCENARIOS already rely on (their `category` strings must match a
Category.name exactly or CM-US-01's dropdown-restriction would lock admins out of
the categories learners already see). Safe to re-run — upserts by name.

Usage: uv run python -m scripts.seed_categories
"""

import asyncio

from lib.prisma_client import db

# icon values are keys into frontend/lib/icon-map.ts's curated lucide set.
SEED_CATEGORIES = [
    {"name": "Work", "slug": "work", "icon": "briefcase", "order": 0},
    {"name": "Social", "slug": "social", "icon": "coffee", "order": 1},
    {"name": "Travel", "slug": "travel", "icon": "plane", "order": 2},
    {"name": "Daily Life", "slug": "daily-life", "icon": "utensils", "order": 3},
]


async def main() -> None:
    await db.connect()
    try:
        for cat in SEED_CATEGORIES:
            await db.category.upsert(
                where={"name": cat["name"]},
                data={
                    "create": {**cat, "protected": True},
                    "update": {"protected": True},
                },
            )
            print(f"seeded category: {cat['name']}")
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
