"""The exception taxonomy.

These classes exist so that callers can tell an *expected, handled* failure
apart from a genuine bug. The hierarchy is part of the public contract, so
it gets tested.
"""

from __future__ import annotations

import pytest

from freewisper.core import errors

CONCRETE_ERRORS = (
    errors.ConfigError,
    errors.AudioError,
    errors.DeviceError,
    errors.ProviderError,
    errors.ProviderUnavailable,
    errors.ProviderTimeout,
    errors.PermissionDenied,
    errors.InjectionError,
    errors.InvalidTransition,
)


def test_every_error_derives_from_the_base() -> None:
    for error_type in CONCRETE_ERRORS:
        assert issubclass(error_type, errors.FreewisperError), error_type.__name__


def test_the_base_error_is_an_exception() -> None:
    assert issubclass(errors.FreewisperError, Exception)


def test_audio_error_hierarchy() -> None:
    assert issubclass(errors.DeviceError, errors.AudioError)
    assert issubclass(errors.AudioError, errors.FreewisperError)


def test_provider_error_hierarchy() -> None:
    assert issubclass(errors.ProviderUnavailable, errors.ProviderError)
    assert issubclass(errors.ProviderTimeout, errors.ProviderError)
    assert issubclass(errors.ProviderError, errors.FreewisperError)


def test_errors_carry_a_message() -> None:
    with pytest.raises(errors.FreewisperError) as excinfo:
        raise errors.ProviderTimeout("groq timed out after 6s")
    assert "groq timed out after 6s" in str(excinfo.value)


def test_errors_can_be_caught_by_the_base_class() -> None:
    with pytest.raises(errors.FreewisperError):
        raise errors.InjectionError("clipboard write failed")


def test_base_error_is_exported_from_the_package() -> None:
    from freewisper import core

    assert core.FreewisperError is errors.FreewisperError
    assert "FreewisperError" in core.__all__
