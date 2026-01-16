"""Ollama integration exceptions."""


class OllamaError(Exception):
    """Base exception for Ollama errors."""
    pass


class OllamaConnectionError(OllamaError):
    """Failed to connect to Ollama."""
    pass


class OllamaTimeoutError(OllamaError):
    """Ollama request timed out."""
    pass


class OllamaModelNotFoundError(OllamaError):
    """Requested model not found in Ollama."""
    pass


class OllamaGenerationError(OllamaError):
    """Error during generation."""
    pass
