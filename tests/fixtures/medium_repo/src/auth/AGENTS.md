# Auth Module Rules

- Token refresh tests live in `tests/auth/test_refresh_flow.py`.
- Auth API handlers must map token errors to API responses.
- Do not let repository errors leak raw database messages to callers.

