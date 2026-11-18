"""The assistant's persona follows the product brand the backend sends, and
defaults to a brand-neutral one when the fields are missing (a backend from
before product branding sends only question and include_raw_data).
"""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.chat import get_chat_service
from app.main import create_application
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService


class SpyService:
    """Stands in for ChatService behind the real /chat route."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "answer": "3",
            "question": kwargs["question"],
            "generated_sql": "SELECT 3",
            "raw_data": None,
            "row_count": 1,
            "execution_time_ms": 1,
        }


async def post_chat(body: dict) -> tuple[int, SpyService]:
    spy = SpyService()
    app = create_application()
    app.dependency_overrides[get_chat_service] = lambda: spy
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/chat", json=body)
    return r.status_code, spy


async def test_request_without_brand_fields_is_accepted_and_defaults_to_none():
    status, spy = await post_chat({"question": "How many violations?"})
    assert status == 200
    assert spy.calls[0]["assistant_name"] is None
    assert spy.calls[0]["product_name"] is None


async def test_request_with_brand_fields_passes_them_on():
    status, spy = await post_chat(
        {"question": "How many violations?", "assistant_name": "Ruth", "product_name": "Ruth AI"}
    )
    assert status == 200
    assert (spy.calls[0]["assistant_name"], spy.calls[0]["product_name"]) == ("Ruth", "Ruth AI")


def test_schema_defaults():
    r = ChatRequest(question="abc?")
    assert r.assistant_name is None and r.product_name is None


class FakeOllama:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, model: str, prompt: str, temperature: float) -> str:
        self.prompts.append(prompt)
        return " three "


def service(ollama: FakeOllama) -> ChatService:
    return ChatService(ollama_client=ollama, db=None, sql_validator=None, sql_model="s", nlg_model="n")


ROWS = [{"count": 3}]


async def test_prompt_is_brand_neutral_without_a_brand():
    ollama = FakeOllama()
    answer = await service(ollama)._generate_answer("How many?", ROWS)
    assert answer == "three"
    first = ollama.prompts[0].splitlines()[0]
    assert first == "You are a helpful assistant for a video analytics platform."
    assert "Ruth" not in ollama.prompts[0] and "Visi" not in ollama.prompts[0]


@pytest.mark.parametrize(
    "assistant, product, expected",
    [
        ("Ruth", "Ruth AI", "You are Ruth, a helpful assistant for the Ruth AI video analytics platform."),
        ("Visi", "Visics AI", "You are Visi, a helpful assistant for the Visics AI video analytics platform."),
        (None, "ACME Vision", "You are a helpful assistant for the ACME Vision video analytics platform."),
    ],
)
async def test_prompt_uses_the_brand(assistant, product, expected):
    ollama = FakeOllama()
    await service(ollama)._generate_answer("How many?", ROWS, assistant, product)
    assert ollama.prompts[0].splitlines()[0] == expected
