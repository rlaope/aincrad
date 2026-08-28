from __future__ import annotations

from io import StringIO
from pathlib import Path

from aincrad.cli import _default_run, main
from aincrad.domain import CharacterClass
from aincrad.history import HistoryArchive


def test_history_projects_the_resolved_action_without_an_empty_story_event(tmp_path: Path) -> None:
    history = tmp_path / "history"
    event_log = tmp_path / "run" / "events.jsonl"
    _default_run(
        seed=12,
        hours=1,
        headless=True,
        output=event_log,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="새벽별",
        history_root=history,
    )

    run = HistoryArchive(history).load_run(1)
    assert run.metadata["hero_name"] == "새벽별"
    assert run.metadata["event_log"] == str(event_log)
    assert event_log.exists()
    events = run.timeline[0].payload["events"]
    assert isinstance(events, list)
    assert all(event.get("kind") != "story_resolution" for event in events)

    output = StringIO()
    assert main(["history", "show", "1", "--history-root", str(history)], stdout=output) == 0
    assert "새벽별" in output.getvalue()
    assert "[행동] 새벽별 — 고요한 심지 여관으로 이동했다." in output.getvalue()
    assert "[이야기]" not in output.getvalue()
    assert "아무 일" not in output.getvalue()
    assert "동료의 합류" not in output.getvalue()
    assert "no_op" not in output.getvalue()
    assert "근거 ID:" not in output.getvalue()


def test_history_action_projection_tolerates_a_non_string_actor_id(tmp_path: Path) -> None:
    history = tmp_path / "history"
    archive = HistoryArchive(history)
    run_number = archive.create_run(
        {"hero_name": "새벽별", "character_class_ko": "전사"}
    )
    archive.append_hourly(
        run_number,
        {
            "day": 1,
            "hour": 0,
            "tick": 0,
            "events": [{"action": "wait", "adventurer_id": []}],
            "party": [
                {
                    "id": "hero",
                    "name": "새벽별",
                    "level": 1,
                    "exp": 0,
                    "hp": 24,
                    "mp": 8,
                    "alive": True,
                }
            ],
        },
    )

    output = StringIO()
    assert main(
        ["history", "show", str(run_number), "--history-root", str(history)],
        stdout=output,
    ) == 0
    assert "[행동] 새벽별 — ‘대기’에 나섰다." in output.getvalue()
