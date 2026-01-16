"""External service integrations.

This package contains integration clients for external services:
- vas: VAS-MS-V2 Video Analytics Service integration
- ai_runtime: AI Runtime service integration
- nlp_chat: NLP Chat Service integration (separate microservice)
"""

from .ai_runtime import AIRuntimeClient
from .nlp_chat import NLPChatClient
from .vas import VASClient

__all__ = ["VASClient", "AIRuntimeClient", "NLPChatClient"]
