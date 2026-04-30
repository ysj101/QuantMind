"""最低限のスモークテスト."""

from __future__ import annotations

from quantmind import __version__


def test_version_is_string() -> None:
    assert isinstance(__version__, str)
    assert __version__.count(".") >= 1
