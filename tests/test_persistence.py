from __future__ import annotations

from pathlib import Path

import pytest

from ai_pcb.persistence.project import ImmutableSnapshotError, ProjectRepository


def test_project_init_creates_empty_master_spec(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    state = repository.init("empty-project")
    assert all(not section.requirements for section in state.master_spec.sections().values())
    root = repository.project_path("empty-project")
    assert (root / "master_spec.yaml").is_file()
    assert (root / "state" / "current.json").is_file()
    assert (root / "evidence").is_dir()
    assert (root / "outputs").is_dir()


def test_historical_snapshot_cannot_be_silently_overwritten(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    state = repository.init("history-project").model_copy(update={"iteration": 1})
    path = repository.save_snapshot(state)
    original = path.read_bytes()
    changed = state.model_copy(update={"blockers": ["changed"]})
    with pytest.raises(ImmutableSnapshotError, match="already exists"):
        repository.save_snapshot(changed)
    assert path.read_bytes() == original

