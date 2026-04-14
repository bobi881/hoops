"""Modifier pipeline -- combines independent realism layers.

Each modifier is a standalone function: ActionContext in, Modifier out.
No modifier knows other modifiers exist. The pipeline combines their
outputs additively and clamps the result.
"""

from __future__ import annotations

import logging
from typing import Callable

from basketball_sim.core.types import ActionContext, AggregatedModifier, Modifier

logger = logging.getLogger(__name__)

# A modifier function takes context, returns a Modifier
ModifierFn = Callable[[ActionContext], Modifier]

# Max consecutive failures before a modifier is disabled for the game
MAX_FAILURES = 10


class ModifierPipeline:
    """Collects and applies independent modifier layers.

    Each layer is a pure function: context in, Modifier out.
    The pipeline combines them additively and clamps the result.
    Order does NOT matter -- addition is commutative.

    Usage:
        pipeline = ModifierPipeline()
        pipeline.register(fatigue_modifier)
        pipeline.register(psychology_modifier)

        agg = pipeline.apply(context)  # combined, clamped modifier
    """

    def __init__(self) -> None:
        self._modifiers: list[tuple[str, ModifierFn]] = []
        self._failure_counts: dict[str, int] = {}
        self._disabled: set[str] = set()

    def register(self, modifier_fn: ModifierFn, name: str | None = None) -> None:
        """Register a modifier function.

        Args:
            modifier_fn: A callable (ActionContext) -> Modifier.
            name: Optional display name for logging. Defaults to function name.
        """
        fn_name = name or getattr(modifier_fn, "__name__", repr(modifier_fn))
        self._modifiers.append((fn_name, modifier_fn))
        self._failure_counts[fn_name] = 0

    def unregister(self, name: str) -> None:
        """Remove a modifier by name."""
        self._modifiers = [(n, fn) for n, fn in self._modifiers if n != name]
        self._failure_counts.pop(name, None)
        self._disabled.discard(name)

    def apply(self, context: ActionContext) -> AggregatedModifier:
        """Run all modifiers and return the combined, clamped result.

        Failed modifiers return neutral (no effect). After MAX_FAILURES
        consecutive failures, a modifier is disabled for the rest of the game.
        """
        agg = AggregatedModifier()

        for fn_name, modifier_fn in self._modifiers:
            if fn_name in self._disabled:
                continue

            try:
                mod = modifier_fn(context)
                agg.combine(mod)
                # Reset failure count on success
                self._failure_counts[fn_name] = 0
            except Exception:
                self._failure_counts[fn_name] += 1
                logger.exception(
                    "Modifier '%s' failed (failure %d/%d)",
                    fn_name,
                    self._failure_counts[fn_name],
                    MAX_FAILURES,
                )
                if self._failure_counts[fn_name] >= MAX_FAILURES:
                    logger.warning(
                        "Modifier '%s' disabled after %d consecutive failures",
                        fn_name,
                        MAX_FAILURES,
                    )
                    self._disabled.add(fn_name)

        agg.clamp()
        return agg

    @property
    def modifier_names(self) -> list[str]:
        """Names of all registered modifiers."""
        return [name for name, _ in self._modifiers]

    @property
    def disabled_modifiers(self) -> set[str]:
        """Names of modifiers disabled due to repeated failures."""
        return set(self._disabled)

    def reset(self) -> None:
        """Reset all failure counts and re-enable disabled modifiers."""
        self._failure_counts = {name: 0 for name, _ in self._modifiers}
        self._disabled.clear()

    def __len__(self) -> int:
        return len(self._modifiers)

    def __repr__(self) -> str:
        active = len(self._modifiers) - len(self._disabled)
        return f"ModifierPipeline(active={active}, disabled={len(self._disabled)})"
