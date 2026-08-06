"""Application error definitions."""


class ServiceError(Exception):
    """Base class for all service errors."""

    def __init__(self, message: str, code: str = "ERR_UNKNOWN") -> None:
        super().__init__(message)
        self.code = code


TIMEOUT_ERROR = "ERR_TIMEOUT"


class DatabaseError(ServiceError):
    """Raised when a database operation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="ERR_DB")
