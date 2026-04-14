"""Rebound resolver -- determines who gets the board after a missed shot.

Uses player rebounding attributes, position on the grid, and height/strength
to determine offensive vs defensive rebound.
"""

from __future__ import annotations

from basketball_sim.core.types import (
    ActionResult,
    EventType,
    GameEvent,
    Player,
    PossessionState,
)
import random


def resolve_rebound(
    possession: PossessionState,
    rng: random.Random,
) -> ActionResult:
    """Resolve a rebound after a missed shot.

    Offensive rebound rate is ~25% in the NBA. Individual chances
    are weighted by rebounding attributes and proximity to the basket.
    """
    # Collect rebounders: offense wants offensive_rebound, defense wants defensive_rebound
    off_candidates: list[tuple[Player, float]] = []
    def_candidates: list[tuple[Player, float]] = []

    # Ball handler (offense)
    bh = possession.ball_handler
    off_candidates.append((
        bh.player,
        bh.player.attributes.offensive_rebound / 100.0,
    ))

    # Off-ball offense
    for obs in possession.off_ball_offense:
        off_candidates.append((
            obs.player,
            obs.player.attributes.offensive_rebound / 100.0,
        ))

    # Defense
    for doc in possession.defense:
        def_candidates.append((
            doc.player,
            doc.player.attributes.defensive_rebound / 100.0,
        ))

    # Team offensive rebound probability (~25% base)
    off_total = sum(w for _, w in off_candidates) if off_candidates else 0
    def_total = sum(w for _, w in def_candidates) if def_candidates else 0

    total = off_total + def_total
    if total == 0:
        off_pct = 0.25
    else:
        # Weight toward defense: multiply def weights by 2.5 to get ~75/25 split
        off_pct = off_total / (off_total + def_total * 2.5)

    off_pct = max(0.10, min(0.40, off_pct))  # clamp to realistic range

    is_offensive = rng.random() < off_pct

    if is_offensive:
        candidates = off_candidates
        reb_type = "offensive"
    else:
        candidates = def_candidates
        reb_type = "defensive"

    # Pick the individual rebounder weighted by their rating
    if candidates:
        players, weights = zip(*candidates)
        rebounder = rng.choices(list(players), weights=list(weights), k=1)[0]
    else:
        # Fallback: ball handler gets it
        rebounder = possession.ball_handler.player

    tags = [f"{reb_type}_rebound"]

    event = GameEvent(
        event_type=EventType.REBOUND,
        player_id=rebounder.player_id,
        data={
            "rebound_type": reb_type,
            "rebounder": rebounder.display_name,
        },
        tags=tags,
    )

    return ActionResult(
        events=[event],
        tags=tags,
        ends_possession=not is_offensive,
        ball_handler_change=rebounder.player_id if is_offensive else None,
    )
