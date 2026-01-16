"""Async Ollama client using httpx."""

import httpx
import structlog

from .exceptions import (
    OllamaConnectionError,
    OllamaGenerationError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
)

logger = structlog.get_logger(__name__)


class OllamaClient:
    """Async HTTP client for Ollama API."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 60,
    ) -> None:
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

    async def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.0,
    ) -> str:
        """Generate text using Ollama model."""
        client = await self._get_client()

        request_body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }

        try:
            response = await client.post("/api/generate", json=request_body)

            if response.status_code == 404:
                raise OllamaModelNotFoundError(f"Model not found: {model}")

            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()

        except httpx.ConnectError as e:
            logger.error("Ollama connection failed", base_url=self._base_url, error=str(e))
            raise OllamaConnectionError(f"Cannot connect to Ollama: {e}") from e
        except httpx.TimeoutException as e:
            logger.error("Ollama request timed out", model=model, timeout=self._timeout)
            raise OllamaTimeoutError(f"Ollama request timed out: {e}") from e
        except OllamaModelNotFoundError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error("Ollama HTTP error", status_code=e.response.status_code)
            raise OllamaGenerationError(f"Ollama error: {e}") from e

    async def health_check(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.warning("Ollama health check failed", error=str(e))
            return False

    async def list_models(self) -> list[str]:
        """List available models in Ollama."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            logger.warning("Failed to list Ollama models", error=str(e))
            return []
