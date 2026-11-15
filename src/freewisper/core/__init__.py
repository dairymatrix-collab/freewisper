"""Core: pure logic with no OS, network, or filesystem dependencies.

The layering rule for this package is strict: nothing in ``freewisper.core``
may import ``tkinter``, ``sounddevice``, ``httpx``, ``os``, ``sys`` or any
platform-specific module. That is what makes the orchestration logic
testable without mocks.

The rule is enforced automatically by ``tests/test_layering.py``.
"""

from __future__ import annotations

from .errors import (
    AudioError,
    CancelledError,
    ConfigError,
    DeviceError,
    FreewisperError,
    InjectionError,
    InvalidTransition,
    PermissionDenied,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
)
from .events import Event, EventBus, Subscriber, Subscription
from .pipeline import (
    DICTATION_GROUP,
    Cleaner,
    Injector,
    Pipeline,
    Recorder,
    Transcriber,
)
from .session import DictationSession
from .states import LEGAL_TRANSITIONS, State, StateMachine, Transition
from .tasks import CancelToken, TaskHandle, TaskRunner, cancellable_sleep

__all__ = [
    "DICTATION_GROUP",
    "LEGAL_TRANSITIONS",
    "AudioError",
    "CancelToken",
    "CancelledError",
    "Cleaner",
    "ConfigError",
    "DeviceError",
    "DictationSession",
    "Event",
    "EventBus",
    "FreewisperError",
    "InjectionError",
    "Injector",
    "InvalidTransition",
    "PermissionDenied",
    "Pipeline",
    "ProviderError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "Recorder",
    "State",
    "StateMachine",
    "Subscriber",
    "Subscription",
    "TaskHandle",
    "TaskRunner",
    "Transcriber",
    "Transition",
    "cancellable_sleep",
]
