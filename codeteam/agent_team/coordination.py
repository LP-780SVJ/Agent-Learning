from threading import RLock
from uuid import uuid4


class TeamStateCoordinator:
    """One in-process transaction domain, not a durable state store."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.runtime_id = f"team-runtime-{uuid4().hex}"
        self.transaction_seq = 0
        self.event_index = 0
        self.scheduler: object | None = None
        self.registry: object | None = None

    def event_metadata_locked(self) -> dict[str, object]:
        self.event_index += 1
        return {
            "runtime_id": self.runtime_id,
            "transaction_id": self.transaction_seq,
            "transaction_event_index": self.event_index,
        }
