# System Architecture

Multi-agent system with:
- OrchestratorAgent: Analyzes intent and coordinates tasks.
- SQLAgent: Generates and executes PostgreSQL queries.
- ChatAgent: Summarizes financial reports using Groq API.
- Redis Pub/Sub: Inter-agent communication.
- PostgreSQL/Qdrant: Data storage and retrieval.
