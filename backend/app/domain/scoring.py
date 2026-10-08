"""Traffic queue scoring and phase selection algorithm (D-09).

Calculates weighted phase scores using vehicle weights, wait times,
and starvation protection.
Owned by Agent A (Phase 1).
"""

from __future__ import annotations

from app.domain.types import JunctionConfig, JunctionState, Phase


def calculate_phase_scores(
    state: JunctionState, config: JunctionConfig, now: float
) -> dict[Phase, float]:
    """Calculate scheduling scores for each phase per D-09."""
    # Stub for Phase 0
    return {Phase.NS: 0.0, Phase.EW: 0.0}


def select_next_phase(
    state: JunctionState, config: JunctionConfig, now: float
) -> Phase:
    """Select next phase based on D-09 scoring rules."""
    # Stub for Phase 0
    return state.serving
