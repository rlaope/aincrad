from __future__ import annotations

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from aincrad.history import (
    HistoryArchive,
    HistoryCorruptionError,
    HistoryValidationError,
    UnsupportedHistoryVersionError,
)


def party_member(character_id: str = "asuna", *, alive: bool = True) -> dict[str, object]:
    return {
        "id": character_id,
        "name": "Asuna",
        "level": 1,
        "exp": 0,
        "hp": 100 if alive else 0,
        "mp": 20,
        "alive": alive,
    }


def hourly(tick: int, *, party: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "day": tick // 24 + 1,
        "hour": tick % 24,
        "tick": tick,
        "events": [],
        "party": [party_member()] if party is None else party,
    }


def canonical_write(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_create_run_assigns_monotonic_numbers_and_canonical_metadata(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)

    first = archive.create_run({"seed": 7, "label": "첫 회차"})
    second = archive.create_run({"seed": 8})

    assert (first, second) == (1, 2)
    raw = (tmp_path / "runs" / "000001" / "run.json").read_bytes()
    assert raw == (
        b'{"metadata":{"label":"\xec\xb2\xab \xed\x9a\x8c\xec\xb0\xa8","seed":7},'
        b'"run_number":1,"schema":"aincrad.history.run","version":1}\n'
    )
    assert (tmp_path / "run-counter.json").read_bytes() == (
        b'{"last_run":2,"schema":"aincrad.history.counter","version":1}\n'
    )


def test_create_run_numbers_are_atomic_across_archive_instances(tmp_path: Path) -> None:
    def create(index: int) -> int:
        return HistoryArchive(tmp_path).create_run({"worker": index})

    with ThreadPoolExecutor(max_workers=8) as executor:
        numbers = list(executor.map(create, range(24)))

    assert sorted(numbers) == list(range(1, 25))
    assert len(list((tmp_path / "runs").glob("*/run.json"))) == 24


def test_create_run_refuses_replaced_root_after_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    displaced = tmp_path / "displaced"
    outside = tmp_path / "outside"
    outside.mkdir()
    archive = HistoryArchive(archive_root)
    original_check_node = archive._check_node
    attacked = False

    def replace_root_after_lock(path: Path, kind: str, *, missing_ok: bool = False) -> bool:
        nonlocal attacked
        result = original_check_node(path, kind, missing_ok=missing_ok)
        if path.name == ".run-number.lock" and not attacked:
            attacked = True
            archive_root.rename(displaced)
            archive_root.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(archive, "_check_node", replace_root_after_lock)

    with pytest.raises(HistoryCorruptionError, match="replaced|symlink"):
        archive.create_run({})

    assert list(outside.iterdir()) == []


def test_append_refuses_replaced_run_after_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    archive = HistoryArchive(archive_root)
    run_number = archive.create_run({})
    run_path = archive_root / "runs" / "000001"
    displaced = archive_root / "runs" / "displaced"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_check_node = archive._check_node
    attacked = False

    def replace_run_after_lock(path: Path, kind: str, *, missing_ok: bool = False) -> bool:
        nonlocal attacked
        result = original_check_node(path, kind, missing_ok=missing_ok)
        if path.name == ".append.lock" and not attacked:
            attacked = True
            run_path.rename(displaced)
            run_path.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(archive, "_check_node", replace_run_after_lock)

    with pytest.raises(HistoryCorruptionError, match="replaced|symlink"):
        archive.append_hourly(run_number, hourly(0))

    assert list(outside.iterdir()) == []


def test_archive_fails_closed_without_required_directory_fd_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd - {os.link})

    with pytest.raises(HistoryCorruptionError, match="directory-relative.*unavailable"):
        HistoryArchive(tmp_path / "archive").create_run({})

    assert list((tmp_path / "archive").iterdir()) == []


def test_deleted_highest_run_is_corruption_and_number_is_never_reused(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    archive.create_run({})
    archive.create_run({})
    run_two = tmp_path / "runs" / "000002"
    for child in (run_two / "records",):
        child.rmdir()
    (run_two / "run.json").unlink()
    run_two.rmdir()

    with pytest.raises(HistoryCorruptionError, match="missing run"):
        archive.create_run({})

    assert json.loads((tmp_path / "run-counter.json").read_bytes())["last_run"] == 2
    assert not (tmp_path / "runs" / "000003").exists()


def test_missing_middle_numeric_run_is_a_corrupt_gap(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    for _ in range(3):
        archive.create_run({})
    run_two = tmp_path / "runs" / "000002"
    (run_two / "records").rmdir()
    (run_two / "run.json").unlink()
    run_two.rmdir()

    with pytest.raises(HistoryCorruptionError, match="missing run 2"):
        archive.list_runs()


def test_numeric_run_substitution_after_enumeration_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = HistoryArchive(tmp_path)
    archive.create_run({"source": "original"})
    run_path = tmp_path / "runs" / "000001"
    replacement = tmp_path / "replacement"
    displaced = tmp_path / "displaced"
    shutil.copytree(run_path, replacement)
    original_enumerate = archive._numeric_run_names_at
    attacked = False

    def enumerate_then_replace(root_fd: int, runs_fd: int):  # type: ignore[no-untyped-def]
        nonlocal attacked
        entries = original_enumerate(root_fd, runs_fd)
        if not attacked:
            attacked = True
            run_path.rename(displaced)
            replacement.rename(run_path)
        return entries

    monkeypatch.setattr(archive, "_numeric_run_names_at", enumerate_then_replace)

    with pytest.raises(HistoryCorruptionError, match="replaced"):
        archive.list_runs()


@pytest.mark.parametrize("bad_name", ["notes", "000002.tmp", "2", "000000"])
def test_unexpected_or_noncanonical_run_entry_is_corruption(tmp_path: Path, bad_name: str) -> None:
    archive = HistoryArchive(tmp_path)
    archive.create_run({})
    (tmp_path / "runs" / bad_name).mkdir()

    with pytest.raises(HistoryCorruptionError, match="unexpected run entry"):
        archive.list_runs()


def test_counter_rollback_and_missing_counter_are_corruption(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    archive.create_run({})
    archive.create_run({})
    counter = tmp_path / "run-counter.json"
    document = json.loads(counter.read_bytes())
    document["last_run"] = 1
    canonical_write(counter, document)

    with pytest.raises(HistoryCorruptionError, match="counter"):
        archive.list_runs()

    counter.unlink()
    with pytest.raises(HistoryCorruptionError, match="counter"):
        archive.create_run({})


def test_load_run_reads_timeline_from_verified_directory_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    alternate_root = tmp_path / "alternate"
    displaced_root = tmp_path / "displaced"
    archive = HistoryArchive(archive_root)
    alternate = HistoryArchive(alternate_root)
    run_number = archive.create_run({"source": "original"})
    alternate.create_run({"source": "alternate"})
    archive.append_hourly(run_number, hourly(0))
    alternate.append_hourly(run_number, {**hourly(0), "events": [{"source": "alternate"}]})
    original_read_document_at = archive._read_document_at
    attacked = False

    def exchange_archives() -> None:
        archive_root.rename(displaced_root)
        alternate_root.rename(archive_root)

    def restore_archives() -> None:
        archive_root.rename(alternate_root)
        displaced_root.rename(archive_root)

    def read_document_at_during_exchange(  # type: ignore[no-untyped-def]
        parent_fd: int, parent_path: Path, name: str, **kwargs
    ):
        nonlocal attacked
        if parent_path.name != "records" or attacked:
            return original_read_document_at(parent_fd, parent_path, name, **kwargs)
        attacked = True
        exchange_archives()
        try:
            return original_read_document_at(parent_fd, parent_path, name, **kwargs)
        finally:
            restore_archives()

    monkeypatch.setattr(archive, "_read_document_at", read_document_at_during_exchange)

    details = archive.load_run(run_number)

    assert attacked
    assert details.metadata == {"source": "original"}
    assert details.timeline[0].payload == hourly(0)


def test_append_rejects_records_directory_substitution_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})
    run_path = tmp_path / "runs" / "000001"
    records_path = run_path / "records"
    displaced = tmp_path / "displaced-records"
    replacement = tmp_path / "replacement-records"
    replacement.mkdir()
    original_validate = archive._validate_timeline_addition
    attacked = False

    def validate_then_replace(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal attacked
        original_validate(*args, **kwargs)
        if not attacked:
            attacked = True
            records_path.rename(displaced)
            replacement.rename(records_path)

    monkeypatch.setattr(archive, "_validate_timeline_addition", validate_then_replace)

    with pytest.raises(HistoryCorruptionError, match="records.*replaced|replaced.*records"):
        archive.append_hourly(run_number, hourly(0))

    assert list(records_path.iterdir()) == []
    assert list(displaced.iterdir()) == []


def test_append_record_types_and_load_timeline(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({"seed": 7, "hero_id": "asuna"})

    assert archive.append_hourly(run_number, hourly(0)) == 1
    for tick in range(1, 23):
        archive.append_hourly(run_number, hourly(tick))
    archive.append_hourly(run_number, hourly(23, party=[party_member(alive=False)]))
    assert archive.append_daily_summary(run_number, {"day": 1, "survivors": 0}) == 25
    assert (
        archive.record_character_end(
            run_number,
            {"character_id": "asuna", "ending": "death", "story": "fell in battle"},
        )
        == 26
    )

    details = archive.load_run(run_number)
    assert details.run_number == 1
    assert details.metadata == {"seed": 7, "hero_id": "asuna"}
    assert details.timeline[0].payload == hourly(0)
    assert details.timeline[-2].payload == {"day": 1, "survivors": 0}
    assert details.timeline[-1].kind == "character_end"


def test_list_runs_returns_cli_ready_summaries(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    archive.create_run({"name": "one"})
    second = archive.create_run({"name": "two"})
    archive.append_hourly(second, hourly(0))

    summaries = archive.list_runs()

    assert [(item.run_number, item.metadata, item.record_count) for item in summaries] == [
        (1, {"name": "one"}, 0),
        (2, {"name": "two"}, 1),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"story": "safe\x1b[2Junsafe"},
        {"story": "line one\nline two"},
        {"bad\x00key": "value"},
        {"not_json": object()},
        {"not_finite": float("nan")},
        {"nested": [{"value": "\x7f"}]},
    ],
)
def test_metadata_boundary_rejects_terminal_controls_and_non_json_values(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    archive = HistoryArchive(tmp_path)

    with pytest.raises(HistoryValidationError):
        archive.create_run(payload)

    assert archive.list_runs() == ()


@pytest.mark.parametrize(
    ("method", "payload"),
    [
        ("append_hourly", {"day": 1, "hour": 0, "tick": 0, "events": [], "party": [], "x": 1}),
        ("append_hourly", {"day": 1, "hour": 0, "tick": 0, "events": [], "party": [{"id": "a"}]}),
        ("append_hourly", {"day": 1, "hour": True, "tick": 0, "events": [], "party": []}),
        ("append_daily_summary", {"day": 1, "survivors": -1}),
        ("append_daily_summary", {"day": 1, "summary": "extra"}),
        ("record_character_end", {"character_id": "a", "ending": "death", "story": "", "extra": 1}),
        ("record_character_end", {"character_id": "", "ending": "death", "story": "end"}),
    ],
)
def test_strict_payload_schemas_reject_wrong_keys_types_and_ranges(
    tmp_path: Path, method: str, payload: dict[str, object]
) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})

    with pytest.raises(HistoryValidationError, match="payload"):
        getattr(archive, method)(run_number, payload)


@pytest.mark.parametrize(
    "payload",
    [
        {**hourly(0), "day": 2},
        {**hourly(0), "hour": 1},
        {**hourly(0), "tick": 1},
    ],
)
def test_hourly_day_hour_tick_must_correspond_and_be_contiguous(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})

    with pytest.raises(HistoryValidationError, match="tick|day|hour"):
        archive.append_hourly(run_number, payload)


def test_daily_summary_has_unique_end_of_day_placement(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})

    with pytest.raises(HistoryValidationError, match="summary"):
        archive.append_daily_summary(run_number, {"day": 1, "survivors": 0})

    for tick in range(24):
        archive.append_hourly(run_number, hourly(tick))
    archive.append_daily_summary(run_number, {"day": 1, "survivors": 1})

    with pytest.raises(HistoryValidationError, match="summary"):
        archive.append_daily_summary(run_number, {"day": 1, "survivors": 1})

    archive.append_hourly(run_number, hourly(24))
    with pytest.raises(HistoryValidationError, match="summary"):
        archive.append_daily_summary(run_number, {"day": 2, "survivors": 1})


def test_daily_summary_survivors_equal_latest_hourly_alive_count(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})
    for tick in range(23):
        archive.append_hourly(run_number, hourly(tick))
    dead = {**party_member("kirito"), "alive": False, "hp": 0}
    archive.append_hourly(run_number, hourly(23, party=[party_member(), dead]))

    with pytest.raises(HistoryValidationError, match="survivors.*alive"):
        archive.append_daily_summary(run_number, {"day": 1, "survivors": 2})


def test_character_end_must_match_run_metadata_hero_id(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({"hero_id": "asuna"})
    archive.append_hourly(
        run_number,
        hourly(0, party=[party_member("kirito", alive=False)]),
    )

    with pytest.raises(HistoryValidationError, match="hero_id"):
        archive.record_character_end(
            run_number,
            {"character_id": "kirito", "ending": "death", "story": "fell"},
        )


def test_character_end_is_terminal_for_every_later_record_kind(tmp_path: Path) -> None:
    for index, later_kind in enumerate(("hourly", "daily_summary", "character_end"), start=1):
        archive = HistoryArchive(tmp_path / str(index))
        run_number = archive.create_run({"hero_id": "asuna"})
        for tick in range(23):
            archive.append_hourly(run_number, hourly(tick))
        archive.append_hourly(
            run_number,
            hourly(
                23,
                party=[party_member(alive=False), party_member("kirito", alive=False)],
            ),
        )
        archive.record_character_end(
            run_number,
            {"character_id": "asuna", "ending": "death", "story": "fell"},
        )

        with pytest.raises(HistoryValidationError, match="terminal"):
            if later_kind == "hourly":
                archive.append_hourly(
                    run_number,
                    hourly(24, party=[party_member("kirito", alive=False)]),
                )
            elif later_kind == "daily_summary":
                archive.append_daily_summary(run_number, {"day": 1, "survivors": 0})
            else:
                archive.record_character_end(
                    run_number,
                    {"character_id": "kirito", "ending": "death", "story": "fell"},
                )


def test_character_end_is_unique_per_character_and_character_stays_ended(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({"hero_id": "asuna"})
    archive.append_hourly(run_number, hourly(0, party=[party_member(alive=False)]))
    ending = {"character_id": "asuna", "ending": "death", "story": "fell"}
    archive.record_character_end(run_number, ending)

    with pytest.raises(HistoryValidationError, match="terminal"):
        archive.record_character_end(run_number, ending)
    with pytest.raises(HistoryValidationError, match="terminal"):
        archive.append_hourly(run_number, hourly(1))


def test_character_end_rejects_character_alive_in_latest_hourly_snapshot(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({"hero_id": "asuna"})
    archive.append_hourly(run_number, hourly(0))

    with pytest.raises(HistoryValidationError, match="latest hourly.*alive=false"):
        archive.record_character_end(
            run_number,
            {"character_id": "asuna", "ending": "death", "story": "fell"},
        )


def test_malformed_canonical_stored_payload_is_corruption(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})
    archive.append_hourly(run_number, hourly(0))
    record_file = tmp_path / "runs" / "000001" / "records" / "000001.json"
    document = json.loads(record_file.read_bytes())
    document["payload"]["party"][0].pop("alive")
    canonical_write(record_file, document)

    with pytest.raises(HistoryCorruptionError, match="payload"):
        archive.load_run(run_number)


def test_duplicate_stored_summary_and_end_are_corruption(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({"hero_id": "asuna"})
    for tick in range(23):
        archive.append_hourly(run_number, hourly(tick))
    archive.append_hourly(run_number, hourly(23, party=[party_member(alive=False)]))
    archive.append_daily_summary(run_number, {"day": 1, "survivors": 0})
    archive.record_character_end(
        run_number, {"character_id": "asuna", "ending": "death", "story": "fell"}
    )
    records = tmp_path / "runs" / "000001" / "records"
    for source_name, target_name, sequence in [
        ("000025.json", "000027.json", 27),
        ("000026.json", "000028.json", 28),
    ]:
        document = json.loads((records / source_name).read_bytes())
        document["sequence"] = sequence
        canonical_write(records / target_name, document)

    with pytest.raises(HistoryCorruptionError, match="summary|character_end"):
        archive.load_run(run_number)


def test_duplicate_stored_character_end_is_corruption(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({"hero_id": "asuna"})
    archive.append_hourly(run_number, hourly(0, party=[party_member(alive=False)]))
    archive.record_character_end(
        run_number, {"character_id": "asuna", "ending": "death", "story": "fell"}
    )
    records = tmp_path / "runs" / "000001" / "records"
    duplicate = json.loads((records / "000002.json").read_bytes())
    duplicate["sequence"] = 3
    canonical_write(records / "000003.json", duplicate)

    with pytest.raises(HistoryCorruptionError, match="character_end"):
        archive.load_run(run_number)


@pytest.mark.parametrize(
    "target_kind", ["root", "runs", "run", "records", "record", "root_lock", "run_lock"]
)
def test_symlinks_fail_closed_without_writing_outside_archive(
    tmp_path: Path, target_kind: str
) -> None:
    archive_root = tmp_path / "archive"
    outside = tmp_path / "outside"
    outside.mkdir()

    if target_kind == "root":
        archive_root.symlink_to(outside, target_is_directory=True)
        archive = HistoryArchive(archive_root)
        operation = lambda: archive.create_run({})  # noqa: E731
    elif target_kind == "runs":
        archive_root.mkdir()
        (archive_root / "runs").symlink_to(outside, target_is_directory=True)
        archive = HistoryArchive(archive_root)
        operation = lambda: archive.create_run({})  # noqa: E731
    else:
        archive = HistoryArchive(archive_root)
        run_number = archive.create_run({})
        run_path = archive_root / "runs" / "000001"
        if target_kind == "run":
            for child in (run_path / "records",):
                child.rmdir()
            (run_path / "run.json").unlink()
            run_path.rmdir()
            run_path.symlink_to(outside, target_is_directory=True)
            operation = lambda: archive.append_hourly(run_number, hourly(0))  # noqa: E731
        elif target_kind == "records":
            (run_path / "records").rmdir()
            (run_path / "records").symlink_to(outside, target_is_directory=True)
            operation = lambda: archive.append_hourly(run_number, hourly(0))  # noqa: E731
        elif target_kind == "record":
            (run_path / "records" / "000001.json").symlink_to(outside / "record.json")
            operation = lambda: archive.append_hourly(run_number, hourly(0))  # noqa: E731
        elif target_kind == "root_lock":
            (archive_root / ".run-number.lock").unlink()
            (archive_root / ".run-number.lock").symlink_to(outside / "lock")
            operation = lambda: archive.create_run({})  # noqa: E731
        else:
            (run_path / ".append.lock").symlink_to(outside / "lock")
            operation = lambda: archive.append_hourly(run_number, hourly(0))  # noqa: E731

    with pytest.raises(HistoryCorruptionError, match="symlink|archive"):
        operation()

    assert list(outside.iterdir()) == []


def test_corrupt_json_is_rejected_without_recovery(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    archive.create_run({})
    run_file = tmp_path / "runs" / "000001" / "run.json"
    run_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(HistoryCorruptionError, match="run.json"):
        archive.load_run(1)
    assert run_file.read_text(encoding="utf-8") == "{broken"


def test_unsupported_schema_version_is_explicitly_rejected(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    archive.create_run({})
    run_file = tmp_path / "runs" / "000001" / "run.json"
    document = json.loads(run_file.read_bytes())
    document["version"] = 99
    canonical_write(run_file, document)

    with pytest.raises(UnsupportedHistoryVersionError, match="version 99"):
        archive.list_runs()


def test_schema_version_must_be_an_integer_not_boolean(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    archive.create_run({})
    run_file = tmp_path / "runs" / "000001" / "run.json"
    document = json.loads(run_file.read_bytes())
    document["version"] = True
    canonical_write(run_file, document)

    with pytest.raises(UnsupportedHistoryVersionError, match="version True"):
        archive.load_run(1)


def test_individual_record_substitution_after_enumeration_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})
    archive.append_hourly(run_number, hourly(0))
    record_path = tmp_path / "runs" / "000001" / "records" / "000001.json"
    replacement = tmp_path / "replacement.json"
    displaced = tmp_path / "displaced.json"
    shutil.copyfile(record_path, replacement)
    original_enumerate = archive._record_names_at
    attacked = False

    def enumerate_then_replace(*args):  # type: ignore[no-untyped-def]
        nonlocal attacked
        entries = original_enumerate(*args)
        if not attacked:
            attacked = True
            record_path.rename(displaced)
            replacement.rename(record_path)
        return entries

    monkeypatch.setattr(archive, "_record_names_at", enumerate_then_replace)

    with pytest.raises(HistoryCorruptionError, match="replaced"):
        archive.load_run(run_number)


def test_record_identity_and_contiguous_timeline_are_validated(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})
    archive.append_hourly(run_number, hourly(0))
    record_file = tmp_path / "runs" / "000001" / "records" / "000001.json"
    document = json.loads(record_file.read_bytes())
    document["sequence"] = 2
    canonical_write(record_file, document)

    with pytest.raises(HistoryCorruptionError, match="sequence"):
        archive.load_run(run_number)


def test_append_rejects_unknown_run_and_invalid_run_number(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)

    with pytest.raises(FileNotFoundError, match="run 1"):
        archive.append_hourly(1, hourly(0))
    with pytest.raises(HistoryValidationError, match="positive integer"):
        archive.load_run(0)


def test_record_files_reject_unexpected_entries_and_symlinked_json(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    run_number = archive.create_run({})
    records = tmp_path / "runs" / "000001" / "records"
    (records / "notes.txt").write_text("bad", encoding="utf-8")

    with pytest.raises(HistoryCorruptionError, match="unexpected record entry"):
        archive.load_run(run_number)

    (records / "notes.txt").unlink()
    (records / "000001.json").symlink_to(tmp_path / "outside.json")
    with pytest.raises(HistoryCorruptionError, match="symlink"):
        archive.load_run(run_number)


def test_root_path_must_not_escape_through_dotdot(tmp_path: Path) -> None:
    root = tmp_path / "container" / ".." / "archive"
    archive = HistoryArchive(root)
    archive.create_run({})

    assert archive.root == root.resolve()
    assert (tmp_path / "archive" / "runs" / "000001" / "run.json").is_file()


def test_lock_is_regular_file_not_fifo(tmp_path: Path) -> None:
    archive = HistoryArchive(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    lock = tmp_path / ".run-number.lock"
    os.mkfifo(lock)

    with pytest.raises(HistoryCorruptionError, match="regular file"):
        archive.create_run({})
