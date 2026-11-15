"""The event bus."""

from __future__ import annotations

import threading

from freewisper.core.events import Event, EventBus, Subscription


def test_publish_reaches_the_subscriber() -> None:
    bus = EventBus()
    seen: list[tuple[Event, dict]] = []
    bus.subscribe(Event.INJECTED, lambda ev, payload: seen.append((ev, dict(payload))))

    delivered = bus.publish(Event.INJECTED, text="hello")

    assert delivered == 1
    assert seen == [(Event.INJECTED, {"text": "hello"})]


def test_a_subscriber_only_receives_its_own_event() -> None:
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(Event.INJECTED, lambda ev, _p: seen.append(ev))

    bus.publish(Event.CLEANUP_DONE)

    assert seen == []


def test_a_raising_subscriber_does_not_block_the_others() -> None:
    """A broken subscriber must never stop the rest of the app."""
    bus = EventBus()
    delivered: list[str] = []

    def boom(_ev: Event, _payload: dict) -> None:
        raise RuntimeError("subscriber exploded")

    bus.subscribe(Event.INJECTED, boom)
    bus.subscribe(Event.INJECTED, lambda ev, _p: delivered.append("second"))
    bus.subscribe(Event.INJECTED, lambda ev, _p: delivered.append("third"))

    count = bus.publish(Event.INJECTED)

    assert count == 2
    assert delivered == ["second", "third"]


def test_subscribers_are_called_in_subscription_order() -> None:
    bus = EventBus()
    order: list[int] = []
    for index in range(5):
        bus.subscribe(Event.INJECTED, lambda ev, _p, i=index: order.append(i))

    bus.publish(Event.INJECTED)

    assert order == [0, 1, 2, 3, 4]


def test_unsubscribe_removes_the_subscriber() -> None:
    bus = EventBus()
    seen: list[str] = []
    subscription = bus.subscribe(Event.INJECTED, lambda ev, _p: seen.append("x"))

    assert bus.unsubscribe(subscription) is True
    bus.publish(Event.INJECTED)

    assert seen == []
    assert bus.subscriber_count(Event.INJECTED) == 0


def test_unsubscribe_by_token_works() -> None:
    bus = EventBus()
    subscription = bus.subscribe(Event.INJECTED, lambda ev, _p: None)

    assert bus.unsubscribe(subscription.token) is True
    assert bus.unsubscribe(subscription.token) is False


def test_publish_with_no_subscribers_returns_zero() -> None:
    bus = EventBus()
    assert bus.publish(Event.ERROR, message="nobody listening") == 0


def test_publishing_from_inside_a_subscriber_is_safe() -> None:
    """A subscriber may publish; it must not deadlock."""
    bus = EventBus()
    seen: list[str] = []

    def relay(_ev: Event, _payload: dict) -> None:
        bus.publish(Event.CLEANUP_DONE)

    bus.subscribe(Event.TRANSCRIPT_READY, relay)
    bus.subscribe(Event.CLEANUP_DONE, lambda ev, _p: seen.append("cleanup"))

    bus.publish(Event.TRANSCRIPT_READY)

    assert seen == ["cleanup"]


def test_unsubscribing_from_inside_a_subscriber_is_safe() -> None:
    bus = EventBus()
    seen: list[str] = []
    holder: list[Subscription] = []

    def unsubscribe_self(_ev: Event, _payload: dict) -> None:
        bus.unsubscribe(holder[0])

    holder.append(bus.subscribe(Event.INJECTED, unsubscribe_self))
    bus.subscribe(Event.INJECTED, lambda ev, _p: seen.append("second"))

    bus.publish(Event.INJECTED)

    assert seen == ["second"]


def test_clear_drops_every_subscription() -> None:
    bus = EventBus()
    bus.subscribe(Event.INJECTED, lambda ev, _p: None)
    bus.subscribe(Event.ERROR, lambda ev, _p: None)
    assert bus.subscriber_count() == 2

    bus.clear()

    assert bus.subscriber_count() == 0


def test_publish_is_thread_safe() -> None:
    """Many threads publishing at once must not lose or duplicate events."""
    bus = EventBus()
    count = 0
    lock = threading.Lock()

    def counter(_ev: Event, _payload: dict) -> None:
        nonlocal count
        with lock:
            count += 1

    bus.subscribe(Event.INJECTED, counter)

    threads = [
        threading.Thread(target=lambda: [bus.publish(Event.INJECTED) for _ in range(50)])
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert count == 400
