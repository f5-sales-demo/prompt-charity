# Developing Prompt Charity

Author English documentation in `docs/en/`. Categorize prompt pages under `docs/en/use-cases/<category>/`; each page contains one `text` fenced block with bracketed inputs, authorized read-only investigation, a reviewable output contract, and an explicit stop before implementation.

Use the existing Carbon icons supported by the shared docs theme. Hero generation provenance and the exact brief live in `output/imagegen/`; optimized publication assets live in `docs/images/`.

## Validation

Run `python3 scripts/validate-prompt-library.py` to check prompt contracts and local links. Run the managed shell checks and required PR CI. The fleet Pages workflow builds and publishes with the governed builder; verify the deployed revision and prompt pages after merge.

The README is canonical content owned by docs-control at `content/prompt-charity/README.md`. Change it there. Shared navigation and portal cards belong to `f5-sales-demo.github.io`.
