"""Shared fixtures and explicit pass/skip/fail accounting for the test suite."""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = ROOT / "skills" / "kami"
SITE_ROOT = ROOT / "site"
REPO_ROOT = ROOT
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from build import main as build_main

_PASS = 0
_FAIL = 0
_SKIP = 0


def check(name: str, predicate: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if predicate:
        _PASS += 1
        print(f"OK: {name}")
    else:
        _FAIL += 1
        print(f"ERROR: {name}{(' - ' + detail) if detail else ''}")


def skip(name: str, detail: str = "", *, ci_required: bool = False) -> None:
    """Record an unavailable optional-dependency test without calling it a pass."""
    global _SKIP, _FAIL
    _SKIP += 1
    if ci_required and os.environ.get("CI"):
        _FAIL += 1
        print(f"ERROR: required CI test skipped: {name}{(' - ' + detail) if detail else ''}")
    else:
        print(f"SKIP: {name}{(' - ' + detail) if detail else ''}")


def write_temp_html(body: str, suffix: str = "-en.html") -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(body)
    f.close()
    return Path(f.name)


def silently(callable_, *args, **kwargs):
    """Run a function with stdout suppressed, return its result."""
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        return callable_(*args, **kwargs)


def run_build_args(args: list[str]) -> tuple[int, str]:
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        rc = build_main(["build.py", *args])
    return rc, sink.getvalue()
