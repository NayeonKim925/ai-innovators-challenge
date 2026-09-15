"""Thin orchestration layer between the deterministic workflow, the optional
LLM narrative step, and the HTTP boundary. Kept out of `main.py` because the
API layer must stay limited to input validation and serialization
(see docs/ARCHITECTURE.md)."""
