---
title: Getting started
description: Use a reusable planning prompt in your chosen harness.
---

1. Choose a prompt from the [use case catalog](/prompt-charity/en/use-cases/).
2. Replace every bracketed input with your objective, context, constraints, and available evidence.
3. Enable your harness's planning mode before submitting the prompt. Claude Code, Codex CLI, and OpenCode are examples of harnesses; consult your installed version's documentation for its planning controls.
4. Copy only the prompt block. No harness-specific command or plugin is required by the prompt text.
5. Review scope, assumptions, alternatives, steps, risks, and acceptance evidence.
6. Resolve material questions and separately authorize implementation when you are ready.

## Permissions and portability

Planning modes differ between harnesses and versions. Prompt wording does not enforce permissions. If your harness has no planning mode, disable write tools and request a written plan with read-only investigation. If it cannot inspect the environment, provide context and expect it to identify unverified claims.

Cross-platform describes the prompt contract; it does not guarantee identical outputs or tool availability. The starter prompts have been checked for vendor-specific dependencies. Live execution compatibility across harnesses remains to be evaluated with recorded examples.

## Good context

Include the outcome, audience, relevant files or supplied evidence, constraints, ownership, and how you will recognize success. Use placeholders or sanitized examples for private material in contributions to this public library.

## English source

Maintain English here. A separate process handles translations; contributors should not generate locale copies.
