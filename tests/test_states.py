"""The state machine."""

from __future__ import annotations

import pytest

from freewisper.core.errors import InvalidTransition
from freewisper.core.events import Event, EventBus
from freewisper.core.states import LEGAL_TRANSITIONS, State, StateMachine


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def machine(bus: EventBus) -> StateMachine:
    return StateMachine(bus)


def test_starts_idle(machine: StateMachine) -> None:
    assert machine.state is State.IDLE


def test_every_legal_transition_is_accepted(machine: StateMachine) -> None:
    """Walk every edge of the transition graph."""
    for source, targets in LEGAL_TRANSITIONS.items():
        for target in targets:
            fresh = StateMachine(EventBus())
            # Drive the machine to `source` legally.
            for step in _path_to(fresh, source):
                fresh.transition(step)
            assert fresh.state is source
            fresh.transition(target)
            assert fresh.state is target


def _path_to(machine: StateMachine, target: State) -> list[State]:
    """A legal path from IDLE to ``target``."""
    paths: dict[State, list[State]] = {
        State.IDLE: [],
        State.ARMED: [State.ARMED],
        State.RECORDING: [State.ARMED, State.RECORDING],
        State.TRANSCRIBING: [State.ARMED, State.RECORDING, State.TRANSCRIBING],
        State.CLEANING: [State.ARMED, State.RECORDING, State.TRANSCRIBING, State.CLEANING],
        State.INJECTING: [
            State.ARMED,
            State.RECORDING,
            State.TRANSCRIBING,
            State.CLEANING,
            State.INJECTING,
        ],
        State.ERROR: [State.ERROR],
    }
    return paths[target]


def test_every_illegal_transition_raises(machine: StateMachine) -> None:
    for source, targets in LEGAL_TRANSITIONS.items():
        for target in State:
            if target in targets:
                continue
            fresh = StateMachine(EventBus())
            for step in _path_to(fresh, source):
                fresh.transition(step)
            with pytest.raises(InvalidTransition):
                fresh.transition(target)


def test_an_illegal_transition_publishes_an_error(bus: EventBus) -> None:
    seen: list[dict] = []
    bus.subscribe(Event.ERROR, lambda ev, payload: seen.append(dict(payload)))

    machine = StateMachine(bus)
    with pytest.raises(InvalidTransition):
        machine.transition(State.INJECTING)

    assert len(seen) == 1
    assert seen[0]["kind"] == "invalid_transition"
    assert seen[0]["source"] is State.IDLE


def test_a_successful_transition_publishes_state_changed(bus: EventBus) -> None:
    seen: list[dict] = []
    bus.subscribe(Event.STATE_CHANGED, lambda ev, payload: seen.append(dict(payload)))

    machine = StateMachine(bus)
    machine.transition(State.ARMED)

    assert len(seen) == 1
    assert seen[0]["source"] is State.IDLE
    assert seen[0]["target"] is State.ARMED


def test_transition_payload_is_forwarded(bus: EventBus) -> None:
    seen: list[dict] = []
    bus.subscribe(Event.STATE_CHANGED, lambda ev, payload: seen.append(dict(payload)))

    StateMachine(bus).transition(State.ARMED, reason="startup")

    assert seen[0]["reason"] == "startup"


def test_the_state_is_unchanged_after_an_illegal_transition(bus: EventBus) -> None:
    machine = StateMachine(bus)
    machine.transition(State.ARMED)

    with pytest.raises(InvalidTransition):
        machine.transition(State.INJECTING)

    assert machine.state is State.ARMED


def test_can_reports_legality(machine: StateMachine) -> None:
    assert machine.can(State.ARMED) is True
    assert machine.can(State.INJECTING) is False


def test_history_records_every_transition(machine: StateMachine) -> None:
    machine.transition(State.ARMED)
    machine.transition(State.RECORDING)

    history = machine.history
    assert len(history) == 2
    assert history[0].source is State.IDLE
    assert history[0].target is State.ARMED
    assert history[1].target is State.RECORDING


def test_hooks_are_called_on_success(bus: EventBus) -> None:
    seen: list[tuple[State, State]] = []
    machine = StateMachine(bus)
    machine.on_transition(lambda src, dst: seen.append((src, dst)))

    machine.transition(State.ARMED)

    assert seen == [(State.IDLE, State.ARMED)]


def test_a_raising_hook_does_not_break_the_machine(bus: EventBus) -> None:
    def boom(_src: State, _dst: State) -> None:
        raise RuntimeError("hook exploded")

    machine = StateMachine(bus)
    machine.on_transition(boom)

    machine.transition(State.ARMED)

    assert machine.state is State.ARMED


def test_force_idle_works_from_any_state(machine: StateMachine) -> None:
    machine.transition(State.ARMED)
    machine.transition(State.RECORDING)

    machine.force_idle()

    assert machine.state is State.IDLE


def test_force_idle_from_idle_is_a_no_op(machine: StateMachine) -> None:
    machine.force_idle()
    assert machine.state is State.IDLE
    assert machine.history == ()


def test_the_full_happy_path(bus: EventBus) -> None:
    machine = StateMachine(bus)
    for step in (
        State.ARMED,
        State.RECORDING,
        State.TRANSCRIBING,
        State.CLEANING,
        State.INJECTING,
        State.IDLE,
    ):
        machine.transition(step)
    assert machine.state is State.IDLE
    assert len(machine.history) == 6


def test_error_state_can_only_reach_idle(bus: EventBus) -> None:
    machine = StateMachine(bus)
    machine.transition(State.ERROR)
    assert machine.can(State.IDLE) is True
    assert machine.can(State.ARMED) is False


def test_the_transition_graph_is_fully_reachable(machine: StateMachine) -> None:
    """Every state must be reachable from IDLE."""
    reachable = {State.IDLE}
    frontier = [State.IDLE]
    while frontier:
        current = frontier.pop()
        for target in LEGAL_TRANSITIONS[current]:
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    assert reachable == set(State)


def test_self_transitions_are_never_legal() -> None:
    """A state may never transition to itself."""
    for source, targets in LEGAL_TRANSITIONS.items():
        assert source not in targets, f"{source.value} -> {source.value} must be illegal"


def test_every_state_has_a_defined_transition_set() -> None:
    """No state may be missing from the transition table."""
    assert set(LEGAL_TRANSITIONS) == set(State)
