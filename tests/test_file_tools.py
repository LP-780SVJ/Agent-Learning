import os
import tempfile
import unittest
from pathlib import Path

from codeteam.schemas.tool_calls import ToolCall
from codeteam.tools.files import (
    FileToolConfig,
    ListFilesArgs,
    ReadFileArgs,
    SearchCodeArgs,
    WriteFileArgs,
    create_file_tools,
    list_files,
    read_file,
    search_code,
    write_file,
)
from codeteam.tools.registry import ToolRegistry


class FileToolTests(unittest.TestCase):
    def test_list_files_returns_workspace_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "src").mkdir()
            (workspace / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
            (workspace / "README.md").write_text("# Demo\n", encoding="utf-8")
            config = FileToolConfig(workspace)

            result = list_files(ListFilesArgs(), config)

            self.assertEqual(result.splitlines(), ["README.md", "src/main.py"])

    def test_read_file_reads_full_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "notes.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
            config = FileToolConfig(workspace)

            result = read_file(ReadFileArgs(path="notes.txt"), config)

            self.assertEqual(result, "one\ntwo\nthree\n")

    def test_read_file_supports_one_based_inclusive_line_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "notes.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
            config = FileToolConfig(workspace)

            result = read_file(
                ReadFileArgs(path="notes.txt", start_line=2, end_line=3),
                config,
            )

            self.assertEqual(result, "two\nthree\n")

    def test_read_file_rejects_files_over_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "large.txt").write_text("0123456789ABCDEF", encoding="utf-8")
            config = FileToolConfig(workspace, max_file_size_bytes=10)

            with self.assertRaisesRegex(ValueError, "size limit"):
                read_file(ReadFileArgs(path="large.txt"), config)

    def test_write_file_saves_old_content_before_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target = workspace / "notes.txt"
            target.write_text("old content\n", encoding="utf-8")
            config = FileToolConfig(workspace)

            result = write_file(
                WriteFileArgs(path="notes.txt", content="new content\n"),
                config,
            )

            self.assertEqual(target.read_text(encoding="utf-8"), "new content\n")
            self.assertIn("Backup saved", result)

            backup_files = [
                path
                for path in (workspace / ".codeteam" / "backups").rglob("*")
                if path.is_file()
            ]
            self.assertEqual(len(backup_files), 1)
            self.assertEqual(backup_files[0].read_text(encoding="utf-8"), "old content\n")

    def test_write_file_does_not_create_backup_for_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = FileToolConfig(workspace)

            result = write_file(
                WriteFileArgs(path="new.txt", content="new content\n"),
                config,
            )

            self.assertEqual(
                (workspace / "new.txt").read_text(encoding="utf-8"),
                "new content\n",
            )
            self.assertNotIn("Backup saved", result)
            self.assertFalse((workspace / ".codeteam" / "backups").exists())

    def test_write_file_rejects_content_over_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = FileToolConfig(workspace, max_file_size_bytes=10)

            with self.assertRaisesRegex(ValueError, "Content exceeds"):
                write_file(
                    WriteFileArgs(path="large.txt", content="0123456789ABCDEF"),
                    config,
                )

    def test_search_code_returns_path_line_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.py").write_text(
                "def main():\n    return 'needle'\n",
                encoding="utf-8",
            )
            config = FileToolConfig(workspace)

            result = search_code(SearchCodeArgs(query="needle"), config)

            self.assertEqual(result, "src/app.py:2:    return 'needle'")

    def test_relative_parent_path_cannot_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            config = FileToolConfig(workspace)

            with self.assertRaisesRegex(ValueError, "escapes workspace"):
                read_file(ReadFileArgs(path="../outside.txt"), config)

    def test_absolute_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            outside = workspace.parent / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")
            config = FileToolConfig(workspace)

            with self.assertRaisesRegex(ValueError, "Absolute paths"):
                read_file(ReadFileArgs(path=str(outside)), config)

    def test_symlink_to_outside_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            outside = Path(temp_dir) / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")
            link_path = workspace / "outside-link.txt"
            try:
                os.symlink(outside, link_path)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlink creation is unavailable: {error}")
            config = FileToolConfig(workspace)

            with self.assertRaisesRegex(ValueError, "escapes workspace"):
                read_file(ReadFileArgs(path="outside-link.txt"), config)

    def test_write_file_cannot_escape_through_symlinked_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            outside_dir = Path(temp_dir) / "outside"
            outside_dir.mkdir()
            link_path = workspace / "linked-dir"
            try:
                os.symlink(outside_dir, link_path)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlink creation is unavailable: {error}")
            config = FileToolConfig(workspace)

            with self.assertRaisesRegex(ValueError, "escapes workspace"):
                write_file(
                    WriteFileArgs(path="linked-dir/secret.txt", content="secret\n"),
                    config,
                )

            self.assertFalse((outside_dir / "secret.txt").exists())

    def test_registry_executes_registered_read_file_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "notes.txt").write_text("hello\n", encoding="utf-8")
            registry = ToolRegistry()
            for tool in create_file_tools(workspace):
                registry.register(tool)

            result = registry.execute(
                ToolCall(
                    call_id="call-read-file",
                    name="read_file",
                    arguments={"path": "notes.txt"},
                )
            )

            self.assertTrue(result.success)
            self.assertEqual(result.content, "hello\n")

    def test_registry_returns_structured_error_for_unsafe_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            registry = ToolRegistry()
            for tool in create_file_tools(workspace):
                registry.register(tool)

            result = registry.execute(
                ToolCall(
                    call_id="call-unsafe-path",
                    name="read_file",
                    arguments={"path": "../outside.txt"},
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.call_id, "call-unsafe-path")
            self.assertIn("escapes workspace", result.error or "")

    def test_registry_returns_structured_error_for_large_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "large.txt").write_text("0123456789ABCDEF", encoding="utf-8")
            registry = ToolRegistry()
            for tool in create_file_tools(workspace, max_file_size_bytes=10):
                registry.register(tool)

            result = registry.execute(
                ToolCall(
                    call_id="call-large-file",
                    name="read_file",
                    arguments={"path": "large.txt"},
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.call_id, "call-large-file")
            self.assertIn("size limit", result.error or "")

    def test_registry_returns_structured_error_for_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            outside = Path(temp_dir) / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")
            link_path = workspace / "outside-link.txt"
            try:
                os.symlink(outside, link_path)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlink creation is unavailable: {error}")

            registry = ToolRegistry()
            for tool in create_file_tools(workspace):
                registry.register(tool)

            result = registry.execute(
                ToolCall(
                    call_id="call-symlink",
                    name="read_file",
                    arguments={"path": "outside-link.txt"},
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.call_id, "call-symlink")
            self.assertIn("escapes workspace", result.error or "")


if __name__ == "__main__":
    unittest.main()
