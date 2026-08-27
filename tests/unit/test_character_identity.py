"""Tests for the replay-safe enum-coded human identity profile."""

import inspect
from dataclasses import FrozenInstanceError, fields, is_dataclass
from typing import Any

import pytest

import aincrad.domain.identity as identity_module
from aincrad.domain.identity import (
    IDENTITY_DIMENSIONS,
    IDENTITY_PROFILE_SCHEMA,
    IDENTITY_PROFILE_VERSION,
    CharacterIdentityError,
    CharacterIdentityProfile,
    CoreValue,
    InquiryStance,
    RelationshipStance,
    RiskAttitude,
)

_VALID_JSON: dict[str, Any] = {
    "schema": "aincrad.identity.profile",
    "version": 1,
    "inquiry_stance": "curious",
    "risk_attitude": "careful",
    "core_value": "harmony",
    "relationship_stance": "cooperative",
}


def _profile() -> CharacterIdentityProfile:
    return CharacterIdentityProfile(
        inquiry_stance=InquiryStance.CURIOUS,
        risk_attitude=RiskAttitude.CAREFUL,
        core_value=CoreValue.HARMONY,
        relationship_stance=RelationshipStance.COOPERATIVE,
    )


def test_error_is_a_value_error() -> None:
    assert issubclass(CharacterIdentityError, ValueError)


def test_profile_is_frozen_with_slots_and_exactly_four_dimensions() -> None:
    profile = _profile()
    assert is_dataclass(profile)
    assert not hasattr(profile, "__dict__")
    assert [f.name for f in fields(profile)] == [
        "inquiry_stance",
        "risk_attitude",
        "core_value",
        "relationship_stance",
    ]
    with pytest.raises(FrozenInstanceError):
        profile.inquiry_stance = InquiryStance.ANALYTICAL  # type: ignore[misc]


def test_enum_wire_values_are_exact_stable_english_sets() -> None:
    assert {member.value for member in InquiryStance} == {"curious", "analytical", "practical"}
    assert {member.value for member in RiskAttitude} == {"bold", "balanced", "careful"}
    assert {member.value for member in CoreValue} == {"honor", "freedom", "harmony", "growth"}
    assert {member.value for member in RelationshipStance} == {
        "leading",
        "cooperative",
        "independent",
    }


def test_profile_requires_enum_members_not_free_text() -> None:
    with pytest.raises(CharacterIdentityError, match="inquiry_stance"):
        CharacterIdentityProfile(
            inquiry_stance="curious",  # type: ignore[arg-type]
            risk_attitude=RiskAttitude.CAREFUL,
            core_value=CoreValue.HARMONY,
            relationship_stance=RelationshipStance.COOPERATIVE,
        )


def test_to_json_emits_exact_keys_schema_and_string_wire_values() -> None:
    document = _profile().to_json()
    assert document == _VALID_JSON
    assert type(document["schema"]) is str
    assert type(document["version"]) is int
    for key in ("inquiry_stance", "risk_attitude", "core_value", "relationship_stance"):
        assert type(document[key]) is str


def test_json_round_trip_preserves_the_profile() -> None:
    profile = _profile()
    assert CharacterIdentityProfile.from_json(profile.to_json()) == profile


def test_schema_constants_are_stable() -> None:
    assert IDENTITY_PROFILE_SCHEMA == "aincrad.identity.profile"
    assert IDENTITY_PROFILE_VERSION == 1


def test_from_json_rejects_non_mapping_input() -> None:
    for bad in (None, "text", 3, ["schema"], True):
        with pytest.raises(CharacterIdentityError, match="mapping"):
            CharacterIdentityProfile.from_json(bad)  # type: ignore[arg-type]


def test_from_json_rejects_missing_keys() -> None:
    for key in _VALID_JSON:
        document = dict(_VALID_JSON)
        del document[key]
        with pytest.raises(CharacterIdentityError, match="keys"):
            CharacterIdentityProfile.from_json(document)


def test_from_json_rejects_unknown_keys() -> None:
    document = dict(_VALID_JSON)
    document["notes"] = "free text"
    with pytest.raises(CharacterIdentityError, match="keys"):
        CharacterIdentityProfile.from_json(document)


def test_from_json_rejects_wrong_schema_and_wrong_version() -> None:
    with pytest.raises(CharacterIdentityError, match="schema"):
        CharacterIdentityProfile.from_json({**_VALID_JSON, "schema": "aincrad.other"})
    with pytest.raises(CharacterIdentityError, match="version"):
        CharacterIdentityProfile.from_json({**_VALID_JSON, "version": 2})


def test_from_json_rejects_non_int_and_bool_version() -> None:
    for bad_version in ("1", 1.0, True):
        with pytest.raises(CharacterIdentityError, match="version"):
            CharacterIdentityProfile.from_json({**_VALID_JSON, "version": bad_version})


def test_from_json_rejects_non_string_and_bool_dimension_values() -> None:
    for bad_value in (True, 0, None, ["curious"], InquiryStance.CURIOUS):
        with pytest.raises(CharacterIdentityError, match="inquiry_stance"):
            CharacterIdentityProfile.from_json({**_VALID_JSON, "inquiry_stance": bad_value})


def test_from_json_rejects_arbitrary_free_text_values() -> None:
    for key in ("inquiry_stance", "risk_attitude", "core_value", "relationship_stance"):
        with pytest.raises(CharacterIdentityError, match=key):
            CharacterIdentityProfile.from_json({**_VALID_JSON, key: "totally made up"})


def test_from_json_rejects_non_string_schema() -> None:
    with pytest.raises(CharacterIdentityError, match="schema"):
        CharacterIdentityProfile.from_json({**_VALID_JSON, "schema": 7})


def test_dimension_metadata_covers_all_four_dimensions_in_order() -> None:
    assert [dimension.key for dimension in IDENTITY_DIMENSIONS] == [
        "inquiry_stance",
        "risk_attitude",
        "core_value",
        "relationship_stance",
    ]


def test_dimension_metadata_has_korean_labels_questions_and_exact_options() -> None:
    expected_values = {
        "inquiry_stance": {member.value for member in InquiryStance},
        "risk_attitude": {member.value for member in RiskAttitude},
        "core_value": {member.value for member in CoreValue},
        "relationship_stance": {member.value for member in RelationshipStance},
    }
    for dimension in IDENTITY_DIMENSIONS:
        assert dimension.label
        assert dimension.question.endswith("?")
        assert any("\uac00" <= ch <= "\ud7a3" for ch in dimension.label)
        assert any("\uac00" <= ch <= "\ud7a3" for ch in dimension.question)
        assert {option.value for option in dimension.options} == expected_values[dimension.key]
        for option in dimension.options:
            assert any("\uac00" <= ch <= "\ud7a3" for ch in option.label)


def test_dimension_metadata_is_immutable() -> None:
    assert isinstance(IDENTITY_DIMENSIONS, tuple)
    dimension = IDENTITY_DIMENSIONS[0]
    assert isinstance(dimension.options, tuple)
    with pytest.raises(FrozenInstanceError):
        dimension.label = "x"  # type: ignore[misc]


def test_identity_module_does_not_touch_world_state() -> None:
    source = inspect.getsource(identity_module)
    assert "WorldState" not in source
    assert "models" not in source
    assert "rules" not in source
