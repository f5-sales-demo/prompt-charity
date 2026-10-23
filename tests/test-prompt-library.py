"""Regression tests for catalog roles, canonical sources and approval contracts."""

# Standard-library unittest keeps the shell test entrypoint dependency-free.
# ruff: noqa: INP001, PT009
# pylint: disable=invalid-name
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate-prompt-library.py"
spec = importlib.util.spec_from_file_location("library", SCRIPT)
library = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = self.root / "docs/en/use-cases/operations/example/index.mdx"
        self.page.parent.mkdir(parents=True)
        (self.root / "prompts").mkdir()
        self.prompt = self.root / "prompts/example.txt"
        self.prompt.write_text(
            "Work in planning mode. Use read-only investigation. Do not edit files.\n"
            "Objective: [Project]\nStop after the plan. Require explicit approval.\n"
            "After approval implement and check acceptance criteria."
        )
        (self.root / "docs/_imports").write_text(
            "prompts/example.txt -> prompts/example.txt\n"
        )
        self.page.write_text(
            "import { Code } from '@astrojs/starlight/components';\n"
            "import prompt from '../../../../_data/prompts/example.txt?raw';\n"
            '<Code code={prompt} lang="text" />\n'
            "<a href={`data:text/plain;charset=utf-8;base64,${Buffer.from(prompt, 'utf8').toString('base64')}`} download=\"example.txt\">Download</a>"
        )

    def test_complete_prompt_and_fallback_are_distinct(self):
        (self.page.parent / "fallback.mdx").write_text(
            "{/* prompt-library: fallback */}\nReference HCL"
        )
        self.assertEqual(library.validate(self.root), [])

    def test_harness_dependency_rejected(self):
        self.prompt.write_text(
            self.prompt.read_text() + "\nUse mcp__vendor__tool or /plan in Codex."
        )
        self.assertTrue(
            any("harness" in error for error in library.validate(self.root))
        )

    def test_missing_canonical_import_rejected(self):
        (self.root / "docs/_imports").write_text("")
        self.assertTrue(any("import" in error for error in library.validate(self.root)))

    def test_missing_approval_rejected(self):
        self.prompt.write_text(
            "Work in planning mode with read-only investigation [project]. Deploy now."
        )
        self.assertTrue(
            any("approval" in error for error in library.validate(self.root))
        )

    def test_unclassified_page_rejected(self):
        (self.page.parent / "starter.md").write_text("Generic starter")
        self.assertTrue(
            any("unclassified" in error for error in library.validate(self.root))
        )

    def test_broken_link_rejected(self):
        self.page.write_text(
            self.page.read_text() + "\n[Missing](/prompt-charity/en/missing/)"
        )
        self.assertTrue(
            any("broken link" in error for error in library.validate(self.root))
        )

    def test_empty_category_rejected(self):
        category = self.root / "docs/en/use-cases/security"
        category.mkdir()
        (category / "index.md").write_text("Empty category")
        self.assertTrue(
            any("empty category" in error for error in library.validate(self.root))
        )

    def test_nested_index_cannot_hide_a_starter(self):
        nested = self.page.parent / "another"
        nested.mkdir()
        (nested / "index.mdx").write_text("Unclassified starter")
        self.assertTrue(
            any("unclassified" in error for error in library.validate(self.root))
        )

    def test_download_must_derive_from_canonical(self):
        self.page.write_text(
            self.page.read_text().replace("Buffer.from(prompt,", 'Buffer.from("other",')
        )
        self.assertTrue(
            any("download" in error for error in library.validate(self.root))
        )


if __name__ == "__main__":
    unittest.main()
