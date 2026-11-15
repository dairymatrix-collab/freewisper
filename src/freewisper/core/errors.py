"""Exception taxonomy for Freewisper.

Every error the app raises deliberately derives from :class:`FreewisperError`, so
callers can distinguish "expected, handled" failures from genuine bugs.
"""

from __future__ import annotations


class FreewisperError(Exception):
    """Base class for every deliberate Freewisper failure."""


class ConfigError(FreewisperError):
    """The configuration could not be read, validated, or written."""


class AudioError(FreewisperError):
    """Audio capture failed."""


class DeviceError(AudioError):
    """The selected input device is missing or cannot be opened."""


class ProviderError(FreewisperError):
    """An external provider (STT or LLM) failed."""


class ProviderUnavailable(ProviderError):
    """The provider is not installed, not configured, or not reachable."""


class ProviderTimeout(ProviderError):
    """The provider did not answer within its timeout."""


class PermissionDenied(FreewisperError):
    """The OS refused an operation (Accessibility, Input Monitoring, mic)."""


class InjectionError(FreewisperError):
    """The transcript could not be written at the cursor."""


class InvalidTransition(FreewisperError):
    """An illegal state-machine transition was attempted."""


class CancelledError(FreewisperError):
    """A cooperatively-cancelled operation stopped before finishing."""
