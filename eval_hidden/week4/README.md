# Week4 Hidden Oracle V2

These pytest files are executed explicitly by `codeteam agent-eval`.
They are intentionally outside `tests/` so normal project pytest runs do not
collect them.

The 11 tasks all evaluate `tests/fixtures/medium_repo` from commit
`3956afc05d6c1ad2f3efaac9a510133436c0f700`. Tasks `B01`, `B02`, and `B04`
apply hash-pinned fault seeds from `evals/week4/task_seeds/`; the remaining
tasks use the archived fixture directly. A valid suite preflight requires every
hidden oracle to fail on pristine task state while the declared public
regression command passes.
