"""Integration tests for Ruth AI Backend.

These tests validate system wiring:
- HTTP API → Service layer → Database
- Service layer → VAS client (mocked)
- Service layer → AI Runtime client (mocked)
- Error handling and idempotency across real request flows
"""
