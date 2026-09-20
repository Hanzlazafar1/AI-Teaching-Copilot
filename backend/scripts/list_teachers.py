"""Utility script to count and list all registered teachers in the database.

Usage:
    cd backend
    python scripts/list_teachers.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add backend directory to sys.path so imports resolve
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import func, select

from db.models import UserModel
from db.session import get_session_factory


async def main() -> None:
    session_factory = get_session_factory()

    async with session_factory() as session:
        # 1. Total count query
        count_stmt = select(func.count(UserModel.id))
        count_res = await session.execute(count_stmt)
        total_count = count_res.scalar() or 0

        print("\n" + "=" * 70)
        print(f"  👩‍🏫 REGISTERED TEACHERS: {total_count} total")
        print("=" * 70)

        if total_count == 0:
            print("  No teachers have registered yet.")
            print("=" * 70 + "\n")
            return

        # 2. Fetch all teachers ordered by registration date
        list_stmt = select(UserModel).order_by(UserModel.created_at.desc())
        list_res = await session.execute(list_stmt)
        users = list_res.scalars().all()

        header = f"{'Email':<30} | {'Name':<20} | {'Grade':<8} | {'Registered Date'}"
        print(header)
        print("-" * len(header))

        for u in users:
            email = u.email[:28]
            name = (u.full_name or "—")[:18]
            grade = u.default_grade or "—"
            created = u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "—"
            print(f"{email:<30} | {name:<20} | {grade:<8} | {created}")

        print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
