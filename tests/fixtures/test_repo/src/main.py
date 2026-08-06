"""Application entry point."""


def create_app():
    """Create and configure the FastAPI application."""
    from src.auth.service import AuthService
    return {"app": "ready", "auth": AuthService()}
