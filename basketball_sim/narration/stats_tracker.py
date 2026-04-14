"""Stats tracker -- accumulates box score statistics from game events.

Subscribes to the event bus and builds player and team statistics
as events flow through. Generates box scores and summary stats.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from basketball_sim.core.types import EventType, GameEvent


@dataclass
class PlayerStats:
    """Box score statistics for a single player."""
    player_id: str
    display_name: str = ""
    minutes: float = 0.0
    points: int = 0
    field_goals_made: int = 0
    field_goals_attempted: int = 0
    three_pointers_made: int = 0
    three_pointers_attempted: int = 0
    free_throws_made: int = 0
    free_throws_attempted: int = 0
    offensive_rebounds: int = 0
    defensive_rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    fouls: int = 0

    @property
    def rebounds(self) -> int:
        return self.offensive_rebounds + self.defensive_rebounds

    @property
    def fg_pct(self) -> float:
        if self.field_goals_attempted == 0:
            return 0.0
        return self.field_goals_made / self.field_goals_attempted

    @property
    def three_pct(self) -> float:
        if self.three_pointers_attempted == 0:
            return 0.0
        return self.three_pointers_made / self.three_pointers_attempted

    @property
    def ft_pct(self) -> float:
        if self.free_throws_attempted == 0:
            return 0.0
        return self.free_throws_made / self.free_throws_attempted

    def format_line(self) -> str:
        """Format a single-line box score entry."""
        name = self.display_name or self.player_id
        return (
            f"{name:<20s} "
            f"{self.points:>3d} PTS  "
            f"{self.field_goals_made:>2d}-{self.field_goals_attempted:<2d} FG  "
            f"{self.three_pointers_made:>2d}-{self.three_pointers_attempted:<2d} 3PT  "
            f"{self.rebounds:>2d} REB  "
            f"{self.assists:>2d} AST  "
            f"{self.steals:>2d} STL  "
            f"{self.blocks:>2d} BLK  "
            f"{self.turnovers:>2d} TO"
        )


@dataclass
class TeamStats:
    """Aggregate team statistics."""
    team_id: str
    team_name: str = ""
    players: dict[str, PlayerStats] = field(default_factory=dict)
    total_points: int = 0
    fast_break_points: int = 0
    points_in_paint: int = 0
    second_chance_points: int = 0
    bench_points: int = 0

    def format_box_score(self) -> str:
        """Format a full team box score."""
        lines = [
            f"\n{'=' * 80}",
            f"  {self.team_name or self.team_id}",
            f"{'=' * 80}",
            f"{'Player':<20s} {'PTS':>4s}  {'FG':>6s}  {'3PT':>6s}  {'REB':>3s}  {'AST':>3s}  {'STL':>3s}  {'BLK':>3s}  {'TO':>3s}",
            "-" * 80,
        ]
        for stats in sorted(self.players.values(), key=lambda s: s.points, reverse=True):
            lines.append(stats.format_line())

        lines.append("-" * 80)
        totals = self._totals()
        lines.append(
            f"{'TOTAL':<20s} "
            f"{totals['points']:>3d} PTS  "
            f"{totals['fgm']:>2d}-{totals['fga']:<2d} FG  "
            f"{totals['tpm']:>2d}-{totals['tpa']:<2d} 3PT  "
            f"{totals['reb']:>2d} REB  "
            f"{totals['ast']:>2d} AST  "
            f"{totals['stl']:>2d} STL  "
            f"{totals['blk']:>2d} BLK  "
            f"{totals['to']:>2d} TO"
        )
        return "\n".join(lines)

    def _totals(self) -> dict[str, int]:
        return {
            "points": sum(p.points for p in self.players.values()),
            "fgm": sum(p.field_goals_made for p in self.players.values()),
            "fga": sum(p.field_goals_attempted for p in self.players.values()),
            "tpm": sum(p.three_pointers_made for p in self.players.values()),
            "tpa": sum(p.three_pointers_attempted for p in self.players.values()),
            "reb": sum(p.rebounds for p in self.players.values()),
            "ast": sum(p.assists for p in self.players.values()),
            "stl": sum(p.steals for p in self.players.values()),
            "blk": sum(p.blocks for p in self.players.values()),
            "to": sum(p.turnovers for p in self.players.values()),
        }


class StatsTracker:
    """Subscribes to game events and accumulates statistics.

    Usage:
        tracker = StatsTracker()
        event_bus.subscribe_all(tracker.handle_event)
        # ... run game ...
        print(tracker.format_box_scores())
    """

    def __init__(self) -> None:
        self._teams: dict[str, TeamStats] = {}
        self._player_team_map: dict[str, str] = {}
        self._last_shot_player: str = ""  # for assist tracking
        self._last_passer: str = ""

    def register_team(self, team_id: str, team_name: str = "") -> None:
        """Register a team for stat tracking."""
        self._teams[team_id] = TeamStats(team_id=team_id, team_name=team_name)

    def register_player(
        self, player_id: str, team_id: str, display_name: str = ""
    ) -> None:
        """Register a player for stat tracking."""
        self._player_team_map[player_id] = team_id
        if team_id in self._teams:
            self._teams[team_id].players[player_id] = PlayerStats(
                player_id=player_id,
                display_name=display_name,
            )

    def handle_event(self, event: GameEvent) -> None:
        """Process a game event and update stats. Designed as an event bus handler."""
        handler = self._handlers.get(event.event_type)
        if handler:
            handler(self, event)

    def _handle_shot_attempt(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        stats.field_goals_attempted += 1
        shot_type = event.data.get("shot_type", "")
        if "three" in shot_type:
            stats.three_pointers_attempted += 1
        self._last_shot_player = event.player_id

    def _handle_shot_made(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        points = event.data.get("points", 2)
        stats.points += points
        stats.field_goals_made += 1

        shot_type = event.data.get("shot_type", "")
        if "three" in shot_type or points == 3:
            stats.three_pointers_made += 1

        # Update team total
        team_id = self._player_team_map.get(event.player_id, "")
        if team_id in self._teams:
            self._teams[team_id].total_points += points

        # Assist tracking: if the last action was a pass to this player
        if self._last_passer and self._last_passer != event.player_id:
            passer_stats = self._get_player_stats(self._last_passer)
            if passer_stats:
                passer_stats.assists += 1
            self._last_passer = ""

    def _handle_shot_missed(self, event: GameEvent) -> None:
        # Shot attempt already counted in SHOT_ATTEMPT
        pass

    def _handle_free_throw(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        stats.free_throws_attempted += 1
        if event.data.get("made", False):
            stats.free_throws_made += 1
            stats.points += 1

    def _handle_rebound(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        reb_type = event.data.get("rebound_type", "defensive")
        if reb_type == "offensive":
            stats.offensive_rebounds += 1
        else:
            stats.defensive_rebounds += 1

    def _handle_steal(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        stats.steals += 1

    def _handle_block(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        stats.blocks += 1

    def _handle_turnover(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        stats.turnovers += 1

    def _handle_foul(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        stats.fouls += 1

    def _handle_pass_completed(self, event: GameEvent) -> None:
        # Track the passer for potential assist
        self._last_passer = event.player_id

    def _handle_assist(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        stats.assists += 1

    _handlers = {
        EventType.SHOT_ATTEMPT: _handle_shot_attempt,
        EventType.SHOT_MADE: _handle_shot_made,
        EventType.SHOT_MISSED: _handle_shot_missed,
        EventType.FREE_THROW: _handle_free_throw,
        EventType.REBOUND: _handle_rebound,
        EventType.STEAL: _handle_steal,
        EventType.BLOCK: _handle_block,
        EventType.TURNOVER: _handle_turnover,
        EventType.FOUL_COMMITTED: _handle_foul,
        EventType.PASS_COMPLETED: _handle_pass_completed,
        EventType.ASSIST: _handle_assist,
    }

    def _get_player_stats(self, player_id: str) -> PlayerStats | None:
        """Look up a player's stats object."""
        team_id = self._player_team_map.get(player_id, "")
        if team_id not in self._teams:
            return None
        return self._teams[team_id].players.get(player_id)

    def get_team_stats(self, team_id: str) -> TeamStats | None:
        """Get stats for a team."""
        return self._teams.get(team_id)

    def format_box_scores(self) -> str:
        """Format box scores for all teams."""
        sections = []
        for team in self._teams.values():
            sections.append(team.format_box_score())
        return "\n".join(sections)

    def reset(self) -> None:
        """Clear all stats."""
        self._teams.clear()
        self._player_team_map.clear()
        self._last_shot_player = ""
        self._last_passer = ""
