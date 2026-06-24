---
name: to-issues
description: Break a plan, spec, or PRD into independently-grabbable issues as local Markdown files using tracer-bullet vertical slices.
disable-model-invocation: true
---

# To Issues

Break a plan into independently-grabbable issues using vertical slices (tracer bullets).

**Tracker for this project = local files.** Issues are saved as Markdown under
`docs/issues/` with sequential numbering (`0001-slug.md`, …). Scan `docs/issues/`
for the highest existing number and increment.

## Process

### 1. Gather context

Work from what's already in the conversation. If the user passes a PRD reference (a `docs/prds/NNNN-*.md` path), read its full body.

### 2. Explore the codebase (optional)

Understand the current state. Issue titles/descriptions use the project's domain glossary (`CONTEXT.md`) and respect ADRs. Look for prefactoring opportunities — "make the change easy, then make the easy change."

### 3. Draft vertical slices

Each issue is a thin vertical slice through ALL layers end-to-end, NOT a horizontal slice of one layer.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer
- A completed slice is demoable/verifiable on its own
- Any prefactoring is done first
</vertical-slice-rules>

### 4. Quiz the user

Present the breakdown as a numbered list (Title / Blocked by / User stories covered). Ask whether the granularity and dependencies feel right. Iterate until approved.

### 5. Write the issues

For each approved slice, write `docs/issues/NNNN-slug.md` using the template below, in dependency order (blockers first), referencing real file names in "Blocked by".

<issue-template>
## Parent

Reference to the parent PRD (`docs/prds/NNNN-*.md`), if any.

## What to build

Concise description of this vertical slice — end-to-end behavior, not layer-by-layer. No file paths/snippets unless a snippet encodes a decision precisely.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Blocked by

- Reference to the blocking issue file, or "None - can start immediately".

</issue-template>

<!-- Adapted from github.com/mattpocock/skills (MIT); tracker switched to local files. -->
