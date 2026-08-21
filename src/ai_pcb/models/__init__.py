"""Typed domain contracts with lazy public re-exports.

Lazy loading keeps low-level contract modules usable while specialization definitions are being
imported, without changing the public ``from ai_pcb.models import ...`` API.
"""

# ruff: noqa: F401 - TYPE_CHECKING imports define the public static-analysis API.

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_pcb.models.acquisition import (
        AcquisitionManifest,
        AcquisitionRequest,
        AcquisitionResult,
        ManufacturerDocumentType,
    )
    from ai_pcb.models.analysis import ComputationalBudget, LatencyBudget
    from ai_pcb.models.architecture import (
        ArchitectureCandidate,
        ArchitectureDecision,
        ArchitectureEvaluation,
        ArchitectureRisk,
        BlockInterface,
        FunctionalBlock,
        SystemArchitecture,
    )
    from ai_pcb.models.components import (
        ComponentCandidate,
        ComponentEvaluation,
        ComponentRequirement,
        ComponentSelection,
        EvidenceAcquisitionRequirement,
    )
    from ai_pcb.models.decision import DecisionStatus, EngineeringDecision
    from ai_pcb.models.evidence import Evidence, EvidenceProvenance, EvidenceSource
    from ai_pcb.models.knowledge import (
        DocumentChunk,
        DocumentMetadata,
        DocumentRecord,
        EngineeringEvidenceCandidate,
        EngineeringEvidenceQuery,
        EngineeringFactCandidate,
        IngestionReport,
    )
    from ai_pcb.models.spec import DesignIntent, MasterSpec, Requirement, RequirementStatus
    from ai_pcb.models.state import DesignState, WorkflowStage
    from ai_pcb.models.validation import (
        ValidationResult,
        ValidationSeverity,
        ValidationStatus,
        ValidatorApplicability,
        VerificationReport,
    )

_EXPORT_MODULES = {
    "AcquisitionManifest": "ai_pcb.models.acquisition",
    "AcquisitionRequest": "ai_pcb.models.acquisition",
    "AcquisitionResult": "ai_pcb.models.acquisition",
    "ArchitectureCandidate": "ai_pcb.models.architecture",
    "ArchitectureDecision": "ai_pcb.models.architecture",
    "ArchitectureEvaluation": "ai_pcb.models.architecture",
    "ArchitectureRisk": "ai_pcb.models.architecture",
    "BlockInterface": "ai_pcb.models.architecture",
    "ComponentCandidate": "ai_pcb.models.components",
    "ComponentEvaluation": "ai_pcb.models.components",
    "ComponentRequirement": "ai_pcb.models.components",
    "ComponentSelection": "ai_pcb.models.components",
    "ComputationalBudget": "ai_pcb.models.analysis",
    "DecisionStatus": "ai_pcb.models.decision",
    "DesignIntent": "ai_pcb.models.spec",
    "DesignState": "ai_pcb.models.state",
    "DocumentChunk": "ai_pcb.models.knowledge",
    "DocumentMetadata": "ai_pcb.models.knowledge",
    "DocumentRecord": "ai_pcb.models.knowledge",
    "EngineeringDecision": "ai_pcb.models.decision",
    "EngineeringEvidenceCandidate": "ai_pcb.models.knowledge",
    "EngineeringEvidenceQuery": "ai_pcb.models.knowledge",
    "EngineeringFactCandidate": "ai_pcb.models.knowledge",
    "Evidence": "ai_pcb.models.evidence",
    "EvidenceAcquisitionRequirement": "ai_pcb.models.components",
    "EvidenceProvenance": "ai_pcb.models.evidence",
    "EvidenceSource": "ai_pcb.models.evidence",
    "IngestionReport": "ai_pcb.models.knowledge",
    "FunctionalBlock": "ai_pcb.models.architecture",
    "LatencyBudget": "ai_pcb.models.analysis",
    "MasterSpec": "ai_pcb.models.spec",
    "ManufacturerDocumentType": "ai_pcb.models.acquisition",
    "Requirement": "ai_pcb.models.spec",
    "RequirementStatus": "ai_pcb.models.spec",
    "SystemArchitecture": "ai_pcb.models.architecture",
    "ValidationResult": "ai_pcb.models.validation",
    "ValidationSeverity": "ai_pcb.models.validation",
    "ValidationStatus": "ai_pcb.models.validation",
    "ValidatorApplicability": "ai_pcb.models.validation",
    "VerificationReport": "ai_pcb.models.validation",
    "WorkflowStage": "ai_pcb.models.state",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
