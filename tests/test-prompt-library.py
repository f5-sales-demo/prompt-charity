"""Regression tests for flat case roles, canonical sources and approval contracts."""

# Standard-library unittest keeps the shell test entrypoint dependency-free.
# ruff: noqa: INP001, PT009
# pylint: disable=invalid-name
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate-prompt-library.py"
spec = importlib.util.spec_from_file_location("library", SCRIPT)
assert spec is not None
assert spec.loader is not None
library = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = self.root / "docs/en/use-cases/example.mdx"
        self.page.parent.mkdir(parents=True)
        (self.root / "prompts").mkdir()
        self.prompt = self.root / "prompts/example.txt"
        self.prompt.write_text(
            "Objective: [Project]\nUse native planning and read-only discovery.\n"
            "Present infrastructure scope and cost for approval.\n"
            "After approval implement and check acceptance criteria."
        )
        (self.root / "docs/_imports").write_text(
            "prompts/example.txt -> prompts/example.txt\n"
        )
        (self.root / "docs/en/index.mdx").write_text(
            '<LinkCard title="Example" href="/prompt-charity/en/use-cases/example/" />'
        )
        self.page.write_text(
            "---\ntitle: Example\n---\n"
            "import { Code } from '@astrojs/starlight/components';\n"
            "import prompt from '../../_data/prompts/example.txt?raw';\n"
            '<Code code={prompt} lang="text" />\n'
            "<a href={`data:text/plain;charset=utf-8;base64,${Buffer.from(prompt, 'utf8').toString('base64')}`} download=\"example.txt\">Download</a>"
        )

    def test_complete_prompt_and_fallback_are_distinct(self):
        support = self.page.with_suffix("")
        support.mkdir()
        (support / "fallback.mdx").write_text(
            "---\ntitle: Fallback\nsidebar:\n  hidden: true\n---\n"
            "export const promptLibraryRole = 'fallback';\nReference HCL"
        )
        self.assertEqual(library.validate(self.root), [])

    def test_declared_supporting_index_is_valid(self):
        support = self.page.with_suffix("")
        support.mkdir()
        (support / "index.mdx").write_text(
            "---\nsidebar:\n  hidden: true\n---\n"
            "export const promptLibraryRole = 'reference';"
        )
        self.assertEqual(library.validate(self.root), [])

    def test_multiple_peer_cases_have_one_card_each(self):
        peer = self.page.with_name("second.mdx")
        peer.write_text(self.page.read_text())
        home = self.root / "docs/en/index.mdx"
        home.write_text(
            home.read_text()
            + '<LinkCard href="/prompt-charity/en/use-cases/second/" />'
        )
        self.assertEqual(library.validate(self.root), [])

    def test_missing_read_only_discovery_rejected(self):
        self.prompt.write_text(self.prompt.read_text().replace("read-only", "live"))
        self.assertTrue(any("read-only" in e for e in library.validate(self.root)))

    def test_missing_acceptance_criteria_rejected(self):
        self.prompt.write_text(
            self.prompt.read_text().replace("acceptance criteria", "results")
        )
        self.assertTrue(
            any("acceptance criteria" in e for e in library.validate(self.root))
        )

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

    def test_category_placeholder_rejected(self):
        category = self.root / "docs/en/use-cases/security"
        category.mkdir()
        (category / "index.md").write_text("Empty category")
        self.assertTrue(
            any(
                "category placeholder" in error for error in library.validate(self.root)
            )
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

    def test_duplicate_homepage_card_rejected(self):
        home = self.root / "docs/en/index.mdx"
        home.write_text(home.read_text() * 2)
        self.assertTrue(
            any("one homepage card" in e for e in library.validate(self.root))
        )

    def test_missing_homepage_card_rejected(self):
        (self.root / "docs/en/index.mdx").write_text("No cards")
        self.assertTrue(
            any("one homepage card" in e for e in library.validate(self.root))
        )

    def test_nested_canonical_case_rejected(self):
        nested = self.page.parent / "operations/index.mdx"
        nested.parent.mkdir()
        nested.write_text(
            self.page.read_text().replace("../../_data/", "../../../_data/")
        )
        self.assertTrue(any("peer-level" in e for e in library.validate(self.root)))

    def test_supporting_guide_requires_hidden_sidebar(self):
        guide = self.page.with_suffix("") / "fallback.mdx"
        guide.parent.mkdir()
        guide.write_text("export const promptLibraryRole = 'fallback';")
        self.assertTrue(any("sidebar.hidden" in e for e in library.validate(self.root)))

    def test_orphan_support_directory_rejected(self):
        guide = self.page.parent / "orphan/reference.mdx"
        guide.parent.mkdir()
        guide.write_text(
            "---\nsidebar:\n  hidden: true\n---\n"
            "export const promptLibraryRole = 'reference';"
        )
        self.assertTrue(
            any("supporting directory" in e for e in library.validate(self.root))
        )

    def test_relocated_raw_import_rejected(self):
        self.page.write_text(
            self.page.read_text() + "\nimport source from '../../_data/missing.tf?raw';"
        )
        self.assertTrue(
            any("relative import" in e for e in library.validate(self.root))
        )

    def test_relocated_component_import_and_contextual_link(self):
        component = self.root / "docs/components/Example.astro"
        component.parent.mkdir()
        component.write_text("<div>Example</div>")
        self.page.write_text(
            self.page.read_text()
            + "\nimport Example from '../../components/Example.astro';\n"
            "[Home](/prompt-charity/en/)"
        )
        self.assertEqual(library.validate(self.root), [])


if __name__ == "__main__":
    unittest.main()
