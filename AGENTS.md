# Agent Instructions

Preserve the product boundary: Raven-Targeter discovers public projects/endpoints; it never executes third-party code or tests credentials. Every endpoint sent to Raven-Validator must come from explicit public evidence and carry evidence/confidence. Run `pytest` and `ruff check .` after changes.
