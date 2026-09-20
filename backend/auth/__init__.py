"""Authentication and security package for Brady AI Writing Co-Pilot."""

from auth.dependencies import get_current_user, get_optional_user
from auth.security import create_access_token, decode_access_token, hash_password, verify_password

__all__ = [
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "verify_password",
    "get_current_user",
    "get_optional_user",
]
