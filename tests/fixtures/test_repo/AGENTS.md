# AGENTS.md

Project instructions for AI agents.

## Architecture

- HTTP routes are defined in `src/auth/api.py`.
- Business logic belongs in `src/auth/service.py` and `src/orders/`.
- Database access must use `src/common/database.py` helpers.
- API handlers must not execute SQL directly.

## Setup

- Install dependencies with `uv sync`.
- Do not use `pip install` directly.

## Testing

- Run tests: `uv run pytest tests/ -q`
- Lint: `uv run ruff check src tests`
- Type check: `uv run mypy src`

## Restrictions

- Do not modify `src/generated/` — it is auto-generated.
- Database migrations require explicit approval.
- Do not push commits directly to the main branch.
