"""Coach AI -- rotation management, timeout logic, scheme adjustments.

Models the coaching decisions that happen during a game: when to call
timeouts, how to manage player rotations, and when to adjust
defensive/offensive schemes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from basketball_sim.core.types import (
    EventType,
    GameEvent,
    GameState,
    Player,
    TeamState,
)
from basketball_sim.modifiers.coaching import set_coaching_adjustment

logger = logging.getLogger(__name__)


@dataclass
class RotationSlot:
    """A player's rotation info."""
    player_id: str
    minutes_played: float = 0.0
    minutes_target: float = 24.0  # target minutes per game
    is_starter: bool = False
    fatigue_threshold: float = 0.4  # sub out when fatigue drops below this


@dataclass
class CoachState:
    """Persistent state for a coach during a game."""
    team_id: str
    rotations: list[RotationSlot] = field(default_factory=list)
    timeouts_called: int = 0
    last_timeout_clock: float = 720.0
    opponent_run: int = 0  # consecutive points by opponent without a score
    our_run: int = 0
    adjustments_made: list[str] = field(default_factory=list)


class CoachAI:
    """Manages coaching decisions for a team during a game.

    Handles:
    - Player rotations based on minutes and fatigue
    - Timeout calls based on opponent runs and game flow
    - Scheme adjustments based on what's working
    """

    def __init__(self, team: TeamState) -> None:
        self.team = team
        self.state = CoachState(team_id=team.team_id)
        self._init_rotations()

    def _init_rotations(self) -> None:
        """Set up initial rotation plan based on roster."""
        starters = self.team.on_court[:5] if len(self.team.on_court) >= 5 else [
            p.player_id for p in self.team.players[:5]
        ]

        for player in self.team.players:
            is_starter = player.player_id in starters
            self.state.rotations.append(RotationSlot(
                player_id=player.player_id,
                minutes_target=32.0 if is_starter else 16.0,
                is_starter=is_starter,
            ))

    def evaluate_timeout(self, game: GameState) -> GameEvent | None:
        """Decide whether to call a timeout.

        Call a timeout when:
        - Opponent is on a big run (7+ unanswered)
        - Late in a close game for strategy
        - Team needs rest
        """
        team_state = (
            game.home_team
            if game.home_team.team_id == self.team.team_id
            else game.away_team
        )

        if team_state.timeouts_remaining <= 0:
            return None

        # Don't call timeouts too frequently
        time_since_last = self.state.last_timeout_clock - game.game_clock
        if time_since_last < 60.0:  # at least 1 minute between timeouts
            return None

        should_call = False
        reason = ""

        # Opponent on a run
        if self.state.opponent_run >= 7:
            should_call = True
            reason = "stop_opponent_run"

        # Late game strategy
        if game.quarter >= 4 and game.game_clock <= 120.0:
            score_diff = abs(game.score.get("home", 0) - game.score.get("away", 0))
            if score_diff <= 5:
                should_call = True
                reason = "late_game_strategy"

        if should_call:
            team_state.timeouts_remaining -= 1
            self.state.timeouts_called += 1
            self.state.last_timeout_clock = game.game_clock
            self.state.opponent_run = 0

            return GameEvent(
                event_type=EventType.TIMEOUT,
                data={
                    "team": self.team.team_id,
                    "reason": reason,
                    "timeouts_remaining": team_state.timeouts_remaining,
                },
                tags=["timeout", reason],
                game_clock=game.game_clock,
                quarter=game.quarter,
            )

        return None

    def evaluate_substitution(self, game: GameState) -> list[GameEvent]:
        """Decide whether to make substitutions based on fatigue and minutes."""
        events: list[GameEvent] = []
        team_state = (
            game.home_team
            if game.home_team.team_id == self.team.team_id
            else game.away_team
        )

        on_court_ids = set(team_state.on_court)
        bench_ids = [
            p.player_id for p in team_state.players
            if p.player_id not in on_court_ids
        ]

        if not bench_ids:
            return events

        # Find tired players who need rest
        players_by_id = {p.player_id: p for p in team_state.players}

        for slot in self.state.rotations:
            if slot.player_id not in on_court_ids:
                continue

            player = players_by_id.get(slot.player_id)
            if player is None:
                continue

            # Check fatigue
            avg_fatigue = (
                player.fatigue.cardiovascular
                + player.fatigue.muscular
                + player.fatigue.mental
            ) / 3.0

            needs_rest = avg_fatigue < slot.fatigue_threshold

            # Check minutes (simplified: each quarter = 12 minutes)
            # In a real implementation, we'd track actual minutes
            if needs_rest and bench_ids:
                sub_in = bench_ids.pop(0)
                sub_out = slot.player_id

                # Swap on court list
                team_state.on_court = [
                    sub_in if pid == sub_out else pid
                    for pid in team_state.on_court
                ]

                events.append(GameEvent(
                    event_type=EventType.SUBSTITUTION,
                    data={
                        "team": self.team.team_id,
                        "sub_in": sub_in,
                        "sub_out": sub_out,
                        "reason": "fatigue",
                    },
                    tags=["substitution"],
                    game_clock=game.game_clock,
                    quarter=game.quarter,
                ))

        return events

    def adjust_scheme(self, game: GameState) -> None:
        """Make scheme adjustments based on game flow.

        Adjusts coaching modifier parameters based on what's happening.
        """
        team_id = self.team.team_id
        other_id = (
            game.away_team.team_id
            if game.home_team.team_id == team_id
            else game.home_team.team_id
        )

        # If opponent is scoring a lot inside, increase paint protection
        # (Simplified: check score differential)
        score_diff = game.score.get("home", 0) - game.score.get("away", 0)
        if team_id == game.away_team.team_id:
            score_diff = -score_diff

        if score_diff < -8:
            # We're losing -- increase defensive intensity
            set_coaching_adjustment(team_id, "defensive_intensity", 0.8)
            set_coaching_adjustment(team_id, "pace", 0.7)  # push pace to catch up
            if "increased_intensity" not in self.state.adjustments_made:
                self.state.adjustments_made.append("increased_intensity")
                logger.info("Coach %s: increasing defensive intensity", team_id)
        elif score_diff > 10:
            # Comfortable lead -- manage pace
            set_coaching_adjustment(team_id, "pace", 0.3)
            set_coaching_adjustment(team_id, "defensive_intensity", 0.6)

    def track_scoring_run(self, event: GameEvent, game: GameState) -> None:
        """Track scoring runs to inform timeout decisions."""
        if event.event_type == EventType.SHOT_MADE:
            points = event.data.get("points", 0)
            # Determine which team scored
            scorer_id = event.player_id

            # Check if scorer is on our team
            our_player_ids = {p.player_id for p in self.team.players}
            if scorer_id in our_player_ids:
                self.state.our_run += points
                self.state.opponent_run = 0
            else:
                self.state.opponent_run += points
                self.state.our_run = 0
