"""Chat API endpoint - proxies to NLP Chat Service.

This endpoint acts as a gateway to the standalone NLP Chat microservice,
which handles natural language database queries using LLM.
"""

from fastapi import APIRouter, HTTPException, status
import structlog

from app.deps import NLPChatClientDep
from app.integrations.nlp_chat import (
    NLPChatConnectionError,
    NLPChatError,
    NLPChatServiceDisabledError,
    NLPChatTimeoutError,
    NLPChatValidationError,
)
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["Chat"])
logger = structlog.get_logger(__name__)


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
- "List devices with the most violations"
- "How many fall detections happened yesterday?"

**Note:** This endpoint proxies to the NLP Chat Service microservice.
The service can be enabled/disabled via the /chat/control endpoints.
""",
    responses={
        200: {
            "description": "Successful response with answer",
            "model": ChatResponse,
        },
        400: {
            "description": "Invalid question or SQL validation failed",
        },
        502: {
            "description": "NLP Chat Service unavailable",
        },
        503: {
            "description": "NLP Chat Service is disabled",
        },
    },
)
async def chat(
    request: ChatRequest,
    nlp_client: NLPChatClientDep,
) -> ChatResponse:
    """Process a natural language question about Ruth AI data.

    Proxies the request to the NLP Chat Service microservice.
    """
    logger.info("Chat request received", question=request.question[:100])

    try:
        result = await nlp_client.ask(
            question=request.question,
            include_raw_data=request.include_raw_data,
        )

        logger.info(
            "Chat request completed",
            question=request.question[:50],
            row_count=result.get("row_count", 0),
            execution_time_ms=result.get("execution_time_ms", 0),
        )

        return ChatResponse(
            answer=result["answer"],
            question=result["question"],
            generated_sql=result.get("generated_sql"),
            raw_data=result.get("raw_data"),
            row_count=result["row_count"],
            execution_time_ms=result["execution_time_ms"],
        )

    except NLPChatServiceDisabledError:
        logger.info("NLP Chat Service is disabled")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_disabled",
                "message": "NLP Chat Service is currently disabled. Enable it via /api/v1/chat/control/enable",
                "question": request.question,
            },
        )

    except NLPChatValidationError as e:
        logger.warning(
            "Chat validation failed",
            question=request.question[:100],
            sql=e.generated_sql,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "validation_error",
                "message": str(e),
                "question": request.question,
                "generated_sql": e.generated_sql,
            },
        ) from e

    except NLPChatConnectionError as e:
        logger.error("NLP Chat Service connection failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "connection_error",
                "message": "Cannot connect to NLP Chat Service. Is it running?",
                "question": request.question,
            },
        ) from e

    except NLPChatTimeoutError as e:
        logger.error("NLP Chat Service timeout", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error": "timeout",
                "message": "NLP Chat Service request timed out. Try a simpler question.",
                "question": request.question,
            },
        ) from e

    except NLPChatError as e:
        logger.error("NLP Chat Service error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "service_error",
                "message": str(e),
                "question": request.question,
            },
        ) from e


@router.get(
    "/chat/status",
    summary="Get NLP Chat Service status",
    description="Check if NLP Chat Service is available and enabled.",
)
async def chat_status(
    nlp_client: NLPChatClientDep,
) -> dict:
    """Get NLP Chat Service status."""
    try:
        health = await nlp_client.health_check()
        is_enabled = await nlp_client.is_enabled()

        return {
            "available": health.get("status") != "unhealthy",
            "enabled": is_enabled,
            "health": health,
        }
    except Exception as e:
        return {
            "available": False,
            "enabled": False,
            "error": str(e),
        }


@router.post(
    "/chat/control/enable",
    summary="Enable NLP Chat Service",
    description="Enable the NLP Chat Service to accept requests.",
)
async def enable_chat(
    nlp_client: NLPChatClientDep,
) -> dict:
    """Enable NLP Chat Service."""
    success = await nlp_client.enable()
    if success:
        logger.info("NLP Chat Service enabled via backend API")
        return {"enabled": True, "message": "NLP Chat Service enabled"}
    else:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to enable NLP Chat Service",
        )


@router.post(
    "/chat/control/disable",
    summary="Disable NLP Chat Service",
    description="Disable the NLP Chat Service. Requests will return 503.",
)
async def disable_chat(
    nlp_client: NLPChatClientDep,
) -> dict:
    """Disable NLP Chat Service."""
    success = await nlp_client.disable()
    if success:
        logger.info("NLP Chat Service disabled via backend API")
        return {"enabled": False, "message": "NLP Chat Service disabled"}
    else:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to disable NLP Chat Service",
        )
