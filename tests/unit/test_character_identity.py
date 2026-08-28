"""Tests for the replay-safe natural-language human identity profile."""

import inspect
from dataclasses import FrozenInstanceError, fields, is_dataclass
from typing import Any

import pytest

import aincrad.domain.identity as identity_module
from aincrad.domain.identity import (
    IDENTITY_DIMENSIONS,
    IDENTITY_PROFILE_SCHEMA,
    IDENTITY_PROFILE_VERSION,
    MAX_IDENTITY_DESCRIPTION_CELLS,
    CharacterIdentityError,
    CharacterIdentityProfile,
    CoreValue,
    InquiryStance,
    RelationshipStance,
    RiskAttitude,
)

_VALID_V2_JSON: dict[str, Any] = {
    "schema": "aincrad.identity.profile",
    "version": 2,
    "personality_description": "차분히 관찰한 뒤 동료의 의견을 듣고 행동한다.",
    "traits_description": "위기에서는 약자를 먼저 돕고 약속을 끝까지 지킨다.",
}
_LEGACY_V1_JSON: dict[str, Any] = {
    "schema": "aincrad.identity.profile",
    "version": 1,
    "inquiry_stance": "curious",
    "risk_attitude": "careful",
    "core_value": "harmony",
    "relationship_stance": "cooperative",
}


def _profile() -> CharacterIdentityProfile:
    return CharacterIdentityProfile(
        personality_description="차분히 관찰한 뒤 동료의 의견을 듣고 행동한다.",
        traits_description="위기에서는 약자를 먼저 돕고 약속을 끝까지 지킨다.",
    )


def test_current_profile_persists_normalized_korean_descriptions_as_v2() -> None:
    profile = CharacterIdentityProfile(
        personality_description="  차분히 관찰한 뒤 동료의 의견을 듣고 행동한다.  ",
        traits_description="위기에서는 약자를 먼저 돕고 약속을 끝까지 지킨다.",
    )

    assert profile.personality_description == "차분히 관찰한 뒤 동료의 의견을 듣고 행동한다."
    assert profile.traits_description == "위기에서는 약자를 먼저 돕고 약속을 끝까지 지킨다."
    assert profile.to_json() == _VALID_V2_JSON


def test_profile_is_frozen_with_slots_and_exactly_two_text_dimensions() -> None:
    profile = _profile()
    assert is_dataclass(profile)
    assert not hasattr(profile, "__dict__")
    assert [field.name for field in fields(profile)] == [
        "personality_description",
        "traits_description",
    ]
    with pytest.raises(FrozenInstanceError):
        profile.personality_description = "새 성격 설명"  # type: ignore[misc]


def test_current_json_round_trip_preserves_profile() -> None:
    profile = _profile()
    assert CharacterIdentityProfile.from_json(profile.to_json()) == profile


def test_current_json_uses_exact_v2_schema_keys() -> None:
    assert _profile().to_json() == _VALID_V2_JSON
    assert type(IDENTITY_PROFILE_VERSION) is int
    assert IDENTITY_PROFILE_SCHEMA == "aincrad.identity.profile"
    assert IDENTITY_PROFILE_VERSION == 2


@pytest.mark.parametrize("field_name", ["personality_description", "traits_description"])
def test_constructor_rejects_non_korean_or_empty_descriptions(field_name: str) -> None:
    values: dict[str, Any] = {
        "personality_description": "침착하게 주변을 살핀다.",
        "traits_description": "동료를 소중히 여기고 약속을 지킨다.",
    }
    for bad_value in ("", "   ", "curious", "\u0301"):
        values[field_name] = bad_value
        with pytest.raises(CharacterIdentityError, match=field_name):
            CharacterIdentityProfile(**values)


@pytest.mark.parametrize("field_name", ["personality_description", "traits_description"])
def test_constructor_rejects_non_string_control_and_unsupported_unicode(
    field_name: str,
) -> None:
    values: dict[str, Any] = {
        "personality_description": "침착하게 주변을 살핀다.",
        "traits_description": "동료를 소중히 여기고 약속을 지킨다.",
    }
    for bad_value in (None, True, 3, ["설명"], "줄\n바꿈", "형식\u200b문자", "\u0301설명"):
        values[field_name] = bad_value
        with pytest.raises(CharacterIdentityError, match=field_name):
            CharacterIdentityProfile(**values)


@pytest.mark.parametrize("field_name", ["personality_description", "traits_description"])
def test_constructor_bounds_each_description_by_display_cells(field_name: str) -> None:
    values: dict[str, Any] = {
        "personality_description": "침착하게 주변을 살핀다.",
        "traits_description": "동료를 소중히 여기고 약속을 지킨다.",
    }
    values[field_name] = "가" * (MAX_IDENTITY_DESCRIPTION_CELLS // 2 + 1)
    with pytest.raises(CharacterIdentityError, match=field_name):
        CharacterIdentityProfile(**values)


def test_from_json_reads_legacy_v1_profile_as_current_natural_text() -> None:
    profile = CharacterIdentityProfile.from_json(_LEGACY_V1_JSON)

    assert profile == CharacterIdentityProfile(
        personality_description="호기심으로 먼저 다가간다; 신중하게 안전을 지킨다.",
        traits_description="조화로운 삶; 동료와는 힘을 모아 협력한다.",
    )
    assert profile.to_json() == {
        "schema": "aincrad.identity.profile",
        "version": 2,
        "personality_description": "호기심으로 먼저 다가간다; 신중하게 안전을 지킨다.",
        "traits_description": "조화로운 삶; 동료와는 힘을 모아 협력한다.",
    }


@pytest.mark.parametrize("document", [None, "text", 3, ["schema"], True])
def test_from_json_rejects_non_mapping_input(document: object) -> None:
    with pytest.raises(CharacterIdentityError, match="mapping"):
        CharacterIdentityProfile.from_json(document)  # type: ignore[arg-type]


@pytest.mark.parametrize("base_document", [_VALID_V2_JSON, _LEGACY_V1_JSON])
def test_from_json_rejects_missing_and_unknown_keys(base_document: dict[str, Any]) -> None:
    for key in base_document:
        document = dict(base_document)
        del document[key]
        with pytest.raises(CharacterIdentityError, match="keys"):
            CharacterIdentityProfile.from_json(document)
    with pytest.raises(CharacterIdentityError, match="keys"):
        CharacterIdentityProfile.from_json({**base_document, "notes": "설명"})


@pytest.mark.parametrize("bad_version", ["2", 2.0, True, 3])
def test_from_json_rejects_invalid_version_types_and_values(bad_version: object) -> None:
    with pytest.raises(CharacterIdentityError, match="version"):
        CharacterIdentityProfile.from_json({**_VALID_V2_JSON, "version": bad_version})


def test_from_json_rejects_wrong_schema() -> None:
    with pytest.raises(CharacterIdentityError, match="schema"):
        CharacterIdentityProfile.from_json({**_VALID_V2_JSON, "schema": "aincrad.other"})


@pytest.mark.parametrize("field_name", ["personality_description", "traits_description"])
def test_from_json_rejects_invalid_current_text(field_name: str) -> None:
    for bad_value in (True, 0, None, ["설명"], "\t", "curious", "줄\n바꿈"):
        with pytest.raises(CharacterIdentityError, match=field_name):
            CharacterIdentityProfile.from_json({**_VALID_V2_JSON, field_name: bad_value})


@pytest.mark.parametrize(
    "legacy_key", ["inquiry_stance", "risk_attitude", "core_value", "relationship_stance"]
)
def test_from_json_rejects_invalid_legacy_enum_wire_values(legacy_key: str) -> None:
    for bad_value in (True, 0, None, ["curious"], "made-up"):
        with pytest.raises(CharacterIdentityError, match=legacy_key):
            CharacterIdentityProfile.from_json({**_LEGACY_V1_JSON, legacy_key: bad_value})


def test_legacy_enum_symbols_and_selection_metadata_remain_available() -> None:
    assert InquiryStance.CURIOUS.value == "curious"
    assert RiskAttitude.CAREFUL.value == "careful"
    assert CoreValue.HARMONY.value == "harmony"
    assert RelationshipStance.COOPERATIVE.value == "cooperative"
    assert [dimension.key for dimension in IDENTITY_DIMENSIONS] == [
        "inquiry_stance",
        "risk_attitude",
        "core_value",
        "relationship_stance",
    ]


def test_error_is_a_value_error() -> None:
    assert issubclass(CharacterIdentityError, ValueError)


def test_identity_module_does_not_touch_world_state() -> None:
    source = inspect.getsource(identity_module)
    assert "WorldState" not in source
    assert "models" not in source
    assert "rules" not in source
