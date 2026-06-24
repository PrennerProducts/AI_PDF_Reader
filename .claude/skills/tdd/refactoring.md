# Refactor Candidates

After a TDD cycle, look for:

- **Duplication** → Extract a function/helper
- **Long functions** → Break into private helpers (keep tests on the public interface)
- **Shallow modules** → Combine or deepen
- **Feature envy** → Move logic to where the data lives
- **Primitive obsession** → Introduce a small value object / dataclass
- **Existing code** the new code reveals as problematic

Run `python -m pytest` after each refactor step. Never refactor while RED.

<!-- Adapted from github.com/mattpocock/skills (MIT). -->
