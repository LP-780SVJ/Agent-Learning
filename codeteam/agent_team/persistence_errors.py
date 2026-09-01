"""Durable Team state failures with explicit recovery semantics."""


class TeamStateError(Exception):
    """Base class for Team persistence failures."""


class TeamStateNotFoundError(TeamStateError):
    pass


class TeamStateAlreadyExistsError(TeamStateError):
    pass


class TeamStateCorruptedError(TeamStateError):
    pass


class TeamStateSchemaUnsupportedError(TeamStateError):
    pass


class TeamStateConflictError(TeamStateError):
    pass


class TeamStatePathError(TeamStateError):
    pass


class TeamStateRecoveryRequiredError(TeamStateError):
    def __init__(self, issues: tuple[str, ...] | list[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues))


class TeamRuntimePoisonedError(TeamStateError):
    """Raised after durable state and live state can no longer be proven aligned."""


class StaleMessageClaimError(TeamStateError):
    pass
