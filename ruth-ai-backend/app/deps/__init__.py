"""Dependency injection modules for Ruth AI Backend."""

from app.deps.db import DBSession, ProjectScopeDep, get_db, get_project_scope
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
    "ProjectScopeDep",
    "get_project_scope",
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
