from __future__ import annotations

from importlib.resources import files


def test_canonical_world_fixture_is_a_packaged_content_resource() -> None:
    fixture = files("aincrad.content").joinpath("data", "glassfrontier_world.json")

    assert fixture.is_file()
