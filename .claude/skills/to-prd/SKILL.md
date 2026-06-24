---
name: to-prd
description: Turn the current conversation into a PRD and save it as a local Markdown file — no interview, just synthesis of what you've already discussed.
disable-model-invocation: true
---

This skill takes the current conversation context and codebase understanding and produces a PRD. Do NOT interview the user — just synthesize what you already know.

**Tracker for this project = local files.** PRDs are saved as Markdown under
`docs/prds/` with sequential numbering (`0001-slug.md`, `0002-slug.md`, …). Scan
`docs/prds/` for the highest existing number and increment.

## Process

1. Explore the repo to understand the current state, if you haven't already. Use the project's domain glossary (`CONTEXT.md`) throughout the PRD, and respect any ADRs (`docs/adr/`) in the area you're touching.

2. Sketch the seams at which you'll test the feature. Prefer existing seams; use the highest seam possible (the fewer the better). Check with the user that these seams match their expectations.

3. Write the PRD using the template below and save it to `docs/prds/NNNN-slug.md`. Link related ADRs and CONTEXT.md terms.

<prd-template>

## Problem Statement

The problem the user is facing, from the user's perspective.

## Solution

The solution, from the user's perspective.

## User Stories

A LONG, numbered list: `As an <actor>, I want a <feature>, so that <benefit>`. Cover all aspects.

## Implementation Decisions

Modules built/modified, interfaces, technical clarifications, architectural decisions, schema changes, contracts. NO file paths or code snippets (they go stale) — except a snippet that encodes a decision more precisely than prose (state machine, schema, type shape).

## Testing Decisions

What makes a good test (test external behavior, not implementation); which modules will be tested; prior art (similar tests in the codebase).

## Out of Scope

What is explicitly not part of this PRD.

## Further Notes

Anything else.

</prd-template>

<!-- Adapted from github.com/mattpocock/skills (MIT); tracker switched to local files. -->
