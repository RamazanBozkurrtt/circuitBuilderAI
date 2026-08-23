from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ai_pcb.architecture.analysis import build_latency_budget
from ai_pcb.components.discovery import EvidenceGroundedCandidateDiscovery
from ai_pcb.components.evaluation import ComponentEvaluator
from ai_pcb.components.lifecycle import ComponentSelectionLifecycle
from ai_pcb.components.manufacturer_facts import TrustedManufacturerFactRepository
from ai_pcb.components.requirements import ComponentRequirementDeriver
from ai_pcb.evidence.store import EvidenceNotFoundError, EvidenceStore
from ai_pcb.models.acquisition import (
    AcquisitionCatalog,
    AcquisitionVerificationStatus,
)
from ai_pcb.models.analysis import (
    FxLMSSuitabilityStatus,
    LatencyBudget,
    LatencyContribution,
    LatencyContributor,
)
from ai_pcb.models.architecture import (
    ArchitectureReview,
    ArchitectureReviewFinding,
    ArchitectureReviewStatus,
    ConstraintKind,
    EngineeringValue,
    ValueStatus,
)
from ai_pcb.models.closure import DesignVariableKind, DesignVariableStatus, ReadinessStatus
from ai_pcb.models.components import (
    CandidateEvidenceStatus,
    CandidateViability,
    ComponentCandidate,
    ComponentCategory,
    ComponentFact,
    ComponentRequirement,
    ComponentSelection,
)
from ai_pcb.models.decision import DecisionStatus
from ai_pcb.models.spec import MasterSpec, RequirementStatus
from ai_pcb.models.state import DesignState, WorkflowStage
from ai_pcb.models.validation import ValidationSeverity, ValidationStatus
from ai_pcb.specializations.builtin import builtin_registry
from ai_pcb.workflow.phase3 import Phase3Workflow


def anc_spec() -> MasterSpec:
    path = Path("projects/anc_controller_v1/master_spec.yaml")
    return MasterSpec.model_validate_json(json.dumps(yaml.safe_load(path.read_text())))


def anc_state() -> DesignState:
    return DesignState(project_name="anc_controller_v1", master_spec=anc_spec())


def run_phase3() -> DesignState:
    return Phase3Workflow(max_iterations=2).invoke(anc_state())


def run_phase31(tmp_path: Path) -> DesignState:
    facts = TrustedManufacturerFactRepository(
        fact_catalog_path=Path("projects/anc_controller_v1/manufacturer_component_facts.yaml"),
        acquisition_catalog_path=Path("knowledge/acquisition_metadata/catalog.json"),
        evidence_store=EvidenceStore(tmp_path / "evidence"),
    )
    discovery = EvidenceGroundedCandidateDiscovery(None, facts)
    return Phase3Workflow(max_iterations=2, candidate_discovery=discovery).invoke(anc_state())


def test_architecture_honors_channels_class_d_and_preserves_alternatives() -> None:
    state = run_phase3()
    assert state.phase3_complete
    assert state.workflow_stage is WorkflowStage.COMPONENT_SELECTION
    assert state.architecture is not None
    roles = {block.role for block in state.architecture.functional_blocks}
    assert "microphone_front_end" in roles
    assert "output_amplification" in roles
    assert any(
        constraint.value == 4
        for block in state.architecture.functional_blocks
        for constraint in block.channel_requirements
        if constraint.constraint_id.endswith("input_channels")
    )
    assert any(
        constraint.value == 4
        for block in state.architecture.functional_blocks
        for constraint in block.channel_requirements
        if constraint.constraint_id.endswith("output_channels")
    )
    class_d = next(
        item
        for item in state.architecture.hard_constraints
        if item.constraint_id.endswith("onboard_class_d_amplification")
    )
    assert class_d.kind is ConstraintKind.HARD_CONSTRAINT
    assert class_d.value is True
    assert state.architecture_decision is not None
    assert len(state.architecture_decision.viable_alternative_ids) == 2


def test_fxlms_is_not_inferred_from_audio_io_and_unknowns_remain_unknown() -> None:
    state = run_phase3()
    assert state.computational_budget is not None
    assert state.computational_budget.suitability.value == "UNKNOWN"
    scenario = state.computational_budget.scenarios[0]
    assert scenario.output_channels.value == 4
    assert scenario.sample_rate.status is ValueStatus.UNKNOWN
    assert scenario.filter_length.status is ValueStatus.UNKNOWN
    requirements = {item.requirement_id: item for item in state.component_requirements}
    assert requirements["class_d_amplifier.speaker_load"].status is RequirementStatus.UNKNOWN


def test_unsupported_part_and_unsupported_approval_fail_closed() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        ComponentCandidate(
            candidate_id="invented",
            category=ComponentCategory.DSP_PROCESSOR,
            manufacturer="Invented Inc",
            part_number="FAKE-1000",
            evidence_status=CandidateEvidenceStatus.IDENTITY_KNOWN,
            identity_source_ids=[],
        )
    with pytest.raises(ValidationError, match="require evidence"):
        ComponentSelection(
            selection_id="unsupported-approval",
            category=ComponentCategory.DSP_PROCESSOR,
            selected_candidate_id="candidate-1",
            status=DecisionStatus.EVIDENCE_VERIFIED,
        )


def _candidate(channel_count: int) -> ComponentCandidate:
    return ComponentCandidate(
        candidate_id=f"class-d-{channel_count}",
        category=ComponentCategory.CLASS_D_AMPLIFIER,
        manufacturer="Documented Manufacturer",
        part_number=f"DOC-{channel_count}",
        evidence_status=CandidateEvidenceStatus.EVIDENCE_VERIFIED,
        identity_source_ids=["retrieved-identity"],
        verified_evidence_ids=["promoted-identity"],
        facts=[
            ComponentFact(
                attribute="channel_count",
                value=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=channel_count,
                    evidence_ids=["promoted-channels"],
                ),
            ),
            ComponentFact(
                attribute="efficiency",
                value=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=0.95,
                    evidence_ids=["promoted-efficiency"],
                ),
            ),
        ],
    )


def test_hard_constraint_eliminates_candidate_regardless_of_optimization() -> None:
    hard = ComponentRequirement(
        requirement_id="class_d_amplifier.channel_count",
        category=ComponentCategory.CLASS_D_AMPLIFIER,
        attribute="channel_count",
        description="Four channels",
        kind=ConstraintKind.HARD_CONSTRAINT,
        status=RequirementStatus.RESOLVED,
        value=4,
        critical=True,
    )
    optimization = ComponentRequirement(
        requirement_id="class_d_amplifier.efficiency",
        category=ComponentCategory.CLASS_D_AMPLIFIER,
        attribute="efficiency",
        description="Efficiency",
        kind=ConstraintKind.OPTIMIZATION_OBJECTIVE,
        status=RequirementStatus.RESOLVED,
        value=0.95,
    )
    evaluation = ComponentEvaluator().evaluate(
        _candidate(2), [hard, optimization], builtin_registry().resolve(["audio_anc"])
    )
    assert evaluation.viability is CandidateViability.REJECTED
    assert any(
        item.kind is ConstraintKind.HARD_CONSTRAINT and item.status is ValidationStatus.FAIL
        for item in evaluation.criteria
    )
    assert evaluation.weighted_optimization_score == 1.0


def test_component_selection_lifecycle_resolves_evidence_ids_in_store(
    tmp_path: Path,
) -> None:
    hard = ComponentRequirement(
        requirement_id="class_d_amplifier.channel_count",
        category=ComponentCategory.CLASS_D_AMPLIFIER,
        attribute="channel_count",
        description="Four channels",
        kind=ConstraintKind.HARD_CONSTRAINT,
        status=RequirementStatus.RESOLVED,
        value=4,
        critical=True,
    )
    candidate = _candidate(4)
    evaluation = ComponentEvaluator().evaluate(
        candidate, [hard], builtin_registry().resolve(["audio_anc"])
    )
    selection = ComponentSelection(
        selection_id="class-d-selection",
        category=ComponentCategory.CLASS_D_AMPLIFIER,
        selected_candidate_id=candidate.candidate_id,
    )
    with pytest.raises(EvidenceNotFoundError, match="unknown evidence"):
        ComponentSelectionLifecycle(EvidenceStore(tmp_path / "evidence")).evidence_verify(
            selection, candidate, evaluation
        )


def test_missing_local_datasheets_create_category_evidence_requirements() -> None:
    spec = anc_spec()
    context = builtin_registry().resolve(spec.design.specializations)
    requirements = ComponentRequirementDeriver().derive(spec, context)
    result = EvidenceGroundedCandidateDiscovery(None).discover(requirements, context)
    assert not result.candidates
    assert {item.category for item in result.evidence_requirements} >= {
        ComponentCategory.DSP_PROCESSOR,
        ComponentCategory.ADC,
        ComponentCategory.DAC,
        ComponentCategory.AUDIO_CODEC,
        ComponentCategory.CLASS_D_AMPLIFIER,
        ComponentCategory.CLOCKING,
        ComponentCategory.POWER_MANAGEMENT,
    }
    assert all(item.status.value == "EVIDENCE_REQUIRED" for item in result.evidence_requirements)


def test_latency_unknown_is_not_zero_and_known_terms_preserve_provenance() -> None:
    unknown = build_latency_budget()
    assert unknown.total.status is ValueStatus.UNKNOWN
    assert unknown.total.value is None
    known = LatencyBudget.from_contributions(
        "known-latency",
        [
            LatencyContribution(
                contribution_id="adc-latency",
                contributor=LatencyContributor.ADC,
                latency=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=1.0,
                    unit="ms",
                    conditions=["48 kHz"],
                    evidence_ids=["adc-datasheet-page-20"],
                ),
            ),
            LatencyContribution(
                contribution_id="dac-latency",
                contributor=LatencyContributor.DAC,
                latency=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=2.0,
                    unit="ms",
                    conditions=["48 kHz"],
                    evidence_ids=["dac-datasheet-page-21"],
                ),
            ),
        ],
    )
    assert known.total.value == 3.0
    assert known.total.evidence_ids == [
        "adc-datasheet-page-20",
        "dac-datasheet-page-21",
    ]


def test_resolved_context_supplies_anc_guidance_without_rf() -> None:
    context = builtin_registry().resolve(["audio_anc"])
    assert context.resolved_ids == ["generic", "mixed_signal", "audio", "audio_anc"]
    assert "rf" not in context.resolved_ids
    criteria = {item.criterion_id for item in context.evaluation_criteria}
    categories = {item.category for item in context.component_categories}
    assert "processing_headroom" in criteria
    assert "DSP_PROCESSOR" in categories
    assert all("rf" not in item.casefold() for item in categories)


class _RejectOnceReviewer:
    def review(self, state: DesignState, *, attempt: int) -> ArchitectureReview:
        assert state.architecture_decision is not None
        if attempt == 1:
            return ArchitectureReview(
                review_id="forced-review-1",
                candidate_id=state.architecture_decision.selected_candidate_id,
                attempt=1,
                status=ArchitectureReviewStatus.REJECTED,
                correction_target="architecture",
                findings=[
                    ArchitectureReviewFinding(
                        finding_id="forced-interface-failure",
                        status=ValidationStatus.FAIL,
                        severity=ValidationSeverity.CRITICAL,
                        category="interface_compatibility",
                        description="Forced independent-review correction for test.",
                    )
                ],
            )
        return ArchitectureReview(
            review_id="forced-review-2",
            candidate_id=state.architecture_decision.selected_candidate_id,
            attempt=2,
            status=ArchitectureReviewStatus.ACCEPTED,
        )


class _AlwaysRejectReviewer:
    def review(self, state: DesignState, *, attempt: int) -> ArchitectureReview:
        assert state.architecture_decision is not None
        return ArchitectureReview(
            review_id=f"forced-review-{attempt}",
            candidate_id=state.architecture_decision.selected_candidate_id,
            attempt=attempt,
            status=ArchitectureReviewStatus.REJECTED,
            correction_target="architecture",
            findings=[
                ArchitectureReviewFinding(
                    finding_id=f"forced-failure-{attempt}",
                    status=ValidationStatus.FAIL,
                    severity=ValidationSeverity.CRITICAL,
                    category="hard_constraint",
                    description="Persistent forced review failure.",
                )
            ],
        )


def test_review_rejects_retries_and_preserves_previous_proposals() -> None:
    final = Phase3Workflow(max_iterations=2, reviewer=_RejectOnceReviewer()).invoke(anc_state())
    assert final.phase3_complete
    assert len(final.architecture_reviews) == 2
    assert len(final.architecture_candidates) == 6
    assert any(candidate.candidate_id.endswith("a1") for candidate in final.architecture_candidates)
    assert any(candidate.candidate_id.endswith("a2") for candidate in final.architecture_candidates)
    assert any(
        transition.to_stage is WorkflowStage.ARCHITECTURE and "correction" in transition.reason
        for transition in final.history
    )


def test_review_loop_is_bounded() -> None:
    final = Phase3Workflow(max_iterations=2, reviewer=_AlwaysRejectReviewer()).invoke(anc_state())
    assert not final.phase3_complete
    assert final.workflow_stage is WorkflowStage.BLOCKED
    assert len(final.architecture_reviews) == 2
    assert any("exhausted 2 attempts" in blocker for blocker in final.blockers)


def test_real_manufacturer_evidence_advances_candidates_without_unsafe_approval(
    tmp_path: Path,
) -> None:
    state = run_phase31(tmp_path)
    by_part = {candidate.part_number: candidate for candidate in state.component_candidates}
    assert by_part["ADSP-21569"].evidence_status is CandidateEvidenceStatus.EVIDENCE_VERIFIED
    assert by_part["PCM3168A"].verified_evidence_ids
    assert by_part["AD1938"].verified_evidence_ids
    assert by_part["ADAU1978"].verified_evidence_ids
    assert by_part["TAS6424-Q1"].verified_evidence_ids
    assert by_part["ADP5054"].verified_evidence_ids
    assert state.architecture is not None
    assert state.architecture.topology == "adc_dsp_digital_class_d"
    assert "dac" not in {block.role for block in state.architecture.functional_blocks}
    assert any(
        connection.interface_type == "synchronous_tdm4_digital_audio"
        for connection in state.architecture.connections
    )
    assert state.architecture_decision is not None
    assert state.architecture_decision.rejected_candidate_ids
    assert all(
        evaluation.viability is not CandidateViability.VIABLE
        for evaluation in state.component_evaluations
    )


def test_unresolved_load_keeps_class_d_selection_provisional_inside_envelope(
    tmp_path: Path,
) -> None:
    state = run_phase31(tmp_path)
    selection = next(
        item for item in state.components if item.category is ComponentCategory.CLASS_D_AMPLIFIER
    )
    assert selection.selected_candidate_id is not None
    assert selection.status is DecisionStatus.PROPOSED
    tas = next(item for item in state.component_candidates if item.part_number == "TAS6424-Q1")
    evaluation = next(
        item for item in state.component_evaluations if item.candidate_id == tas.candidate_id
    )
    load = next(item for item in evaluation.criteria if item.criterion_id.endswith("speaker_load"))
    assert load.status is ValidationStatus.UNKNOWN


def test_fxlms_scenarios_produce_conservative_likely_capable_status(tmp_path: Path) -> None:
    state = run_phase31(tmp_path)
    assert state.computational_budget is not None
    assert state.computational_budget.suitability is FxLMSSuitabilityStatus.LIKELY_CAPABLE
    assert all(
        scenario.operations_per_second.status is ValueStatus.ESTIMATED
        for scenario in state.computational_budget.scenarios
    )
    assert all(
        scenario.processing_headroom.status is ValueStatus.ESTIMATED
        for scenario in state.computational_budget.scenarios
    )
    stress = next(
        scenario
        for scenario in state.computational_budget.scenarios
        if scenario.scenario_id.endswith("16paths")
    )
    assert stress.operations_per_second.value == 1_966_080_000
    assert stress.processing_headroom.value == 0.0
    dsp = next(
        item for item in state.components if item.category is ComponentCategory.DSP_PROCESSOR
    )
    assert dsp.status is DecisionStatus.PROPOSED
    assert dsp.selected_candidate_id is not None


def test_phase33_selected_latency_path_removes_dac_and_keeps_unknown_total(
    tmp_path: Path,
) -> None:
    state = run_phase31(tmp_path)
    assert state.latency_budget is not None
    assert state.latency_budget.total.status is ValueStatus.UNKNOWN
    adc = next(
        item
        for item in state.latency_budget.contributions
        if item.contributor is LatencyContributor.ADC
    )
    assert adc.latency.status is ValueStatus.KNOWN
    assert adc.latency.evidence_ids
    assert any("ADAU1978" in item for item in adc.latency.conditions)
    assert all(
        item.contributor is not LatencyContributor.DAC
        for item in state.latency_budget.contributions
    )
    known = [
        item.latency.value
        for item in state.latency_budget.contributions
        if item.latency.status is ValueStatus.KNOWN
    ]
    assert sum(float(value) for value in known if value is not None) == pytest.approx(364.4208333)
    assert state.latency_budget.candidate_comparisons
    selected = state.latency_budget.candidate_comparisons[0]
    assert selected.comparison_id == "latency-path-adau1978-tas6424-96k"
    assert selected.documented_converter_delay.status is ValueStatus.KNOWN


def test_design_variables_are_classified_closed_and_do_not_rewrite_master_spec(
    tmp_path: Path,
) -> None:
    state = run_phase31(tmp_path)
    variables = {item.variable_id: item for item in state.design_variables}
    assert variables["audio.sample_rate"].kind is DesignVariableKind.ENGINEERING_DESIGN_VARIABLE
    assert variables["audio.sample_rate"].status is DesignVariableStatus.RESOLVED
    assert variables["audio.sample_rate"].resolution is not None
    assert variables["audio.sample_rate"].resolution.value == 96
    assert variables["audio.sample_rate"].evidence_ids
    assert variables["electrical.speaker_impedance"].kind is DesignVariableKind.USER_CONSTRAINT
    assert variables["electrical.speaker_impedance"].status is DesignVariableStatus.DESIGN_ENVELOPE
    assert variables["electrical.speaker_impedance"].envelope is not None
    assert state.master_spec.audio.requirements["sample_rate"].status is RequirementStatus.UNKNOWN
    assert state.master_spec.electrical.requirements["speaker_impedance"].value is None


def test_phase4_readiness_closes_phase33_architecture_gate(tmp_path: Path) -> None:
    state = run_phase31(tmp_path)
    assert state.phase4_readiness is not None
    assert state.phase4_readiness.status is ReadinessStatus.READY_FOR_PHASE_4
    assert not state.phase4_readiness.blockers
    interface = next(
        item
        for item in state.phase4_readiness.criteria
        if item.criterion_id == "major-interface-compatibility"
    )
    assert interface.status is ValidationStatus.PASS
    assert state.microphone_front_end is not None
    assert state.microphone_front_end.adc_part_number == "ADAU1978"
    assert state.clock_tree is not None
    signals = {item.signal_id: item for item in state.clock_tree.signals}
    assert signals["audio-mclk"].frequency_hz == 24_576_000
    assert signals["audio-bclk"].frequency_hz == 12_288_000
    assert signals["audio-fsync"].frequency_hz == 96_000
    assert state.power_tree is not None
    assert {rail.rail_id for rail in state.power_tree.rails} == {
        "pvdd-vbat",
        "3v3-digital-analog",
        "1v8-reference-analog",
        "1v0-dsp-core",
    }


def test_component_fact_repository_rejects_nontrusted_manufacturer_document(
    tmp_path: Path,
) -> None:
    source_catalog = AcquisitionCatalog.model_validate_json(
        Path("knowledge/acquisition_metadata/catalog.json").read_text(encoding="utf-8")
    )
    acquisition = next(
        item
        for item in source_catalog.documents
        if item.acquisition_id == "acquisition-e7fb2a74d5f69cae96221c1b"
    ).model_copy(
        update={
            "verification_status": AcquisitionVerificationStatus.IDENTITY_UNVERIFIED,
            "verification_messages": ["forced nontrusted test fixture"],
        }
    )
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        AcquisitionCatalog(documents=[acquisition]).model_dump_json(indent=2),
        encoding="utf-8",
    )
    facts_path = tmp_path / "facts.yaml"
    facts_path.write_text(
        """facts:
  - fact_id: fact-test-untrusted
    candidate_category: DSP_PROCESSOR
    candidate_manufacturer: Analog Devices
    candidate_part_number: ADSP-21569
    attribute: memory
    value: documented
    acquisition_id: acquisition-e7fb2a74d5f69cae96221c1b
    document_sha256: 0c908438ea8f71ccd559f44db26e7715fcd93dbf1d962c36e9a790e09efca85e
    page: 1
    evidence_text: ADSP-21569
    normalized_fact: Test fact that must not be exposed.
""",
        encoding="utf-8",
    )
    repository = TrustedManufacturerFactRepository(
        fact_catalog_path=facts_path,
        acquisition_catalog_path=catalog_path,
        evidence_store=EvidenceStore(tmp_path / "evidence"),
    )
    with pytest.raises(ValueError, match="untrusted acquisition"):
        repository.candidates()
