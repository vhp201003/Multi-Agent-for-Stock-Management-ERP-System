# Multi-Agent System

A multi-agent system for financial queries, using FastAPI, Groq API, Redis, PostgreSQL, and Qdrant.

## Setup

1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Set GROQ_API_KEY in .env
3. Run `docker-compose up -d` to start Redis, PostgreSQL, Qdrant
4. Sync dependencies: `uv sync`
5. Run app: `./scripts/run.sh`
6. Test API: `curl -X POST "http://localhost:8000/query" -d '{"query": "Lấy giá cổ phiếu Apple"}'`

## Structure
- `src/`: Source code (agents, tools, api, typing)
- `config/`: Prompts and settings
- `tests/`: Unit tests
- `docs/`: Documentation
