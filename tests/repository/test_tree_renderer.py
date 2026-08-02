import importlib
import tempfile
import unittest
from pathlib import Path

from codeteam.repository.models import FileKind, RepositoryFile, RepositorySnapshot


class DirectoryTreeRendererTests(unittest.TestCase):
    def _load_renderer_class(self) -> type:
        try:
            module = importlib.import_module("codeteam.repository.tree_renderer")
        except Exception as error:
            self.fail(f"tree_renderer module must import cleanly: {error!r}")

        renderer_class = getattr(module, "DirectoryTreeRenderer", None)
        if renderer_class is None:
            self.fail("tree_renderer must expose DirectoryTreeRenderer.")
        return renderer_class

    def test_renders_compact_directory_counts_without_losing_full_file_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = RepositorySnapshot(
                root=root,
                is_git_repo=False,
                files=[
                    RepositoryFile(
                        path="src/app.py",
                        language="python",
                        kind=FileKind.SOURCE,
                        size_bytes=10,
                    ),
                    RepositoryFile(
                        path="src/generated/client.py",
                        language="python",
                        kind=FileKind.GENERATED,
                        size_bytes=20,
                    ),
                    RepositoryFile(
                        path="tests/test_app.py",
                        language="python",
                        kind=FileKind.TEST,
                        size_bytes=30,
                    ),
                ],
            )

            renderer = self._load_renderer_class()(max_depth=1)
            rendered = renderer.render(snapshot)

            self.assertIn(f"{root.name}/ [3 files]", rendered)
            self.assertIn("src/ [2 files]", rendered)
            self.assertIn("tests/ [1 files]", rendered)
            self.assertNotIn("app.py", rendered)
            self.assertEqual(
                [file.path for file in snapshot.files],
                ["src/app.py", "src/generated/client.py", "tests/test_app.py"],
            )
