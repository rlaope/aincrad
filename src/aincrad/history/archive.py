"""Filesystem implementation for the append-only run history archive."""

from __future__ import annotations

import fcntl
import json
import math
import os
import secrets
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, cast

RUN_SCHEMA = "aincrad.history.run"
RECORD_SCHEMA = "aincrad.history.record"
COUNTER_SCHEMA = "aincrad.history.counter"
SCHEMA_VERSION = 1
_RECORD_KINDS = frozenset({"hourly", "daily_summary", "character_end"})
_PARTY_KEYS = frozenset({"id", "name", "level", "exp", "hp", "mp", "alive"})
_PAYLOAD_KEYS = {
    "hourly": frozenset({"day", "hour", "tick", "events", "party"}),
    "daily_summary": frozenset({"day", "survivors"}),
    "character_end": frozenset({"character_id", "ending", "story"}),
}

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class HistoryError(Exception):
    """Base class for history archive failures."""


class HistoryValidationError(HistoryError, ValueError):
    """Caller data cannot cross the safe JSON archive boundary."""


class HistoryCorruptionError(HistoryError):
    """Stored data is invalid; the archive never repairs it implicitly."""


class UnsupportedHistoryVersionError(HistoryCorruptionError):
    """Stored data uses an unsupported schema version."""


@dataclass(frozen=True)
class HistoryRecord:
    """One immutable item in a run timeline."""

    sequence: int
    kind: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class RunDetails:
    """Metadata and ordered timeline for one run."""

    run_number: int
    metadata: Mapping[str, object]
    timeline: tuple[HistoryRecord, ...]


@dataclass(frozen=True)
class RunSummary:
    """Compact run information for list views."""

    run_number: int
    metadata: Mapping[str, object]
    record_count: int


@dataclass(frozen=True)
class _EntryIdentity:
    name: str
    device: int
    inode: int
    mode: int

    @classmethod
    def from_stat(cls, name: str, info: os.stat_result) -> _EntryIdentity:
        return cls(name, info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))


def _safe_string(value: str, location: str) -> str:
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        raise HistoryValidationError(f"{location} contains terminal control characters")
    return value


def _json_value(value: object, location: str) -> JsonValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _safe_string(value, location)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HistoryValidationError(f"{location} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise HistoryValidationError(f"{location} has a non-string mapping key")
            safe_key = _safe_string(key, f"{location} key")
            result[safe_key] = _json_value(item, f"{location}.{safe_key}")
        return result
    if isinstance(value, list):
        return [_json_value(item, f"{location}[{index}]") for index, item in enumerate(value)]
    raise HistoryValidationError(f"{location} contains non-JSON value {type(value).__name__}")


def _json_mapping(value: Mapping[str, object], location: str) -> dict[str, JsonValue]:
    validated = _json_value(value, location)
    if not isinstance(validated, dict):  # pragma: no cover - guaranteed by Mapping input
        raise HistoryValidationError(f"{location} must be a mapping")
    return validated


def _encode(document: Mapping[str, JsonValue]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _positive_run_number(run_number: int) -> None:
    if type(run_number) is not int or run_number < 1:
        raise HistoryValidationError("run_number must be a positive integer")


def _integer(value: JsonValue, location: str, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        range_text = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise HistoryValidationError(f"{location} must be an integer in range {range_text}")
    return value


def _nonempty_string(value: JsonValue, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise HistoryValidationError(f"{location} must be a non-empty string")
    return value


class HistoryArchive:
    """Store immutable, canonical JSON documents below a filesystem root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
        self.runs_path = self.root / "runs"
        self.counter_path = self.root / "run-counter.json"

    @staticmethod
    def _require_dir_fd_support() -> None:
        required = (os.open, os.mkdir, os.rename, os.link, os.unlink, os.stat, os.rmdir)
        if (
            not getattr(os, "O_DIRECTORY", 0)
            or not getattr(os, "O_NOFOLLOW", 0)
            or any(operation not in os.supports_dir_fd for operation in required)
        ):
            raise HistoryCorruptionError(
                "secure directory-relative filesystem operations unavailable"
            )

    @contextmanager
    def _optional_root_fd(self) -> Iterator[int | None]:
        self._require_dir_fd_support()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            descriptor = os.open(self.root, flags)
        except FileNotFoundError:
            yield None
            return
        except OSError as error:
            raise HistoryCorruptionError(
                f"{self.root}: cannot open secure archive directory: {error}"
            ) from error
        try:
            self._verify_directory_fd(descriptor, self.root)
            yield descriptor
            self._verify_directory_fd(descriptor, self.root)
        finally:
            os.close(descriptor)

    @contextmanager
    def _directory_fd(
        self,
        path: Path,
        *,
        parent_fd: int | None = None,
        name: str | None = None,
        expected: _EntryIdentity | None = None,
    ) -> Iterator[int]:
        self._require_dir_fd_support()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            target = path if parent_fd is None else name or path.name
            descriptor = os.open(target, flags, dir_fd=parent_fd)
        except OSError as error:
            raise HistoryCorruptionError(
                f"{path}: cannot open secure archive directory: {error}"
            ) from error
        try:
            opened = os.fstat(descriptor)
            if expected is not None and (
                opened.st_dev,
                opened.st_ino,
                stat.S_IFMT(opened.st_mode),
            ) != (expected.device, expected.inode, expected.mode):
                raise HistoryCorruptionError(f"{path}: archive directory was replaced")
            self._verify_directory_fd(descriptor, path, parent_fd=parent_fd, name=name)
            yield descriptor
            self._verify_directory_fd(descriptor, path, parent_fd=parent_fd, name=name)
        finally:
            os.close(descriptor)

    def _verify_directory_fd(
        self, descriptor: int, path: Path, *, parent_fd: int | None = None, name: str | None = None
    ) -> None:
        opened = os.fstat(descriptor)
        try:
            current = os.stat(
                path if parent_fd is None else name or path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise HistoryCorruptionError(
                f"{path}: archive directory was replaced or removed"
            ) from error
        if not stat.S_ISDIR(opened.st_mode) or not stat.S_ISDIR(current.st_mode):
            raise HistoryCorruptionError(f"{path}: symlink or non-directory archive parent")
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise HistoryCorruptionError(f"{path}: archive directory was replaced")

    def _mkdir_at(self, parent_fd: int, parent_path: Path, name: str) -> None:
        self._verify_directory_fd(parent_fd, parent_path)
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as error:
            raise HistoryCorruptionError(
                f"{parent_path / name}: cannot create directory: {error}"
            ) from error
        self._verify_directory_fd(parent_fd, parent_path)

    @contextmanager
    def _lock_at(self, parent_fd: int, parent_path: Path, name: str) -> Iterator[None]:
        path = parent_path / name
        flags = os.O_RDWR | os.O_NOFOLLOW
        descriptor: int | None = None
        for _ in range(3):
            try:
                descriptor = os.open(name, flags, dir_fd=parent_fd)
                break
            except FileNotFoundError:
                try:
                    descriptor = os.open(
                        name,
                        flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=parent_fd,
                    )
                    break
                except FileExistsError:
                    continue
            except OSError as error:
                raise HistoryCorruptionError(
                    f"{path}: cannot open archive lock: {error}"
                ) from error
        if descriptor is None:
            raise HistoryCorruptionError(f"{path}: archive lock changed during secure open")
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            os.close(descriptor)
            raise HistoryCorruptionError(f"{path}: lock must be a regular file")
        with os.fdopen(descriptor, "a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                self._check_node(path, "file")
                self._verify_directory_fd(parent_fd, parent_path)
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                    raise HistoryCorruptionError(f"{path}: archive lock was replaced")
                yield
                self._verify_directory_fd(parent_fd, parent_path)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _inside_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise HistoryCorruptionError(f"{path}: path is outside archive root") from error

    def _check_node(self, path: Path, kind: str, *, missing_ok: bool = False) -> bool:
        self._inside_root(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            if missing_ok:
                return False
            raise HistoryCorruptionError(f"{path}: archive node is missing") from None
        if stat.S_ISLNK(info.st_mode):
            raise HistoryCorruptionError(f"{path}: symlink is forbidden in archive")
        valid = {
            "directory": stat.S_ISDIR,
            "file": stat.S_ISREG,
        }[kind](info.st_mode)
        if not valid:
            label = "regular file" if kind == "file" else kind
            raise HistoryCorruptionError(f"{path}: expected {label}")
        resolved_root = self.root.resolve(strict=True)
        try:
            path.resolve(strict=True).relative_to(resolved_root)
        except ValueError as error:
            raise HistoryCorruptionError(f"{path}: resolved path is outside archive") from error
        return True

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            raise HistoryCorruptionError(f"{self.root}: symlink archive root is forbidden")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise HistoryCorruptionError(
                f"{self.root}: cannot create archive root: {error}"
            ) from error
        self._check_node(self.root, "directory")

    def _run_path(self, run_number: int) -> Path:
        _positive_run_number(run_number)
        path = self.runs_path / f"{run_number:06d}"
        self._inside_root(path)
        return path

    def create_run(self, metadata: Mapping[str, object]) -> int:
        """Atomically create a run using the durable monotonic counter."""
        safe_metadata = _json_mapping(metadata, "metadata")
        self._ensure_root()
        with (
            self._directory_fd(self.root) as root_fd,
            self._lock_at(root_fd, self.root, ".run-number.lock"),
        ):
            self._mkdir_at(root_fd, self.root, "runs")
            with self._directory_fd(self.runs_path, parent_fd=root_fd, name="runs") as runs_fd:
                last_run, _ = self._validated_counter_at(
                    root_fd, runs_fd, initialize=True
                )
                run_number = last_run + 1
                final_name = f"{run_number:06d}"
                try:
                    os.stat(final_name, dir_fd=runs_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise HistoryCorruptionError(
                        f"{self.runs_path / final_name}: next run path already exists"
                    )
                staging_name = f".run-tmp-{secrets.token_hex(12)}"
                os.mkdir(staging_name, 0o700, dir_fd=runs_fd)
                staging_path = self.runs_path / staging_name
                try:
                    with self._directory_fd(
                        staging_path, parent_fd=runs_fd, name=staging_name
                    ) as staging_fd:
                        os.mkdir("records", 0o700, dir_fd=staging_fd)
                        document: dict[str, JsonValue] = {
                            "metadata": safe_metadata,
                            "run_number": run_number,
                            "schema": RUN_SCHEMA,
                            "version": SCHEMA_VERSION,
                        }
                        self._write_file_at(staging_fd, staging_path, "run.json", _encode(document))
                    self._verify_directory_fd(
                        runs_fd, self.runs_path, parent_fd=root_fd, name="runs"
                    )
                    os.rename(staging_name, final_name, src_dir_fd=runs_fd, dst_dir_fd=runs_fd)
                    os.fsync(runs_fd)
                    self._write_counter_at(root_fd, run_number)
                except BaseException:
                    self._remove_staging_at(runs_fd, staging_name)
                    raise
                return run_number

    def append_hourly(self, run_number: int, payload: Mapping[str, object]) -> int:
        """Append one renderer-compatible hourly record."""
        return self._append(run_number, "hourly", payload)

    def append_daily_summary(self, run_number: int, payload: Mapping[str, object]) -> int:
        """Append the unique summary immediately after a completed day."""
        return self._append(run_number, "daily_summary", payload)

    def record_character_end(self, run_number: int, payload: Mapping[str, object]) -> int:
        """Append one final ending for a character."""
        return self._append(run_number, "character_end", payload)

    def _append(self, run_number: int, kind: str, payload: Mapping[str, object]) -> int:
        safe_payload = _json_mapping(payload, "payload")
        self._validate_payload_shape(kind, safe_payload)
        _positive_run_number(run_number)
        run_name = f"{run_number:06d}"
        run_path = self._run_path(run_number)
        with self._optional_root_fd() as root_fd:
            if root_fd is None:
                raise FileNotFoundError(f"run {run_number} does not exist")
            try:
                runs_info = os.stat("runs", dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    os.stat("run-counter.json", dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    raise FileNotFoundError(
                        f"run {run_number} does not exist"
                    ) from None
                raise HistoryCorruptionError(
                    f"{self.runs_path}: runs directory is missing"
                ) from None
            if not stat.S_ISDIR(runs_info.st_mode):
                raise HistoryCorruptionError(f"{self.runs_path}: expected directory")
            with self._directory_fd(
                self.runs_path, parent_fd=root_fd, name="runs"
            ) as runs_fd:
                _, run_entries = self._validated_counter_at(
                    root_fd, runs_fd, initialize=False
                )
                run_entry = next(
                    (entry for entry in run_entries if entry.name == run_name), None
                )
                if run_entry is None:
                    raise FileNotFoundError(f"run {run_number} does not exist")
                try:
                    run_context = self._directory_fd(
                        run_path,
                        parent_fd=runs_fd,
                        name=run_name,
                        expected=run_entry,
                    )
                    with run_context as run_fd, self._lock_at(
                        run_fd, run_path, ".append.lock"
                    ):
                        run_document = self._load_run_document_at(
                            root_fd, runs_fd, run_fd, run_number
                        )
                        records_path = run_path / "records"
                        with self._directory_fd(
                            records_path, parent_fd=run_fd, name="records"
                        ) as records_fd:
                            timeline = self._load_timeline_at(
                                root_fd,
                                runs_fd,
                                run_fd,
                                records_fd,
                                run_number,
                                hero_id=cast(
                                    dict[str, object], run_document["metadata"]
                                ).get("hero_id"),
                            )
                            details = RunDetails(
                                run_number=run_number,
                                metadata=cast(
                                    dict[str, object], run_document["metadata"]
                                ),
                                timeline=timeline,
                            )
                            self._verify_fd_chain(
                                root_fd,
                                runs_fd,
                                run_fd=run_fd,
                                run_name=run_name,
                                records_fd=records_fd,
                            )
                            self._validate_timeline_addition(
                                kind,
                                safe_payload,
                                details.timeline,
                                hero_id=details.metadata.get("hero_id"),
                            )
                            sequence = len(details.timeline) + 1
                            document: dict[str, JsonValue] = {
                                "kind": kind,
                                "payload": safe_payload,
                                "run_number": run_number,
                                "schema": RECORD_SCHEMA,
                                "sequence": sequence,
                                "version": SCHEMA_VERSION,
                            }
                            self._verify_fd_chain(
                                root_fd,
                                runs_fd,
                                run_fd=run_fd,
                                run_name=run_name,
                                records_fd=records_fd,
                            )
                            self._atomic_write_at(
                                records_fd,
                                records_path,
                                f"{sequence:06d}.json",
                                _encode(document),
                                replace=False,
                            )
                            self._verify_fd_chain(
                                root_fd,
                                runs_fd,
                                run_fd=run_fd,
                                run_name=run_name,
                                records_fd=records_fd,
                            )
                            return sequence
                except HistoryCorruptionError as error:
                    if str(error).startswith(
                        f"{run_path}: cannot open secure archive directory"
                    ):
                        raise FileNotFoundError(
                            f"run {run_number} does not exist"
                        ) from error
                    raise

    def load_run(self, run_number: int) -> RunDetails:
        """Load and strictly validate one run and its ordered timeline."""
        _positive_run_number(run_number)
        run_name = f"{run_number:06d}"
        run_path = self._run_path(run_number)
        with (
            self._directory_fd(self.root) as root_fd,
            self._directory_fd(self.runs_path, parent_fd=root_fd, name="runs") as runs_fd,
        ):
            _, run_entries = self._validated_counter_at(
                root_fd, runs_fd, initialize=False
            )
            run_entry = next(
                (entry for entry in run_entries if entry.name == run_name), None
            )
            if run_entry is None:
                raise FileNotFoundError(f"run {run_number} does not exist")
            try:
                with self._directory_fd(
                    run_path,
                    parent_fd=runs_fd,
                    name=run_name,
                    expected=run_entry,
                ) as run_fd:
                    return self._load_run_from_fd(
                        root_fd, runs_fd, run_fd, run_number
                    )
            except HistoryCorruptionError as error:
                if str(error).startswith(
                    f"{run_path}: cannot open secure archive directory"
                ):
                    raise FileNotFoundError(f"run {run_number} does not exist") from error
                raise

    def list_runs(self) -> tuple[RunSummary, ...]:
        """List validated runs in numeric order for CLI/TUI selection."""
        with self._optional_root_fd() as root_fd:
            if root_fd is None:
                return ()
            try:
                runs_info = os.stat("runs", dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    os.stat("run-counter.json", dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return ()
                raise HistoryCorruptionError(
                    f"{self.runs_path}: runs directory is missing"
                ) from None
            if not stat.S_ISDIR(runs_info.st_mode):
                raise HistoryCorruptionError(f"{self.runs_path}: expected directory")
            with self._directory_fd(
                self.runs_path, parent_fd=root_fd, name="runs"
            ) as runs_fd:
                _, run_entries = self._validated_counter_at(
                    root_fd, runs_fd, initialize=False
                )
                summaries = []
                for run_entry in run_entries:
                    run_number = int(run_entry.name)
                    run_path = self.runs_path / run_entry.name
                    with self._directory_fd(
                        run_path,
                        parent_fd=runs_fd,
                        name=run_entry.name,
                        expected=run_entry,
                    ) as run_fd:
                        details = self._load_run_from_fd(
                            root_fd, runs_fd, run_fd, run_number
                        )
                    summaries.append(
                        RunSummary(
                            details.run_number,
                            details.metadata,
                            len(details.timeline),
                        )
                    )
                return tuple(summaries)

    def _verify_fd_chain(
        self,
        root_fd: int,
        runs_fd: int,
        *,
        run_fd: int | None = None,
        run_name: str | None = None,
        records_fd: int | None = None,
    ) -> None:
        self._verify_directory_fd(root_fd, self.root)
        self._verify_directory_fd(
            runs_fd, self.runs_path, parent_fd=root_fd, name="runs"
        )
        if run_fd is not None and run_name is not None:
            run_path = self.runs_path / run_name
            self._verify_directory_fd(
                run_fd, run_path, parent_fd=runs_fd, name=run_name
            )
            if records_fd is not None:
                self._verify_directory_fd(
                    records_fd,
                    run_path / "records",
                    parent_fd=run_fd,
                    name="records",
                )

    def _numeric_run_names_at(
        self, root_fd: int, runs_fd: int
    ) -> list[_EntryIdentity]:
        self._verify_fd_chain(root_fd, runs_fd)
        try:
            names = os.listdir(runs_fd)
        except OSError as error:
            raise HistoryCorruptionError(
                f"{self.runs_path}: cannot enumerate runs: {error}"
            ) from error
        entries = []
        for name in names:
            path = self.runs_path / name
            if not name.isdecimal() or len(name) != 6 or name == "000000":
                raise HistoryCorruptionError(f"{path}: unexpected run entry")
            try:
                info = os.stat(name, dir_fd=runs_fd, follow_symlinks=False)
            except OSError as error:
                raise HistoryCorruptionError(
                    f"{path}: cannot inspect run entry: {error}"
                ) from error
            if stat.S_ISLNK(info.st_mode):
                raise HistoryCorruptionError(f"{path}: symlink run entry is forbidden")
            if not stat.S_ISDIR(info.st_mode):
                raise HistoryCorruptionError(f"{path}: expected directory")
            entries.append(_EntryIdentity.from_stat(name, info))
        self._verify_fd_chain(root_fd, runs_fd)
        return sorted(entries, key=lambda entry: int(entry.name))

    def _validated_counter_at(
        self, root_fd: int, runs_fd: int, *, initialize: bool
    ) -> tuple[int, tuple[_EntryIdentity, ...]]:
        names = self._numeric_run_names_at(root_fd, runs_fd)
        self._verify_fd_chain(root_fd, runs_fd)
        try:
            document = self._read_document_at(root_fd, self.root, "run-counter.json")
        except FileNotFoundError:
            if initialize and not names:
                self._write_counter_at(root_fd, 0)
                return 0, ()
            raise HistoryCorruptionError(f"{self.counter_path}: counter is missing") from None
        self._verify_fd_chain(root_fd, runs_fd)
        expected = {"last_run", "schema", "version"}
        self._validate_envelope(self.counter_path, document, COUNTER_SCHEMA, expected)
        last_run = document["last_run"]
        if type(last_run) is not int or last_run < 0:
            raise HistoryCorruptionError(f"{self.counter_path}: counter last_run is invalid")
        numbers = [int(entry.name) for entry in names]
        expected_numbers = list(range(1, last_run + 1))
        if numbers != expected_numbers:
            missing = sorted(set(expected_numbers) - set(numbers))
            if missing:
                raise HistoryCorruptionError(f"{self.runs_path}: missing run {missing[0]}")
            raise HistoryCorruptionError(
                f"{self.counter_path}: counter rollback or run gap detected"
            )
        for entry in names:
            run_path = self.runs_path / entry.name
            with self._directory_fd(
                run_path,
                parent_fd=runs_fd,
                name=entry.name,
                expected=entry,
            ) as run_fd:
                self._load_run_document_at(
                    root_fd, runs_fd, run_fd, int(entry.name)
                )
        return last_run, tuple(names)

    def _load_run_document_at(
        self, root_fd: int, runs_fd: int, run_fd: int, run_number: int
    ) -> dict[str, JsonValue]:
        run_name = f"{run_number:06d}"
        run_path = self.runs_path / run_name
        self._verify_fd_chain(root_fd, runs_fd, run_fd=run_fd, run_name=run_name)
        try:
            entries = set(os.listdir(run_fd))
        except OSError as error:
            raise HistoryCorruptionError(
                f"{run_path}: cannot enumerate run: {error}"
            ) from error
        unexpected = entries - {"run.json", "records", ".append.lock"}
        if unexpected:
            raise HistoryCorruptionError(
                f"{run_path}: unexpected run entry {min(unexpected)!r}"
            )
        self._verify_fd_chain(root_fd, runs_fd, run_fd=run_fd, run_name=run_name)
        path = run_path / "run.json"
        try:
            document = self._read_document_at(run_fd, run_path, "run.json")
        except FileNotFoundError:
            raise HistoryCorruptionError(f"{path}: archive node is missing") from None
        self._verify_fd_chain(root_fd, runs_fd, run_fd=run_fd, run_name=run_name)
        expected = {"metadata", "run_number", "schema", "version"}
        self._validate_envelope(path, document, RUN_SCHEMA, expected)
        if document["run_number"] != run_number:
            raise HistoryCorruptionError(f"{path}: run_number does not match directory")
        if not isinstance(document["metadata"], dict):
            raise HistoryCorruptionError(f"{path}: metadata must be a mapping")
        return document

    def _record_names_at(
        self, root_fd: int, runs_fd: int, run_fd: int, records_fd: int, run_number: int
    ) -> list[_EntryIdentity]:
        run_name = f"{run_number:06d}"
        records_path = self.runs_path / run_name / "records"
        self._verify_fd_chain(
            root_fd,
            runs_fd,
            run_fd=run_fd,
            run_name=run_name,
            records_fd=records_fd,
        )
        try:
            names = os.listdir(records_fd)
        except OSError as error:
            raise HistoryCorruptionError(
                f"{records_path}: cannot enumerate records: {error}"
            ) from error
        entries = []
        for name in names:
            path = records_path / name
            if (
                len(name) != 11
                or not name.endswith(".json")
                or not name[:6].isdecimal()
                or name[:6] == "000000"
            ):
                raise HistoryCorruptionError(f"{path}: unexpected record entry")
            try:
                info = os.stat(name, dir_fd=records_fd, follow_symlinks=False)
            except OSError as error:
                raise HistoryCorruptionError(
                    f"{path}: cannot inspect record entry: {error}"
                ) from error
            if stat.S_ISLNK(info.st_mode):
                raise HistoryCorruptionError(f"{path}: symlink record is forbidden")
            if not stat.S_ISREG(info.st_mode):
                raise HistoryCorruptionError(f"{path}: expected regular file")
            entries.append(_EntryIdentity.from_stat(name, info))
        self._verify_fd_chain(
            root_fd,
            runs_fd,
            run_fd=run_fd,
            run_name=run_name,
            records_fd=records_fd,
        )
        return sorted(entries, key=lambda entry: int(entry.name[:6]))

    def _load_run_from_fd(
        self, root_fd: int, runs_fd: int, run_fd: int, run_number: int
    ) -> RunDetails:
        run_name = f"{run_number:06d}"
        run_path = self.runs_path / run_name
        run_document = self._load_run_document_at(
            root_fd, runs_fd, run_fd, run_number
        )
        records_path = run_path / "records"
        with self._directory_fd(
            records_path, parent_fd=run_fd, name="records"
        ) as records_fd:
            timeline = self._load_timeline_at(
                root_fd,
                runs_fd,
                run_fd,
                records_fd,
                run_number,
                hero_id=cast(dict[str, object], run_document["metadata"]).get(
                    "hero_id"
                ),
            )
        return RunDetails(
            run_number=run_number,
            metadata=cast(dict[str, object], run_document["metadata"]),
            timeline=timeline,
        )

    def _load_timeline_at(
        self,
        root_fd: int,
        runs_fd: int,
        run_fd: int,
        records_fd: int,
        run_number: int,
        *,
        hero_id: object = None,
    ) -> tuple[HistoryRecord, ...]:
        records_path = self.runs_path / f"{run_number:06d}" / "records"
        records: list[HistoryRecord] = []
        for expected_sequence, record_entry in enumerate(
            self._record_names_at(
                root_fd, runs_fd, run_fd, records_fd, run_number
            ),
            start=1,
        ):
            record = self._load_record_at(
                root_fd,
                runs_fd,
                run_fd,
                records_fd,
                run_number,
                record_entry,
                expected_sequence,
            )
            try:
                self._validate_timeline_addition(
                    record.kind,
                    cast(dict[str, JsonValue], record.payload),
                    tuple(records),
                    hero_id=hero_id,
                )
            except HistoryValidationError as error:
                raise HistoryCorruptionError(
                    f"{records_path / record_entry.name}: invalid payload timeline: {error}"
                ) from error
            records.append(record)
        return tuple(records)

    def _load_record_at(
        self,
        root_fd: int,
        runs_fd: int,
        run_fd: int,
        records_fd: int,
        run_number: int,
        entry: _EntryIdentity,
        expected_sequence: int,
    ) -> HistoryRecord:
        run_name = f"{run_number:06d}"
        path = self.runs_path / run_name / "records" / entry.name
        self._verify_fd_chain(
            root_fd,
            runs_fd,
            run_fd=run_fd,
            run_name=run_name,
            records_fd=records_fd,
        )
        try:
            document = self._read_document_at(
                records_fd, path.parent, entry.name, expected=entry
            )
        except FileNotFoundError:
            raise HistoryCorruptionError(f"{path}: archive node is missing") from None
        self._verify_fd_chain(
            root_fd,
            runs_fd,
            run_fd=run_fd,
            run_name=run_name,
            records_fd=records_fd,
        )
        expected = {"kind", "payload", "run_number", "schema", "sequence", "version"}
        self._validate_envelope(path, document, RECORD_SCHEMA, expected)
        if document["run_number"] != run_number:
            raise HistoryCorruptionError(f"{path}: run_number does not match run")
        if (
            document["sequence"] != expected_sequence
            or entry.name != f"{expected_sequence:06d}.json"
        ):
            raise HistoryCorruptionError(
                f"{path}: sequence is not contiguous or does not match filename"
            )
        kind = document["kind"]
        if not isinstance(kind, str) or kind not in _RECORD_KINDS:
            raise HistoryCorruptionError(f"{path}: invalid record kind")
        payload = document["payload"]
        if not isinstance(payload, dict):
            raise HistoryCorruptionError(f"{path}: payload must be a mapping")
        try:
            self._validate_payload_shape(kind, payload)
        except HistoryValidationError as error:
            raise HistoryCorruptionError(f"{path}: invalid payload: {error}") from error
        return HistoryRecord(expected_sequence, kind, cast(dict[str, object], payload))

    def _validate_payload_shape(self, kind: str, payload: dict[str, JsonValue]) -> None:
        expected = _PAYLOAD_KEYS[kind]
        if set(payload) != expected:
            raise HistoryValidationError(f"payload for {kind} must have exactly {sorted(expected)}")
        if kind == "hourly":
            day = _integer(payload["day"], "payload.day", 1)
            hour = _integer(payload["hour"], "payload.hour", 0, 23)
            tick = _integer(payload["tick"], "payload.tick", 0)
            if day != tick // 24 + 1 or hour != tick % 24:
                raise HistoryValidationError("payload day/hour must correspond to tick")
            if not isinstance(payload["events"], list):
                raise HistoryValidationError("payload.events must be a list")
            party = payload["party"]
            if not isinstance(party, list):
                raise HistoryValidationError("payload.party must be a list")
            ids: set[str] = set()
            for index, raw_member in enumerate(party):
                location = f"payload.party[{index}]"
                if not isinstance(raw_member, dict) or set(raw_member) != _PARTY_KEYS:
                    raise HistoryValidationError(
                        f"{location} must have exactly {sorted(_PARTY_KEYS)}"
                    )
                member_id = _nonempty_string(raw_member["id"], f"{location}.id")
                _nonempty_string(raw_member["name"], f"{location}.name")
                _integer(raw_member["level"], f"{location}.level", 1)
                _integer(raw_member["exp"], f"{location}.exp", 0)
                _integer(raw_member["hp"], f"{location}.hp", 0)
                _integer(raw_member["mp"], f"{location}.mp", 0)
                if type(raw_member["alive"]) is not bool:
                    raise HistoryValidationError(f"{location}.alive must be a boolean")
                if member_id in ids:
                    raise HistoryValidationError(f"payload.party has duplicate id {member_id!r}")
                ids.add(member_id)
        elif kind == "daily_summary":
            _integer(payload["day"], "payload.day", 1)
            _integer(payload["survivors"], "payload.survivors", 0)
        else:
            _nonempty_string(payload["character_id"], "payload.character_id")
            _nonempty_string(payload["ending"], "payload.ending")
            _nonempty_string(payload["story"], "payload.story")

    def _validate_timeline_addition(
        self,
        kind: str,
        payload: dict[str, JsonValue],
        timeline: tuple[HistoryRecord, ...],
        *,
        hero_id: object = None,
    ) -> None:
        self._validate_payload_shape(kind, payload)
        hourly_records = [record for record in timeline if record.kind == "hourly"]
        summaries = {
            cast(int, record.payload["day"])
            for record in timeline
            if record.kind == "daily_summary"
        }
        ended = {
            cast(str, record.payload["character_id"])
            for record in timeline
            if record.kind == "character_end"
        }
        if ended:
            raise HistoryValidationError("character_end is terminal; no later record is allowed")
        if kind == "hourly":
            tick = cast(int, payload["tick"])
            if tick != len(hourly_records):
                raise HistoryValidationError(
                    f"payload.tick must be contiguous; expected {len(hourly_records)}"
                )
            if tick > 0 and tick % 24 == 0 and tick // 24 not in summaries:
                raise HistoryValidationError("daily summary must follow the completed day")
            party_ids = {
                cast(str, member["id"])
                for member in cast(list[dict[str, JsonValue]], payload["party"])
            }
            overlap = party_ids & ended
            if overlap:
                raise HistoryValidationError(
                    f"payload.party contains ended character {min(overlap)!r}"
                )
        elif kind == "daily_summary":
            day = cast(int, payload["day"])
            if day in summaries:
                raise HistoryValidationError(f"daily summary for day {day} already exists")
            if not hourly_records or cast(int, hourly_records[-1].payload["tick"]) != day * 24 - 1:
                raise HistoryValidationError(
                    "daily summary must immediately follow the final hour of its day"
                )
            if timeline and timeline[-1].kind != "hourly":
                raise HistoryValidationError("daily summary placement is invalid")
            party = cast(list[dict[str, object]], hourly_records[-1].payload["party"])
            alive_count = sum(member["alive"] is True for member in party)
            if cast(int, payload["survivors"]) != alive_count:
                raise HistoryValidationError(
                    "payload.survivors must equal alive count in the preceding hourly snapshot"
                )
        else:
            character_id = cast(str, payload["character_id"])
            if not isinstance(hero_id, str) or not hero_id or character_id != hero_id:
                raise HistoryValidationError(
                    "payload.character_id must equal run metadata hero_id"
                )
            if character_id in ended:
                raise HistoryValidationError(f"character_end for {character_id!r} already exists")
            latest_party = (
                cast(list[dict[str, object]], hourly_records[-1].payload["party"])
                if hourly_records
                else []
            )
            latest_member = next(
                (member for member in latest_party if member["id"] == character_id),
                None,
            )
            if latest_member is None or latest_member["alive"] is not False:
                raise HistoryValidationError(
                    "character_end latest hourly snapshot must contain character with alive=false"
                )

    def _validate_envelope(
        self,
        path: Path,
        document: dict[str, JsonValue],
        schema: str,
        expected_keys: set[str],
    ) -> None:
        if set(document) != expected_keys:
            raise HistoryCorruptionError(f"{path}: document fields do not match schema")
        if document["schema"] != schema:
            raise HistoryCorruptionError(f"{path}: schema must be {schema}")
        version = document["version"]
        if type(version) is not int or version != SCHEMA_VERSION:
            raise UnsupportedHistoryVersionError(f"{path}: unsupported version {version}")

    def _read_document_at(
        self,
        parent_fd: int,
        parent_path: Path,
        name: str,
        *,
        expected: _EntryIdentity | None = None,
    ) -> dict[str, JsonValue]:
        path = parent_path / name
        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise
        except OSError as error:
            raise HistoryCorruptionError(f"{path}: cannot inspect archive file: {error}") from error
        if not stat.S_ISREG(before.st_mode):
            raise HistoryCorruptionError(f"{path}: expected regular file")
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            with os.fdopen(descriptor, "rb") as source:
                opened = os.fstat(source.fileno())
                opened_identity = (
                    opened.st_dev,
                    opened.st_ino,
                    stat.S_IFMT(opened.st_mode),
                )
                if expected is not None and opened_identity != (
                    expected.device,
                    expected.inode,
                    expected.mode,
                ):
                    raise HistoryCorruptionError(f"{path}: archive file was replaced")
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise HistoryCorruptionError(f"{path}: archive file was replaced")
                raw = source.read()
                after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
                    raise HistoryCorruptionError(f"{path}: archive file was replaced")
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=self._unique_object,
                parse_constant=lambda constant: self._reject_constant(constant),
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise HistoryCorruptionError(f"{path}: invalid JSON: {error}") from error
        if not isinstance(value, dict):
            raise HistoryCorruptionError(f"{path}: document must be a JSON object")
        document = cast(dict[str, JsonValue], value)
        try:
            if raw != _encode(document):
                raise HistoryCorruptionError(f"{path}: document is not canonical JSON")
            _json_mapping(cast(dict[str, object], document), "stored document")
        except HistoryValidationError as error:
            raise HistoryCorruptionError(f"{path}: unsafe stored value: {error}") from error
        return document

    @staticmethod
    def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key, value in pairs:
            if key in result:
                raise HistoryCorruptionError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(constant: str) -> JsonValue:
        raise HistoryCorruptionError(f"invalid JSON constant {constant}")

    def _write_counter_at(self, root_fd: int, last_run: int) -> None:
        document: dict[str, JsonValue] = {
            "last_run": last_run,
            "schema": COUNTER_SCHEMA,
            "version": SCHEMA_VERSION,
        }
        self._atomic_write_at(
            root_fd, self.root, "run-counter.json", _encode(document), replace=True
        )

    def _write_file_at(self, parent_fd: int, parent_path: Path, name: str, data: bytes) -> None:
        path = parent_path / name
        self._verify_directory_fd(parent_fd, parent_path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
        except OSError as error:
            raise HistoryCorruptionError(f"{path}: cannot create archive file: {error}") from error
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(parent_fd)
        self._verify_directory_fd(parent_fd, parent_path)

    def _atomic_write_at(
        self,
        parent_fd: int,
        parent_path: Path,
        target_name: str,
        data: bytes,
        *,
        replace: bool,
    ) -> None:
        target_path = parent_path / target_name
        self._verify_directory_fd(parent_fd, parent_path)
        try:
            existing = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISREG(existing.st_mode):
                raise HistoryCorruptionError(f"{target_path}: expected regular file")
            if not replace:
                raise HistoryCorruptionError(f"{target_path}: target already exists")
        temporary_name = f".history-tmp-{secrets.token_hex(12)}"
        self._write_file_at(parent_fd, parent_path, temporary_name, data)
        try:
            self._verify_directory_fd(parent_fd, parent_path)
            if replace:
                os.rename(
                    temporary_name,
                    target_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
            else:
                os.link(
                    temporary_name,
                    target_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            os.fsync(parent_fd)
            self._verify_directory_fd(parent_fd, parent_path)
        except FileExistsError as error:
            raise HistoryCorruptionError(f"{target_path}: target already exists") from error
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_fd)

    def _remove_staging_at(self, runs_fd: int, staging_name: str) -> None:
        try:
            staging_fd = os.open(
                staging_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=runs_fd,
            )
        except FileNotFoundError:
            return
        try:
            with suppress(FileNotFoundError):
                os.unlink("run.json", dir_fd=staging_fd)
            with suppress(FileNotFoundError):
                os.rmdir("records", dir_fd=staging_fd)
        finally:
            os.close(staging_fd)
        os.rmdir(staging_name, dir_fd=runs_fd)
