"""Mosaic AI Gateway client for LLM calls.

Provides async client for OpenAI-compatible LLM endpoint fronted by
Mosaic AI Gateway. Every LLM call carries user identity tags.
"""
from __future__ import annotations

from coco.gateway.client import GatewayClient
from coco.gateway.errors import (
    GatewayBackendError,
    GatewayRateLimited,
    GatewaySafetyBlocked,
)

__all__ = [
    "GatewayClient",
    "GatewayRateLimited",
    "GatewaySafetyBlocked",
    "GatewayBackendError",
]
