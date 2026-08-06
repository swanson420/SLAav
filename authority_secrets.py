"""
Secrets interface (Item 4 — credential rotation / KMS path).

Current backend: environment variables (fail-closed).
Swap get_signing_key / get_api_key_role_map to a KMS or secrets-manager
client without changing call sites.

Rotation sketch (not automated here):
  1. Set ZENDESK_AUTHORITY_SIGNING_KEY_NEXT to the new key.
  2. Dual-verify period (accept either key) — requires call-site support.
  3. Promote next → current; unset next.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Optional


class SecretsError(RuntimeError):
    pass


def get_signing_key() -> str:
    key = os.environ.get("ZENDESK_AUTHORITY_SIGNING_KEY")
    if not key:
        raise SecretsError(
            "ZENDESK_AUTHORITY_SIGNING_KEY is not set. Refusing to start "
            "without a real signing key."
        )
    return key


def get_signing_key_next() -> Optional[str]:
    """Optional next key for dual-verify rotation window."""
    return os.environ.get("ZENDESK_AUTHORITY_SIGNING_KEY_NEXT") or None


def get_api_key_role_map() -> Dict[str, str]:
    """
    Map API key → role.

    Preferred: ZENDESK_AUTHORITY_API_KEYS as JSON object
      {"key-one": "readonly", "key-two": "admin"}

    Fallback: single ZENDESK_AUTHORITY_API_KEY → role "readonly"
    (preserves prior single-key behaviour).
    """
    multi = os.environ.get("ZENDESK_AUTHORITY_API_KEYS")
    if multi:
        try:
            mapping = json.loads(multi)
        except json.JSONDecodeError as e:
            raise SecretsError(f"ZENDESK_AUTHORITY_API_KEYS is not valid JSON: {e}") from e
        if not isinstance(mapping, dict) or not mapping:
            raise SecretsError("ZENDESK_AUTHORITY_API_KEYS must be a non-empty JSON object")
        for k, v in mapping.items():
            if v not in ("ingestion", "refresh", "readonly", "admin"):
                raise SecretsError(f"Unknown role '{v}' for key fingerprint plan")
        return {str(k): str(v) for k, v in mapping.items()}

    single = os.environ.get("ZENDESK_AUTHORITY_API_KEY")
    if not single:
        raise SecretsError(
            "Neither ZENDESK_AUTHORITY_API_KEYS nor ZENDESK_AUTHORITY_API_KEY is set. "
            "Refusing to start with endpoints unauthenticated."
        )
    return {single: "readonly"}


def key_fingerprint(api_key: str) -> str:
    """Stable non-reversible id for audit rows (never store the raw key)."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]
