"""Chat API endpoint for natural language database queries."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.sql_validator import SQLValidator
from app.integrations.ollama import OllamaClient
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import (
    ChatError,
    ChatLLMError,
    ChatService,
    ChatSQLExecutionError,
    ChatSQLValidationError,
)

router = APIRouter(tags=["Chat"])
logger = structlog.get_logger(__name__)

# Global Ollama client (set during startup)
_ollama_client: OllamaClient | None = None


def set_ollama_client(client: OllamaClient) -> None:
    """Set the global Ollama client instance."""
    global _ollama_client
    _ollama_client = client


def get_ollama_client() -> OllamaClient:
    """Get the Ollama client instance."""
    if _ollama_client is None:
        raise RuntimeError("Ollama client not initialized")
    return _ollama_client


async def get_chat_service(
    db: AsyncSession = Depends(get_db_session),
) -> ChatService:
    """Dependency injection for ChatService."""
    settings = get_settings()
    ollama_client = get_ollama_client()

    sql_validator = SQLValidator(
        allowed_tables=settings.allowed_tables_list,
        max_result_rows=settings.chat_max_result_rows,
    )

    return ChatService(
        ollama_client=ollama_client,
        db=db,
        sql_validator=sql_validator,
        sql_model=settings.ollama_sql_model,
        nlg_model=settings.ollama_nlg_model,
        sql_temperature=settings.ollama_sql_temperature,
        nlg_temperature=settings.ollama_nlg_temperature,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a question about the data",
    description="""
Ask natural language questions about Ruth AI data.

The chatbot will:
1. Convert your question to SQL
2. Execute the query (read-only)
3. Return a human-readable answer

**Example questions:**
- "How many violations occurred today?"
- "Show me all active devices"
- "What is the most common event type this week?"
""",
)
async def chat(
    request: ChatRequest,
    chat_service: ChatServiceDep,
) -> ChatResponse:
    """Process a natural language question about Ruth AI data."""
    logger.info("Chat request received", question=request.question[:100])

    try:
        result = await chat_service.ask(
            question=request.question,
            include_raw_data=request.include_raw_data,
        )

        logger.info(
            "Chat request completed",
            question=request.question[:50],
            row_count=result["row_count"],
            execution_time_ms=result["execution_time_ms"],
        )

        return ChatResponse(
            answer=result["answer"],
            question=result["question"],
            generated_sql=result["generated_sql"],
            raw_data=result["raw_data"],
            row_count=result["row_count"],
            execution_time_ms=result["execution_time_ms"],
        )

    except ChatSQLValidationError as e:
        logger.warning("SQL validation failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "sql_validation_error",
                "message": str(e),
                "question": request.question,
                "generated_sql": e.generated_sql,
            },
        ) from e

    except ChatSQLExecutionError as e:
        logger.error("SQL execution failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "sql_execution_error",
                "message": "Query execution failed. Please try rephrasing your question.",
                "question": request.question,
                "generated_sql": e.generated_sql,
            },
        ) from e

    except ChatLLMError as e:
        logger.error("LLM error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "llm_error",
                "message": "AI service is currently unavailable. Please try again later.",
                "question": request.question,
            },
        ) from e

    except ChatError as e:
        logger.error("Chat error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "chat_error",
                "message": str(e),
                "question": request.question,
            },
        ) from e
