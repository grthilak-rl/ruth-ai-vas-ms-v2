"""NLP Chat Service integration exceptions."""


class NLPChatError(Exception):
    """Base exception for NLP Chat Service errors."""
    pass


class NLPChatConnectionError(NLPChatError):
    """Failed to connect to NLP Chat Service."""
    pass


class NLPChatTimeoutError(NLPChatError):
    """NLP Chat Service request timed out."""
    pass


class NLPChatServiceDisabledError(NLPChatError):
    """NLP Chat Service is disabled."""
    pass


class NLPChatValidationError(NLPChatError):
    """Question validation or SQL generation failed."""

    def __init__(self, message: str, generated_sql: str | None = None):
        super().__init__(message)
        self.generated_sql = generated_sql
