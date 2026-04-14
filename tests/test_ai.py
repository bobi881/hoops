"""Tests for Phase 3 AI decision-making."""

from __future__ import annotations

import random

from basketball_sim.core.types import (
    Action,
    ActionType,
    BallHandlerRhythm,
    DefenderBalance,
    DefenderPositioning,
    DefenderStance,
    GameState,
    HelpDefenseStatus,
    MatchupState,
    OffBallState,
    Player,
    PlayerAttributes,
    PlayerOnCourt,
    PossessionState,
    TeamState,
)
from basketball_sim.ai.offensive_ai import BasicOffensiveAI
from basketball_sim.ai.defensive_ai import BasicDefensiveAI
from basketball_sim.ai.coach_ai import CoachAI
from basketball_sim.data.loader import load_moves


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _player(pid: str = "p1", **attr_overrides) -> Player:
    p = Player(
        player_id=pid,
        display_name=f"Player {pid}",
        team_id="t1",
        position="PG",
    )
    for attr, val in attr_overrides.items():
        if hasattr(p.attributes, attr):
            setattr(p.attributes, attr, val)
    return p


def _game(seed: int = 42, score: dict | None = None, quarter: int = 1, clock: float = 720.0) -> GameState:
    home = TeamState(team_id="t1", name="Home", players=[
        _player(f"h{i}") for i in range(1, 11)
    ], on_court=[f"h{i}" for i in range(1, 6)])
    away = TeamState(team_id="t2", name="Away", players=[
        _player(f"a{i}") for i in range(1, 11)
    ], on_court=[f"a{i}" for i in range(1, 6)])

    for p in away.players:
        p.team_id = "t2"

    return GameState(
        home_team=home,
        away_team=away,
        quarter=quarter,
        game_clock=clock,
        possession_team_id="t1",
        score=score or {"home": 50, "away": 50},
        rng=random.Random(seed),
    )


def _possession(
    game: GameState,
    matchup: MatchupState | None = None,
    shot_clock: float = 24.0,
    n_actions: int = 0,
) -> PossessionState:
    off_players = [p for p in game.home_team.players if p.player_id in game.home_team.on_court]
    def_players = [p for p in game.away_team.players if p.player_id in game.away_team.on_court]

    bh = PlayerOnCourt(
        player=off_players[0],
        cell="D6",
        matchup=matchup or MatchupState(),
        is_ball_handler=True,
    )

    off_ball = [
        OffBallState(player=off_players[i], cell=["B6", "F6", "A5", "G5"][i-1], openness=0.3)
        for i in range(1, min(5, len(off_players)))
    ]

    defense = [
        PlayerOnCourt(player=def_players[i], cell=["D6", "B6", "F6", "C3", "E3"][i])
        for i in range(min(5, len(def_players)))
    ]

    possession = PossessionState(
        ball_handler=bh,
        off_ball_offense=off_ball,
        defense=defense,
        shot_clock=shot_clock,
        game_clock=game.game_clock,
        quarter=game.quarter,
        score=dict(game.score),
        offensive_team_id="t1",
        defensive_team_id="t2",
    )

    # Simulate prior actions
    for _ in range(n_actions):
        possession.actions_this_possession.append(
            Action(action_type=ActionType.DRIBBLE_MOVE, player_id="h1")
        )

    return possession


# ---------------------------------------------------------------------------
# Offensive AI tests
# ---------------------------------------------------------------------------

class TestBasicOffensiveAI:
    def setup_method(self):
        self.moves = load_moves()
        self.ai = BasicOffensiveAI(move_registry=self.moves)

    def test_decide_returns_action(self):
        game = _game()
        possession = _possession(game)
        action = self.ai.decide(possession, game)
        assert isinstance(action, Action)
        assert action.player_id == "h1"

    def test_shot_clock_pressure_forces_shot(self):
        game = _game()
        possession = _possession(game, shot_clock=3.0)
        action = self.ai.decide(possession, game)
        assert action.action_type == ActionType.SHOT

    def test_beaten_defender_attacks(self):
        game = _game()
        matchup = MatchupState(positioning=DefenderPositioning.BEATEN)
        possession = _possession(game, matchup=matchup)
        action = self.ai.decide(possession, game)
        # Should drive or shoot, not dribble
        assert action.action_type in (ActionType.SHOT, ActionType.DRIVE)

    def test_defender_on_floor_capitalizes(self):
        game = _game()
        matchup = MatchupState(balance=DefenderBalance.ON_FLOOR)
        possession = _possession(game, matchup=matchup)
        action = self.ai.decide(possession, game)
        assert action.action_type in (ActionType.SHOT, ActionType.DRIVE)

    def test_force_shot(self):
        game = _game()
        possession = _possession(game)
        action = self.ai.force_shot(possession, game)
        assert action.action_type == ActionType.SHOT

    def test_dribble_move_selection(self):
        game = _game()
        possession = _possession(game, shot_clock=20.0)
        # With default matchup (LOCKED_UP, SET), should dribble
        action = self.ai.decide(possession, game)
        # Could be dribble, pass, or shot depending on RNG
        assert action.action_type in (
            ActionType.DRIBBLE_MOVE, ActionType.PASS, ActionType.SHOT
        )

    def test_multiple_decisions_deterministic(self):
        """Same seed produces same decisions."""
        game1 = _game(seed=123)
        game2 = _game(seed=123)
        poss1 = _possession(game1)
        poss2 = _possession(game2)
        action1 = self.ai.decide(poss1, game1)
        action2 = self.ai.decide(poss2, game2)
        assert action1.action_type == action2.action_type
        assert action1.data == action2.data


# ---------------------------------------------------------------------------
# Defensive AI tests
# ---------------------------------------------------------------------------

class TestBasicDefensiveAI:
    def setup_method(self):
        self.ai = BasicDefensiveAI()

    def test_react_returns_events(self):
        game = _game()
        possession = _possession(game)
        action = Action(
            action_type=ActionType.DRIBBLE_MOVE,
            player_id="h1",
            data={"move": "crossover"},
        )
        events = self.ai.react(action, possession, game)
        assert isinstance(events, list)

    def test_help_defense_triggers_on_beaten(self):
        game = _game(seed=1)
        matchup = MatchupState(positioning=DefenderPositioning.BEATEN)
        possession = _possession(game, matchup=matchup)
        action = Action(
            action_type=ActionType.DRIBBLE_MOVE,
            player_id="h1",
        )
        events = self.ai.react(action, possession, game)
        # Help defense should trigger
        help_tags = [tag for e in events for tag in e.tags if "help_defense" in tag]
        assert len(help_tags) > 0 or matchup.help_status != HelpDefenseStatus.NO_HELP

    def test_react_to_drive(self):
        game = _game()
        possession = _possession(game)
        action = Action(
            action_type=ActionType.DRIVE,
            player_id="h1",
            data={"direction": "basket"},
        )
        events = self.ai.react(action, possession, game)
        assert isinstance(events, list)

    def test_react_to_shot(self):
        game = _game()
        possession = _possession(game)
        action = Action(
            action_type=ActionType.SHOT,
            player_id="h1",
            data={"shot_type": "mid_range"},
        )
        events = self.ai.react(action, possession, game)
        assert isinstance(events, list)


# ---------------------------------------------------------------------------
# Coach AI tests
# ---------------------------------------------------------------------------

class TestCoachAI:
    def test_init(self):
        team = TeamState(
            team_id="t1", name="Home",
            players=[_player(f"p{i}") for i in range(1, 11)],
            on_court=[f"p{i}" for i in range(1, 6)],
        )
        coach = CoachAI(team)
        assert coach.state.team_id == "t1"
        assert len(coach.state.rotations) == 10

    def test_timeout_on_run(self):
        team = TeamState(
            team_id="t1", name="Home",
            players=[_player(f"p{i}") for i in range(1, 11)],
            on_court=[f"p{i}" for i in range(1, 6)],
            timeouts_remaining=5,
        )
        coach = CoachAI(team)
        game = _game()
        # Simulate an opponent scoring run
        coach.state.opponent_run = 10
        coach.state.last_timeout_clock = 720.0
        game.game_clock = 600.0

        timeout_event = coach.evaluate_timeout(game)
        assert timeout_event is not None
        assert "stop_opponent_run" in timeout_event.tags

    def test_no_timeout_without_run(self):
        team = TeamState(
            team_id="t1", name="Home",
            players=[_player(f"p{i}") for i in range(1, 6)],
            on_court=[f"p{i}" for i in range(1, 6)],
            timeouts_remaining=5,
        )
        coach = CoachAI(team)
        game = _game()
        coach.state.opponent_run = 2
        timeout_event = coach.evaluate_timeout(game)
        assert timeout_event is None

    def test_no_timeout_when_none_remaining(self):
        team = TeamState(
            team_id="t1", name="Home",
            players=[_player(f"p{i}") for i in range(1, 6)],
            on_court=[f"p{i}" for i in range(1, 6)],
            timeouts_remaining=0,
        )
        coach = CoachAI(team)
        game = _game()
        coach.state.opponent_run = 15
        timeout_event = coach.evaluate_timeout(game)
        assert timeout_event is None

    def test_scheme_adjustment(self):
        from basketball_sim.modifiers.coaching import reset_coaching, get_coaching_adjustment
        reset_coaching()

        team = TeamState(
            team_id="t1", name="Home",
            players=[_player(f"p{i}") for i in range(1, 6)],
            on_court=[f"p{i}" for i in range(1, 6)],
        )
        coach = CoachAI(team)
        game = _game(score={"home": 40, "away": 60})  # losing by 20

        coach.adjust_scheme(game)
        assert get_coaching_adjustment("t1", "defensive_intensity") > 0.5
