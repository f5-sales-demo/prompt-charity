"""Validate canonical complete prompts, supporting page roles and local links."""

# Keep the existing CLI filename convention.
# pylint: disable=invalid-name

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

IMPORT_PAIR_SIZE = 2

ROOT = Path(__file__).resolve().parents[1]


def documentation_imports(root: Path) -> tuple[dict[str, Path], list[str]]:
    """Check staged import mappings without creating publication files."""
    errors = []
    imports = {}
    imports_file = root / "docs/_imports"
    if imports_file.exists():
        for line in imports_file.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split(" -> ")
            source = Path(parts[0])
            destination = (
                Path(parts[1]) if len(parts) == IMPORT_PAIR_SIZE else Path(source.name)
            )
            if any(p.is_absolute() or ".." in p.parts for p in [source, destination]):
                errors.append(f"Unsafe documentation import: {line}")
                continue
            if destination.as_posix() in imports:
                errors.append(f"Duplicate documentation import: {destination}")
            imports[destination.as_posix()] = source
            if not (root / source).is_file():
                errors.append(f"Missing documentation import source: {source}")
    return imports, errors


def canonical_contract(
    root: Path,
    page: Path,
    text: str,
    imports: dict[str, Path],
    prompt_imports: list[tuple[str, str]],
) -> list[str]:
    """Check source, approval contract and copy/download use of each prompt."""
    errors = []
    for variable, path in prompt_imports:
        staged = (page.parent / path.removesuffix("?raw")).resolve()
        data_root = (root / "docs/_data").resolve()
        if not staged.is_relative_to(data_root):
            errors.append(f"{page}: unsafe prompt import")
            continue
        key = staged.relative_to(data_root).as_posix()
        canonical = imports.get(key)
        if canonical is None or not canonical.is_relative_to("prompts"):
            errors.append(f"{page}: missing canonical documentation import for {key}")
            continue
        if not (root / canonical).is_file():
            continue
        block = (root / canonical).read_text(encoding="utf-8")
        for required in [
            "planning mode",
            "read-only",
            "Do not edit files",
            "acceptance criteria",
            "Stop after the plan",
            "approval",
        ]:
            if required not in block:
                errors.append(f"{page}: missing {required} in canonical prompt")  # noqa: PERF401 - keep each contract failure explicit
        if not re.search(r"\[[^\]]+\]", block):
            errors.append(f"{page}: no input placeholders")
        if re.search(
            r"\bclaude\b|\bcodex\b|\bopencode\b|/plan\b|mcp__|[A-Za-z]:\\|AskUserQuestion|functions\.exec|cua_repl",
            block,
            re.IGNORECASE,
        ):
            errors.append(f"{page}: harness or platform dependency")
        if len(re.findall(rf'<Code\s+code=\{{{variable}\}}\s+lang="text"', text)) != 1:
            errors.append(f"{page}: expected one canonical Code block")
        if (
            not re.search(
                rf"Buffer\.from\({variable}, ['\"]utf8['\"]\)\.toString\(['\"]base64['\"]\)",
                text,
            )
            or 'download="' not in text
        ):
            errors.append(f"{page}: download must derive from canonical prompt")
        if re.search(r"```text\n", text):
            errors.append(f"{page}: duplicate inline prompt")
    return errors


def local_links(root: Path, page: Path, text: str) -> list[str]:
    """Check relative and repository-base documentation links."""
    errors = []
    for link in re.findall(r"\]\(([^)]+)\)|href=\"([^\"]+)\"|link: (\S+)", text):
        destination = next(part for part in link if part)
        parsed = urlsplit(destination)
        if parsed.scheme or destination.startswith("#"):
            continue
        path = unquote(parsed.path)
        target = (
            root / "docs" / path.removeprefix("/prompt-charity/")
            if path.startswith("/prompt-charity/")
            else page.parent / path
        )
        candidates = [
            target,
            Path(str(target).rstrip("/") + ".md"),
            Path(str(target).rstrip("/") + ".mdx"),
            target / "index.md",
            target / "index.mdx",
        ]
        if not any(candidate.is_file() for candidate in candidates):
            errors.append(f"{page}: broken link {destination}")
    return errors


def relative_imports(
    root: Path, page: Path, text: str, imports: dict[str, Path]
) -> list[str]:
    """Resolve relocated component and raw-source imports before the build."""
    errors = []
    data_root = (root / "docs/_data").resolve()
    for path in re.findall(r"from\s+['\"](\.[^'\"]+)['\"]", text):
        target = (page.parent / path.split("?")[0]).resolve()
        if target.is_relative_to(data_root):
            source = imports.get(target.relative_to(data_root).as_posix())
            valid = source is not None and (root / source).is_file()
        else:
            valid = (
                target.is_relative_to((root / "docs").resolve()) and target.is_file()
            )
        if not valid:
            errors.append(f"{page}: broken relative import {path}")
    return errors


def homepage_cards(root: Path, use_cases: list[Path]) -> list[str]:
    """Require exactly one homepage card per peer-level use case."""
    home = root / "docs/en/index.mdx"
    text = home.read_text(encoding="utf-8") if home.exists() else ""
    cards = re.findall(r'<LinkCard\b[^>]*href="([^"]+)"[^>]*>', text)
    routes = {f"/prompt-charity/en/use-cases/{page.stem}/" for page in use_cases}
    errors = [
        f"{route}: expected one homepage card"
        for route in sorted(routes)
        if cards.count(route) != 1
    ]
    errors.extend(
        f"{card}: homepage card must link to a peer-level use case"
        for card in cards
        if card not in routes
    )
    return errors


def validate(root: Path) -> list[str]:
    """Return all library errors without modifying content or staged imports."""
    docs = root / "docs/en"
    catalog = docs / "use-cases"
    imports, errors = documentation_imports(root)
    use_cases = []
    for page in docs.rglob("*"):
        if page.suffix not in {".md", ".mdx"}:
            continue
        text = page.read_text(encoding="utf-8")
        prompt_imports = re.findall(
            r"import\s+(\w+)\s+from\s+['\"]([^'\"]+/_data/prompts/[^'\"]+\?raw)['\"]",
            text,
        )
        supporting = bool(
            re.search(
                r"export\s+const\s+promptLibraryRole\s*=\s*['\"](?:fallback|reference)['\"]",
                text,
            )
            or re.search(r"<!-- prompt-library: (fallback|reference) -->", text)
        )
        is_use_case = page.is_relative_to(catalog)
        peer = page.parent == catalog and page.stem != "index"
        if supporting and not re.search(r"sidebar:\s*\n\s+hidden: true", text):
            errors.append(f"{page}: supporting guide requires sidebar.hidden: true")
        if is_use_case and page.stem == "index" and not supporting:
            errors.append(f"{page}: category placeholder is not a use case")
        if prompt_imports:
            use_cases.append(page)
            if not is_use_case or supporting or len(prompt_imports) != 1:
                errors.append(f"{page}: expected one canonical use-case prompt")
            if not peer:
                errors.append(f"{page}: canonical case must be a peer-level page")
            errors.extend(canonical_contract(root, page, text, imports, prompt_imports))
        elif is_use_case and not supporting:
            errors.append(
                f"{page}: unclassified use-case page; declare fallback/reference or import canonical prompt"
            )
        errors.extend(local_links(root, page, text))
        errors.extend(relative_imports(root, page, text, imports))
    if not use_cases:
        errors.append("No canonical use-case pages found")
    if catalog.exists():
        peer_names = {page.stem for page in use_cases if page.parent == catalog}
        for directory in catalog.iterdir():
            if directory.is_dir() and directory.name not in peer_names:
                errors.append(
                    f"{directory}: supporting directory requires a peer-level case"
                )
            elif directory.is_dir() and not any(directory.rglob("*.md*")):
                errors.append(f"{directory}: empty supporting directory")
    errors.extend(homepage_cards(root, use_cases))
    return errors


def main() -> None:
    """Validate the selected repository and report all contract violations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        raise SystemExit("\n".join(errors))
    print(
        "Verified canonical complete prompts, flat use cases, unique homepage cards and English documentation links"
    )


if __name__ == "__main__":
    main()
