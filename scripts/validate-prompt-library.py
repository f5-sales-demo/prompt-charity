"""Validate portable planning contracts and English documentation links."""

from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/en"
errors = []
prompts = 0
for page in DOCS.rglob("*"):
    if page.suffix not in {".md", ".mdx"}:
        continue
    source = page.read_text(encoding="utf-8")
    blocks = re.findall(r"```text\n(.*?)```", source, re.S)
    if page.parent.name != "en" and page.name != "index.md":
        prompts += 1
        if len(blocks) != 1:
            errors.append(f"{page}: expected one copyable prompt")
    for block in blocks:
        for required in ["planning mode", "read-only", "Do not edit files", "acceptance criteria", "Stop after the plan"]:
            if required not in block:
                errors.append(f"{page}: missing {required}")
        if not re.search(r"\[[^\]]+\]", block):
            errors.append(f"{page}: no input placeholders")
        if re.search(r"claude|codex|opencode|/plan|mcp__|[A-Za-z]:\\", block, re.I):
            errors.append(f"{page}: harness or platform dependency")
    for link in re.findall(r"\]\(([^)]+)\)|href=\"([^\"]+)\"|link: (\S+)", source):
        destination = next(part for part in link if part)
        parsed = urlsplit(destination)
        if parsed.scheme or destination.startswith("#"):
            continue
        path = unquote(parsed.path)
        target = ROOT / "docs" / path.removeprefix("/prompt-charity/") if path.startswith("/prompt-charity/") else page.parent / path
        candidates = [target, Path(str(target).rstrip("/") + ".md"), Path(str(target).rstrip("/") + ".mdx"), target / "index.md", target / "index.mdx"]
        if not any(candidate.is_file() for candidate in candidates):
            errors.append(f"{page}: broken link {destination}")
if prompts == 0:
    errors.append("No prompt pages found")
if errors:
    raise SystemExit("\n".join(errors))
print(f"Verified {prompts} portable planning prompts and all English documentation links")
