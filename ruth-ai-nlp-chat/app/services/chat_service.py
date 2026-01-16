"""NLP Chat Service for natural language database queries.

Converts natural language questions into SQL queries using Ollama LLM,
executes them against PostgreSQL, and returns human-readable answers.
"""

import re
import time
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sql_validator import SQLValidator
from app.integrations.ollama import OllamaClient
from app.integrations.ollama.exceptions import OllamaError

logger = structlog.get_logger(__name__)


class ChatError(Exception):
    """Base exception for chat service errors."""
    pass


class ChatSQLValidationError(ChatError):
    """Generated SQL failed validation."""

    def __init__(self, message: str, generated_sql: str | None = None):
        super().__init__(message)
        self.generated_sql = generated_sql


class ChatSQLExecutionError(ChatError):
    """SQL execution failed."""

    def __init__(self, message: str, generated_sql: str | None = None):
        super().__init__(message)
        self.generated_sql = generated_sql


class ChatLLMError(ChatError):
    """LLM interaction failed."""
    pass


class ChatService:
    """Service for natural language database queries."""

    # Ruth AI database schema description for LLM context
    SCHEMA_DESCRIPTION = """
Database Schema for Ruth AI Video Analytics Platform:

Table `devices` has columns:
- id (UUID, primary key) - Ruth AI internal device ID
- vas_device_id (VARCHAR) - External VAS device identifier
- name (VARCHAR) - Device display name
- description (TEXT, nullable) - Device description
- location (VARCHAR, nullable) - Physical location
- is_active (BOOLEAN) - Whether device is active
- last_synced_at (TIMESTAMP, nullable) - Last sync timestamp
- created_at (TIMESTAMP) - Record creation time
- updated_at (TIMESTAMP) - Record update time

Table `stream_sessions` has columns:
- id (UUID, primary key) - Session ID
- device_id (UUID, foreign key to devices.id) - Associated device
- vas_stream_id (VARCHAR, nullable) - VAS stream identifier
- model_id (VARCHAR) - AI model used (e.g., 'fall_detection')
- model_version (VARCHAR, nullable) - Model version
- inference_fps (INTEGER) - Frames per second for inference
- confidence_threshold (FLOAT) - Confidence threshold
- state (ENUM: 'live', 'stopped', 'starting', 'stopping', 'error') - Stream state
- started_at (TIMESTAMP, nullable) - Session start time
- stopped_at (TIMESTAMP, nullable) - Session stop time
- error_message (VARCHAR, nullable) - Error details if state is 'error'
- frames_processed (INTEGER) - Total frames processed
- events_count (INTEGER) - Events detected
- violations_count (INTEGER) - Violations created
- created_at (TIMESTAMP) - Record creation time
- updated_at (TIMESTAMP) - Record update time

Table `events` has columns:
- id (UUID, primary key) - Event ID
- device_id (UUID, foreign key to devices.id) - Source device
- stream_session_id (UUID, nullable, foreign key to stream_sessions.id) - Associated session
- violation_id (UUID, nullable, foreign key to violations.id) - Linked violation
- event_type (ENUM: 'fall_detected', 'no_fall', 'person_detected', 'unknown') - Detection type
- confidence (FLOAT) - Model confidence score (0.0 to 1.0)
- timestamp (TIMESTAMP) - When event occurred
- model_id (VARCHAR) - AI model that detected event
- model_version (VARCHAR) - Model version
- bounding_boxes (JSONB, nullable) - Detected object coordinates
- frame_id (VARCHAR, nullable) - Frame reference
- inference_time_ms (INTEGER, nullable) - Processing time
- created_at (TIMESTAMP) - Record creation time
- updated_at (TIMESTAMP) - Record update time

Table `violations` has columns:
- id (UUID, primary key) - Violation ID
- device_id (UUID, foreign key to devices.id) - Source device
- stream_session_id (UUID, nullable, foreign key to stream_sessions.id) - Associated session
- type (ENUM: 'fall_detected') - Violation type
- status (ENUM: 'open', 'reviewed', 'dismissed', 'resolved') - Lifecycle status
- confidence (FLOAT) - Confidence score
- timestamp (TIMESTAMP) - When violation was detected
- camera_name (VARCHAR) - Denormalized camera name
- model_id (VARCHAR) - AI model that detected
- model_version (VARCHAR) - Model version
- bounding_boxes (JSONB, nullable) - Detection coordinates
- reviewed_by (VARCHAR, nullable) - Reviewer username
- reviewed_at (TIMESTAMP, nullable) - Review timestamp
- resolution_notes (TEXT, nullable) - Operator notes
- created_at (TIMESTAMP) - Record creation time
- updated_at (TIMESTAMP) - Record update time

Table `evidence` has columns:
- id (UUID, primary key) - Evidence ID
- violation_id (UUID, foreign key to violations.id) - Linked violation
- evidence_type (ENUM: 'snapshot', 'bookmark') - Type of evidence
- status (ENUM: 'pending', 'processing', 'ready', 'failed') - Processing status
- vas_snapshot_id (VARCHAR, nullable) - VAS snapshot reference
- vas_bookmark_id (VARCHAR, nullable) - VAS bookmark reference
- bookmark_duration_seconds (INTEGER, nullable) - Video clip duration
- requested_at (TIMESTAMP) - When evidence was requested
- ready_at (TIMESTAMP, nullable) - When evidence became ready
- error_message (VARCHAR, nullable) - Error details if failed
- retry_count (INTEGER) - Number of retries
- last_retry_at (TIMESTAMP, nullable) - Last retry time
- created_at (TIMESTAMP) - Record creation time
- updated_at (TIMESTAMP) - Record update time
"""

    def __init__(
        self,
        ollama_client: OllamaClient,
        db: AsyncSession,
        sql_validator: SQLValidator,
        sql_model: str,
        nlg_model: str,
        sql_temperature: float = 0.0,
        nlg_temperature: float = 0.3,
    ) -> None:
        self._ollama = ollama_client
        self._db = db
        self._validator = sql_validator
        self._sql_model = sql_model
        self._nlg_model = nlg_model
        self._sql_temp = sql_temperature
        self._nlg_temp = nlg_temperature

    async def ask(
        self,
        question: str,
        include_raw_data: bool = False,
    ) -> dict[str, Any]:
        """Process a natural language question."""
        start_time = time.time()

        # 1. Preprocess question for date handling
        processed_question, date_hint = self._preprocess_question(question)

        # 2. Generate SQL
        try:
            sql = await self._generate_sql(processed_question, date_hint)
        except OllamaError as e:
            raise ChatLLMError(f"Failed to generate SQL: {e}") from e

        logger.info("Generated SQL", question=question[:100], sql=sql[:200])

        # 3. Validate SQL
        validation = self._validator.validate(sql)
        if not validation.is_valid:
            raise ChatSQLValidationError(
                f"Invalid SQL: {validation.error}",
                generated_sql=sql,
            )

        safe_sql = validation.sanitized_sql or sql

        # 4. Execute SQL
        try:
            results = await self._execute_sql(safe_sql)
        except Exception as e:
            logger.error("SQL execution failed", sql=safe_sql, error=str(e))
            raise ChatSQLExecutionError(
                f"Query execution failed: {e}",
                generated_sql=safe_sql,
            ) from e

        # 5. Generate natural language answer
        try:
            answer = await self._generate_answer(question, results)
        except OllamaError as e:
            logger.warning("NLG failed, using fallback", error=str(e))
            answer = self._fallback_answer(results)

        execution_time_ms = int((time.time() - start_time) * 1000)

        return {
            "answer": answer,
            "question": question,
            "generated_sql": safe_sql,
            "raw_data": results if include_raw_data else None,
            "row_count": len(results),
            "execution_time_ms": execution_time_ms,
        }

    def _preprocess_question(self, question: str) -> tuple[str, str]:
        """Extract date references from question."""
        q_lower = question.lower().strip()
        now = datetime.now()
        date_hint = ""

        if "today" in q_lower:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=23, minute=59, second=59, microsecond=0)
            date_hint = f"Use timestamp BETWEEN '{start}' AND '{end}' for date filter."

        elif "yesterday" in q_lower:
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59, microsecond=0)
            date_hint = f"Use timestamp BETWEEN '{start}' AND '{end}' for date filter."

        elif "this week" in q_lower:
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            date_hint = f"Use timestamp >= '{start}' for date filter."

        elif "this month" in q_lower:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            date_hint = f"Use timestamp >= '{start}' for date filter."

        elif "last week" in q_lower:
            start = now - timedelta(days=now.weekday() + 7)
            end = now - timedelta(days=now.weekday() + 1)
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = end.replace(hour=23, minute=59, second=59, microsecond=0)
            date_hint = f"Use timestamp BETWEEN '{start}' AND '{end}' for date filter."

        elif "last month" in q_lower:
            first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_end = first_this_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            date_hint = f"Use timestamp BETWEEN '{last_month_start}' AND '{last_month_end}' for date filter."

        else:
            date_match = re.search(
                r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(\d{4}))?",
                q_lower,
            )
            if date_match:
                day, month_str, year_str = date_match.groups()
                try:
                    month = datetime.strptime(month_str, "%B").month
                    year = int(year_str) if year_str else now.year
                    start = datetime(year, month, int(day), 0, 0, 0)
                    end = datetime(year, month, int(day), 23, 59, 59)
                    date_hint = f"Use timestamp BETWEEN '{start}' AND '{end}' for date filter."
                except ValueError:
                    pass

        return question, date_hint

    async def _generate_sql(self, question: str, date_hint: str) -> str:
        """Generate SQL from natural language question."""
        prompt = f"""Generate a PostgreSQL SELECT query for this question.

Schema:
- violations: id, device_id, type, status, confidence, timestamp, camera_name
- events: id, device_id, event_type, confidence, timestamp
- devices: id, vas_device_id, name, description, location, is_active
- stream_sessions: id, device_id, model_id, state, started_at, stopped_at

Examples:
Q: How many violations are there?
A: SELECT COUNT(*) FROM violations

Q: How many devices are there?
A: SELECT COUNT(*) FROM devices

Q: How many events are there?
A: SELECT COUNT(*) FROM events

Q: List all violations
A: SELECT * FROM violations

Q: Show open violations
A: SELECT * FROM violations WHERE status = 'open'

Q: "{question}"
A: """

        sql = await self._ollama.generate(
            model=self._sql_model,
            prompt=prompt,
            temperature=self._sql_temp,
        )

        # Clean up response
        sql = sql.strip()
        if "```" in sql:
            parts = sql.split("```")
            for part in parts:
                part_stripped = part.strip()
                if part_stripped.upper().startswith("SELECT"):
                    sql = part_stripped
                    break
                elif part_stripped.lower().startswith("sql"):
                    sql = part_stripped[3:].strip()
                    break

        sql = sql.rstrip(";")
        return sql

    async def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        """Execute SQL and return results as list of dicts."""
        result = await self._db.execute(text(sql))
        rows = result.fetchall()

        if not rows:
            return []

        columns = result.keys()
        return [dict(zip(columns, row)) for row in rows]

    async def _generate_answer(self, question: str, results: list[dict[str, Any]]) -> str:
        """Generate natural language answer from SQL results."""
        if not results:
            return "I couldn't find any records matching your query."

        rows_text = "\n".join(
            [", ".join(f"{k}: {v}" for k, v in row.items()) for row in results[:20]]
        )

        if len(results) > 20:
            rows_text += f"\n... and {len(results) - 20} more rows"

        prompt = f"""You are Ruth, a helpful assistant for the Ruth AI Video Analytics Platform.
The user asked: "{question}"
The SQL query returned these results:
{rows_text}

Write a **short, direct answer** (1-3 sentences max).
Be clear and concise. Do not add extra commentary or questions.
If showing counts or statistics, be precise with numbers.
"""

        answer = await self._ollama.generate(
            model=self._nlg_model,
            prompt=prompt,
            temperature=self._nlg_temp,
        )

        return answer.strip()

    def _fallback_answer(self, results: list[dict[str, Any]]) -> str:
        """Generate basic answer when NLG fails."""
        if not results:
            return "No results found."

        count = len(results)
        if count == 1:
            row = results[0]
            formatted = ", ".join(f"{k}: {v}" for k, v in row.items())
            return f"Found 1 record: {formatted}"
        return f"Found {count} records."
