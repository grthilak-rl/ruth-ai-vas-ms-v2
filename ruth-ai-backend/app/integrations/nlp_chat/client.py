"""NLP Chat Service HTTP client.

Connects to the standalone NLP Chat microservice for natural language queries.
"""

from typing import Any

import httpx
import structlog

from .exceptions import (
    NLPChatConnectionError,
    NLPChatError,
    NLPChatServiceDisabledError,
    NLPChatTimeoutError,
    NLPChatValidationError,
)

logger = structlog.get_logger(__name__)


class NLPChatClient:
    """HTTP client for NLP Chat Service."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 120,
    ) -> None:
        """Initialize NLP Chat client.

        Args:
            base_url: NLP Chat Service base URL (e.g., http://ruth-ai-nlp-chat:8081)
            timeout_seconds: Request timeout (LLM calls can be slow)
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def ask(
        self,
        question: str,
        include_raw_data: bool = False,
    ) -> dict[str, Any]:
        """Ask a natural language question.

        Args:
            question: Natural language question
            include_raw_data: Include raw SQL results

        Returns:
            Response dict with answer, sql, row_count, etc.

        Raises:
            NLPChatConnectionError: Cannot connect to service
            NLPChatTimeoutError: Request timed out
            NLPChatServiceDisabledError: Service is disabled
            NLPChatValidationError: Question/SQL validation failed
            NLPChatError: Other errors
        """
        client = await self._get_client()

        try:
            response = await client.post(
                "/chat",
                json={
                    "question": question,
                    "include_raw_data": include_raw_data,
                },
            )

            if response.status_code == 503:
                raise NLPChatServiceDisabledError(
                    "NLP Chat Service is currently disabled"
                )

            if response.status_code == 400:
                # Validation error
                detail = response.json().get("detail", {})
                raise NLPChatValidationError(
                    message=detail.get("message", "Validation failed"),
                    generated_sql=detail.get("generated_sql"),
                )

            if response.status_code == 502:
                raise NLPChatError("LLM service unavailable")

            response.raise_for_status()
            return response.json()

        except httpx.ConnectError as e:
            logger.error("NLP Chat connection failed", base_url=self._base_url)
            raise NLPChatConnectionError(
                f"Cannot connect to NLP Chat Service: {e}"
            ) from e

        except httpx.TimeoutException as e:
            logger.error("NLP Chat request timed out", timeout=self._timeout)
            raise NLPChatTimeoutError(
                f"NLP Chat request timed out after {self._timeout}s"
            ) from e

        except (NLPChatServiceDisabledError, NLPChatValidationError, NLPChatError):
            raise

        except httpx.HTTPStatusError as e:
            logger.error("NLP Chat HTTP error", status_code=e.response.status_code)
            raise NLPChatError(f"NLP Chat error: {e}") from e

    async def health_check(self) -> dict[str, Any]:
        """Get NLP Chat Service health status.

        Returns:
            Health status dict with components
        """
        try:
            client = await self._get_client()
            response = await client.get("/health")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning("NLP Chat health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    async def is_healthy(self) -> bool:
        """Quick health check.

        Returns:
            True if service is healthy
        """
        try:
            client = await self._get_client()
            response = await client.get("/health/live")
            return response.status_code == 200
        except Exception:
            return False

    async def is_enabled(self) -> bool:
        """Check if NLP service is enabled.

        Returns:
            True if service is enabled
        """
        try:
            client = await self._get_client()
            response = await client.get("/control/status")
            if response.status_code == 200:
                return response.json().get("enabled", False)
            return False
        except Exception:
            return False

    async def enable(self) -> bool:
        """Enable the NLP service.

        Returns:
            True if successfully enabled
        """
        try:
            client = await self._get_client()
            response = await client.post("/control/enable")
            return response.status_code == 200
        except Exception as e:
            logger.error("Failed to enable NLP service", error=str(e))
            return False

    async def disable(self) -> bool:
        """Disable the NLP service.

        Returns:
            True if successfully disabled
        """
        try:
            client = await self._get_client()
            response = await client.post("/control/disable")
            return response.status_code == 200
        except Exception as e:
            logger.error("Failed to disable NLP service", error=str(e))
            return False
