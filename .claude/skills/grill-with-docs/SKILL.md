---
name: grill-with-docs
description: A relentless interview to sharpen a plan or design, which also creates docs (ADRs and glossary) as we go.
disable-model-invocation: true
---

Run a `/grilling` session, using the `/domain-modeling` skill.

When resolving terminology, capture it in `CONTEXT.md` (see the domain-modeling
skill). For this project the export contract is a documented tabu zone — never
revise export/VenDoc terminology without flagging the impact on
`tests/test_export_contract.py` and `docs/VENDOC_DRAGAN_HANDOVER.md`.

<!-- Adapted from github.com/mattpocock/skills (MIT). Methodology is
language-agnostic; this repo is Python/FastAPI/pytest. -->
