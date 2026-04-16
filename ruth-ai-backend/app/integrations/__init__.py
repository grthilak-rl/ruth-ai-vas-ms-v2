"""External service integrations.

This package contains integration clients for external services:
- vas: VAS-MS-V2 Video Analytics Service integration
- unified_runtime: Unified AI Runtime integration
- nlp_chat: NLP Chat Service integration (separate microservice)
"""

from .nlp_chat import NLPChatClient
from .vas import VASClient

__all__ = ["VASClient", "NLPChatClient"]
