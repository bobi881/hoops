"""Mental state updater -- mutates player mental/fatigue state from events.

Subscribes to the event bus and nudges per-player confidence, momentum,
and frustration based on outcomes. Fatigue is already drained per-action
inside the resolvers; this module handles the psychology side.

This is intentionally a separate subscriber rather than a modifier so it
can mutate state (modifiers are supposed to be pure functions of context).
"""

from __future__ import annotations

from basketball_sim.core.types import EventType, GameEvent, Player


class MentalStateUpdater:
    """Updates player mental state from game events.

    Usage:
        updater = MentalStateUpdater(all_players_iterable)
        event_bus.subscribe_all(updater.handle_event)
    """

    def __init__(self, players) -> None:
        self._players: dict[str, Player] = {p.player_id: p for p in players}

    def handle_event(self, event: GameEvent) -> None:
        """Route events to the appropriate update function."""
        handler = self._handlers.get(event.event_type)
        if handler is not None:
            handler(self, event)

    def _on_made(self, event: GameEvent) -> None:
        p = self._players.get(event.player_id)
        if p is None:
            return
        points = event.data.get("points", 2)
        # Small confidence + momentum bump; slight frustration relief.
        p.mental.confidence = min(1.0, p.mental.confidence + 0.02 * points)
        p.mental.momentum = max(-1.0, min(1.0, p.mental.momentum + 0.05 * points))
        p.mental.frustration = max(0.0, p.mental.frustration - 0.03)

    def _on_miss(self, event: GameEvent) -> None:
        p = self._players.get(event.player_id)
        if p is None:
            return
        p.mental.confidence = max(0.0, p.mental.confidence - 0.015)
        p.mental.momentum = max(-1.0, p.mental.momentum - 0.03)
        p.mental.frustration = min(1.0, p.mental.frustration + 0.015)

    def _on_turnover(self, event: GameEvent) -> None:
        p = self._players.get(event.player_id)
        if p is None:
            return
        p.mental.confidence = max(0.0, p.mental.confidence - 0.02)
        p.mental.frustration = min(1.0, p.mental.frustration + 0.04)
        p.mental.momentum = max(-1.0, p.mental.momentum - 0.05)

    def _on_steal(self, event: GameEvent) -> None:
        # The stealer gets a confidence / momentum boost.
        p = self._players.get(event.player_id)
        if p is None:
            return
        p.mental.confidence = min(1.0, p.mental.confidence + 0.02)
        p.mental.momentum = max(-1.0, min(1.0, p.mental.momentum + 0.05))

    def _on_block(self, event: GameEvent) -> None:
        p = self._players.get(event.player_id)
        if p is None:
            return
        p.mental.confidence = min(1.0, p.mental.confidence + 0.015)
        p.mental.momentum = max(-1.0, min(1.0, p.mental.momentum + 0.04))

    def _on_quarter_start(self, event: GameEvent) -> None:
        # Small cross-game drift back toward baseline between quarters:
        # frustration cools a bit, momentum decays slightly.
        for p in self._players.values():
            p.mental.frustration *= 0.8
            p.mental.momentum *= 0.6

    _handlers = {
        EventType.SHOT_MADE: _on_made,
        EventType.SHOT_MISSED: _on_miss,
        EventType.TURNOVER: _on_turnover,
        EventType.STEAL: _on_steal,
        EventType.BLOCK: _on_block,
        EventType.QUARTER_START: _on_quarter_start,
    }
