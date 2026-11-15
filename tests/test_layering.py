"""The layering rule, enforced automatically.

``freewisper.core`` must be pure logic: no OS calls, no network, no
filesystem, no GUI. That is what makes the orchestration testable with
in-memory fakes instead of mocks.

This module makes that rule *executable* rather than a comment that drifts
out of date.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent / "src" / "freewisper" / "core"

#: Top-level modules that would break the "core is pure" guarantee.
FORBIDDEN_ROOTS = frozenset(
    {
        # GUI
        "tkinter",
        "AppKit",
        "objc",
        "Quartz",
        "pynput",
        "pystray",
        "PIL",
        # audio / hardware
        "sounddevice",
        "scipy",
        "vosk",
        "faster_whisper",
        # network
        "httpx",
        "requests",
        "urllib",
        "socket",
        "aiohttp",
        # OS / filesystem
        "os",
        "sys",
        "platform",
        "subprocess",
        "shutil",
        "pathlib",
        "tempfile",
        "glob",
        # app layers core must not depend on
        "freewisper.config",
        "freewisper.ui",
        "freewisper.platform",
        "freewisper.cli",
    }
)


def core_modules() -> list[Path]:
    """Every Python file in the core package."""
    return sorted(CORE_DIR.rglob("*.py"))


def imported_roots(tree: ast.AST) -> set[str]:
    """The top-level module names imported anywhere in a file."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — stays inside the package
                continue
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_core_is_not_empty() -> None:
    assert len(core_modules()) >= 6


@pytest.mark.parametrize("path", core_modules(), ids=lambda p: p.name)
def test_core_imports_nothing_forbidden(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offending = imported_roots(tree) & FORBIDDEN_ROOTS
    assert not offending, f"{path.name} imports forbidden module(s): {sorted(offending)}"


@pytest.mark.parametrize("path", core_modules(), ids=lambda p: p.name)
def test_core_never_prints(path: Path) -> None:
    """Core must not write to stdout; it publishes events instead."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "print", f"{path.name} calls print() at line {node.lineno}"


@pytest.mark.parametrize("path", core_modules(), ids=lambda p: p.name)
def test_core_never_opens_files(path: Path) -> None:
    """Core must not touch the filesystem."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", f"{path.name} calls open() at line {node.lineno}"


def test_core_has_no_module_level_mutable_state() -> None:
    """No global mutable state — every instance owns its own."""
    for path in core_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(
                node.value, (ast.List, ast.Dict, ast.Set)
            ):
                names = [
                    t.id
                    for t in node.targets
                    if isinstance(t, ast.Name) and not t.id.startswith("__")
                ]
                assert not names or all(name.isupper() for name in names), (
                    f"{path.name} defines mutable module-level state: {names}"
                )
