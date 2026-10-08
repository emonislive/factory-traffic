"""Junction configuration validation logic (D-10).

Validates that every direction belongs to exactly one phase, phases are conflicting,
and timing constraints are positive and within bounds.
Owned by Agent A (Phase 1).
"""

from __future__ import annotations

from app.domain.types import Direction, JunctionConfig, Phase


def validate_junction_config(config: JunctionConfig) -> None:
    """Validate junction configuration per D-10.

    Raises ValueError if configuration is invalid.
    """
    if not config.id or not config.id.strip():
        raise ValueError("Junction ID must not be empty")

    if not config.name or not config.name.strip():
        raise ValueError("Junction name must not be empty")

    # D-10: Two phases only (NS and EW)
    if len(config.phases) != 2:
        raise ValueError("Junction must have exactly two phases (NS and EW)")

    if Phase.NS not in config.phases or Phase.EW not in config.phases:
        raise ValueError("Junction must define both Phase.NS and Phase.EW")

    ns_dirs = set(config.phases[Phase.NS])
    ew_dirs = set(config.phases[Phase.EW])

    if not ns_dirs:
        raise ValueError("Phase.NS must contain at least one direction")
    if not ew_dirs:
        raise ValueError("Phase.EW must contain at least one direction")

    # Conflicting: phases must be disjoint
    overlap = ns_dirs.intersection(ew_dirs)
    if overlap:
        raise ValueError(f"Phases must be disjoint, found overlapping directions: {overlap}")

    all_assigned = ns_dirs.union(ew_dirs)
    expected_dirs = {Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST}
    if all_assigned != expected_dirs:

        diff = expected_dirs.symmetric_difference(all_assigned)
        raise ValueError(f"Directions mismatch: {diff}")




    # Timing validation (D-07, D-12, D-17, D-18, D-19)
    t = config.timings
    if t.green <= 0:
        raise ValueError("green timing must be positive")
    if t.yellow <= 0:
        raise ValueError("yellow timing must be positive")
    if t.all_red <= 0:
        raise ValueError("all_red timing must be positive")
    if t.min_green <= 0:
        raise ValueError("min_green timing must be positive")
    if t.max_green < t.min_green:
        raise ValueError("max_green must be >= min_green")
    if t.ack_timeout <= 0:
        raise ValueError("ack_timeout must be positive")
    if t.max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    if t.starvation_after <= 0:
        raise ValueError("starvation_after must be positive")
    if t.emergency_timeout <= 0:
        raise ValueError("emergency_timeout must be positive")
    if t.manual_lease <= 0:
        raise ValueError("manual_lease must be positive")
    if t.stale_event_after <= 0:
        raise ValueError("stale_event_after must be positive")
