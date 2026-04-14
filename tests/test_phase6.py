"""Tests for Phase 6 content: expanded moves, badges, mod loader, schemes."""

from __future__ import annotations

import json
from pathlib import Path

from basketball_sim.data.loader import load_moves, load_badges
from basketball_sim.core.mod_loader import ModLoader, ModMetadata, LoadedMod


# ---------------------------------------------------------------------------
# Expanded dribble moves
# ---------------------------------------------------------------------------

class TestExpandedMoves:
    def test_move_count_at_least_30(self):
        moves = load_moves()
        assert len(moves) >= 30, f"Expected 30+ moves, got {len(moves)}"

    def test_all_moves_have_required_fields(self):
        moves = load_moves()
        for move_id, move in moves.items():
            assert move.move_id, f"Move missing id"
            assert move.display_name, f"Move {move_id} missing display_name"
            assert move.transitions, f"Move {move_id} has no transitions"
            assert isinstance(move.tags_on_success, list), f"Move {move_id} tags_on_success not a list"
            assert move.energy_cost >= 0, f"Move {move_id} has negative energy cost"

    def test_elite_moves_require_high_handling(self):
        moves = load_moves()
        elite_moves = {mid: m for mid, m in moves.items() if m.category == "elite"}
        for mid, move in elite_moves.items():
            bh = move.required_attributes.get("ball_handling", 0)
            assert bh >= 85, f"Elite move {mid} only requires {bh} ball_handling"

    def test_post_moves_exist(self):
        moves = load_moves()
        post_moves = {mid: m for mid, m in moves.items() if m.category == "post"}
        assert len(post_moves) >= 4, f"Expected 4+ post moves, got {len(post_moves)}"

    def test_combo_moves_exist(self):
        moves = load_moves()
        combo = {mid: m for mid, m in moves.items() if m.category == "combo"}
        assert len(combo) >= 2

    def test_finishing_moves_exist(self):
        moves = load_moves()
        finishing = {mid: m for mid, m in moves.items() if m.category == "finishing"}
        assert len(finishing) >= 2

    def test_move_categories_variety(self):
        moves = load_moves()
        categories = {m.category for m in moves.values()}
        expected = {"crossover", "deception", "advanced_crossover", "separation", "elite", "post"}
        for cat in expected:
            assert cat in categories, f"Missing category: {cat}"


# ---------------------------------------------------------------------------
# Badges
# ---------------------------------------------------------------------------

class TestBadges:
    def test_badge_count_at_least_80(self):
        badges = load_badges()
        assert len(badges) >= 80, f"Expected 80+ badges, got {len(badges)}"

    def test_all_badges_have_required_fields(self):
        badges = load_badges()
        for badge_id, badge in badges.items():
            assert badge.get("id"), f"Badge missing id"
            assert badge.get("display_name"), f"Badge {badge_id} missing display_name"
            assert badge.get("tier") in ("bronze", "silver", "gold", "hall_of_fame"), \
                f"Badge {badge_id} has invalid tier: {badge.get('tier')}"
            assert badge.get("category"), f"Badge {badge_id} missing category"

    def test_badge_categories_variety(self):
        badges = load_badges()
        categories = {b.get("category") for b in badges.values()}
        expected = {"playmaking", "shooting", "finishing", "defense", "rebounding", "mental", "physical"}
        for cat in expected:
            assert cat in categories, f"Missing badge category: {cat}"

    def test_hall_of_fame_badges_exist(self):
        badges = load_badges()
        hof = {bid: b for bid, b in badges.items() if b.get("tier") == "hall_of_fame"}
        assert len(hof) >= 5, f"Expected 5+ HoF badges, got {len(hof)}"


# ---------------------------------------------------------------------------
# Defensive schemes
# ---------------------------------------------------------------------------

class TestDefensiveSchemes:
    def test_schemes_load(self):
        path = Path(__file__).parent.parent / "basketball_sim" / "data" / "schemes" / "defensive_schemes.json"
        with open(path) as f:
            schemes = json.load(f)
        assert len(schemes) >= 8

    def test_scheme_categories(self):
        path = Path(__file__).parent.parent / "basketball_sim" / "data" / "schemes" / "defensive_schemes.json"
        with open(path) as f:
            schemes = json.load(f)
        categories = {s["category"] for s in schemes}
        assert "man" in categories
        assert "zone" in categories
        assert "press" in categories
        assert "junk" in categories

    def test_all_schemes_have_intensity(self):
        path = Path(__file__).parent.parent / "basketball_sim" / "data" / "schemes" / "defensive_schemes.json"
        with open(path) as f:
            schemes = json.load(f)
        for scheme in schemes:
            assert "intensity" in scheme, f"Scheme {scheme['id']} missing intensity"
            assert 0 <= scheme["intensity"] <= 1.0


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

class TestRules:
    def test_nba_rules_load(self):
        path = Path(__file__).parent.parent / "basketball_sim" / "data" / "rules" / "nba_rules.json"
        with open(path) as f:
            rules = json.load(f)
        assert rules["shot_clock"] == 24.0
        assert rules["num_quarters"] == 4
        assert rules["personal_foul_limit"] == 6

    def test_ncaa_rules_load(self):
        path = Path(__file__).parent.parent / "basketball_sim" / "data" / "rules" / "ncaa_rules.json"
        with open(path) as f:
            rules = json.load(f)
        assert rules["shot_clock"] == 30.0
        assert rules["num_quarters"] == 2
        assert rules["personal_foul_limit"] == 5

    def test_fiba_rules_load(self):
        path = Path(__file__).parent.parent / "basketball_sim" / "data" / "rules" / "fiba_rules.json"
        with open(path) as f:
            rules = json.load(f)
        assert rules["quarter_length"] == 600.0
        assert rules["personal_foul_limit"] == 5


# ---------------------------------------------------------------------------
# Mod loader
# ---------------------------------------------------------------------------

class TestModLoader:
    def test_loader_init(self):
        loader = ModLoader(Path("nonexistent_mods"))
        assert loader.mods_dir == Path("nonexistent_mods")

    def test_discover_empty_dir(self):
        loader = ModLoader(Path("nonexistent_mods"))
        mods = loader.discover_and_load()
        assert mods == []

    def test_merge_empty(self):
        loader = ModLoader(Path("nonexistent_mods"))
        loader.discover_and_load()
        moves, badges = loader.merge_into_registry({"a": 1}, {"b": 2})
        assert moves == {"a": 1}
        assert badges == {"b": 2}

    def test_loaded_mod_structure(self):
        meta = ModMetadata(mod_id="test", name="Test Mod")
        mod = LoadedMod(metadata=meta)
        assert mod.metadata.mod_id == "test"
        assert mod.moves == {}
        assert mod.badges == {}
        assert mod.modifier_functions == []
