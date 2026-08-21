from __future__ import annotations

import pytest

from ai_pcb.models.spec import MasterSpec, Requirement, RequirementStatus
from ai_pcb.models.state import DesignState


@pytest.fixture
def resolved_spec() -> MasterSpec:
    spec = MasterSpec.empty_template("test-project")
    requirement = Requirement(
        status=RequirementStatus.RESOLVED,
        critical=True,
        value="explicitly-declared-test-value",
        description="Test-only explicit requirement",
    )
    updates = {
        name: section.model_copy(update={"requirements": {"declared": requirement}})
        for name, section in spec.sections().items()
    }
    return spec.model_copy(update=updates)


@pytest.fixture
def design_state(resolved_spec: MasterSpec) -> DesignState:
    return DesignState(project_name="test-project", master_spec=resolved_spec)
