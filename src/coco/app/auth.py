"""User authentication and identity extraction.

Databricks Apps injects forwarded headers on every authenticated
request. This module reads those headers to produce a
:class:`UserIdentity` for downstream session + trace tagging.

The earlier version of this file included a JWT-decode fallback that
parsed `X-Forwarded-Access-Token` *without signature verification*.
That path has been removed — unverified JWT decoding is a dangerous
pattern to ship in an OSS reference implementation, and the current
SP-only deploy does not need it. Apps always gives us
`X-Forwarded-Email`; that is the only identity source this code
trusts in a deployed environment.

Local development falls back to the `COCO_USER_ID` env var so
`uvicorn main:app --reload` works without standing up an Apps
runtime. Tests use the same hook.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Request

logger = logging.getLogger(__name__)


@dataclass
class UserIdentity:
    """Authenticated user identity."""

    user_id: str
    access_token: str
    email: Optional[str] = None


def extract_user_identity(request: Request) -> UserIdentity:
    """Resolve the caller's identity from Databricks Apps request headers.

    Lookup order:

    1. `X-Forwarded-Email` / `X-Forwarded-Preferred-Username` /
       `X-Forwarded-User`. Apps injects these on every authenticated
       request regardless of whether `user_api_scopes` / OBO is
       configured, so this is the stable identity source.
    2. `COCO_USER_ID` env var. Stub for local development.
    """
    email = request.headers.get("x-forwarded-email") or request.headers.get("X-Forwarded-Email")
    username = request.headers.get("x-forwarded-preferred-username") or request.headers.get(
        "x-forwarded-user"
    )
    if email or username:
        user_id = email or username or ""
        return UserIdentity(
            user_id=user_id,
            access_token="apps-sp",  # opaque marker; we never use this for auth
            email=email or user_id,
        )

    stub_id = os.environ.get("COCO_USER_ID", "anonymous@example.com")
    logger.warning(
        "No Databricks Apps identity headers found on request; using stub user_id=%s. "
        "This is expected for local development only.",
        stub_id,
    )
    return UserIdentity(user_id=stub_id, access_token="stub", email=stub_id)
