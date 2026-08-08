# AGENTS.md

Project instructions for the medium CodeTeam fixture.

## Commands

- Run tests: `uv run pytest tests/ -q`
- Lint: `uv run ruff check src tests`
- Type check: `uv run mypy src`

## Architecture

- API modules may validate request shape, but business rules belong in service modules.
- SQL and persistence helpers belong in repository modules or `src/common/database.py`.
- Shared event names and event envelopes belong in `src/common/events.py`.
- Inventory reservation state must be updated through `src/inventory/`.
- Payment provider details must stay behind `src/billing/payment_gateway.py`.

## Restrictions

- Do not modify `src/generated/`; it is generated from schemas.
- Do not edit `vendor/` code directly.
- Database migrations require explicit approval.
- New domain events must be documented in `docs/`.

