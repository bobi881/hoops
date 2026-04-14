"""Pub/sub event bus -- the backbone of the simulator.

The engine emits typed events. Narration, stats, rendering, and any other
system subscribes to event types they care about. No module-to-module
coupling -- everything communicates through events.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

from basketball_sim.core.types import EventType, GameEvent

logger = logging.getLogger(__name__)

# Subscriber callback signature: receives a GameEvent, returns nothing
EventHandler = Callable[[GameEvent], None]


class EventBus:
    """Simple synchronous pub/sub event bus.

    Usage:
        bus = EventBus()
        bus.subscribe(EventType.SHOT_MADE, my_handler)
        bus.emit(GameEvent(event_type=EventType.SHOT_MADE, ...))
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []
        self._history: list[GameEvent] = []
        self._record_history: bool = True

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler that receives ALL events."""
        self._global_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a handler for a specific event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event: GameEvent) -> None:
        """Emit an event to all registered handlers.

        Handlers for the specific event type are called first,
        then global handlers. Exceptions in handlers are caught
        and logged -- a broken subscriber never crashes the engine.
        """
        if self._record_history:
            self._history.append(event)

        # Type-specific handlers
        for handler in self._handlers.get(event.event_type, []):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Handler %s failed on event %s",
                    handler.__name__,
                    event.event_type.name,
                )

        # Global handlers
        for handler in self._global_handlers:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Global handler %s failed on event %s",
                    handler.__name__,
                    event.event_type.name,
                )

    def emit_many(self, events: list[GameEvent]) -> None:
        """Emit a batch of events in order."""
        for event in events:
            self.emit(event)

    @property
    def history(self) -> list[GameEvent]:
        """All events emitted so far (for replay / debugging)."""
        return self._history

    def clear_history(self) -> None:
        """Clear the event history."""
        self._history.clear()

    def clear(self) -> None:
        """Remove all handlers and clear history."""
        self._handlers.clear()
        self._global_handlers.clear()
        self._history.clear()
