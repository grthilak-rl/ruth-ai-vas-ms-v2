"""Dependency injection modules for Ruth AI Backend."""

from app.deps.db import DBSession, get_db
from app.deps.services import (
    DeviceServiceDep,
    EvidenceServiceDep,
    EventIngestionServiceDep,
    NLPChatClientDep,
    StreamServiceDep,
    VASClientDep,
    ViolationServiceDep,
    get_device_service,
    get_evidence_service,
    get_event_ingestion_service,
    get_nlp_chat_client,
    get_nlp_chat_client_optional,
    get_stream_service,
    get_vas_client,
    get_violation_service,
    set_nlp_chat_client,
    set_vas_client,
)

__all__ = [
    # Database
    "DBSession",
    "get_db",
    # VAS Client
    "get_vas_client",
    "set_vas_client",
    "VASClientDep",
    # NLP Chat Client
    "get_nlp_chat_client",
    "get_nlp_chat_client_optional",
    "set_nlp_chat_client",
    "NLPChatClientDep",
    # Service dependencies
    "get_device_service",
    "get_stream_service",
    "get_violation_service",
    "get_evidence_service",
    "get_event_ingestion_service",
    # Type aliases
    "DeviceServiceDep",
    "StreamServiceDep",
    "ViolationServiceDep",
    "EvidenceServiceDep",
    "EventIngestionServiceDep",
]
