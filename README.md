# SAGE (Sovereign On-Premise Agentic AI Workbench)

An air-gap-capable, on-premise agentic AI workbench designed for organizations handling classified or confidential industrial data.

## Quick Start (Phase 0)

1. Make sure you have Docker and Docker Compose installed.
2. Run development environment:
   ```bash
   make dev
   ```
3. Check health endpoint:
   ```bash
   curl http://localhost:8000/health
   ```

## Development
- `make up` - Start services in background
- `make down` - Stop services
- `make migrate` - Run database migrations
- `make lint` - Run ruff linter
- `make test` - Run tests
