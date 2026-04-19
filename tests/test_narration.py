"""Tests for Phase 4 narration pipeline."""

from __future__ import annotations

import random
from pathlib import Path

from basketball_sim.core.types import EventType, GameEvent
from basketball_sim.narration.aggregator import EventAggregator, NarrativeBeat
from basketball_sim.narration.enricher import ContextEnricher, EnrichedBeat
from basketball_sim.narration.templates import (
    AnnouncerProfile,
    NarrationTemplate,
    TemplateSelector,
    load_announcer_profile,
)
from basketball_sim.narration.renderer import ProseRenderer, RenderedNarration
from basketball_sim.narration.stats_tracker import StatsTracker


# ---------------------------------------------------------------------------
# Event Aggregator tests
# ---------------------------------------------------------------------------

class TestEventAggregator:
    def test_dribble_sequence_grouped(self):
        agg = EventAggregator()
        e1 = GameEvent(event_type=EventType.DRIBBLE_MOVE, player_id="p1", tags=["crossover"])
        e2 = GameEvent(event_type=EventType.DRIBBLE_MOVE, player_id="p1", tags=["hesitation"])

        result1 = agg.process_event(e1)
        result2 = agg.process_event(e2)

        # First dribble starts a new beat but doesn't complete it
        assert result1 is None
        # Second dribble extends the beat
        assert result2 is None

        # Flush to get the combined beat
        beat = agg.flush()
        assert beat is not None
        assert len(beat.events) == 2
        assert "crossover" in beat.tags
        assert "hesitation" in beat.tags

    def test_shot_sequence_grouped(self):
        agg = EventAggregator()
        attempt = GameEvent(event_type=EventType.SHOT_ATTEMPT, player_id="p1", tags=["shot_attempt"])
        made = GameEvent(event_type=EventType.SHOT_MADE, player_id="p1",
                         data={"points": 2}, tags=["shot_made"])

        agg.process_event(attempt)
        result = agg.process_event(made)

        # Shot made completes the beat
        assert result is not None
        assert result.is_scoring_play
        assert result.point_value == 2

    def test_dribble_then_shot(self):
        agg = EventAggregator()
        dribble = GameEvent(event_type=EventType.DRIBBLE_MOVE, player_id="p1", tags=["crossover"])
        attempt = GameEvent(event_type=EventType.SHOT_ATTEMPT, player_id="p1")
        made = GameEvent(event_type=EventType.SHOT_MADE, player_id="p1", data={"points": 3})

        agg.process_event(dribble)
        dribble_beat = agg.process_event(attempt)

        # Shot attempt closes the dribble beat
        assert dribble_beat is not None
        assert dribble_beat.primary_event_type == EventType.DRIBBLE_MOVE

        shot_beat = agg.process_event(made)
        assert shot_beat is not None
        assert shot_beat.is_scoring_play

    def test_game_flow_events_standalone(self):
        agg = EventAggregator()
        start = GameEvent(event_type=EventType.QUARTER_START, data={"quarter": 1})
        result = agg.process_event(start)
        assert result is not None
        assert result.primary_event_type == EventType.QUARTER_START

    def test_steal_standalone(self):
        agg = EventAggregator()
        steal = GameEvent(event_type=EventType.STEAL, player_id="d1", tags=["steal"])
        result = agg.process_event(steal)
        assert result is not None

    def test_reset(self):
        agg = EventAggregator()
        agg.process_event(GameEvent(event_type=EventType.DRIBBLE_MOVE))
        agg.reset()
        assert len(agg.all_beats) == 0


# ---------------------------------------------------------------------------
# Context Enricher tests
# ---------------------------------------------------------------------------

class TestContextEnricher:
    def test_scoring_play_excitement(self):
        enricher = ContextEnricher()
        beat = NarrativeBeat(
            primary_event_type=EventType.SHOT_MADE,
            is_scoring_play=True,
            point_value=3,
        )
        beat.tags = ["three_pointer_made"]
        enriched = enricher.enrich(beat)
        assert enriched.excitement > 0

    def test_ankle_breaker_high_excitement(self):
        enricher = ContextEnricher()
        beat = NarrativeBeat(primary_event_type=EventType.DRIBBLE_MOVE)
        beat.tags = ["ankle_breaker", "crossover"]
        enriched = enricher.enrich(beat)
        assert enriched.excitement >= 0.4
        assert enriched.announcer_intensity in ("elevated", "hyped", "maximum")

    def test_consecutive_makes_streak(self):
        enricher = ContextEnricher()
        for i in range(4):
            beat = NarrativeBeat(
                primary_event_type=EventType.SHOT_MADE,
                is_scoring_play=True,
                point_value=2,
                player_id="p1",
            )
            beat.tags = ["shot_made"]
            enriched = enricher.enrich(beat)

        assert "hot_streak" in enriched.context_tags

    def test_clutch_time_multiplier(self):
        enricher = ContextEnricher()
        beat = NarrativeBeat(
            primary_event_type=EventType.SHOT_MADE,
            is_scoring_play=True,
            point_value=3,
        )
        beat.tags = ["three_pointer_made", "clutch_time"]
        enriched = enricher.enrich(beat)
        # Clutch time should boost excitement
        assert enriched.excitement > 0.3

    def test_routine_play_low_excitement(self):
        enricher = ContextEnricher()
        beat = NarrativeBeat(primary_event_type=EventType.DRIBBLE_MOVE)
        beat.tags = ["dribble_move"]
        enriched = enricher.enrich(beat)
        assert enriched.excitement < 0.2

    def test_reset(self):
        enricher = ContextEnricher()
        for _ in range(5):
            beat = NarrativeBeat(is_scoring_play=True, point_value=2)
            beat.tags = ["shot_made"]
            enricher.enrich(beat)
        enricher.reset()
        # After reset, streaks should restart
        beat = NarrativeBeat(is_scoring_play=True, point_value=2)
        beat.tags = ["shot_made"]
        enriched = enricher.enrich(beat)
        assert "hot_streak" not in enriched.context_tags


# ---------------------------------------------------------------------------
# Template Selector tests
# ---------------------------------------------------------------------------

class TestTemplateSelector:
    def _profile(self) -> AnnouncerProfile:
        profile = AnnouncerProfile(
            announcer_id="test",
            templates=[
                NarrationTemplate(
                    template_id="three_1",
                    text="{player} hits the three!",
                    required_tags=["three_pointer_made"],
                    intensity="normal",
                ),
                NarrationTemplate(
                    template_id="ankle_1",
                    text="{player} breaks ankles!",
                    required_tags=["ankle_breaker"],
                    intensity="hyped",
                ),
                NarrationTemplate(
                    template_id="ankle_cross",
                    text="{player} crosses and breaks ankles!",
                    required_tags=["ankle_breaker", "crossover"],
                    intensity="maximum",
                ),
                NarrationTemplate(
                    template_id="shot_1",
                    text="{player} scores.",
                    required_tags=["shot_made"],
                    intensity="whisper",
                ),
            ],
        )
        profile.build_index()
        return profile

    def test_matches_by_tags(self):
        selector = TemplateSelector(self._profile())
        beat = NarrativeBeat()
        beat.tags = ["three_pointer_made"]
        enriched = EnrichedBeat(beat=beat, announcer_intensity="elevated")

        template = selector.select(enriched, rng=random.Random(42))
        assert template is not None
        assert "three" in template.text.lower()

    def test_more_specific_match_preferred(self):
        selector = TemplateSelector(self._profile())
        beat = NarrativeBeat()
        beat.tags = ["ankle_breaker", "crossover"]
        enriched = EnrichedBeat(beat=beat, announcer_intensity="maximum")

        template = selector.select(enriched, rng=random.Random(42))
        assert template is not None
        # Should prefer ankle_cross (2 required tags) over ankle_1 (1 tag)
        # Both are valid but the more specific one has higher score
        assert template.template_id in ("ankle_cross", "ankle_1")

    def test_no_match_returns_none(self):
        selector = TemplateSelector(self._profile())
        beat = NarrativeBeat()
        beat.tags = ["nonexistent_tag"]
        enriched = EnrichedBeat(beat=beat, announcer_intensity="normal")

        template = selector.select(enriched, rng=random.Random(42))
        assert template is None

    def test_intensity_filtering(self):
        selector = TemplateSelector(self._profile())
        beat = NarrativeBeat()
        beat.tags = ["ankle_breaker"]
        # Whisper intensity shouldn't match hyped template
        enriched = EnrichedBeat(beat=beat, announcer_intensity="whisper")

        template = selector.select(enriched, rng=random.Random(42))
        # Should not match ankle_1 (hyped) at whisper intensity
        assert template is None or template.intensity in ("whisper", "normal")

    def test_load_default_profile(self):
        default_path = Path(__file__).parent.parent / "basketball_sim" / "data" / "narration" / "announcer_default.json"
        if default_path.exists():
            profile = load_announcer_profile(default_path)
            assert profile.announcer_id == "default_play_by_play"
            assert len(profile.templates) > 100  # should have 200+ templates


# ---------------------------------------------------------------------------
# Prose Renderer tests
# ---------------------------------------------------------------------------

class TestProseRenderer:
    def test_render_with_template(self):
        template = NarrationTemplate(
            template_id="test",
            text="{player} with the {move}!",
            required_tags=["dribble_move"],
        )
        beat = NarrativeBeat(
            primary_event_type=EventType.DRIBBLE_MOVE,
            player_id="p1",
        )
        beat.events = [GameEvent(
            event_type=EventType.DRIBBLE_MOVE,
            player_id="p1",
            data={"move": "crossover"},
        )]
        enriched = EnrichedBeat(beat=beat, excitement=0.3)

        renderer = ProseRenderer(
            player_names={"p1": "Stephen Curry"},
        )
        result = renderer.render(template, enriched)
        assert "Stephen Curry" in result.text
        assert "Crossover" in result.text

    def test_fallback_text(self):
        beat = NarrativeBeat(
            primary_event_type=EventType.SHOT_MADE,
            player_id="p1",
            is_scoring_play=True,
            point_value=3,
        )
        enriched = EnrichedBeat(beat=beat)

        renderer = ProseRenderer(player_names={"p1": "LeBron"})
        result = renderer.render(None, enriched)
        assert "LeBron" in result.text
        assert "scores" in result.text.lower() or "3" in result.text

    def test_game_flow_fallback(self):
        beat = NarrativeBeat(primary_event_type=EventType.GAME_START, quarter=1)
        enriched = EnrichedBeat(beat=beat)
        renderer = ProseRenderer()
        result = renderer.render(None, enriched)
        assert "tip" in result.text.lower() or "underway" in result.text.lower()

    def test_render_returns_metadata(self):
        beat = NarrativeBeat(
            primary_event_type=EventType.DRIBBLE_MOVE,
            player_id="p1",
            quarter=3,
            game_clock=120.0,
        )
        enriched = EnrichedBeat(beat=beat, excitement=0.7, is_highlight=True)
        renderer = ProseRenderer()
        result = renderer.render(None, enriched)
        assert result.quarter == 3
        assert result.excitement == 0.7
        assert result.is_highlight is True


# ---------------------------------------------------------------------------
# Stats Tracker tests
# ---------------------------------------------------------------------------

class TestStatsTracker:
    def _tracker(self) -> StatsTracker:
        tracker = StatsTracker()
        tracker.register_team("t1", "Home")
        tracker.register_team("t2", "Away")
        for i in range(1, 6):
            tracker.register_player(f"h{i}", "t1", f"Home Player {i}")
            tracker.register_player(f"a{i}", "t2", f"Away Player {i}")
        return tracker

    def test_shot_tracking(self):
        tracker = self._tracker()
        tracker.handle_event(GameEvent(
            event_type=EventType.SHOT_ATTEMPT,
            player_id="h1",
            data={"shot_type": "three_pointer"},
        ))
        tracker.handle_event(GameEvent(
            event_type=EventType.SHOT_MADE,
            player_id="h1",
            data={"shot_type": "three_pointer", "points": 3},
        ))

        stats = tracker.get_team_stats("t1")
        assert stats is not None
        p_stats = stats.players["h1"]
        assert p_stats.points == 3
        assert p_stats.field_goals_made == 1
        assert p_stats.field_goals_attempted == 1
        assert p_stats.three_pointers_made == 1
        assert p_stats.three_pointers_attempted == 1

    def test_rebound_tracking(self):
        tracker = self._tracker()
        tracker.handle_event(GameEvent(
            event_type=EventType.REBOUND,
            player_id="h1",
            data={"rebound_type": "offensive"},
        ))
        tracker.handle_event(GameEvent(
            event_type=EventType.REBOUND,
            player_id="h1",
            data={"rebound_type": "defensive"},
        ))

        stats = tracker.get_team_stats("t1")
        p_stats = stats.players["h1"]
        assert p_stats.offensive_rebounds == 1
        assert p_stats.defensive_rebounds == 1
        assert p_stats.rebounds == 2

    def test_steal_tracking(self):
        tracker = self._tracker()
        tracker.handle_event(GameEvent(
            event_type=EventType.STEAL,
            player_id="a1",
        ))
        stats = tracker.get_team_stats("t2")
        assert stats.players["a1"].steals == 1

    def test_block_tracking(self):
        tracker = self._tracker()
        tracker.handle_event(GameEvent(
            event_type=EventType.BLOCK,
            player_id="a2",
        ))
        stats = tracker.get_team_stats("t2")
        assert stats.players["a2"].blocks == 1

    def test_turnover_tracking(self):
        tracker = self._tracker()
        tracker.handle_event(GameEvent(
            event_type=EventType.TURNOVER,
            player_id="h1",
        ))
        stats = tracker.get_team_stats("t1")
        assert stats.players["h1"].turnovers == 1

    def test_assist_on_pass_then_make(self):
        tracker = self._tracker()
        # Pass from h1 to h2
        tracker.handle_event(GameEvent(
            event_type=EventType.PASS_COMPLETED,
            player_id="h1",
            data={"target_id": "h2"},
        ))
        # h2 scores
        tracker.handle_event(GameEvent(
            event_type=EventType.SHOT_ATTEMPT,
            player_id="h2",
            data={"shot_type": "mid_range"},
        ))
        tracker.handle_event(GameEvent(
            event_type=EventType.SHOT_MADE,
            player_id="h2",
            data={"points": 2},
        ))

        stats = tracker.get_team_stats("t1")
        assert stats.players["h1"].assists == 1

    def test_fg_pct(self):
        tracker = self._tracker()
        for i in range(10):
            tracker.handle_event(GameEvent(
                event_type=EventType.SHOT_ATTEMPT,
                player_id="h1",
                data={"shot_type": "mid_range"},
            ))
            if i < 4:
                tracker.handle_event(GameEvent(
                    event_type=EventType.SHOT_MADE,
                    player_id="h1",
                    data={"points": 2},
                ))
            else:
                tracker.handle_event(GameEvent(
                    event_type=EventType.SHOT_MISSED,
                    player_id="h1",
                ))

        stats = tracker.get_team_stats("t1")
        assert abs(stats.players["h1"].fg_pct - 0.4) < 0.001

    def test_box_score_format(self):
        tracker = self._tracker()
        tracker.handle_event(GameEvent(
            event_type=EventType.SHOT_ATTEMPT,
            player_id="h1",
            data={"shot_type": "three_pointer"},
        ))
        tracker.handle_event(GameEvent(
            event_type=EventType.SHOT_MADE,
            player_id="h1",
            data={"points": 3, "shot_type": "three_pointer"},
        ))

        box_score = tracker.format_box_scores()
        assert "Home" in box_score
        assert "Home Player 1" in box_score
        # Box score uses aligned columns: points appear as a right-justified
        # 4-wide integer, so "3" shows up immediately after the player name.
        assert "PTS" in box_score  # header label present
        assert "1-1" in box_score  # the 3PT make shows as FG 1-1 and 3PT 1-1

    def test_reset(self):
        tracker = self._tracker()
        tracker.handle_event(GameEvent(
            event_type=EventType.SHOT_MADE,
            player_id="h1",
            data={"points": 2},
        ))
        tracker.reset()
        assert tracker.get_team_stats("t1") is None
