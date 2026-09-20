"""Authentication API routes: Registration, Login, Profile, and Preferences."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from auth.schemas import (
    TokenResponse,
    UserLoginRequest,
    UserPreferencesUpdateRequest,
    UserProfileResponse,
    UserRegisterRequest,
)
from auth.security import create_access_token, hash_password, verify_password
from db.models import UserModel
from db.repository import create_user, get_user_by_email, update_user_preferences
from db.session import get_db_session

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get(
    "/teachers/count",
    summary="Get total count of registered teachers",
)
async def get_teacher_count(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    """Return total number of registered teachers in the system."""
    from sqlalchemy import func, select
    stmt = select(func.count(UserModel.id))
    result = await session.execute(stmt)
    return {"total_registered_teachers": result.scalar() or 0}


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new teacher account",
)
async def register(
    req: UserRegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Register a new teacher with email, password, and classroom defaults."""
    existing = await get_user_by_email(session, req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    hashed_pw = hash_password(req.password)
    user = await create_user(
        session,
        email=req.email,
        hashed_password=hashed_pw,
        full_name=req.full_name,
        school_district=req.school_district,
        default_grade=req.default_grade,
        default_mode=req.default_mode,
        custom_instructions=req.custom_instructions,
    )

    access_token = create_access_token(subject=user.id)
    profile = UserProfileResponse.model_validate(user)
    return TokenResponse(access_token=access_token, user=profile)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and obtain a JWT access token",
)
async def login(
    req: UserLoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Authenticate with email and password to receive a JWT token."""
    user = await get_user_by_email(session, req.email)
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(subject=user.id)
    profile = UserProfileResponse.model_validate(user)
    return TokenResponse(access_token=access_token, user=profile)


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current teacher profile",
)
async def get_me(
    current_user: UserModel = Depends(get_current_user),
) -> UserProfileResponse:
    """Fetch profile and saved classroom defaults of the logged-in teacher."""
    return UserProfileResponse.model_validate(current_user)


@router.patch(
    "/preferences",
    response_model=UserProfileResponse,
    summary="Update teaching grade and classroom preferences",
)
async def update_preferences(
    req: UserPreferencesUpdateRequest,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> UserProfileResponse:
    """Update preferred grade level, writing mode, and classroom accommodation notes."""
    updated = await update_user_preferences(
        session,
        current_user.id,
        full_name=req.full_name,
        school_district=req.school_district,
        default_grade=req.default_grade,
        default_mode=req.default_mode,
        custom_instructions=req.custom_instructions,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found.")

    return UserProfileResponse.model_validate(updated)
