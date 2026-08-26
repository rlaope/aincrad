from __future__ import annotations

from io import StringIO
from pathlib import Path

from aincrad.cli import _default_run, main
from aincrad.domain import CharacterClass
from aincrad.history import HistoryArchive


def test_history_associates_replayable_log_and_projects_story_evidence(tmp_path: Path) -> None:
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
    story = run.timeline[0].payload["events"][-1]
    assert story["kind"] == "story_resolution"
    assert story["scene"]
    assert story["opportunity"]
    assert story["evidence_ids"]

    output = StringIO()
    assert main(["history", "show", "1", "--history-root", str(history)], stdout=output) == 0
    assert "새벽별" in output.getvalue()
    assert "[이야기]" in output.getvalue()
    assert "근거 ID:" in output.getvalue()
