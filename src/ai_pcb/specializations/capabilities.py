from __future__ import annotations

from collections.abc import Iterable

from ai_pcb.specializations.models import (
    CapabilityAssessment,
    CapabilityReport,
    CapabilityStatus,
    EngineeringCapability,
    ResolvedSpecializationContext,
)


def current_engine_capabilities() -> frozenset[EngineeringCapability]:
    """Capabilities genuinely implemented through Phase 2; future EDA work is absent."""

    return frozenset(
        {
            EngineeringCapability.DATASHEET_RETRIEVAL,
            EngineeringCapability.EVIDENCE_TRACEABILITY,
            EngineeringCapability.ARCHITECTURE_ANALYSIS,
            EngineeringCapability.COMPONENT_SELECTION,
            EngineeringCapability.REAL_TIME_PROCESSING_ANALYSIS,
        }
    )


def assess_capabilities(
    context: ResolvedSpecializationContext,
    *,
    available: Iterable[EngineeringCapability],
    stage: str,
) -> CapabilityReport:
    available_set = frozenset(available)
    assessments: list[CapabilityAssessment] = []
    for requirement in context.capabilities:
        if stage not in requirement.applicable_stages:
            status = CapabilityStatus.NOT_APPLICABLE
        elif requirement.capability in available_set:
            status = CapabilityStatus.AVAILABLE
        elif requirement.required:
            status = CapabilityStatus.REQUIRED_BUT_UNAVAILABLE
        else:
            status = CapabilityStatus.OPTIONAL_UNAVAILABLE
        assessments.append(
            CapabilityAssessment(
                capability=requirement.capability,
                status=status,
                required=requirement.required,
                applicable_stages=requirement.applicable_stages,
                declared_by=requirement.declared_by,
            )
        )
    return CapabilityReport(stage=stage, assessments=assessments)
