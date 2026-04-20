"""Custom exceptions for Gateway layer."""
from __future__ import annotations


class GatewayError(Exception):
    """Base class for Gateway errors."""

    pass


class GatewayRateLimited(GatewayError):
    """Gateway rate limit hit (429 Too Many Requests)."""

    def __init__(
        self,
        retry_after_seconds: int | None = None,
    ):
        self.retry_after_seconds = retry_after_seconds
        msg = "Gateway rate limited"
        if retry_after_seconds:
            msg += f"; retry after {retry_after_seconds}s"
        super().__init__(msg)


class GatewaySafetyBlocked(GatewayError):
    """Gateway blocked request due to safety filter (PHI/PII)."""

    def __init__(
        self,
        detail: str | None = None,
    ):
        self.detail = detail
        msg = "Gateway safety filter blocked request"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class GatewayBackendError(GatewayError):
    """Gateway or LLM backend returned 5xx error."""

    def __init__(
        self,
        status_code: int,
        response_text: str | None = None,
    ):
        self.status_code = status_code
        self.response_text = response_text
        msg = f"Gateway backend error: HTTP {status_code}"
        if response_text:
            msg += f" ({response_text[:100]})"
        super().__init__(msg)
