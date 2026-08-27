import pytest

from aincrad.domain.identity import (
    HERO_ID,
    MAX_HERO_NAME_CELLS,
    HeroNameError,
    validate_hero_name,
)


def test_stable_hero_identity_is_independent_of_exact_accepted_name() -> None:
    assert HERO_ID == "hero"
    assert validate_hero_name("  Aria  ") == "Aria"
    assert validate_hero_name("  아리아  ") == "아리아"
    assert validate_hero_name("ArIa") == "ArIa"


def test_hero_name_error_is_a_value_error() -> None:
    assert issubclass(HeroNameError, ValueError)


def test_hero_name_requires_a_string() -> None:
    with pytest.raises(TypeError, match="str"):
        validate_hero_name(123)  # type: ignore[arg-type]


def test_hero_name_rejects_empty_or_whitespace_only_input() -> None:
    for raw in ("", " ", "\u3000"):
        with pytest.raises(HeroNameError, match="empty"):
            validate_hero_name(raw)


@pytest.mark.parametrize(
    "raw",
    (
        "hero\u202ename",
        "hero\x00name",
        "hero\tname",
        "hero\nname",
        "hero\ue000name",
        "hero\ud800name",
        "hero\u0378name",
    ),
)
def test_hero_name_rejects_every_unicode_other_category(raw: str) -> None:
    with pytest.raises(HeroNameError, match="control|format"):
        validate_hero_name(raw)


def test_hero_name_accepts_emoji_without_changing_it() -> None:
    assert validate_hero_name("  Astra 🌟  ") == "Astra 🌟"


def test_hero_name_cell_limit_has_deterministic_narrow_and_wide_boundaries() -> None:
    assert MAX_HERO_NAME_CELLS == 24
    assert validate_hero_name("a" * 24) == "a" * 24
    assert validate_hero_name("한" * 12) == "한" * 12
    assert validate_hero_name("🌟" * 12) == "🌟" * 12
    assert validate_hero_name("❤️" * 12) == "❤️" * 12

    for raw in ("a" * 25, "한" * 13, "🌟" * 13, "❤️" * 13):
        with pytest.raises(HeroNameError, match="24"):
            validate_hero_name(raw)


def test_combining_marks_are_preserved_and_have_zero_cell_width() -> None:
    name = "e" + "\u0301" * 30

    assert validate_hero_name(name) == name


def test_hero_name_rejects_zero_width_only_input() -> None:
    with pytest.raises(HeroNameError, match="unsupported Unicode sequence"):
        validate_hero_name("\u0301")


@pytest.mark.parametrize(
    "raw",
    [
        "\u0301A",
        "\ufe0fA",
        "\u20e3A",
        "🏽A",
        "A \u0301B",
        "👩‍💻",
        "👍🏽🏽",
        "🚗🏽",
        "🇰🏽",
    ],
)
def test_hero_name_rejects_unattached_extenders_and_zwj(raw: str) -> None:
    with pytest.raises(HeroNameError, match="unsupported Unicode sequence"):
        validate_hero_name(raw)


def test_hero_name_accepts_exact_emoji_modifier_base_sequence() -> None:
    assert validate_hero_name("👍🏽") == "👍🏽"
