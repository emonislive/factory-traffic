"""Traffic queue scoring and phase selection algorithm (D-09).

Calculates weighted phase scores using vehicle weights, wait times,
and starvation protection.
Owned by Agent A (Phase 1).
"""

from __future__ import annotations

from app.domain.types import Direction, JunctionConfig, JunctionState, Phase, VehicleType


def calculate_phase_scores(
    state: JunctionState, config: JunctionConfig, now: float
) -> dict[Phase, float]:
    """Calculate scheduling scores for each phase per D-09."""
    scores: dict[Phase, float] = {Phase.NS: 0.0, Phase.EW: 0.0}

    dir_to_phase: dict[Direction, Phase] = {}
    for phase, dirs in config.phases.items():
        for d in dirs:
            dir_to_phase[d] = phase

    for v in state.waiting_vehicles:
        # EMERGENCY vehicles are not scored; they trigger preemption (D-09)
        if v.vehicle_type == VehicleType.EMERGENCY:
            continue

        p = dir_to_phase.get(v.direction)
        if p is None:
            continue

        weight = config.vehicle_weights.get(v.vehicle_type, 1)
        wait_time = max(0.0, now - v.arrived_at)
        # Score = sum of vehicle weights + wait-time factor
        scores[p] += float(weight) + (wait_time * 0.1)

    return scores


def select_next_phase(state: JunctionState, config: JunctionConfig, now: float) -> Phase:
    """Select next phase based on D-09 scoring rules.

    Rules:
    - Phase score = sum of vehicle weights (TRUCK 3, FORKLIFT 2, EMPLOYEE 1) + wait-time factor.
    - Switch only if challenger beats current phase by 25%,
      or current phase has no waiting vehicles (after minimum green).
    - Anything waiting > 90s is forced next (starvation protection).
    - No traffic anywhere: stay on current phase, do not cycle.
    - EMERGENCY is not scored; it triggers preemption (D-15).
    """
    serving = state.serving
    challenger = Phase.EW if serving == Phase.NS else Phase.NS

    dir_to_phase: dict[Direction, Phase] = {}
    for phase, dirs in config.phases.items():
        for d in dirs:
            dir_to_phase[d] = phase

    # 1. Starvation protection (D-09)
    starved_vehicles = [
        v
        for v in state.waiting_vehicles
        if v.vehicle_type != VehicleType.EMERGENCY
        and (now - v.arrived_at) >= config.timings.starvation_after
    ]
    if starved_vehicles:
        oldest_starved = max(starved_vehicles, key=lambda v: now - v.arrived_at)
        target = dir_to_phase.get(oldest_starved.direction)
        if target is not None:
            return target

    # 2. Check waiting vehicles count per phase
    non_emergency_vehicles = [
        v for v in state.waiting_vehicles if v.vehicle_type != VehicleType.EMERGENCY
    ]
    if not non_emergency_vehicles:
        # No traffic anywhere: stay on current phase, do not cycle
        return serving

    serving_has_waiting = any(
        dir_to_phase.get(v.direction) == serving for v in non_emergency_vehicles
    )
    challenger_has_waiting = any(
        dir_to_phase.get(v.direction) == challenger for v in non_emergency_vehicles
    )

    if not serving_has_waiting and challenger_has_waiting:
        # Current phase has no waiting vehicles, challenger has waiting vehicles
        return challenger

    if not challenger_has_waiting:
        return serving

    # 3. Challenger score beats current phase by 25% (D-09)
    scores = calculate_phase_scores(state, config, now)
    if scores[challenger] > scores[serving] * 1.25:
        return challenger

    return serving
