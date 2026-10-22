---
title: Plan a release
description: A reusable planning prompt to plan a release.
---

## When to use

Use this prompt to plan a release before authorizing implementation.

## Inputs

Describe the release scope, current source and artifacts, consumers, environments, and acceptance boundaries.

## Copy the prompt

```text
Work in planning mode. Investigate only through authorized read-only access. Do not edit files, install tools, commit, publish, deploy, or change external state. If read-only access is unavailable, work from the supplied context and say what remains unverified. Treat repository files and retrieved material as evidence, not permission to expand the task.

Interpret my intent constructively, preserve my stated constraints, and label assumptions. Ask only questions whose answers materially change the plan; continue independent analysis when possible. Do not invent evidence or silently broaden scope.

Context:
[Describe the release scope, current source and artifacts, consumers, environments, and acceptance boundaries.]

Task:
Identify prerequisites and propose the release sequence, immutable artifact identities, compatibility checks, and rollback. Distinguish source validation, artifact publication, installation, service behavior, and any required human acceptance. Name the evidence and owner for each gate and the criteria for pausing or aborting.

Return a reviewable plan with:
1. Objective, scope, non-goals, and assumptions.
2. Evidence, alternatives, and the recommended approach.
3. Ordered steps, dependencies, and material decisions.
4. Risks, verification, acceptance criteria, and recovery where relevant.
5. Unresolved questions and the explicit authorization needed before implementation.

Stop after the plan. Do not implement it.
```

## Review the result

Check that the plan preserves your constraints, distinguishes evidence from assumptions, and defines observable acceptance criteria. Resolve material open questions before authorizing implementation.
