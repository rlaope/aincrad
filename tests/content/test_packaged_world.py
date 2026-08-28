from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from importlib.resources import files

import pytest

from aincrad.content.fixtures import (
    FixtureSchemaError,
    load_packaged_world_fixture,
    validate_world_fixture,
)


def test_canonical_world_fixture_is_a_packaged_content_resource() -> None:
    fixture = files("aincrad.content").joinpath("data", "glassfrontier_world.json")

    assert fixture.is_file()


def test_current_world_uses_exact_typed_edge_records_not_legacy_connections() -> None:
    fixture = files("aincrad.content").joinpath("data", "glassfrontier_world.json")
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    locations = [
        raw["towns"][0],
        *raw["towns"][0]["facilities"],
        *raw["hunting_grounds"],
        *raw["dungeons"][0]["floors"],
    ]

    assert all({"region", "terrain", "edges"}.issubset(location) for location in locations)
    assert all("connections" not in location for location in locations)
    malformed = deepcopy(raw)
    malformed["towns"][0]["edges"][0]["unexpected"] = "value"
    with pytest.raises(FixtureSchemaError, match="edge keys must be exact"):
        validate_world_fixture(malformed)


def test_rules_v2_snapshot_is_packaged_with_the_frozen_pre_expansion_digest() -> None:
    frozen = files("aincrad.content").joinpath("data", "glassfrontier_world_rules_v2.json")

    assert frozen.is_file()
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == (
        "8eb1b9d0edd75ec31e467ea0ca338a8c40c3d0b29c36498b09bde7c3d1e0909a"
    )
    assert load_packaged_world_fixture(revision="rules-v2")["world_id"] == "glassfrontier"
