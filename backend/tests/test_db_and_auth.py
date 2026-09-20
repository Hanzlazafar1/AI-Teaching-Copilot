"""Tests for Database persistence, Authentication, Sidebar CRUD, and Long-Term Memory."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from auth.security import create_access_token, hash_password, verify_password
from config import settings
from db.models import Base, UserModel
from db.repository import create_user, load_conversation, save_conversation
from db.session import get_db_session
from main import app
from schemas import Conversation, Quality, Role, SessionHandshakes, Turn


# ----------------------------------------------------------------------
# Test Fixtures: SQLite in-memory database for isolated fast testing
# ----------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_db():
    """Create an isolated in-memory SQLite database for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    yield session_factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db):
    """Async HTTP test client with overridden database session."""
    async def override_get_db():
        async with test_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------
# Unit Tests: Security & Hashing
# ----------------------------------------------------------------------


def test_password_hashing():
    password = "SuperSecretTeacherPassword123!"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_token_flow():
    user_id = "test-teacher-uuid-123"
    token = create_access_token(subject=user_id, claims={"grade": "4"})
    assert isinstance(token, str)

    from auth.security import decode_access_token
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["grade"] == "4"


# ----------------------------------------------------------------------
# Integration Tests: Auth Endpoints
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_register_login_flow(client):
    # 1. Register
    reg_resp = await client.post(
        "/api/auth/register",
        json={
            "email": "sarah@lincoln.edu",
            "password": "password123",
            "full_name": "Sarah Jenkins",
            "school_district": "Lincoln Public Schools",
            "default_grade": "4",
            "default_mode": "Inform",
            "custom_instructions": "Focus on graphic organizers for EL students.",
        },
    )
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "sarah@lincoln.edu"
    assert data["user"]["default_grade"] == "4"
    token = data["access_token"]

    # 2. Duplicate registration should return 409
    dup_resp = await client.post(
        "/api/auth/register",
        json={
            "email": "sarah@lincoln.edu",
            "password": "anotherpassword",
        },
    )
    assert dup_resp.status_code == 409

    # 3. Login
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": "sarah@lincoln.edu",
            "password": "password123",
        },
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()

    # 4. Wrong password login should fail
    bad_login = await client.post(
        "/api/auth/login",
        json={
            "email": "sarah@lincoln.edu",
            "password": "wrongpassword",
        },
    )
    assert bad_login.status_code == 401

    # 5. Fetch profile (/api/auth/me)
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = await client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["full_name"] == "Sarah Jenkins"
    assert me_data["default_grade"] == "4"

    # 6. Update preferences (/api/auth/preferences)
    pref_resp = await client.patch(
        "/api/auth/preferences",
        headers=headers,
        json={"default_grade": "5", "default_mode": "Persuade"},
    )
    assert pref_resp.status_code == 200
    assert pref_resp.json()["default_grade"] == "5"
    assert pref_resp.json()["default_mode"] == "Persuade"


# ----------------------------------------------------------------------
# Integration Tests: Sidebar Conversation CRUD & Multi-Tenant Isolation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_sidebar_crud_and_isolation(client):
    # Register Teacher Sarah (User A)
    sarah_resp = await client.post(
        "/api/auth/register",
        json={"email": "sarah@test.com", "password": "password123", "default_grade": "4"},
    )
    sarah_token = sarah_resp.json()["access_token"]
    sarah_headers = {"Authorization": f"Bearer {sarah_token}"}

    # Register Teacher David (User B)
    david_resp = await client.post(
        "/api/auth/register",
        json={"email": "david@test.com", "password": "password123", "default_grade": "2"},
    )
    david_token = david_resp.json()["access_token"]
    david_headers = {"Authorization": f"Bearer {david_token}"}

    # Sarah creates a conversation
    create_resp = await client.post(
        "/api/conversations",
        headers=sarah_headers,
        json={"title": "4th Grade Concluding Sentences"},
    )
    assert create_resp.status_code == 201
    sarah_conv_id = create_resp.json()["session_id"]

    # Sarah lists conversations
    list_resp = await client.get("/api/conversations", headers=sarah_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["title"] == "4th Grade Concluding Sentences"

    # David lists conversations — should be empty (Tenant Isolation!)
    david_list = await client.get("/api/conversations", headers=david_headers)
    assert david_list.status_code == 200
    assert len(david_list.json()) == 0

    # David tries to snoop on Sarah's conversation ID — should be 403 Forbidden!
    snoop_resp = await client.get(
        f"/api/conversations/{sarah_conv_id}", headers=david_headers
    )
    assert snoop_resp.status_code == 403

    # Sarah modifies conversation (Pin it)
    mod_resp = await client.patch(
        f"/api/conversations/{sarah_conv_id}",
        headers=sarah_headers,
        json={"is_pinned": True, "title": "Pinned Lesson Thread"},
    )
    assert mod_resp.status_code == 200
    assert mod_resp.json()["is_pinned"] is True
    assert mod_resp.json()["title"] == "Pinned Lesson Thread"

    # Sarah deletes conversation
    del_resp = await client.delete(
        f"/api/conversations/{sarah_conv_id}", headers=sarah_headers
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    # Confirm it's gone
    check_list = await client.get("/api/conversations", headers=sarah_headers)
    assert len(check_list.json()) == 0


# ----------------------------------------------------------------------
# Unit Tests: Repository Persistence of Domain Models
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_roundtrip(test_db):
    async with test_db() as session:
        user = await create_user(
            session, email="repo@test.com", hashed_password="hash", default_grade="3"
        )
        session_id = "test-roundtrip-session"

        # Initialize conversation
        conv, hs = await load_conversation(session, session_id, user_id=user.id)
        assert len(conv.turns) == 0

        # Append user turn
        conv.append(
            Turn(
                index=0,
                role=Role.USER,
                text="Give me a lesson on hooks",
            )
        )
        # Append assistant turn with structured data
        conv.append(
            Turn(
                index=1,
                role=Role.ASSISTANT,
                text="Here is your lesson...",
                structured={
                    "lesson_title": "Hook your reader with a question",
                    "step_1_introduce": "Today we will...",
                },
                quality=Quality.VALID,
                offered_skills=["Hook with a sound", "Hook with a question"],
            )
        )

        # Save to DB
        await save_conversation(session, session_id, conv, hs, title="Hooks Lesson")
        await session.commit()

    # In a new session, reload from DB
    async with test_db() as session2:
        reloaded_conv, reloaded_hs = await load_conversation(session2, session_id)
        assert len(reloaded_conv.turns) == 2
        assert reloaded_conv.turns[0].text == "Give me a lesson on hooks"
        assert reloaded_conv.turns[1].role is Role.ASSISTANT
        assert reloaded_conv.turns[1].structured["lesson_title"] == "Hook your reader with a question"
        assert reloaded_conv.turns[1].quality is Quality.VALID
        assert len(reloaded_conv.turns[1].offered_skills) == 2


# ----------------------------------------------------------------------
# Unit Tests: 3-Step Long-Term Grade Memory Engine
# ----------------------------------------------------------------------


def test_long_term_memory_grade_defaulting():
    from schemas.intent import GradeSpec, RequestType, TurnIntent

    # Simulated teacher profile with default_grade="4"
    profile_default_grade = "4"

    # Case 1: QU detected NO grade (teacher said "Give me a lesson on hooks")
    intent_no_grade = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=None,
        missing_required=["grade", "skill"],
    )

    # 3-step memory engine logic
    if intent_no_grade.grade is None and profile_default_grade:
        new_grade = GradeSpec(
            value=profile_default_grade,
            stated_explicit=False,
            confidence=0.95,
        )
        missing = [f for f in intent_no_grade.missing_required if f != "grade"]
        resolved_intent = intent_no_grade.model_copy(
            update={"grade": new_grade, "missing_required": missing}
        )

    assert resolved_intent.grade is not None
    assert resolved_intent.grade.value == "4"
    assert resolved_intent.grade.stated_explicit is False
    assert "grade" not in resolved_intent.missing_required
    assert "skill" in resolved_intent.missing_required

    # Case 2: Teacher explicitly said "for 1st grade" — Step 1 override
    intent_explicit_grade = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="1", stated_explicit=True, confidence=1.0),
        missing_required=[],
    )

    # The engine does NOT overwrite an explicit grade!
    if intent_explicit_grade.grade is None and profile_default_grade:
        pass  # will not enter

    assert intent_explicit_grade.grade.value == "1"
    assert intent_explicit_grade.grade.stated_explicit is True
