"""The new backend against the nlp-chat that predates product branding.

The backend now sends ``assistant_name`` and ``product_name`` with every
chat question. An nlp-chat built before that change must ignore the two
fields, not reject them (422), so the backend can be deployed first.

The "old nlp-chat" below is a verbatim copy of the pre-change request
schema (ruth-ai-nlp-chat/app/schemas/chat.py: ChatRequest) and of how its
route called the service (question and include_raw_data only). The request
runs through the real backend route (/api/v1/chat) and the real
NLPChatClient, over ASGI.
"""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from app.deps.db import get_db
from app.deps.services import get_nlp_chat_client
from app.integrations.nlp_chat.client import NLPChatClient
from app.main import create_application
from app.services import product_branding as pb

# --- nlp-chat before product branding (verbatim request schema) ----------


class OldChatRequest(BaseModel):
    """Request schema for POST /chat."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Natural language question about the data",
        examples=[
            "How many violations occurred today?",
            "Show me all active devices",
            "What is the most common event type?",
        ],
    )
    include_raw_data: bool = Field(
        default=False,
        description="Include raw SQL results in response",
    )


def old_nlp_chat(received: list) -> FastAPI:
    app = FastAPI()

    @app.post("/chat")
    async def chat(request: OldChatRequest):
        # The old route passed exactly these two to ChatService.ask.
        received.append(request)
        return {
            "answer": "There are 3 open violations.",
            "question": request.question,
            "generated_sql": None,
            "raw_data": None,
            "row_count": 3,
            "execution_time_ms": 12,
        }

    return app


# --- fixtures ------------------------------------------------------------


class FakeDB:
    async def execute(self, _stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))


@pytest.fixture(autouse=True)
def _fresh_brand_cache():
    pb.clear_cache()
    yield
    pb.clear_cache()


def client_into(app: FastAPI, sent: list) -> NLPChatClient:
    """The real NLPChatClient, its HTTP going to ``app`` over ASGI."""
    nlp = NLPChatClient(base_url="http://nlp-chat")

    async def record(request: httpx.Request):
        sent.append(request)

    nlp._client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://nlp-chat",
        event_hooks={"request": [record]},
    )
    return nlp


async def test_new_backend_works_with_the_pre_branding_nlp_chat():
    received: list[OldChatRequest] = []
    sent: list[httpx.Request] = []
    nlp = client_into(old_nlp_chat(received), sent)

    backend = create_application()
    backend.dependency_overrides[get_db] = lambda: FakeDB()
    backend.dependency_overrides[get_nlp_chat_client] = lambda: nlp
    async with AsyncClient(transport=ASGITransport(app=backend), base_url="http://test") as c:
        r = await c.post("/api/v1/chat", json={"question": "How many open violations?"})

    # Answered, not rejected.
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "There are 3 open violations."

    # The backend did send the brand (the seeded Visics default)...
    import json

    body = json.loads(sent[0].content)
    assert body["assistant_name"] == "Visi"
    assert body["product_name"] == "Visics AI"
    # ...and the old service simply ignored it.
    assert len(received) == 1
    assert received[0].model_dump() == {"question": "How many open violations?", "include_raw_data": False}
    assert not hasattr(received[0], "assistant_name")


def test_old_schema_ignores_rather_than_forbids_unknown_fields():
    """The reason it works: pydantic's default (extra='ignore'), which the
    old ChatRequest never overrode."""
    assert OldChatRequest.model_config.get("extra") in (None, "ignore")
    parsed = OldChatRequest.model_validate(
        {"question": "abc?", "assistant_name": "Ruth", "product_name": "Ruth AI"}
    )
    assert parsed.model_dump() == {"question": "abc?", "include_raw_data": False}
