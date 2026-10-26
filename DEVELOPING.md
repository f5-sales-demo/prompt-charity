# Developing Prompt Charity

Author English documentation in `docs/en/`. Place peer-level prompt pages at `docs/en/use-cases/<case>.mdx`;
each real use-case page imports one canonical `prompts/*.txt` source through `docs/_imports` and Starlight
`Code`. Include bracketed inputs, read-only planning, explicit plan approval, and complete post-approval
implementation and verification instructions. Fallback/reference pages are supporting documentation, not
prompts. Mark MDX supporting pages with `export const promptLibraryRole = 'fallback';` (or `reference`).
Add exactly one homepage card per case. Do not create category or overview pages. Put supporting guides in a
matching `<case>/` directory and set `sidebar.hidden: true`; keep the prompt template hidden and link supporting
pages contextually. Update `docs/llms-config.json` promotion metadata for each case.
Derive the plain-text download from that same source; never maintain a second prompt copy.

Use the existing Carbon icons supported by the shared docs theme. Hero generation provenance and the exact brief live in `output/imagegen/`; optimized publication assets live in `docs/images/`.

## Validation

Run `python3 scripts/validate-prompt-library.py` to check prompt contracts and local links. Run the managed shell checks and required PR CI. The fleet Pages workflow builds and publishes with the governed builder; verify the deployed revision and prompt pages after merge.

The README is canonical content owned by docs-control at `content/prompt-charity/README.md`. Change it there. Shared navigation and portal cards belong to `f5-sales-demo.github.io`.
