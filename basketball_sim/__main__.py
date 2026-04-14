"""Entry point for running a basketball simulation.

Usage:
    python -m basketball_sim
    python -m basketball_sim --seed 42
    python -m basketball_sim --quarters 2
"""

from __future__ import annotations

import argparse
import logging
import random
import sys

from basketball_sim.core.engine import GameEngine
from basketball_sim.core.event_bus import EventBus
from basketball_sim.core.pipeline import ModifierPipeline
from basketball_sim.core.types import (
    EventType,
    GameEvent,
    GameState,
    Player,
    PlayerAttributes,
    PlayerMentalState,
    PlayerTendencies,
    RulesConfig,
    TeamState,
)
from basketball_sim.ai.offensive_ai import BasicOffensiveAI
from basketball_sim.ai.defensive_ai import BasicDefensiveAI
from basketball_sim.data.loader import load_moves
from basketball_sim.modifiers.fatigue import fatigue_modifier
from basketball_sim.modifiers.psychology import psychology_modifier
from basketball_sim.modifiers.tendencies import tendencies_modifier
from basketball_sim.modifiers.history import history_modifier, reset_history
from basketball_sim.modifiers.situational import situational_modifier
from basketball_sim.modifiers.chemistry import chemistry_modifier
from basketball_sim.modifiers.coaching import coaching_modifier
from basketball_sim.narration.aggregator import EventAggregator
from basketball_sim.narration.enricher import ContextEnricher
from basketball_sim.narration.templates import TemplateSelector
from basketball_sim.narration.renderer import ProseRenderer
from basketball_sim.narration.stats_tracker import StatsTracker


# ---------------------------------------------------------------------------
# Sample rosters
# ---------------------------------------------------------------------------

def _build_player(
    pid: str,
    name: str,
    team: str,
    pos: str,
    **attr_overrides: int,
) -> Player:
    p = Player(player_id=pid, display_name=name, team_id=team, position=pos)
    for attr, val in attr_overrides.items():
        if hasattr(p.attributes, attr):
            setattr(p.attributes, attr, val)
    p.move_repertoire = ["crossover", "hesitation", "jab_step", "step_back"]
    if p.attributes.ball_handling >= 78:
        p.move_repertoire.extend(["behind_the_back", "spin_move"])
    return p


def build_sample_teams() -> tuple[TeamState, TeamState]:
    """Create two sample teams with realistic-ish rosters."""
    home_players = [
        _build_player("h1", "Marcus Cole", "home", "PG",
                       ball_handling=88, speed=85, three_point=82, passing_vision=87, passing_accuracy=84),
        _build_player("h2", "Jaylen Wright", "home", "SG",
                       ball_handling=76, three_point=80, mid_range=78, perimeter_defense=80),
        _build_player("h3", "DeAndre Harris", "home", "SF",
                       ball_handling=72, three_point=75, driving_layup=82, strength=78),
        _build_player("h4", "Terrence Williams", "home", "PF",
                       interior_defense=80, defensive_rebound=82, strength=85, post_offense=75, block=72),
        _build_player("h5", "Andre Mitchell", "home", "C",
                       interior_defense=85, defensive_rebound=88, block=80, strength=90, dunk=78),
        _build_player("h6", "Chris Taylor", "home", "PG",
                       ball_handling=80, speed=82, three_point=72, passing_vision=78),
        _build_player("h7", "Devon Jackson", "home", "SG",
                       ball_handling=70, three_point=76, mid_range=74),
        _build_player("h8", "Malik Brown", "home", "SF",
                       ball_handling=68, three_point=70, driving_layup=75, perimeter_defense=76),
    ]
    home_players[0].tendencies = PlayerTendencies(
        iso_frequency=0.5, pass_first_vs_score=0.4, flashy_play_tendency=0.5,
        clutch_usage=0.8, three_vs_midrange=0.6,
    )
    home_players[0].mental = PlayerMentalState(confidence=0.7, composure=0.8)

    away_players = [
        _build_player("a1", "Jordan Thomas", "away", "PG",
                       ball_handling=85, speed=88, three_point=78, passing_vision=82, passing_accuracy=80),
        _build_player("a2", "Kevin Reed", "away", "SG",
                       ball_handling=78, three_point=85, mid_range=80, perimeter_defense=72),
        _build_player("a3", "Brandon Lewis", "away", "SF",
                       ball_handling=75, three_point=72, driving_layup=85, strength=82, dunk=75),
        _build_player("a4", "Marcus Patterson", "away", "PF",
                       interior_defense=78, defensive_rebound=80, strength=82, post_offense=78, block=70),
        _build_player("a5", "David Carter", "away", "C",
                       interior_defense=82, defensive_rebound=85, block=78, strength=88, dunk=75),
        _build_player("a6", "Tyler Green", "away", "PG",
                       ball_handling=78, speed=80, three_point=70, passing_vision=75),
        _build_player("a7", "Isaiah Moore", "away", "SG",
                       ball_handling=72, three_point=78, mid_range=76),
        _build_player("a8", "Ryan Scott", "away", "PF",
                       interior_defense=75, defensive_rebound=78, strength=80),
    ]
    away_players[0].tendencies = PlayerTendencies(
        iso_frequency=0.4, pass_first_vs_score=0.5, flashy_play_tendency=0.3,
        clutch_usage=0.7, three_vs_midrange=0.5,
    )
    away_players[1].tendencies = PlayerTendencies(
        three_vs_midrange=0.85, heat_check_tendency=0.6,
    )

    home = TeamState(
        team_id="home",
        name="Storm",
        players=home_players,
        on_court=[p.player_id for p in home_players[:5]],
    )
    away = TeamState(
        team_id="away",
        name="Thunder",
        players=away_players,
        on_court=[p.player_id for p in away_players[:5]],
    )
    return home, away


# ---------------------------------------------------------------------------
# Narration listener
# ---------------------------------------------------------------------------

class NarrationListener:
    """Listens to events and produces narration in real-time."""

    def __init__(self, player_names: dict[str, str], team_names: dict[str, str]) -> None:
        self.aggregator = EventAggregator()
        self.enricher = ContextEnricher()
        self.selector = TemplateSelector()
        self.renderer = ProseRenderer(
            profile=self.selector.profile,
            player_names=player_names,
            team_names=team_names,
        )
        self._suppress = {
            EventType.POSSESSION_START,
            EventType.POSSESSION_END,
        }

    def handle_event(self, event: GameEvent) -> None:
        """Process an event through the narration pipeline."""
        if event.event_type in self._suppress:
            return

        beat = self.aggregator.process_event(event)
        if beat is None:
            return

        enriched = self.enricher.enrich(beat)
        template = self.selector.select(enriched, rng=random)
        rendered = self.renderer.render(template, enriched)

        if rendered.text.strip():
            # Format with game clock
            clock = _format_clock(event.game_clock)
            q = event.quarter or 1
            prefix = f"  Q{q} {clock} |"
            print(f"{prefix} {rendered.text}")

    def flush(self) -> None:
        """Flush any remaining beats."""
        beat = self.aggregator.flush()
        if beat:
            enriched = self.enricher.enrich(beat)
            template = self.selector.select(enriched, rng=random)
            rendered = self.renderer.render(template, enriched)
            if rendered.text.strip():
                print(f"           | {rendered.text}")


def _format_clock(seconds: float) -> str:
    if seconds <= 0:
        return " 0:00"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:2d}:{secs:02d}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Basketball Simulator")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--quarters", type=int, default=4, help="Number of quarters")
    parser.add_argument("--quarter-length", type=float, default=720.0,
                        help="Quarter length in seconds (default: 720 = 12 min)")
    parser.add_argument("--quiet", action="store_true", help="Suppress play-by-play narration")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Build teams
    home, away = build_sample_teams()

    # Collect name maps
    player_names = {}
    for p in home.players + away.players:
        player_names[p.player_id] = p.display_name
    team_names = {"home": home.name, "away": away.name}

    # Set up event bus
    bus = EventBus()

    # Set up stats tracker
    stats = StatsTracker()
    stats.register_team("home", home.name)
    stats.register_team("away", away.name)
    for p in home.players:
        stats.register_player(p.player_id, "home", p.display_name)
    for p in away.players:
        stats.register_player(p.player_id, "away", p.display_name)
    bus.subscribe_all(stats.handle_event)

    # Set up narration
    if not args.quiet:
        narrator = NarrationListener(player_names, team_names)
        bus.subscribe_all(narrator.handle_event)

    # Set up modifier pipeline
    pipeline = ModifierPipeline()
    pipeline.register(fatigue_modifier, "fatigue")
    pipeline.register(psychology_modifier, "psychology")
    pipeline.register(tendencies_modifier, "tendencies")
    pipeline.register(history_modifier, "history")
    pipeline.register(situational_modifier, "situational")
    pipeline.register(chemistry_modifier, "chemistry")
    pipeline.register(coaching_modifier, "coaching")

    # Reset game-level state
    reset_history()

    # Set up AI
    moves = load_moves()
    offensive_ai = BasicOffensiveAI(move_registry=moves)
    defensive_ai = BasicDefensiveAI()

    # Set up rules
    rules = RulesConfig(
        quarter_length=args.quarter_length,
        num_quarters=args.quarters,
    )

    # Build engine
    engine = GameEngine(
        event_bus=bus,
        pipeline=pipeline,
        offensive_ai=offensive_ai,
        defensive_ai=defensive_ai,
        rules=rules,
    )

    # Build game state
    game = GameState(
        home_team=home,
        away_team=away,
        possession_team_id="home",
        rng=random.Random(args.seed),
    )

    # Print header
    print()
    print("=" * 60)
    print(f"  {home.name} vs {away.name}")
    print(f"  Seed: {args.seed} | Quarters: {args.quarters}")
    print("=" * 60)
    print()

    # Simulate
    final = engine.simulate_game(game)

    # Flush narration
    if not args.quiet:
        narrator.flush()

    # Print final score
    print()
    print("=" * 60)
    print(f"  FINAL SCORE")
    print(f"  {home.name}: {final.score['home']}  |  {away.name}: {final.score['away']}")
    print("=" * 60)

    # Print box scores
    print(stats.format_box_scores())

    # Print engine stats
    print(f"\n  Engine: {engine.stats.possessions_simulated} possessions, "
          f"{engine.stats.actions_resolved} actions in "
          f"{engine.stats.total_time_seconds:.3f}s")
    if engine.stats.avg_time_per_possession > 0:
        print(f"  Avg time per possession: {engine.stats.avg_time_per_possession * 1000:.2f}ms")
    print()


if __name__ == "__main__":
    main()
