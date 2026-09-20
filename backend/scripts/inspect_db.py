"""Inspect the database contents: registered teachers, conversations, and turns.

Usage:
    cd backend
    ..\\.venv\\Scripts\\python.exe scripts/inspect_db.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import settings
from db.models import ConversationModel, TurnModel, UserModel
from db.session import get_engine, get_session_factory


async def inspect_database() -> None:
    engine = get_engine()
    session_factory = get_session_factory(engine)

    print("=" * 80)
    print(f"DATABASE INSPECTION: {settings.database_url}")
    print("=" * 80)

    try:
        async with session_factory() as session:
            # 1. Teachers / Users
            user_result = await session.execute(select(UserModel).order_by(UserModel.created_at))
            users = user_result.scalars().all()
            print(f"\n👩‍🏫 REGISTERED TEACHERS ({len(users)} found):")
            print("-" * 80)
            if not users:
                print("  No registered teachers found yet.")
            for u in users:
                print(f"  • ID: {u.id}")
                print(f"    Email: {u.email} | Name: {u.full_name or 'N/A'}")
                print(f"    Grade: {u.default_grade or 'None'} | Mode: {u.default_mode or 'None'} | Created: {u.created_at}")

            # 2. Conversations & Turns
            conv_result = await session.execute(
                select(ConversationModel)
                .options(selectinload(ConversationModel.turns))
                .order_by(ConversationModel.created_at.desc())
            )
            convs = conv_result.scalars().all()
            print(f"\n💬 CONVERSATION THREADS ({len(convs)} found):")
            print("-" * 80)
            if not convs:
                print("  No conversations recorded yet.")

            for i, c in enumerate(convs, 1):
                print(f"\n[{i}] Thread ID: {c.id}")
                print(f"    Title: {c.title or '(Untitled)'}")
                print(f"    Teacher (User ID): {c.user_id or 'Guest'}")
                print(f"    Pinned: {c.is_pinned} | Created: {c.created_at} | Updated: {c.updated_at}")
                if c.handshakes:
                    print(f"    Handshakes/State: {json.dumps(c.handshakes)}")

                turns = sorted(c.turns, key=lambda t: t.turn_index)
                print(f"    Turns Count: {len(turns)}")
                for t in turns:
                    role_icon = "👤 User" if t.role == "user" else "🤖 Assistant"
                    quality_badge = f" [Quality: {t.quality}]" if t.quality else ""
                    print(f"      Turn #{t.turn_index} ({role_icon}){quality_badge}:")
                    # Truncate preview of long messages
                    preview = (t.text[:150] + "...") if len(t.text) > 150 else t.text
                    print(f"        Message: {preview}")
                    if t.lesson_title:
                        print(f"        Lesson Title: {t.lesson_title}")
                    if t.structured:
                        print(f"        Structured Payload: [JSON with keys: {list(t.structured.keys())}]")
                    if t.grounding:
                        print(f"        Grounding: {len(t.grounding)} curriculum excerpt(s) used")

    except Exception as e:
        print(f"\n❌ Error connecting to database ({settings.database_url}):\n   {type(e).__name__}: {e}")
        print("\nNote: If using Docker PostgreSQL, ensure the container is running: `docker compose up -d`")
        print("      If using SQLite for local development, set DATABASE_URL=sqlite+aiosqlite:///copilot.db in .env")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(inspect_database())
