from __future__ import annotations

import pytest

from aincrad.domain.display import display_units, is_emoji_modifier_base, is_unattached_extender
from aincrad.tui.layout import clip_display, display_width, pad_display, wrap_display


def test_combining_mark_does_not_consume_an_extra_terminal_cell() -> None:
    decomposed = "e\u0301"

    assert display_width(decomposed) == 1
    assert pad_display(decomposed, 3) == decomposed + "  "


@pytest.mark.parametrize("mark", ["\u20dd", "\ufe0f"])
def test_combining_class_zero_marks_do_not_consume_terminal_cells(mark: str) -> None:
    assert display_width("a" + mark) == 1


def test_emoji_variation_sequence_uses_two_terminal_cells() -> None:
    assert display_width("❤️") == 2


@pytest.mark.parametrize("grapheme", ["1️⃣"])
def test_common_emoji_graphemes_are_atomic_two_cell_units(grapheme: str) -> None:
    assert display_width(grapheme) == 2
    assert clip_display(grapheme, 2) == grapheme
    assert wrap_display(grapheme, 2) == [grapheme]


def test_zwj_is_not_treated_as_a_supported_atomic_display_unit() -> None:
    assert display_width("👩‍💻") == 5
    assert clip_display("👩‍💻", 2) != "👩‍💻"


@pytest.mark.parametrize(("text", "index"), [("", 0), ("A", -1), ("A", 1)])
def test_unattached_extender_rejects_invalid_index(text: str, index: int) -> None:
    with pytest.raises(ValueError, match="valid text index"):
        is_unattached_extender(text, index)


@pytest.mark.parametrize("text", ["👍🏽🏽", "🚗🏽", "🇰🏽"])
def test_invalid_modifier_sequences_are_not_atomic_display_units(text: str) -> None:
    assert len(display_units(text)) > 1
    assert clip_display(text, 2) != text
    wrapped = wrap_display(text, 2)
    assert "".join(wrapped) != text
    assert all(display_width(line) <= 2 for line in wrapped)


def test_modifier_base_policy_is_pinned_to_unicode_14() -> None:
    assert is_emoji_modifier_base("👍")
    assert not is_emoji_modifier_base("\U0001FAF7")
    assert not is_emoji_modifier_base("\U0001FAF8")


@pytest.mark.parametrize("text", ["☝️🏽", "👍\u0301🏽", "❤️️", "1️⃣⃣"])
def test_rejected_mark_sequences_are_not_atomic_display_units(text: str) -> None:
    assert clip_display(text, 2) != text


@pytest.mark.parametrize("text", ["한", "❤️", "1️⃣", "🇰🇷"])
def test_wrap_width_one_never_returns_an_overwide_line(text: str) -> None:
    assert all(display_width(line) <= 1 for line in wrap_display(text, 1))


def test_ri_pair_cannot_strand_an_extender_across_wrap_boundary() -> None:
    lines = wrap_display("🇰🇰\u0301A", 1)

    assert all(display_width(line) <= 1 for line in lines)
    assert all(not line.startswith("\u0301") for line in lines)


@pytest.mark.parametrize("text", ["\x1b[2J", "\u202eABC", "A\u200dB"])
@pytest.mark.parametrize("width", [1, 2, 6])
def test_direct_layout_apis_neutralize_terminal_controls(text: str, width: int) -> None:
    outputs = [clip_display(text, width), pad_display(text, width), *wrap_display(text, width)]

    assert all(
        "\x1b" not in output and "\u202e" not in output and "\u200d" not in output
        for output in outputs
    )
    assert all(display_width(output) <= width for output in outputs)
