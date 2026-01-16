# Ruth AI NLP Chat Service

Standalone microservice for natural language database queries using Ollama LLM.

## Overview

This service converts natural language questions into SQL queries, executes them against the Ruth AI database, and returns human-readable answers.

## Features

- Text-to-SQL using Ollama LLM
- SQL security validation (read-only, table allowlist, pattern blocking)
- Natural language response generation
- Service enable/disable control via API
- Health check endpoints

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | Ask a natural language question |
| `/health` | GET | Full health status |
| `/health/live` | GET | Liveness probe |
| `/health/ready` | GET | Readiness probe |
| `/control/enable` | POST | Enable the service |
| `/control/disable` | POST | Disable the service |
| `/control/status` | GET | Check if service is enabled |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection URL |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `OLLAMA_SQL_MODEL` | `anindya/prem1b-sql-ollama-fp16` | Model for SQL generation |
| `OLLAMA_NLG_MODEL` | `llama3.2:1b` | Model for NLG |
| `CHAT_MAX_RESULT_ROWS` | `100` | Max rows returned |
| `NLP_SERVICE_ENABLED` | `true` | Initial enabled state |

## Running

```bash
# Development
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8081 --workers 2
```

## Docker

```bash
docker build -t ruth-ai-nlp-chat .
docker run -p 8081:8081 ruth-ai-nlp-chat
```
