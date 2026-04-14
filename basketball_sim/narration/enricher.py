"""Stage 2: Context Enricher -- adds excitement, momentum, streak info.

Takes raw narrative beats and enriches them with contextual metadata
that drives template selection and announcer tone. Reads tags to
determine the emotional weight of a moment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from basketball_sim.core.types import EventType
from basketball_sim.narration.aggregator import NarrativeBeat


@dataclass
class EnrichedBeat:
    """A narrative beat with added context for template selection."""
    beat: NarrativeBeat
    excitement: float = 0.0  # 0.0 (routine) to 1.0 (incredible)
    momentum_shift: float = 0.0  # -1 to 1, how much this changes momentum
    is_highlight: bool = False
    is_momentum_play: bool = False
    streak_info: str = ""  # e.g., "3rd_consecutive_make", "scoring_drought"
    context_tags: list[str] = field(default_factory=list)
    announcer_intensity: str = "normal"  # "whisper", "normal", "elevated", "hyped", "maximum"


# Tags that boost excitement
_EXCITING_TAGS = {
    "ankle_breaker": 0.40,
    "three_pointer_made": 0.25,
    "block": 0.30,
    "steal": 0.20,
    "dunk": 0.35,
    "fast_break": 0.20,
    "contested_make": 0.30,
    "tough_shot": 0.25,
    "buzzer_beater": 0.50,
    "showboat": 0.20,
    "wide_open": -0.10,  # routine play
    "on_fire": 0.15,
    "clutch_time": 0.20,
    "clutch_gene": 0.25,
    "heat_check": 0.15,
    "cross_court": 0.10,
    "showtime": 0.15,
    "help_defense_committed": 0.10,
    "rim_protection": 0.15,
}


class ContextEnricher:
    """Enriches narrative beats with excitement and context.

    Tracks game flow to detect streaks, momentum shifts, and
    escalating sequences. Uses this to set excitement level and
    announcer intensity.
    """

    def __init__(self) -> None:
        self._consecutive_makes: int = 0
        self._consecutive_misses: int = 0
        self._last_scorer: str = ""
        self._scoring_run: int = 0
        self._scoring_run_team: str = ""
        self._total_beats: int = 0

    def enrich(self, beat: NarrativeBeat) -> EnrichedBeat:
        """Add context to a narrative beat."""
        self._total_beats += 1
        enriched = EnrichedBeat(beat=beat)

        # Calculate base excitement from tags
        excitement = 0.0
        for tag in beat.tags:
            excitement += _EXCITING_TAGS.get(tag, 0.0)

        # Scoring play excitement
        if beat.is_scoring_play:
            excitement += 0.10
            if beat.point_value == 3:
                excitement += 0.10

            # Track streaks
            self._consecutive_makes += 1
            self._consecutive_misses = 0

            if self._consecutive_makes >= 3:
                enriched.streak_info = f"{self._consecutive_makes}_consecutive_makes"
                enriched.context_tags.append("hot_streak")
                excitement += min(0.15, self._consecutive_makes * 0.03)

            # Scoring run tracking
            if beat.player_id == self._last_scorer:
                self._scoring_run += beat.point_value
                if self._scoring_run >= 8:
                    enriched.context_tags.append("personal_run")
                    excitement += 0.15
            else:
                self._scoring_run = beat.point_value
                self._last_scorer = beat.player_id

        elif beat.primary_event_type == EventType.SHOT_MISSED:
            self._consecutive_misses += 1
            self._consecutive_makes = 0
            if self._consecutive_misses >= 4:
                enriched.streak_info = f"{self._consecutive_misses}_consecutive_misses"
                enriched.context_tags.append("scoring_drought")

        # Turnovers and steals are momentum-shifting
        if beat.primary_event_type in (EventType.STEAL, EventType.TURNOVER):
            enriched.momentum_shift = 0.3
            enriched.is_momentum_play = True

        # Blocks shift momentum too
        if beat.primary_event_type == EventType.BLOCK:
            enriched.momentum_shift = 0.4
            enriched.is_momentum_play = True
            excitement += 0.15

        # Game situation multipliers
        if "clutch_time" in beat.tags:
            excitement *= 1.5
        if "final_minute" in beat.tags:
            excitement *= 1.3

        # Clamp excitement
        enriched.excitement = max(0.0, min(1.0, excitement))

        # Set announcer intensity based on excitement
        if enriched.excitement >= 0.8:
            enriched.announcer_intensity = "maximum"
        elif enriched.excitement >= 0.6:
            enriched.announcer_intensity = "hyped"
        elif enriched.excitement >= 0.4:
            enriched.announcer_intensity = "elevated"
        elif enriched.excitement >= 0.15:
            enriched.announcer_intensity = "normal"
        else:
            enriched.announcer_intensity = "whisper"

        # Mark highlights
        enriched.is_highlight = enriched.excitement >= 0.5

        return enriched

    def reset(self) -> None:
        """Reset tracking state."""
        self._consecutive_makes = 0
        self._consecutive_misses = 0
        self._last_scorer = ""
        self._scoring_run = 0
        self._scoring_run_team = ""
        self._total_beats = 0
