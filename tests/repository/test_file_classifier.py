import unittest

from codeteam.repository.file_classifier import FileClassifier
from codeteam.repository.language_detector import LanguageDetector
from codeteam.repository.models import FileKind


class FileClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = FileClassifier()
        self.language_detector = LanguageDetector()

    def test_generated_directory_is_marked_generated(self) -> None:
        self.assertEqual(
            self.classifier.classify("generated/client.py"),
            FileKind.GENERATED,
        )

    def test_test_python_file_keeps_language_separate_from_role(self) -> None:
        path = "tests/test_scanner.py"

        self.assertEqual(self.classifier.classify(path), FileKind.TEST)
        self.assertEqual(self.language_detector.detect(path), "python")

    def test_agents_file_is_instruction_not_documentation(self) -> None:
        self.assertEqual(
            self.classifier.classify("AGENTS.md"),
            FileKind.INSTRUCTION,
        )

    def test_node_modules_file_is_marked_vendored_for_folding_or_ignoring(self) -> None:
        self.assertEqual(
            self.classifier.classify("node_modules/package/index.js"),
            FileKind.VENDORED,
        )

    def test_binary_extension_is_marked_binary(self) -> None:
        self.assertEqual(
            self.classifier.classify("bin/tool.exe"),
            FileKind.BINARY,
        )
