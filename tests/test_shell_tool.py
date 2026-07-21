import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from codeteam.schemas.tool_calls import ToolCall
from codeteam.tools.registry import ToolRegistry
from codeteam.tools.shell import (
    RunCommandArgs,
    ShellToolConfig,
    create_shell_tool,
    run_command,
)


class ShellToolTests(unittest.TestCase):
    def test_run_command_captures_stdout_and_stderr_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ShellToolConfig(Path(temp_dir))

            payload = self._run_json(
                RunCommandArgs(
                    argv=[
                        sys.executable,
                        "-c",
                        "import sys; sys.stdout.write('out'); sys.stderr.write('err')",
                    ],
                ),
                config,
            )

            self.assertEqual(payload["stdout"], "out")
            self.assertEqual(payload["stderr"], "err")
            self.assertEqual(payload["exit_code"], 0)
            self.assertFalse(payload["timed_out"])

    def test_nonzero_exit_code_does_not_crash_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ToolRegistry()
            registry.register(create_shell_tool(Path(temp_dir)))

            result = registry.execute(
                ToolCall(
                    call_id="call-nonzero",
                    name="run_command",
                    arguments={
                        "argv": [
                            sys.executable,
                            "-c",
                            "import sys; sys.stderr.write('failed'); sys.exit(2)",
                        ],
                    },
                )
            )

            payload = json.loads(result.content)
            self.assertTrue(result.success)
            self.assertEqual(payload["exit_code"], 2)
            self.assertEqual(payload["stderr"], "failed")
            self.assertFalse(payload["timed_out"])

    def test_timeout_kills_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ShellToolConfig(Path(temp_dir))

            started_at = time.monotonic()
            payload = self._run_json(
                RunCommandArgs(
                    argv=[
                        sys.executable,
                        "-c",
                        "import time; time.sleep(5)",
                    ],
                    timeout_seconds=0.2,
                ),
                config,
            )
            elapsed = time.monotonic() - started_at

            self.assertTrue(payload["timed_out"])
            self.assertIsNone(payload["exit_code"])
            self.assertLess(elapsed, 2.0)

    def test_rejects_sudo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ShellToolConfig(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "Dangerous command"):
                run_command(RunCommandArgs(argv=["sudo", "ls"]), config)

    def test_rejects_git_push(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ShellToolConfig(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "git push"):
                run_command(RunCommandArgs(argv=["git", "-C", ".", "push"]), config)

    def test_rejects_cwd_outside_workspace_through_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            registry = ToolRegistry()
            registry.register(create_shell_tool(workspace))

            result = registry.execute(
                ToolCall(
                    call_id="call-bad-cwd",
                    name="run_command",
                    arguments={
                        "argv": [sys.executable, "-c", "print('ok')"],
                        "cwd": "../outside",
                    },
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.call_id, "call-bad-cwd")
            self.assertIn("cwd escapes workspace", result.error or "")

    def test_truncates_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ShellToolConfig(Path(temp_dir))

            payload = self._run_json(
                RunCommandArgs(
                    argv=[
                        sys.executable,
                        "-c",
                        "import sys; sys.stdout.write('x'*20); sys.stderr.write('y'*20)",
                    ],
                    max_output_bytes=5,
                ),
                config,
            )

            self.assertEqual(payload["stdout"], "xxxxx")
            self.assertEqual(payload["stderr"], "yyyyy")
            self.assertTrue(payload["stdout_truncated"])
            self.assertTrue(payload["stderr_truncated"])

    def test_rejects_env_outside_whitelist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ShellToolConfig(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "Environment variable"):
                run_command(
                    RunCommandArgs(
                        argv=[sys.executable, "-c", "print('ok')"],
                        env={"SECRET_TOKEN": "secret"},
                    ),
                    config,
                )

    def test_accepts_allowed_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ShellToolConfig(Path(temp_dir))

            payload = self._run_json(
                RunCommandArgs(
                    argv=[
                        sys.executable,
                        "-c",
                        "import os; print(os.getenv('PYTHONUNBUFFERED'))",
                    ],
                    env={"PYTHONUNBUFFERED": "1"},
                ),
                config,
            )

            self.assertEqual(payload["stdout"], "1\n")

    def test_rejects_path_argument_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            config = ShellToolConfig(workspace)

            with self.assertRaisesRegex(ValueError, "Path argument escapes workspace"):
                run_command(
                    RunCommandArgs(argv=[sys.executable, "../outside.py"]),
                    config,
                )

    def test_rejects_symlink_path_argument_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            outside = Path(temp_dir) / "outside.py"
            outside.write_text("print('secret')\n", encoding="utf-8")
            link_path = workspace / "outside-link.py"
            try:
                os.symlink(outside, link_path)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlink creation is unavailable: {error}")
            config = ShellToolConfig(workspace)

            with self.assertRaisesRegex(ValueError, "Path argument escapes workspace"):
                run_command(
                    RunCommandArgs(argv=[sys.executable, "outside-link.py"]),
                    config,
                )

    def test_registry_executes_run_command_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ToolRegistry()
            registry.register(create_shell_tool(Path(temp_dir)))

            result = registry.execute(
                ToolCall(
                    call_id="call-run",
                    name="run_command",
                    arguments={
                        "argv": [sys.executable, "-c", "print('hello')"],
                    },
                )
            )

            payload = json.loads(result.content)
            self.assertTrue(result.success)
            self.assertEqual(payload["stdout"], "hello\n")
            self.assertEqual(payload["stderr"], "")

    def _run_json(
        self,
        args: RunCommandArgs,
        config: ShellToolConfig,
    ) -> dict[str, object]:
        return json.loads(run_command(args, config))


if __name__ == "__main__":
    unittest.main()
