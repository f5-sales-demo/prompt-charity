---
title: Prompt template
description: A portable contract for contributing a complete prompt.
sidebar:
  hidden: true
---

A prompt page has an English title and description, a use case, required inputs, one complete copyable block imported
from a canonical source outside rendered docs, a plain-text download, and guidance for reviewing the result. Put it at
`docs/en/use-cases/<case>.mdx` and add one homepage card. Supporting guides live in a matching `<case>/` directory,
declare their fallback or reference role, and set `sidebar.hidden: true`.

```text
## Objective and inputs

Objective: [Describe the intended outcome.]
Context and inputs: [Relevant evidence, environment, audience and ownership.]

## Working agreement

Follow native planning and approval controls and workspace conventions. Use authorized read-only discovery to
establish prerequisites. Present infrastructure scope, cost, risks and verification for approval before
applying changes. Continue approved work through verification, using supported handoffs while preserving
approved scope, identities, ownership and original deadlines. Clarify missing authorization or material
choices and report unavailable evidence.

## Deployment requirements

[Essential scope, dependencies, technical constraints and security boundaries. Let the agent choose implementation details that do not affect the required outcome.]

## Acceptance criteria

[Observable checks proving completion, evidence to retain, bounded deadlines and reviewed recovery/cleanup when relevant.]
```

Keep harness setup outside the block. Include the desired outcome and essential technical constraints in the
canonical prompt. Let the harness manage ordinary planning artifacts and choose native commands and
implementation organization after discovery. A contribution should include an example of supplied context and
how a reviewer can judge the resulting plan; never publish private inputs or transcripts.
