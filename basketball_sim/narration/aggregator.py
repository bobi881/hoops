"""Stage 1: Event Aggregator -- groups raw events into narrative beats.

A dribble sequence + drive + shot = one beat, not six separate events.
The aggregator collapses sequential related events into coherent
narrative units that the rest of the pipeline can work with.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from basketball_sim.core.types import EventType, GameEvent


@dataclass
class NarrativeBeat:
    """A single narrative moment composed of one or more raw events.

    A beat is the fundamental unit of narration -- something worth
    describing in prose. Examples:
    - A dribble sequence that breaks the defender's ankles
    - A shot attempt and its result
    - A steal leading to a fast break
    - A pass completion
    """
    events: list[GameEvent] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    primary_event_type: EventType | None = None
    player_id: str = ""
    is_scoring_play: bool = False
    point_value: int = 0
    game_clock: float = 0.0
    shot_clock: float = 0.0
    quarter: int = 1

    def add_event(self, event: GameEvent) -> None:
        """Add an event to this beat."""
        self.events.append(event)
        self.tags.extend(event.tags)
        if not self.player_id and event.player_id:
            self.player_id = event.player_id
        if event.game_clock:
            self.game_clock = event.game_clock
        if event.shot_clock:
            self.shot_clock = event.shot_clock
        if event.quarter:
            self.quarter = event.quarter


# Event types that START a new beat (not grouped with previous)
_BEAT_STARTERS = {
    EventType.POSSESSION_START,
    EventType.POSSESSION_END,
    EventType.QUARTER_START,
    EventType.QUARTER_END,
    EventType.GAME_START,
    EventType.GAME_END,
    EventType.TIMEOUT,
    EventType.SUBSTITUTION,
    EventType.FREE_THROW,
}

# Event types that are part of a shot sequence
_SHOT_SEQUENCE = {
    EventType.SHOT_ATTEMPT,
    EventType.SHOT_MADE,
    EventType.SHOT_MISSED,
    EventType.BLOCK,
}

# Event types that are part of a dribble sequence
_DRIBBLE_SEQUENCE = {
    EventType.DRIBBLE_MOVE,
    EventType.ANKLE_BREAKER,
}


class EventAggregator:
    """Groups raw events into narrative beats.

    Rules:
    - Consecutive dribble moves are grouped into one beat
    - Shot attempt + result (made/missed) are one beat
    - Steals and turnovers are their own beats
    - Game flow events (quarter start/end) are their own beats
    - Blocks are grouped with the shot they block
    """

    def __init__(self) -> None:
        self._current_beat: NarrativeBeat | None = None
        self._completed_beats: list[NarrativeBeat] = []

    def process_event(self, event: GameEvent) -> NarrativeBeat | None:
        """Process a single event. Returns a completed beat if one is ready.

        Call this for each event in order. When a beat is complete (the next
        event starts a new logical sequence), the previous beat is returned.
        """
        # Beat starters always close the current beat and start fresh
        if event.event_type in _BEAT_STARTERS:
            completed = self._close_current_beat()
            beat = NarrativeBeat(primary_event_type=event.event_type)
            beat.add_event(event)
            self._completed_beats.append(beat)
            # These are self-contained beats, return immediately
            return completed or beat

        # Dribble events group together
        if event.event_type in _DRIBBLE_SEQUENCE:
            if self._current_beat and self._current_beat.primary_event_type in _DRIBBLE_SEQUENCE:
                # Extend existing dribble beat
                self._current_beat.add_event(event)
                return None
            else:
                completed = self._close_current_beat()
                self._current_beat = NarrativeBeat(
                    primary_event_type=event.event_type
                )
                self._current_beat.add_event(event)
                return completed

        # Shot events group together
        if event.event_type in _SHOT_SEQUENCE:
            if self._current_beat and self._current_beat.primary_event_type == EventType.SHOT_ATTEMPT:
                # This is the result of a shot attempt
                self._current_beat.add_event(event)
                if event.event_type == EventType.SHOT_MADE:
                    self._current_beat.is_scoring_play = True
                    self._current_beat.point_value = event.data.get("points", 0)
                # Shot sequence is complete
                return self._close_current_beat()
            elif event.event_type == EventType.SHOT_ATTEMPT:
                # Start a new shot beat (close any dribble sequence first)
                completed = self._close_current_beat()
                self._current_beat = NarrativeBeat(
                    primary_event_type=EventType.SHOT_ATTEMPT
                )
                self._current_beat.add_event(event)
                return completed
            else:
                # Shot result without preceding attempt -- standalone beat
                completed = self._close_current_beat()
                beat = NarrativeBeat(primary_event_type=event.event_type)
                beat.add_event(event)
                if event.event_type == EventType.SHOT_MADE:
                    beat.is_scoring_play = True
                    beat.point_value = event.data.get("points", 0)
                self._completed_beats.append(beat)
                return completed or beat

        # Everything else (steal, turnover, pass, rebound, foul) is its own beat
        completed = self._close_current_beat()
        beat = NarrativeBeat(primary_event_type=event.event_type)
        beat.add_event(event)

        if event.event_type == EventType.REBOUND:
            self._completed_beats.append(beat)
            return completed or beat

        self._completed_beats.append(beat)
        return completed or beat

    def flush(self) -> NarrativeBeat | None:
        """Flush any remaining open beat."""
        return self._close_current_beat()

    def _close_current_beat(self) -> NarrativeBeat | None:
        """Close and return the current beat, if any."""
        if self._current_beat is not None:
            beat = self._current_beat
            self._completed_beats.append(beat)
            self._current_beat = None
            return beat
        return None

    @property
    def all_beats(self) -> list[NarrativeBeat]:
        """All completed beats so far."""
        return self._completed_beats

    def reset(self) -> None:
        """Clear all state."""
        self._current_beat = None
        self._completed_beats.clear()
