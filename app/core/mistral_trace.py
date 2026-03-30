"""Timeouts et journalisation des appels API Mistral (latence, succès / échec)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger("app.mistral")


class MistralCallTimeoutError(Exception):
    """Dépassement du délai pour un appel Mistral."""

    def __init__(self, operation: str, timeout_seconds: float) -> None:
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        super().__init__(f"{operation} timeout after {timeout_seconds}s")


async def traced_mistral_call(
    operation: str,
    coro: Awaitable[T],
    timeout_seconds: float | None = None,
) -> T:
    """
    Exécute un appel async Mistral avec timeout et logs structurés.
    """
    from app.core.config import get_settings

    settings = get_settings()
    limit = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.mistral_http_timeout_seconds
    )
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=limit)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "mistral_ok operation=%s latency_ms=%.1f",
            operation,
            elapsed_ms,
        )
        return result
    except asyncio.TimeoutError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "mistral_timeout operation=%s latency_ms=%.1f limit_s=%.1f",
            operation,
            elapsed_ms,
            limit,
        )
        raise MistralCallTimeoutError(operation, limit) from e
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "mistral_error operation=%s latency_ms=%.1f",
            operation,
            elapsed_ms,
        )
        raise
