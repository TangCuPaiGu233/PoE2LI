"""Tests for app.core.game_context helpers."""

import pytest

from app.core.game_context import is_ninja_cost_guide_query


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("帮我估算忍者网BD造价", True),
        ("poe.ninja 这套 bd 造价多少", True),
        ("忍者网算一下这套构建造价", True),
        ("https://poe.ninja/poe2/builds/x/character/a/b 算造价", False),
        ("eNabcd 算一下造价", False),
        ("忍者网是什么", False),
        ("", False),
    ],
)
def test_is_ninja_cost_guide_query(msg: str, expected: bool) -> None:
    assert is_ninja_cost_guide_query(msg) is expected
