"""Pydantic schemas for authentication and teacher profile management."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Teacher registration payload."""

    email: EmailStr
    password: str = Field(min_length=6, description="Password (at least 6 characters)")
    full_name: Optional[str] = None
    school_district: Optional[str] = None
    default_grade: Optional[str] = Field(
        None, description="Preferred teaching grade (e.g., '4', 'K-2')"
    )
    default_mode: Optional[str] = Field(
        None, description="Preferred writing mode (e.g., 'Inform', 'Opinion')"
    )
    custom_instructions: Optional[str] = Field(
        None, description="Classroom notes or student accommodation guidelines"
    )


class UserLoginRequest(BaseModel):
    """Teacher login credentials."""

    email: EmailStr
    password: str


class UserProfileResponse(BaseModel):
    """Public profile of an authenticated teacher."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: Optional[str] = None
    school_district: Optional[str] = None
    default_grade: Optional[str] = None
    default_mode: Optional[str] = None
    custom_instructions: Optional[str] = None
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT access token response."""

    access_token: str
    token_type: str = "bearer"
    user: UserProfileResponse


class UserPreferencesUpdateRequest(BaseModel):
    """Teacher preferences update payload."""

    full_name: Optional[str] = None
    school_district: Optional[str] = None
    default_grade: Optional[str] = None
    default_mode: Optional[str] = None
    custom_instructions: Optional[str] = None
