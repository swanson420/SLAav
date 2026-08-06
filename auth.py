"""
API key authentication dependency for FastAPI endpoints.
"""

from typing import Optional
from fastapi import Header, HTTPException

from authority_secrets import get_api_key_role_map, SecretsError


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> str:
    try:
        role_map = get_api_key_role_map()
    except SecretsError as e:
        raise HTTPException(status_code=500, detail=f"Server auth misconfigured: {e}")

    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    role = role_map.get(x_api_key)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return role
