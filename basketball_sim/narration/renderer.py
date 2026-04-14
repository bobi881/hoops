"""Stage 4: Prose Renderer -- fills templates with game data and outputs text.

Takes a selected template and an enriched beat, substitutes player names,
game data, and announcer-specific fragments to produce final narration text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basketball_sim.core.types import EventType
from basketball_sim.narration.aggregator import NarrativeBeat
from basketball_sim.narration.enricher import EnrichedBeat
from basketball_sim.narration.templates import AnnouncerProfile, NarrationTemplate


@dataclass
class RenderedNarration:
    """Final rendered narration text with metadata."""
    text: str
    beat: NarrativeBeat
    excitement: float = 0.0
    is_highlight: bool = False
    quarter: int = 1
    game_clock: float = 0.0


class ProseRenderer:
    """Fills templates with player-specific data and applies announcer style.

    Template variables:
    - {player}: Ball handler / primary actor
    - {defender}: Primary defender
    - {target}: Pass target
    - {move}: Dribble move name
    - {shot_type}: Type of shot
    - {cell}: Grid position
    - {points}: Point value
    - {score}: Current score
    - {quarter}: Current quarter
    - {clock}: Game clock
    - {team}: Offensive team name
    """

    def __init__(
        self,
        profile: AnnouncerProfile | None = None,
        player_names: dict[str, str] | None = None,
        team_names: dict[str, str] | None = None,
    ) -> None:
        self._profile = profile
        self._player_names = player_names or {}
        self._team_names = team_names or {}

    def render(
        self,
        template: NarrationTemplate | None,
        enriched: EnrichedBeat,
    ) -> RenderedNarration:
        """Render a template with game data, or generate fallback text."""
        beat = enriched.beat

        if template is None:
            text = self._fallback_text(enriched)
        else:
            text = self._fill_template(template.text, enriched)

        # Apply announcer style emphasis
        if enriched.announcer_intensity == "maximum" and self._profile:
            if self._profile.signature_phrases:
                import random
                phrase = random.choice(self._profile.signature_phrases)
                # Prepend signature phrase if not already in text
                if phrase.upper() not in text.upper():
                    text = f"{phrase}! {text}"

        return RenderedNarration(
            text=text,
            beat=beat,
            excitement=enriched.excitement,
            is_highlight=enriched.is_highlight,
            quarter=beat.quarter,
            game_clock=beat.game_clock,
        )

    def _fill_template(self, template_text: str, enriched: EnrichedBeat) -> str:
        """Replace template variables with actual game data."""
        beat = enriched.beat
        data: dict[str, Any] = {}

        # Collect data from all events in the beat
        for event in beat.events:
            data.update(event.data)

        # Build substitution map
        subs: dict[str, str] = {
            "player": self._resolve_name(beat.player_id),
            "defender": data.get("defender_name", "the defender"),
            "target": self._resolve_name(data.get("target_id", "")),
            "move": _humanize_move(data.get("move", "")),
            "shot_type": _humanize_shot_type(data.get("shot_type", "")),
            "cell": data.get("cell", ""),
            "points": str(data.get("points", "")),
            "score": str(data.get("score", "")),
            "quarter": _ordinal(beat.quarter),
            "clock": _format_clock(beat.game_clock),
            "team": self._team_names.get(data.get("team", ""), "the offense"),
            "contest": _contest_description(data.get("contest", 0.5)),
            "rebound_type": data.get("rebound_type", ""),
            "rebounder": self._resolve_name(data.get("rebounder_id", "")),
            "pass_type": _humanize_pass_type(data.get("pass_type", "")),
        }

        # Fill template
        result = template_text
        for key, value in subs.items():
            result = result.replace(f"{{{key}}}", str(value))

        # Clean up any unfilled placeholders
        result = re.sub(r"\{[a-z_]+\}", "", result)
        # Clean up double spaces
        result = re.sub(r"  +", " ", result).strip()

        return result

    def _fallback_text(self, enriched: EnrichedBeat) -> str:
        """Generate simple fallback text when no template matches."""
        beat = enriched.beat
        player = self._resolve_name(beat.player_id)
        event_type = beat.primary_event_type

        if event_type == EventType.SHOT_MADE:
            points = beat.point_value
            return f"{player} scores{f' for {points}' if points else ''}."
        elif event_type == EventType.SHOT_MISSED:
            return f"{player} misses."
        elif event_type == EventType.SHOT_ATTEMPT:
            if beat.is_scoring_play:
                return f"{player} hits the shot!"
            return f"{player} puts up a shot."
        elif event_type == EventType.DRIBBLE_MOVE:
            return f"{player} works the handle."
        elif event_type == EventType.PASS_COMPLETED:
            return f"{player} finds the open man."
        elif event_type == EventType.STEAL:
            return f"Stolen by {player}!"
        elif event_type == EventType.TURNOVER:
            return f"Turnover by {player}."
        elif event_type == EventType.REBOUND:
            return f"Rebound {player}."
        elif event_type == EventType.BLOCK:
            return f"Blocked by {player}!"
        elif event_type == EventType.FOUL_COMMITTED:
            return f"Foul on {player}."
        elif event_type == EventType.QUARTER_START:
            q = beat.quarter
            return f"Start of the {_ordinal(q)} quarter."
        elif event_type == EventType.QUARTER_END:
            return f"End of the {_ordinal(beat.quarter)} quarter."
        elif event_type == EventType.GAME_START:
            return "Tip-off! The game is underway."
        elif event_type == EventType.GAME_END:
            return "That's the final buzzer!"
        elif event_type == EventType.TIMEOUT:
            return "Timeout called."
        elif event_type == EventType.SUBSTITUTION:
            return "Substitution coming in."
        elif event_type == EventType.POSSESSION_START:
            return ""  # Silent
        elif event_type == EventType.POSSESSION_END:
            return ""  # Silent

        return ""

    def _resolve_name(self, player_id: str) -> str:
        """Look up a player's display name."""
        if not player_id:
            return "a player"
        return self._player_names.get(player_id, player_id)


def _humanize_move(move_id: str) -> str:
    """Convert a move ID to human-readable text."""
    return move_id.replace("_", " ").title() if move_id else "the move"


def _humanize_shot_type(shot_type: str) -> str:
    """Convert a shot type to human-readable text."""
    mapping = {
        "three_pointer": "three-pointer",
        "corner_three": "corner three",
        "mid_range": "mid-range jumper",
        "driving_layup": "driving layup",
        "layup": "layup",
        "dunk": "dunk",
        "floater": "floater",
        "pull_up_three": "pull-up three",
        "pull_up_mid": "pull-up jumper",
        "contested_three": "contested three",
        "contested_mid_range": "contested jumper",
    }
    return mapping.get(shot_type, shot_type.replace("_", " "))


def _humanize_pass_type(pass_type: str) -> str:
    """Convert a pass type to readable text."""
    mapping = {
        "chest_pass": "chest pass",
        "bounce_pass": "bounce pass",
        "skip_pass": "skip pass",
        "lob_pass": "lob pass",
        "no_look": "no-look pass",
    }
    return mapping.get(pass_type, pass_type.replace("_", " "))


def _contest_description(contest: float) -> str:
    """Convert contest value to a description."""
    if contest < 0.15:
        return "wide open"
    elif contest < 0.35:
        return "open"
    elif contest < 0.55:
        return "lightly contested"
    elif contest < 0.75:
        return "contested"
    else:
        return "heavily contested"


def _ordinal(n: int) -> str:
    """Convert integer to ordinal string (1st, 2nd, 3rd, 4th)."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_clock(seconds: float) -> str:
    """Format game clock seconds to mm:ss."""
    if seconds <= 0:
        return "0:00"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"
