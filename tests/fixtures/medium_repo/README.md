# Medium Fixture Repo

This repository is a controlled fixture for CodeTeam retrieval and context tests.

It contains several small business modules with deliberate cross-module dependencies:

- auth token refresh
- order cancellation and export
- inventory reservations
- billing webhooks and invoice retries
- event-driven notifications
- generated and vendored code noise
- one broken experimental Python file

The fixture is intentionally small enough to audit by hand but large enough that Top 5 retrieval is meaningful.

