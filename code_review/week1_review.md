# Week 1 Code Review

[P2] Block shell/interpreter string bypasses of workspace checks — codeteam/tools/shell.py:151

`run_command` advertises a safe command runner inside the workspace, but `_validate_argv` only checks the top-level executable name and path-like argv entries. Calls such as `["sh", "-c", "cat /etc/hosts"]` pass validation because `sh` is not in `DANGEROUS_COMMANDS` and the external path is hidden inside the `-c` string; I verified this can read `/etc/hosts` while the configured workspace is a temporary directory. The same pattern can bypass the direct `rm`/`git push` checks through shell or interpreter commands, so either block shell/interpreter `-c` style execution or move to a stricter allowlist/sandbox model.

[P2] Declare Pydantic v2 or use version-compatible APIs — codeteam/tools/registry.py:22

Runtime code and tests use Pydantic v2-only APIs such as `model_validate`, `model_validate_json`, and `model_dump_json`, but the repository does not include a `pyproject.toml`, `requirements.txt`, or README setup note that pins `pydantic>=2`. In the current machine's system Python, Pydantic is 1.10.12, and `python -m unittest discover -s tests` fails 28 tests because those APIs do not exist; the untracked `.venv` has Pydantic 2.13.4 and passes. A clean checkout therefore has no objective way to recreate the passing environment, so add dependency/test-runner metadata or replace the calls with v1/v2 compatibility wrappers.

## Overall Assessment

The implementation is small and fairly coherent: agent loop state, tool registry, file tools, shell runner, pricing, events, and final-output semantics are separated cleanly enough for a personal learning project. The tests are mostly objective rather than cosmetic: they assert stop reasons, structured tool errors, symlink/path escapes, backup behavior, timeout handling, output truncation, pricing totals, and final-output semantic validation.

Verification:

- `.venv/bin/python -m unittest discover -s tests`: 83 tests passed.
- `python -m unittest discover -s tests` with system Python/Pydantic 1.10.12: 28 failures/errors from v2-only Pydantic APIs.
- `pytest -q` from the system pytest console script did not collect the package in this environment; `python -m pytest -q` collected tests but hit the same Pydantic v1 incompatibility.

Material test gaps:

- Add shell-tool tests for `sh -c`, `bash -c`, and `python -c` attempts that reference workspace-external paths or direct dangerous commands.
- Add a documented, reproducible test command tied to declared dependencies so test results are not dependent on an untracked local `.venv`.
