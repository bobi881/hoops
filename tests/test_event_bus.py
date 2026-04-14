"""Tests for the event bus pub/sub system."""

from basketball_sim.core.event_bus import EventBus
from basketball_sim.core.types import EventType, GameEvent


def test_subscribe_and_emit():
    bus = EventBus()
    received = []

    def handler(event: GameEvent):
        received.append(event)

    bus.subscribe(EventType.SHOT_MADE, handler)
    event = GameEvent(event_type=EventType.SHOT_MADE, player_id="harden")
    bus.emit(event)

    assert len(received) == 1
    assert received[0].player_id == "harden"


def test_only_matching_type_received():
    bus = EventBus()
    received = []

    bus.subscribe(EventType.SHOT_MADE, lambda e: received.append(e))

    bus.emit(GameEvent(event_type=EventType.SHOT_MISSED))
    assert len(received) == 0

    bus.emit(GameEvent(event_type=EventType.SHOT_MADE))
    assert len(received) == 1


def test_subscribe_all():
    bus = EventBus()
    received = []

    bus.subscribe_all(lambda e: received.append(e))

    bus.emit(GameEvent(event_type=EventType.SHOT_MADE))
    bus.emit(GameEvent(event_type=EventType.TURNOVER))
    bus.emit(GameEvent(event_type=EventType.GAME_START))

    assert len(received) == 3


def test_handler_exception_doesnt_crash():
    bus = EventBus()
    received = []

    def bad_handler(event: GameEvent):
        raise RuntimeError("handler exploded")

    def good_handler(event: GameEvent):
        received.append(event)

    bus.subscribe(EventType.SHOT_MADE, bad_handler)
    bus.subscribe(EventType.SHOT_MADE, good_handler)

    # Should not raise -- bad handler is caught
    bus.emit(GameEvent(event_type=EventType.SHOT_MADE))

    # Good handler still received the event
    assert len(received) == 1


def test_history():
    bus = EventBus()
    bus.emit(GameEvent(event_type=EventType.SHOT_MADE))
    bus.emit(GameEvent(event_type=EventType.TURNOVER))

    assert len(bus.history) == 2
    assert bus.history[0].event_type == EventType.SHOT_MADE
    assert bus.history[1].event_type == EventType.TURNOVER


def test_clear():
    bus = EventBus()
    received = []
    bus.subscribe(EventType.SHOT_MADE, lambda e: received.append(e))
    bus.emit(GameEvent(event_type=EventType.SHOT_MADE))

    bus.clear()

    bus.emit(GameEvent(event_type=EventType.SHOT_MADE))
    # Handler was cleared, so received should still be 1
    assert len(received) == 1
    # History records the post-clear emit (only 1, not 2)
    assert len(bus.history) == 1


def test_unsubscribe():
    bus = EventBus()
    received = []

    def handler(event: GameEvent):
        received.append(event)

    bus.subscribe(EventType.SHOT_MADE, handler)
    bus.emit(GameEvent(event_type=EventType.SHOT_MADE))
    assert len(received) == 1

    bus.unsubscribe(EventType.SHOT_MADE, handler)
    bus.emit(GameEvent(event_type=EventType.SHOT_MADE))
    assert len(received) == 1  # no new event


def test_emit_many():
    bus = EventBus()
    received = []
    bus.subscribe_all(lambda e: received.append(e))

    events = [
        GameEvent(event_type=EventType.DRIBBLE_MOVE),
        GameEvent(event_type=EventType.SHOT_ATTEMPT),
        GameEvent(event_type=EventType.SHOT_MADE),
    ]
    bus.emit_many(events)

    assert len(received) == 3
