from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from ai_pcb.models.common import Identifier
from ai_pcb.models.spec import MasterSpec
from ai_pcb.models.state import DesignState
from ai_pcb.specializations.builtin import builtin_registry


class ProjectRepositoryError(RuntimeError):
    pass


class ProjectAlreadyExistsError(ProjectRepositoryError):
    pass


class ProjectNotFoundError(ProjectRepositoryError):
    pass


class ImmutableSnapshotError(ProjectRepositoryError):
    pass


class ProjectRepository:
    def __init__(self, projects_root: Path) -> None:
        self.projects_root = projects_root.resolve()

    def project_path(self, project_name: str) -> Path:
        safe_name = TypeAdapter(Identifier).validate_python(project_name)
        return self.projects_root / safe_name

    def init(self, project_name: str, *, specializations: list[str] | None = None) -> DesignState:
        requested = specializations or ["generic"]
        # Resolve before creating directories so an invalid request leaves no partial project.
        builtin_registry().resolve(requested)
        root = self.project_path(project_name)
        try:
            root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ProjectAlreadyExistsError(f"project already exists: {project_name}") from exc
        for subdirectory in ("state", "evidence", "outputs"):
            (root / subdirectory).mkdir()
        spec = MasterSpec.empty_template(project_name, specializations=requested)
        state = DesignState(project_name=project_name, master_spec=spec)
        self._atomic_replace(root / "master_spec.yaml", _yaml_bytes(spec))
        self.save_current(state)
        return state

    def load_spec(self, project_name: str) -> MasterSpec:
        path = self.project_path(project_name) / "master_spec.yaml"
        if not path.is_file():
            raise ProjectNotFoundError(f"MASTER_SPEC not found for project: {project_name}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return MasterSpec.model_validate_json(json.dumps(raw))

    def load_state(self, project_name: str) -> DesignState:
        path = self.project_path(project_name) / "state" / "current.json"
        if not path.is_file():
            raise ProjectNotFoundError(f"state not found for project: {project_name}")
        state = DesignState.model_validate_json(path.read_text(encoding="utf-8"))
        current_spec = self.load_spec(project_name)
        if state.master_spec != current_spec:
            raw_state = state.model_dump(mode="json")
            raw_state["master_spec"] = current_spec.model_dump(mode="json")
            raw_state.pop("requested_specializations", None)
            raw_state.pop("resolved_specializations", None)
            state = DesignState.model_validate(raw_state)
        return state

    def save_current(self, state: DesignState) -> Path:
        path = self.project_path(state.project_name) / "state" / "current.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_replace(path, state.model_dump_json(indent=2).encode())
        return path

    def checkpoint_current(self, state: DesignState) -> None:
        self.save_current(state)

    def save_snapshot(self, state: DesignState) -> Path:
        if state.iteration < 1:
            raise ValueError("historical snapshots start at iteration 1")
        path = (
            self.project_path(state.project_name)
            / "state"
            / f"iteration_{state.iteration:03d}.json"
        )
        if path.exists():
            raise ImmutableSnapshotError(f"historical snapshot already exists: {path.name}")
        self._atomic_create(path, state.model_dump_json(indent=2).encode())
        return path

    def persist_iteration(self, state: DesignState) -> None:
        # History first: if it cannot be created, current remains untouched.
        self.save_snapshot(state)
        self.save_current(state)

    @staticmethod
    def _atomic_replace(destination: Path, payload: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _atomic_create(destination: Path, payload: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # rename is non-replacing on Windows, providing atomic create semantics here.
            try:
                temporary.rename(destination)
            except FileExistsError as exc:
                raise ImmutableSnapshotError(
                    f"historical snapshot already exists: {destination.name}"
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)


def _yaml_bytes(spec: MasterSpec) -> bytes:
    rendered = yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    return rendered.encode("utf-8")
