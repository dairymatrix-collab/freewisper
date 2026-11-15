"""Command-line interface behaviour."""

from __future__ import annotations

import json

import pytest

from freewisper.cli import main


def test_run_dry_run_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "dry run" in out.lower()
    assert "Resolved paths" in out
    assert "config file" in out


def test_run_dry_run_shows_the_effective_config(capsys: pytest.CaptureFixture[str]) -> None:
    main(["run", "--dry-run"])
    out = capsys.readouterr().out
    assert "Effective configuration" in out
    assert "hotkey" in out
    assert "cleanup_providers" in out


def test_run_without_dry_run_reports_not_wired_up(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["run"])
    err = capsys.readouterr().err
    assert code == 3
    assert "Phase 2" in err


def test_version_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    assert "freewisper" in capsys.readouterr().out


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["definitely-not-a-command"])


def test_history_reports_its_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["history"]) == 0
    assert "history.db" in capsys.readouterr().out


def test_devices_reports_a_missing_backend_cleanly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Importing sounddevice initialises PortAudio, which raises OSError (not
    # ImportError) on a machine with no audio device — so catch broadly.
    try:
        import sounddevice  # noqa: F401
    except Exception:  # noqa: BLE001
        code = main(["devices"])
        err = capsys.readouterr().err
        assert code == 2
        assert "sounddevice" in err
    else:  # pragma: no cover - depends on the environment
        pytest.skip("sounddevice is installed in this environment")


def test_devices_never_crashes_on_a_machine_without_audio(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Whatever the audio backend does, the CLI must exit cleanly."""
    code = main(["devices"])
    assert code in (0, 1, 2)
    assert "Traceback" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_lists_the_checks(capsys: pytest.CaptureFixture[str]) -> None:
    main(["doctor"])
    out = capsys.readouterr().out
    for expected in ("python", "config", "api key", "speech-to-text", "hotkey", "hud"):
        assert expected in out


def test_doctor_exit_code_matches_the_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Exit code 1 iff a check failed."""
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert (code == 1) == ("[FAIL]" in out)


def test_doctor_strict_promotes_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    """With --strict, a warning is enough to fail."""
    code = main(["doctor", "--strict"])
    out = capsys.readouterr().out
    degraded = "[WARN]" in out
    failed = "[FAIL]" in out
    assert (code == 1) == (degraded or failed)


def test_doctor_json_output_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload
    assert set(payload[0]) == {"name", "status", "detail"}
    assert payload[0]["status"] in {"PASS", "WARN", "FAIL"}


def test_doctor_reports_the_config_file_location(capsys: pytest.CaptureFixture[str]) -> None:
    main(["doctor"])
    out = capsys.readouterr().out
    assert "config.json" in out


def test_the_cli_actually_writes_to_the_log_file() -> None:
    """The log file must not be an empty stub — the app records what it did."""
    from freewisper.config import paths

    main(["run", "--dry-run"])

    log_path = paths.log_file()
    assert log_path.is_file()
    text = log_path.read_text(encoding="utf-8")
    assert text.strip(), "the log file was created but nothing was written to it"
    assert "dry run" in text


def test_doctor_results_are_recorded_in_the_log() -> None:
    from freewisper.config import paths

    main(["doctor"])
    text = paths.log_file().read_text(encoding="utf-8")
    assert "doctor:" in text
