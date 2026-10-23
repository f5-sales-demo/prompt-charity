---
title: Prompt template
description: A portable contract for contributing a complete prompt.
---

A prompt page has an English title and description, a use case, required inputs, one complete copyable block imported from a canonical source outside rendered docs, a plain-text download, and guidance for reviewing the result. Put it in the appropriate category.

```text
Work in planning mode. Use only authorized read-only investigation. Do not edit files, install tools, commit, publish, deploy, or change external state.

Objective: [Describe the intended outcome.]
Context: [Supply relevant evidence, system details, audience, and ownership.]
Constraints: [Specify scope, non-goals, limits, and acceptance boundaries.]

Interpret my intent constructively. Preserve constraints, label assumptions, and distinguish evidence from hypotheses. If access or evidence is missing, say what remains unverified. Ask questions only when their answers materially affect the plan.

Propose a reviewable plan with the objective, alternatives, recommended approach, ordered steps, dependencies, risks, meaningful verification, observable acceptance criteria, and recovery where relevant. Identify unresolved decisions and authorization needed before implementation.

Stop after the plan and wait for explicit approval. After approval, implement the scoped plan, keep the session active through bounded waits, verify every completion gate, and report any unmet gate with evidence. Recovery changes require a reviewed plan.
```

Keep harness setup outside the block. Include the full technical specification and post-approval implementation instructions in the canonical prompt; choose native commands after environment discovery. A contribution should include an example of supplied context and how a reviewer can judge the resulting plan; never publish private inputs or transcripts.
