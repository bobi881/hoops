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
        """Format a single-line box score entry.

        Column widths match the header printed by ``TeamStats.format_box_score``.
        """
        name = self.display_name or self.player_id
        fg = f"{self.field_goals_made}-{self.field_goals_attempted}"
        tpt = f"{self.three_pointers_made}-{self.three_pointers_attempted}"
        return (
            f"{name:<20s} "
            f"{self.points:>4d}  "
            f"{fg:>6s}  "
            f"{tpt:>6s}  "
            f"{self.rebounds:>3d}  "
            f"{self.assists:>3d}  "
            f"{self.steals:>3d}  "
            f"{self.blocks:>3d}  "
            f"{self.turnovers:>3d}"
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
        """Format a full team box score with aligned columns."""
        lines = [
            f"\n{'=' * 80}",
            f"  {self.team_name or self.team_id}",
            f"{'=' * 80}",
            (
                f"{'Player':<20s} "
                f"{'PTS':>4s}  "
                f"{'FG':>6s}  "
                f"{'3PT':>6s}  "
                f"{'REB':>3s}  "
                f"{'AST':>3s}  "
                f"{'STL':>3s}  "
                f"{'BLK':>3s}  "
                f"{'TO':>3s}"
            ),
            "-" * 80,
        ]
        for stats in sorted(self.players.values(), key=lambda s: s.points, reverse=True):
            lines.append(stats.format_line())

        lines.append("-" * 80)
        totals = self._totals()
        fg = f"{totals['fgm']}-{totals['fga']}"
        tpt = f"{totals['tpm']}-{totals['tpa']}"
        lines.append(
            f"{'TOTAL':<20s} "
            f"{totals['points']:>4d}  "
            f"{fg:>6s}  "
            f"{tpt:>6s}  "
            f"{totals['reb']:>3d}  "
            f"{totals['ast']:>3d}  "
            f"{totals['stl']:>3d}  "
            f"{totals['blk']:>3d}  "
            f"{totals['to']:>3d}"
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

    # Maximum number of actions between a completed pass and a made shot
    # for the pass to count as an assist. Matches real-world convention of
    # "receiver must score on the next touch or take at most one dribble".
    # The counter advances on the receiver's DRIBBLE_MOVE events plus the
    # shot attempt itself, so a value of 2 allows one dribble + the shot.
    ASSIST_WINDOW_ACTIONS = 2

    def __init__(self) -> None:
        self._teams: dict[str, TeamStats] = {}
        self._player_team_map: dict[str, str] = {}
        self._last_passer: str = ""
        self._actions_since_pass: int = 0

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
        # Shot attempt consumes a "touch" relative to the last pass
        self._actions_since_pass += 1

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

        # Assist tracking: the receiver must score within ASSIST_WINDOW_ACTIONS
        # of the pass, and on a different player.
        if (
            self._last_passer
            and self._last_passer != event.player_id
            and self._actions_since_pass <= self.ASSIST_WINDOW_ACTIONS
        ):
            passer_stats = self._get_player_stats(self._last_passer)
            if passer_stats:
                passer_stats.assists += 1
        # Whether credited or not, the window closes at the next made shot.
        self._last_passer = ""
        self._actions_since_pass = 0

    def _handle_shot_missed(self, event: GameEvent) -> None:
        # Shot attempt already counted in SHOT_ATTEMPT. A miss also closes
        # the assist window -- no assist on a missed shot.
        self._last_passer = ""
        self._actions_since_pass = 0

    def _handle_free_throw(self, event: GameEvent) -> None:
        stats = self._get_player_stats(event.player_id)
        if stats is None:
            return
        stats.free_throws_attempted += 1
        if event.data.get("made", False):
            stats.free_throws_made += 1
            stats.points += 1
            team_id = self._player_team_map.get(event.player_id, "")
            if team_id in self._teams:
                self._teams[team_id].total_points += 1

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
        # Track the passer for a potential assist; reset the touch counter.
        self._last_passer = event.player_id
        self._actions_since_pass = 0

    def _handle_dribble_move(self, event: GameEvent) -> None:
        # Dribbles by the receiver after a pass narrow the assist window.
        # Skip pure defensive-adjustment sentinels (no player_id / flagged
        # in data) so we don't mistakenly count help-defense events.
        if not self._last_passer or not event.player_id:
            return
        if "defensive_adjustment" in event.data:
            return
        if event.player_id == self._last_passer:
            return
        self._actions_since_pass += 1

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
        EventType.DRIBBLE_MOVE: _handle_dribble_move,
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
        self._last_passer = ""
        self._actions_since_pass = 0
