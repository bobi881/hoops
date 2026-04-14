"""Pass resolver -- grid-based passing lanes and interception risk.

Checks the passing lane between passer and receiver on the grid,
calculates turnover risk from defenders in the lane, and resolves.
"""

from __future__ import annotations

from basketball_sim.core.grid import COURT
from basketball_sim.core.types import (
    ActionContext,
    ActionResult,
    AggregatedModifier,
    EventType,
    GameEvent,
    MatchupState,
)


def resolve_pass(
    matchup: MatchupState,
    agg: AggregatedModifier,
    context: ActionContext,
) -> ActionResult:
    """Resolve a pass attempt.

    Pass success depends on:
    1. Passer's passing_vision and passing_accuracy
    2. Grid distance (longer = harder)
    3. Defenders in the passing lane
    4. Receiver's openness and catch readiness
    """
    rng = context.rng
    passer = context.attacker
    pass_data = context.action.data

    target_id = pass_data.get("target_id", "")
    from_cell = context.cell
    to_cell = pass_data.get("target_cell", "D5")
    pass_type = pass_data.get("pass_type", "chest_pass")

    # --- Base success from passer attributes ---
    base_success = (
        passer.attributes.passing_vision / 100.0 * 0.5
        + passer.attributes.passing_accuracy / 100.0 * 0.5
    )
    # base_success: 0.0 to 1.0 (a 70/70 passer = 0.70)

    # --- Distance penalty ---
    distance = COURT.manhattan_distance(from_cell, to_cell)
    distance_penalty = distance * 0.02  # each cell of distance adds 2% risk

    # Skip passes (cross-court) are riskier
    if distance >= 4:
        distance_penalty += 0.05
        pass_type = "skip_pass"

    # --- Passing lane check ---
    lane_cells = COURT.cells_between(from_cell, to_cell)
    defenders_in_lane = 0
    for defender_on_court in context.possession.defense:
        if defender_on_court.cell in lane_cells:
            defenders_in_lane += 1

    lane_risk = defenders_in_lane * 0.08  # each defender in lane = 8% steal chance

    # --- Turnover probability ---
    turnover_pct = max(0.01, min(0.40, 0.05 + distance_penalty + lane_risk - base_success * 0.15))

    # --- Roll ---
    stolen = rng.random() < turnover_pct

    tags: list[str] = list(agg.tags)

    if stolen:
        # Steal / deflection
        tags.extend(["pass_stolen", "turnover"])

        steal_event = GameEvent(
            event_type=EventType.STEAL,
            data={
                "pass_type": pass_type,
                "from_cell": from_cell,
                "to_cell": to_cell,
                "defenders_in_lane": defenders_in_lane,
            },
            tags=["steal", "turnover"],
        )
        turnover_event = GameEvent(
            event_type=EventType.TURNOVER,
            player_id=context.action.player_id,
            data={"cause": "pass_stolen", "pass_type": pass_type},
            tags=["turnover"],
        )

        return ActionResult(
            events=[steal_event, turnover_event],
            tags=tags,
            ends_possession=True,
        )
    else:
        # Pass completed
        tags.extend(["pass_completed"])
        if pass_type == "skip_pass":
            tags.append("skip_pass")
        if distance >= 5:
            tags.append("cross_court")

        pass_event = GameEvent(
            event_type=EventType.PASS_COMPLETED,
            player_id=context.action.player_id,
            data={
                "target_id": target_id,
                "pass_type": pass_type,
                "from_cell": from_cell,
                "to_cell": to_cell,
                "distance": distance,
            },
            tags=tags,
        )

        return ActionResult(
            events=[pass_event],
            tags=tags,
            ends_possession=False,
            ball_handler_change=target_id,
            # Reset matchup state for the new ball handler
            new_matchup=MatchupState(),
        )
