"""Junction configuration validation logic (D-10).

Validates that every direction belongs to exactly one phase, phases are conflicting,
and timing constraints are positive and within bounds.
Owned by Agent A (Phase 1).
"""

from __future__ import annotations

from app.domain.types import JunctionConfig


def validate_junction_config(config: JunctionConfig) -> None:
    """Validate junction configuration per D-10.

    Raises ValueError if configuration is invalid.
    """
    # Stub for Phase 0
    pass
