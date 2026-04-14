"""Stage 3: Template Selector -- matches tag combinations to narration templates.

Templates are keyed to specific tag patterns. The selector finds the
best matching template for a given enriched beat, considering both
tag overlap and announcer intensity level.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from basketball_sim.narration.enricher import EnrichedBeat

logger = logging.getLogger(__name__)


@dataclass
class NarrationTemplate:
    """A single narration template with its matching criteria."""
    template_id: str
    text: str
    required_tags: list[str] = field(default_factory=list)
    optional_tags: list[str] = field(default_factory=list)
    intensity: str = "normal"  # minimum intensity to use this template
    weight: float = 1.0  # selection weight for randomized variety
    category: str = ""


@dataclass
class AnnouncerProfile:
    """An announcer's personality and template library."""
    announcer_id: str
    display_name: str = ""
    style: str = "neutral"
    excitement_baseline: float = 0.5
    signature_phrases: list[str] = field(default_factory=list)
    templates: list[NarrationTemplate] = field(default_factory=list)

    # Index for fast lookup: frozenset of required_tags -> list of templates
    _tag_index: dict[frozenset[str], list[NarrationTemplate]] = field(
        default_factory=dict, repr=False
    )

    def build_index(self) -> None:
        """Build the tag-based template index for fast lookup."""
        self._tag_index.clear()
        for tmpl in self.templates:
            key = frozenset(tmpl.required_tags)
            if key not in self._tag_index:
                self._tag_index[key] = []
            self._tag_index[key].append(tmpl)

    def find_templates(
        self, tags: set[str], intensity: str
    ) -> list[NarrationTemplate]:
        """Find all templates whose required tags are a subset of the given tags.

        Returns templates sorted by match quality (more required tags = better match).
        """
        intensity_order = ["whisper", "normal", "elevated", "hyped", "maximum"]
        min_idx = intensity_order.index(intensity) if intensity in intensity_order else 1

        matches: list[tuple[int, NarrationTemplate]] = []

        for required_set, templates in self._tag_index.items():
            if required_set.issubset(tags):
                for tmpl in templates:
                    tmpl_idx = (
                        intensity_order.index(tmpl.intensity)
                        if tmpl.intensity in intensity_order
                        else 1
                    )
                    # Template intensity must be <= current intensity
                    if tmpl_idx <= min_idx:
                        # Score by number of matching required + optional tags
                        score = len(required_set)
                        for opt_tag in tmpl.optional_tags:
                            if opt_tag in tags:
                                score += 0.5
                        matches.append((score, tmpl))

        # Sort by match quality (best matches first)
        matches.sort(key=lambda x: x[0], reverse=True)
        return [tmpl for _, tmpl in matches]


class TemplateSelector:
    """Selects the best narration template for an enriched beat."""

    def __init__(self, profile: AnnouncerProfile | None = None) -> None:
        self._profile = profile or _default_profile()
        self._profile.build_index()
        self._recently_used: list[str] = []  # avoid repetition
        self._max_recent = 10

    @property
    def profile(self) -> AnnouncerProfile:
        return self._profile

    def select(self, enriched: EnrichedBeat, rng: Any = None) -> NarrationTemplate | None:
        """Select the best template for an enriched beat.

        Uses tag matching and intensity filtering. Adds randomness
        to avoid repetitive narration.
        """
        import random as random_mod
        if rng is None:
            rng = random_mod

        tags = set(enriched.beat.tags + enriched.context_tags)
        intensity = enriched.announcer_intensity

        candidates = self._profile.find_templates(tags, intensity)

        if not candidates:
            # Fallback: try with just the primary event type tag
            fallback_tags = set()
            if enriched.beat.primary_event_type is not None:
                fallback_tags.add(enriched.beat.primary_event_type.name.lower())
            if enriched.beat.is_scoring_play:
                fallback_tags.add("shot_made")
            candidates = self._profile.find_templates(fallback_tags, intensity)

        if not candidates:
            return None

        # Filter out recently used templates for variety
        fresh = [t for t in candidates if t.template_id not in self._recently_used]
        pool = fresh if fresh else candidates

        # Weighted random selection from top candidates
        top = pool[:min(5, len(pool))]
        weights = [t.weight for t in top]
        chosen = rng.choices(top, weights=weights, k=1)[0]

        # Track recently used
        self._recently_used.append(chosen.template_id)
        if len(self._recently_used) > self._max_recent:
            self._recently_used.pop(0)

        return chosen

    def reset(self) -> None:
        """Clear recently used tracking."""
        self._recently_used.clear()


def load_announcer_profile(path: Path) -> AnnouncerProfile:
    """Load an announcer profile from a JSON file."""
    with open(path, "r") as f:
        data = json.load(f)

    templates = []
    for tmpl_data in data.get("templates", []):
        templates.append(NarrationTemplate(
            template_id=tmpl_data.get("id", ""),
            text=tmpl_data.get("text", ""),
            required_tags=tmpl_data.get("required_tags", []),
            optional_tags=tmpl_data.get("optional_tags", []),
            intensity=tmpl_data.get("intensity", "normal"),
            weight=tmpl_data.get("weight", 1.0),
            category=tmpl_data.get("category", ""),
        ))

    profile = AnnouncerProfile(
        announcer_id=data.get("announcer_id", "unknown"),
        display_name=data.get("display_name", ""),
        style=data.get("personality", {}).get("style", "neutral"),
        excitement_baseline=data.get("personality", {}).get("excitement_baseline", 0.5),
        signature_phrases=data.get("personality", {}).get("signature_phrases", []),
        templates=templates,
    )
    profile.build_index()
    return profile


def _default_profile() -> AnnouncerProfile:
    """Load the default announcer profile from the data directory."""
    default_path = Path(__file__).parent.parent / "data" / "narration" / "announcer_default.json"
    if default_path.exists():
        return load_announcer_profile(default_path)

    # Minimal fallback if no JSON file exists
    return AnnouncerProfile(
        announcer_id="fallback",
        display_name="Fallback Announcer",
        templates=[
            NarrationTemplate(
                template_id="fallback_shot_made",
                text="{player} scores!",
                required_tags=["shot_made"],
            ),
            NarrationTemplate(
                template_id="fallback_shot_missed",
                text="{player} misses the shot.",
                required_tags=["shot_missed"],
            ),
            NarrationTemplate(
                template_id="fallback_dribble",
                text="{player} with the handle.",
                required_tags=["dribble_move"],
            ),
        ],
    )
