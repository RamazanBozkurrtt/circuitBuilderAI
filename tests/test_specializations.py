from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ai_pcb.cli import main
from ai_pcb.models.evidence import Evidence, EvidenceProvenance, EvidenceSource
from ai_pcb.models.spec import MasterSpec, Requirement, RequirementStatus
from ai_pcb.models.state import DesignState
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
    ValidatorApplicability,
)
from ai_pcb.persistence.project import ProjectRepository
from ai_pcb.specializations.builtin import GENERIC, builtin_registry
from ai_pcb.specializations.capabilities import assess_capabilities
from ai_pcb.specializations.models import (
    CapabilityStatus,
    DesignSpecialization,
    EngineeringCapability,
    ValidationDomain,
)
from ai_pcb.specializations.registry import (
    SpecializationConflictError,
    SpecializationDependencyCycleError,
    SpecializationRegistry,
    UnknownSpecializationError,
)
from ai_pcb.validation.engine import ValidationEngine
from ai_pcb.validation.spec import MasterSpecValidator


def context_for(*requested: str):
    return builtin_registry().resolve(list(requested))


def state_for(*requested: str) -> DesignState:
    spec = MasterSpec.empty_template("specialized-board", specializations=list(requested))
    return DesignState(project_name="specialized-board", master_spec=spec)


def test_generic_exists_and_is_active_for_every_design() -> None:
    registry = builtin_registry()
    assert registry.get("generic").id == "generic"
    assert context_for("rf").resolved_ids[0] == "generic"


def test_unknown_specialization_is_rejected() -> None:
    with pytest.raises(UnknownSpecializationError, match="unknown specialization"):
        context_for("not-a-domain")


def test_anc_dependency_chain_is_complete_and_deterministic() -> None:
    first = context_for("audio_anc")
    second = context_for("audio_anc")
    assert first.resolved_ids == ["generic", "mixed_signal", "audio", "audio_anc"]
    assert first == second


def test_duplicate_requests_are_deduplicated() -> None:
    context = context_for("audio_anc", "audio_anc", "audio")
    assert context.requested == ["audio_anc", "audio"]
    assert context.resolved_ids == ["generic", "mixed_signal", "audio", "audio_anc"]


def test_dependency_cycles_are_rejected() -> None:
    registry = SpecializationRegistry(
        [
            GENERIC,
            DesignSpecialization(
                id="cycle_a", name="A", version="1", description="A", extends=["cycle_b"]
            ),
            DesignSpecialization(
                id="cycle_b", name="B", version="1", description="B", extends=["cycle_a"]
            ),
        ]
    )
    with pytest.raises(SpecializationDependencyCycleError, match="cycle_a -> cycle_b"):
        registry.resolve(["cycle_a"])


def test_conflicts_are_surfaced_explicitly() -> None:
    registry = SpecializationRegistry(
        [
            GENERIC,
            DesignSpecialization(
                id="profile_a",
                name="A",
                version="1",
                description="A",
                conflicts=["profile_b"],
            ),
            DesignSpecialization(id="profile_b", name="B", version="1", description="B"),
        ]
    )
    with pytest.raises(SpecializationConflictError, match="profile_a conflicts with profile_b"):
        registry.resolve(["profile_a", "profile_b"])


def test_domain_requirements_do_not_leak_between_profiles() -> None:
    generic = context_for("generic")
    audio = context_for("audio")
    anc = context_for("audio_anc")
    rf = context_for("rf")

    assert ValidationDomain.AUDIO not in generic.validation_domains
    assert ValidationDomain.REAL_TIME_ANC not in generic.validation_domains
    assert ValidationDomain.AUDIO in audio.validation_domains
    assert ValidationDomain.REAL_TIME_ANC not in audio.validation_domains
    assert ValidationDomain.AUDIO in anc.validation_domains
    assert ValidationDomain.REAL_TIME_ANC in anc.validation_domains
    assert ValidationDomain.LATENCY in anc.validation_domains
    assert ValidationDomain.RF in rf.validation_domains
    assert ValidationDomain.AUDIO not in rf.validation_domains
    assert ValidationDomain.REAL_TIME_ANC not in rf.validation_domains


def test_unrelated_compatible_profiles_compose() -> None:
    context = context_for("rf", "high_speed_digital")
    assert context.resolved_ids == [
        "generic",
        "mixed_signal",
        "rf",
        "high_speed_digital",
    ]


def test_capability_aggregation_and_stage_enforcement_are_deterministic() -> None:
    context = context_for("audio_anc")
    assert context.capabilities == context_for("audio_anc").capabilities
    assert len({item.capability for item in context.capabilities}) == len(context.capabilities)

    early = assess_capabilities(context, available=[], stage="SPECIFICATION")
    schematic = assess_capabilities(context, available=[], stage="SCHEMATIC_VERIFICATION")
    early_latency = next(
        item
        for item in early.assessments
        if item.capability is EngineeringCapability.LATENCY_ANALYSIS
    )
    schematic_latency = next(
        item
        for item in schematic.assessments
        if item.capability is EngineeringCapability.LATENCY_ANALYSIS
    )
    assert early_latency.status is CapabilityStatus.NOT_APPLICABLE
    assert not early_latency.blocks_stage
    assert schematic_latency.status is CapabilityStatus.REQUIRED_BUT_UNAVAILABLE
    assert schematic_latency.blocks_stage
    assert EngineeringCapability.LATENCY_ANALYSIS in schematic.missing_required


def test_generic_spec_validation_does_not_require_audio_or_anc_sections() -> None:
    spec = MasterSpec.empty_template("generic-board")
    requirement = Requirement(
        status=RequirementStatus.RESOLVED,
        critical=True,
        value="explicit",
        description="Explicit generic requirement",
    )
    context = context_for("generic")
    updates = {
        domain.value: spec.sections()[domain.value].model_copy(
            update={"requirements": {"declared": requirement}}
        )
        for domain in context.requirement_domains
    }
    state = DesignState(project_name="generic-board", master_spec=spec.model_copy(update=updates))
    report = ValidationEngine([MasterSpecValidator()]).run(
        state, report_id="generic-spec", stage="SPECIFICATION"
    )
    assert report.can_advance
    assert all("audio" not in result.result_id for result in report.results)
    assert all("processing" not in result.result_id for result in report.results)


class _AlwaysGenericValidator:
    @property
    def name(self) -> str:
        return "generic_test"

    @property
    def applicability(self) -> ValidatorApplicability:
        return ValidatorApplicability(applicable_stages=["SCHEMATIC_VERIFICATION"])

    def validate(self, state: DesignState) -> list[ValidationResult]:
        return [
            ValidationResult(
                result_id="generic-test",
                validator=self.name,
                status=ValidationStatus.PASS,
                severity=ValidationSeverity.INFO,
                summary="Test-only generic validation executed",
            )
        ]


class _FutureAncLatencyValidator:
    @property
    def name(self) -> str:
        return "anc_total_latency"

    @property
    def applicability(self) -> ValidatorApplicability:
        return ValidatorApplicability(
            applicable_specializations=["audio_anc"],
            applicable_stages=["SCHEMATIC_VERIFICATION"],
            required_capability=EngineeringCapability.LATENCY_ANALYSIS,
        )

    def validate(self, state: DesignState) -> list[ValidationResult]:
        raise AssertionError("unavailable validator must not execute")


def test_specialized_validator_is_inactive_for_generic_and_unavailable_never_passes() -> None:
    validators = [_AlwaysGenericValidator(), _FutureAncLatencyValidator()]
    generic = ValidationEngine(validators, available_capabilities=frozenset()).run(
        state_for("generic"), report_id="generic", stage="SCHEMATIC_VERIFICATION"
    )
    anc = ValidationEngine(validators, available_capabilities=frozenset()).run(
        state_for("audio_anc"), report_id="anc", stage="SCHEMATIC_VERIFICATION"
    )
    assert [item.validator for item in generic.results] == ["generic_test"]
    unavailable = next(item for item in anc.results if item.validator == "anc_total_latency")
    assert unavailable.status is ValidationStatus.UNKNOWN
    assert unavailable.status is not ValidationStatus.PASS
    assert not anc.can_advance


def test_init_defaults_to_generic_and_anc_init_resolves_dependencies(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    generic = repository.init("generic-project")
    anc = repository.init("anc-project", specializations=["audio_anc"])
    assert generic.requested_specializations == ["generic"]
    assert [item.id for item in generic.resolved_specializations] == ["generic"]
    assert anc.requested_specializations == ["audio_anc"]
    assert [item.id for item in anc.resolved_specializations] == [
        "generic",
        "mixed_signal",
        "audio",
        "audio_anc",
    ]
    assert (
        repository.load_state("anc-project").resolved_specializations
        == anc.resolved_specializations
    )


def test_cli_init_supports_specialization_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "cli-projects"
    monkeypatch.setenv("AI_PCB_PROJECTS_DIR", str(project_root))
    assert main(["init", "cli-generic"]) == 0
    assert main(["init", "cli-anc", "--specialization", "audio_anc"]) == 0
    generic_raw = yaml.safe_load(
        (project_root / "cli-generic" / "master_spec.yaml").read_text()
    )
    assert generic_raw["design"]["specializations"] == ["generic"]
    raw = yaml.safe_load((project_root / "cli-anc" / "master_spec.yaml").read_text())
    assert raw["design"]["specializations"] == ["audio_anc"]
    state = json.loads((project_root / "cli-anc" / "state" / "current.json").read_text())
    assert [item["id"] for item in state["resolved_specializations"]] == [
        "generic",
        "mixed_signal",
        "audio",
        "audio_anc",
    ]


def test_legacy_master_spec_without_design_defaults_to_generic() -> None:
    raw = MasterSpec.empty_template("legacy").model_dump(mode="json")
    raw.pop("design")
    raw["schema_version"] = "1.0"
    spec = MasterSpec.model_validate(raw)
    state = DesignState(project_name="legacy", master_spec=spec)
    assert state.requested_specializations == ["generic"]
    assert [item.id for item in state.resolved_specializations] == ["generic"]


def test_specialization_resolution_does_not_change_evidence_provenance() -> None:
    evidence = Evidence(
        evidence_id="source-1",
        title="Source",
        provenance=EvidenceProvenance(
            source=EvidenceSource.DATASHEET,
            manufacturer="Example",
            document="Example data sheet",
            page="12",
        ),
        extracted_content="A source statement",
        normalized_fact="A normalized source fact",
        confidence=0.9,
    )
    before = evidence.model_dump(mode="json")
    context_for("audio_anc")
    assert evidence.model_dump(mode="json") == before


def test_specialization_guidance_is_scoped_to_active_profiles() -> None:
    generic_text = " ".join(
        concern
        for guidance in context_for("generic").engineering_guidance
        for concern in guidance.concerns
    ).lower()
    anc_text = " ".join(
        concern
        for guidance in context_for("audio_anc").engineering_guidance
        for concern in guidance.concerns
    ).lower()
    assert "fxlms" not in generic_text
    assert "microphone" not in generic_text
    assert "fxlms" in anc_text
    assert "total end-to-end latency" in anc_text


def test_invalid_resolved_snapshot_is_rejected() -> None:
    state = state_for("audio_anc")
    raw = state.model_dump()
    raw["resolved_specializations"][0]["version"] = "tampered"
    historical = DesignState.model_validate(raw)
    assert historical.resolved_specializations[0].version == "tampered"
    with pytest.raises(ValueError, match="snapshot differs"):
        historical.specialization_context()
