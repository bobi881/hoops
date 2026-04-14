"""Tests for Phase 5 realism modifier layers."""

from __future__ import annotations

import random

from basketball_sim.core.types import (
    Action,
    ActionContext,
    ActionType,
    AggregatedModifier,
    FatigueState,
    GameState,
    MatchupState,
    Modifier,
    OffBallState,
    Player,
    PlayerAttributes,
    PlayerMentalState,
    PlayerOnCourt,
    PlayerTendencies,
    PossessionState,
    TeamState,
)
from basketball_sim.modifiers.fatigue import fatigue_modifier
from basketball_sim.modifiers.psychology import psychology_modifier
from basketball_sim.modifiers.tendencies import tendencies_modifier
from basketball_sim.modifiers.history import (
    history_modifier,
    record_action,
    reset_history,
)
from basketball_sim.modifiers.situational import situational_modifier
from basketball_sim.modifiers.chemistry import (
    chemistry_modifier,
    get_chemistry,
    reset_chemistry,
    set_chemistry,
)
from basketball_sim.modifiers.coaching import (
    coaching_modifier,
    get_coaching_adjustment,
    reset_coaching,
    set_coaching_adjustment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _player(
    pid: str = "p1",
    fatigue: FatigueState | None = None,
    mental: PlayerMentalState | None = None,
    tendencies: PlayerTendencies | None = None,
    attributes: PlayerAttributes | None = None,
) -> Player:
    p = Player(
        player_id=pid,
        display_name=f"Player {pid}",
        team_id="t1",
        position="PG",
    )
    if fatigue:
        p.fatigue = fatigue
    if mental:
        p.mental = mental
    if tendencies:
        p.tendencies = tendencies
    if attributes:
        p.attributes = attributes
    return p


def _context(
    attacker: Player | None = None,
    defender: Player | None = None,
    action_type: ActionType = ActionType.DRIBBLE_MOVE,
    data: dict | None = None,
    cell: str = "D6",
    shot_clock: float = 24.0,
    game_clock: float = 720.0,
    quarter: int = 1,
    score: dict | None = None,
    off_team: str = "t1",
    seed: int = 42,
) -> ActionContext:
    atk = attacker or _player("p1")
    dfn = defender or _player("d1", attributes=PlayerAttributes(basketball_iq=70))
    dfn.team_id = "t2"

    poc = PlayerOnCourt(player=atk, cell=cell, matchup=MatchupState())
    possession = PossessionState(
        ball_handler=poc,
        off_ball_offense=[OffBallState(player=_player("p2"), cell="B6")],
        defense=[PlayerOnCourt(player=dfn, cell="D6")],
        shot_clock=shot_clock,
        game_clock=game_clock,
        quarter=quarter,
        score=score or {"home": 50, "away": 50},
        offensive_team_id=off_team,
        defensive_team_id="t2" if off_team == "t1" else "t1",
    )
    game = GameState(
        home_team=TeamState(team_id="t1", name="Home"),
        away_team=TeamState(team_id="t2", name="Away"),
        quarter=quarter,
        game_clock=game_clock,
        score=score or {"home": 50, "away": 50},
    )
    return ActionContext(
        action=Action(action_type=action_type, player_id=atk.player_id, data=data or {}),
        attacker=atk,
        defender=dfn,
        matchup=MatchupState(),
        possession=possession,
        game_state=game,
        rng=random.Random(seed),
        cell=cell,
    )


# ---------------------------------------------------------------------------
# Fatigue modifier tests
# ---------------------------------------------------------------------------

class TestFatigueModifier:
    def test_fresh_player_neutral(self):
        ctx = _context()
        mod = fatigue_modifier(ctx)
        # Fresh player (all 1.0) should get near-zero penalties
        assert abs(mod.positioning_boost) < 0.01
        assert abs(mod.balance_boost) < 0.01
        assert abs(mod.shot_pct_boost) < 0.01

    def test_tired_attacker_negative(self):
        tired = _player("p1", fatigue=FatigueState(
            cardiovascular=0.3, muscular=0.4, mental=0.5, accumulated=0.8
        ))
        ctx = _context(attacker=tired)
        mod = fatigue_modifier(ctx)
        # Tired attacker should get negative boosts
        assert mod.positioning_boost < -0.01
        assert mod.shot_pct_boost < -0.01

    def test_tired_defender_positive(self):
        tired_def = _player("d1", fatigue=FatigueState(
            cardiovascular=0.3, muscular=0.3, mental=0.4, accumulated=0.7
        ))
        tired_def.team_id = "t2"
        ctx = _context(defender=tired_def)
        mod = fatigue_modifier(ctx)
        # Tired defender helps the attacker
        # The net effect should be positive because attacker is fresh, defender is tired
        assert mod.stance_boost > 0

    def test_gassed_tag(self):
        gassed = _player("p1", fatigue=FatigueState(
            cardiovascular=0.2, muscular=0.2, mental=0.3, accumulated=0.5
        ))
        ctx = _context(attacker=gassed)
        mod = fatigue_modifier(ctx)
        assert "gassed" in mod.tags

    def test_winded_tag(self):
        winded = _player("p1", fatigue=FatigueState(
            cardiovascular=0.5, muscular=0.5, mental=0.7, accumulated=0.9
        ))
        ctx = _context(attacker=winded)
        mod = fatigue_modifier(ctx)
        assert "winded" in mod.tags


# ---------------------------------------------------------------------------
# Psychology modifier tests
# ---------------------------------------------------------------------------

class TestPsychologyModifier:
    def test_confident_player_positive(self):
        confident = _player("p1", mental=PlayerMentalState(
            confidence=0.9, momentum=0.5, focus=0.8
        ))
        ctx = _context(attacker=confident)
        mod = psychology_modifier(ctx)
        assert mod.shot_pct_boost > 0
        assert "feeling_it" in mod.tags

    def test_frustrated_player_negative(self):
        frustrated = _player("p1", mental=PlayerMentalState(
            confidence=0.3, frustration=0.8, focus=0.4
        ))
        ctx = _context(attacker=frustrated)
        mod = psychology_modifier(ctx)
        assert mod.shot_pct_boost < 0
        assert "frustrated" in mod.tags

    def test_on_fire_tag(self):
        hot = _player("p1", mental=PlayerMentalState(momentum=0.7))
        ctx = _context(attacker=hot)
        mod = psychology_modifier(ctx)
        assert "on_fire" in mod.tags

    def test_ice_cold_tag(self):
        cold = _player("p1", mental=PlayerMentalState(momentum=-0.6))
        ctx = _context(attacker=cold)
        mod = psychology_modifier(ctx)
        assert "ice_cold" in mod.tags

    def test_composure_reduces_frustration(self):
        # High composure player with frustration
        composed = _player("p1", mental=PlayerMentalState(
            frustration=0.8, composure=0.95, confidence=0.5
        ))
        uncomposed = _player("p1", mental=PlayerMentalState(
            frustration=0.8, composure=0.2, confidence=0.5
        ))
        ctx_c = _context(attacker=composed)
        ctx_u = _context(attacker=uncomposed)
        mod_c = psychology_modifier(ctx_c)
        mod_u = psychology_modifier(ctx_u)
        # Composed player should be less affected by frustration
        assert mod_c.shot_pct_boost > mod_u.shot_pct_boost


# ---------------------------------------------------------------------------
# Tendencies modifier tests
# ---------------------------------------------------------------------------

class TestTendenciesModifier:
    def test_iso_player_benefits(self):
        iso_player = _player("p1", tendencies=PlayerTendencies(iso_frequency=0.8))
        ctx = _context(attacker=iso_player)
        mod = tendencies_modifier(ctx)
        assert mod.positioning_boost > 0

    def test_flashy_move_with_flashy_player(self):
        flashy = _player("p1", tendencies=PlayerTendencies(flashy_play_tendency=0.8))
        ctx = _context(attacker=flashy, data={"move": "behind_the_back"})
        mod = tendencies_modifier(ctx)
        assert mod.positioning_boost > 0
        assert "showtime" in mod.tags

    def test_shot_tendency_three(self):
        three_pref = _player("p1", tendencies=PlayerTendencies(three_vs_midrange=0.9))
        ctx = _context(
            attacker=three_pref,
            action_type=ActionType.SHOT,
            data={"shot_type": "three_pointer"},
        )
        mod = tendencies_modifier(ctx)
        assert mod.shot_pct_boost > 0

    def test_heat_check_tendency(self):
        heat_check = _player(
            "p1",
            tendencies=PlayerTendencies(heat_check_tendency=0.8),
            mental=PlayerMentalState(momentum=0.6),
        )
        ctx = _context(
            attacker=heat_check,
            action_type=ActionType.SHOT,
            data={"shot_type": "three_pointer"},
        )
        mod = tendencies_modifier(ctx)
        assert "heat_check" in mod.tags


# ---------------------------------------------------------------------------
# History modifier tests
# ---------------------------------------------------------------------------

class TestHistoryModifier:
    def setup_method(self):
        reset_history()

    def test_first_use_no_effect(self):
        ctx = _context(data={"move": "crossover"})
        mod = history_modifier(ctx)
        # No prior history, should be near-neutral
        assert abs(mod.positioning_boost) < 0.01

    def test_novelty_bonus(self):
        # Record some crossovers, then try a spin move
        record_action("p1", "d1", "crossover")
        record_action("p1", "d1", "crossover")
        ctx = _context(data={"move": "spin_move"})
        mod = history_modifier(ctx)
        assert mod.positioning_boost > 0
        assert "new_look" in mod.tags

    def test_repetition_penalty(self):
        record_action("p1", "d1", "crossover")
        record_action("p1", "d1", "crossover")
        record_action("p1", "d1", "crossover")
        ctx = _context(data={"move": "crossover"})
        mod = history_modifier(ctx)
        assert mod.positioning_boost < 0
        assert "defender_reading_it" in mod.tags

    def test_variety_bonus(self):
        for move in ["crossover", "hesitation", "spin_move", "step_back", "jab_step", "behind_the_back"]:
            record_action("p1", "d1", move)
        ctx = _context(data={"move": "crossover"})
        mod = history_modifier(ctx)
        assert "unpredictable" in mod.tags

    def test_non_dribble_returns_neutral(self):
        ctx = _context(action_type=ActionType.SHOT, data={"shot_type": "mid_range"})
        mod = history_modifier(ctx)
        assert mod.positioning_boost == 0.0


# ---------------------------------------------------------------------------
# Situational modifier tests
# ---------------------------------------------------------------------------

class TestSituationalModifier:
    def test_clutch_time_detected(self):
        clutch_player = _player("p1", tendencies=PlayerTendencies(clutch_usage=0.8),
                                mental=PlayerMentalState(composure=0.8))
        ctx = _context(
            attacker=clutch_player,
            quarter=4,
            game_clock=90.0,
            score={"home": 100, "away": 98},
            off_team="t1",
        )
        mod = situational_modifier(ctx)
        assert "clutch_time" in mod.tags
        assert mod.shot_pct_boost > 0

    def test_garbage_time(self):
        ctx = _context(score={"home": 120, "away": 85}, off_team="t1")
        mod = situational_modifier(ctx)
        assert "garbage_time" in mod.tags

    def test_home_court(self):
        ctx = _context(off_team="t1")  # t1 = home team
        mod = situational_modifier(ctx)
        assert "home_court" in mod.tags
        assert mod.shot_pct_boost > 0

    def test_shot_clock_pressure(self):
        ctx = _context(shot_clock=3.0)
        mod = situational_modifier(ctx)
        assert "shot_clock_winding" in mod.tags
        assert mod.shot_pct_boost < 0


# ---------------------------------------------------------------------------
# Chemistry modifier tests
# ---------------------------------------------------------------------------

class TestChemistryModifier:
    def setup_method(self):
        reset_chemistry()

    def test_default_neutral(self):
        ctx = _context(action_type=ActionType.PASS, data={"target_id": "p2"})
        mod = chemistry_modifier(ctx)
        # Default chemistry is 0.5, so effect should be near zero
        assert abs(mod.positioning_boost) < 0.05

    def test_great_chemistry_bonus(self):
        set_chemistry("p1", "p2", 0.95)
        ctx = _context(action_type=ActionType.PASS, data={"target_id": "p2"})
        mod = chemistry_modifier(ctx)
        assert mod.positioning_boost > 0
        assert "great_chemistry" in mod.tags

    def test_poor_chemistry_penalty(self):
        set_chemistry("p1", "p2", 0.1)
        ctx = _context(action_type=ActionType.PASS, data={"target_id": "p2"})
        mod = chemistry_modifier(ctx)
        assert mod.positioning_boost < 0
        assert "poor_chemistry" in mod.tags

    def test_symmetry(self):
        set_chemistry("p1", "p2", 0.9)
        assert get_chemistry("p2", "p1") == 0.9


# ---------------------------------------------------------------------------
# Coaching modifier tests
# ---------------------------------------------------------------------------

class TestCoachingModifier:
    def setup_method(self):
        reset_coaching()

    def test_default_neutral(self):
        ctx = _context()
        mod = coaching_modifier(ctx)
        # No adjustments set, should be near-zero
        assert abs(mod.positioning_boost) < 0.01

    def test_defensive_focus_penalty(self):
        set_coaching_adjustment("t2", "focus_p1", 0.8)
        ctx = _context()
        mod = coaching_modifier(ctx)
        assert mod.positioning_boost < 0
        assert "defense_keying_on_player" in mod.tags

    def test_matchup_hunting(self):
        set_coaching_adjustment("t1", "exploit_d1", 0.7)
        ctx = _context()
        ctx.defender.player_id = "d1"
        mod = coaching_modifier(ctx)
        assert mod.positioning_boost > 0
        assert "matchup_hunting" in mod.tags

    def test_high_intensity_defense(self):
        set_coaching_adjustment("t2", "defensive_intensity", 0.9)
        ctx = _context()
        mod = coaching_modifier(ctx)
        assert mod.positioning_boost < 0
        assert "locked_in_defense" in mod.tags

    def test_pace_adjustment(self):
        set_coaching_adjustment("t1", "pace", 0.8)
        ctx = _context()
        mod = coaching_modifier(ctx)
        assert mod.rhythm_boost > 0
