"""Stable hero identity, display-name validation, and identity profile."""

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

from aincrad.domain.display import display_width, is_unattached_extender

HERO_ID = "hero"
MAX_HERO_NAME_CELLS = 24

IDENTITY_PROFILE_SCHEMA = "aincrad.identity.profile"
IDENTITY_PROFILE_VERSION = 2
MAX_IDENTITY_DESCRIPTION_CELLS = 240


class CharacterIdentityError(ValueError):
    """Raised when a character identity profile or its JSON form is invalid."""


class InquiryStance(StrEnum):
    """How the hero approaches the unknown."""

    CURIOUS = "curious"
    ANALYTICAL = "analytical"
    PRACTICAL = "practical"


class RiskAttitude(StrEnum):
    """How the hero weighs danger against opportunity."""

    BOLD = "bold"
    BALANCED = "balanced"
    CAREFUL = "careful"


class CoreValue(StrEnum):
    """What the hero holds most dear."""

    HONOR = "honor"
    FREEDOM = "freedom"
    HARMONY = "harmony"
    GROWTH = "growth"


class RelationshipStance(StrEnum):
    """How the hero relates to companions."""

    LEADING = "leading"
    COOPERATIVE = "cooperative"
    INDEPENDENT = "independent"


@dataclass(frozen=True, slots=True)
class IdentityOption:
    """One selectable enum-coded answer with a Korean label."""

    value: str
    label: str


@dataclass(frozen=True, slots=True)
class IdentityDimension:
    """CLI metadata for one identity dimension: Korean label, question, options."""

    key: str
    label: str
    question: str
    options: tuple[IdentityOption, ...]


IDENTITY_DIMENSIONS: tuple[IdentityDimension, ...] = (
    IdentityDimension(
        key="inquiry_stance",
        label="탐구 성향",
        question="낯선 것을 마주하면 어떻게 다가가나요?",
        options=(
            IdentityOption(value=InquiryStance.CURIOUS.value, label="호기심으로 먼저 다가간다"),
            IdentityOption(value=InquiryStance.ANALYTICAL.value, label="차분히 분석하고 관찰한다"),
            IdentityOption(value=InquiryStance.PRACTICAL.value, label="실용적인 쓸모부터 따진다"),
        ),
    ),
    IdentityDimension(
        key="risk_attitude",
        label="위험 태도",
        question="위험과 기회가 함께 오면 어떻게 하나요?",
        options=(
            IdentityOption(value=RiskAttitude.BOLD.value, label="과감하게 기회를 잡는다"),
            IdentityOption(value=RiskAttitude.BALANCED.value, label="득실을 저울질해 움직인다"),
            IdentityOption(value=RiskAttitude.CAREFUL.value, label="신중하게 안전을 지킨다"),
        ),
    ),
    IdentityDimension(
        key="core_value",
        label="핵심 가치",
        question="가장 소중히 여기는 가치는 무엇인가요?",
        options=(
            IdentityOption(value=CoreValue.HONOR.value, label="명예를 지키는 삶"),
            IdentityOption(value=CoreValue.FREEDOM.value, label="자유로운 삶"),
            IdentityOption(value=CoreValue.HARMONY.value, label="조화로운 삶"),
            IdentityOption(value=CoreValue.GROWTH.value, label="성장하는 삶"),
        ),
    ),
    IdentityDimension(
        key="relationship_stance",
        label="관계 성향",
        question="동료와 함께할 때 어떤 자리가 편한가요?",
        options=(
            IdentityOption(value=RelationshipStance.LEADING.value, label="앞장서서 이끈다"),
            IdentityOption(value=RelationshipStance.COOPERATIVE.value, label="힘을 모아 협력한다"),
            IdentityOption(value=RelationshipStance.INDEPENDENT.value, label="독립적으로 움직인다"),
        ),
    ),
)

_DIMENSION_ENUMS: dict[str, type[StrEnum]] = {
    "inquiry_stance": InquiryStance,
    "risk_attitude": RiskAttitude,
    "core_value": CoreValue,
    "relationship_stance": RelationshipStance,
}
_LEGACY_PROFILE_KEYS = frozenset({"schema", "version", *_DIMENSION_ENUMS})
_CURRENT_PROFILE_KEYS = frozenset(
    {"schema", "version", "personality_description", "traits_description"}
)
_LEGACY_PERSONALITY_LABELS: dict[str, dict[StrEnum, str]] = {
    "inquiry_stance": {
        InquiryStance.CURIOUS: "호기심으로 먼저 다가간다",
        InquiryStance.ANALYTICAL: "차분히 분석하고 관찰한다",
        InquiryStance.PRACTICAL: "실용적인 쓸모부터 따진다",
    },
    "risk_attitude": {
        RiskAttitude.BOLD: "과감하게 기회를 잡는다",
        RiskAttitude.BALANCED: "득실을 저울질해 움직인다",
        RiskAttitude.CAREFUL: "신중하게 안전을 지킨다",
    },
}
_LEGACY_TRAIT_LABELS: dict[str, dict[StrEnum, str]] = {
    "core_value": {
        CoreValue.HONOR: "명예를 지키는 삶",
        CoreValue.FREEDOM: "자유로운 삶",
        CoreValue.HARMONY: "조화로운 삶",
        CoreValue.GROWTH: "성장하는 삶",
    },
    "relationship_stance": {
        RelationshipStance.LEADING: "앞장서서 이끈다",
        RelationshipStance.COOPERATIVE: "힘을 모아 협력한다",
        RelationshipStance.INDEPENDENT: "독립적으로 움직인다",
    },
}


@dataclass(frozen=True, slots=True)
class CharacterIdentityProfile:
    """Replay-safe human identity profile described in natural Korean text."""

    personality_description: str
    traits_description: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "personality_description",
            _sanitize_identity_description("personality_description", self.personality_description),
        )
        object.__setattr__(
            self,
            "traits_description",
            _sanitize_identity_description("traits_description", self.traits_description),
        )

    def to_json(self) -> dict[str, str | int]:
        """Return the exact-key wire document for this profile."""
        return {
            "schema": IDENTITY_PROFILE_SCHEMA,
            "version": IDENTITY_PROFILE_VERSION,
            "personality_description": self.personality_description,
            "traits_description": self.traits_description,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> Self:
        """Parse strict v2 text or legacy v1 enum-coded identity metadata."""
        if not isinstance(document, Mapping):
            raise CharacterIdentityError("identity profile document must be a mapping")
        keys = set(document)
        if keys not in {_CURRENT_PROFILE_KEYS, _LEGACY_PROFILE_KEYS}:
            raise CharacterIdentityError("identity profile document has invalid keys")

        schema = document["schema"]
        if type(schema) is not str or schema != IDENTITY_PROFILE_SCHEMA:
            raise CharacterIdentityError(f"schema must be {IDENTITY_PROFILE_SCHEMA}")
        version = document["version"]
        if type(version) is not int or version not in {1, IDENTITY_PROFILE_VERSION}:
            raise CharacterIdentityError(f"version must be 1 or {IDENTITY_PROFILE_VERSION}")

        expected_keys = _LEGACY_PROFILE_KEYS if version == 1 else _CURRENT_PROFILE_KEYS
        if keys != expected_keys:
            raise CharacterIdentityError("identity profile document has invalid keys")
        if version == IDENTITY_PROFILE_VERSION:
            return cls(
                personality_description=document["personality_description"],
                traits_description=document["traits_description"],
            )

        parsed: dict[str, StrEnum] = {}
        for key, enum_type in _DIMENSION_ENUMS.items():
            value = document[key]
            if type(value) is not str:
                raise CharacterIdentityError(f"{key} must be a string wire value")
            try:
                parsed[key] = enum_type(value)
            except ValueError:
                raise CharacterIdentityError(f"{key} has unknown wire value") from None
        relationship_label = _LEGACY_TRAIT_LABELS["relationship_stance"][
            parsed["relationship_stance"]
        ]
        return cls(
            personality_description=(
                f"{_LEGACY_PERSONALITY_LABELS['inquiry_stance'][parsed['inquiry_stance']]}; "
                f"{_LEGACY_PERSONALITY_LABELS['risk_attitude'][parsed['risk_attitude']]}."
            ),
            traits_description=(
                f"{_LEGACY_TRAIT_LABELS['core_value'][parsed['core_value']]}; "
                f"동료와는 {relationship_label}."
            ),
        )


def _sanitize_identity_description(key: str, raw: str) -> str:
    if type(raw) is not str:
        raise CharacterIdentityError(f"{key} must be a string")

    description = unicodedata.normalize("NFC", raw).strip()
    if not description:
        raise CharacterIdentityError(f"{key} cannot be empty")
    if _has_unsupported_sequence(description):
        raise CharacterIdentityError(f"{key} contains an unsupported Unicode sequence")
    if any(unicodedata.category(character).startswith("C") for character in description):
        raise CharacterIdentityError(f"{key} cannot contain control or format characters")
    if not any("가" <= character <= "힣" for character in description):
        raise CharacterIdentityError(f"{key} must contain Korean text")

    cells = display_width(description)
    if cells == 0:
        raise CharacterIdentityError(f"{key} must occupy display cells")
    if cells > MAX_IDENTITY_DESCRIPTION_CELLS:
        raise CharacterIdentityError(
            f"{key} cannot exceed {MAX_IDENTITY_DESCRIPTION_CELLS} display cells"
        )
    return description


class HeroNameError(ValueError):
    """Raised when a hero display name is invalid."""


def validate_hero_name(raw: str) -> str:
    """Return a hero display name with surrounding whitespace removed."""
    if not isinstance(raw, str):
        raise TypeError("hero name must be a str")

    name = raw.strip()
    if not name:
        raise HeroNameError("hero name cannot be empty")
    if _has_unsupported_sequence(name):
        raise HeroNameError("hero name contains an unsupported Unicode sequence")
    if any(unicodedata.category(character).startswith("C") for character in name):
        raise HeroNameError("hero name cannot contain control or format characters")

    cells = display_width(name)
    if cells == 0:
        raise HeroNameError("hero name must occupy display cells")
    if cells > MAX_HERO_NAME_CELLS:
        raise HeroNameError(f"hero name cannot exceed {MAX_HERO_NAME_CELLS} display cells")
    return name


def _has_unsupported_sequence(name: str) -> bool:
    return any(is_unattached_extender(name, index) for index in range(len(name)))
