"""Typed domain contracts with lazy public re-exports.

Lazy loading keeps low-level contract modules usable while specialization definitions are being
imported, without changing the public ``from ai_pcb.models import ...`` API.
"""

# ruff: noqa: F401 - TYPE_CHECKING imports define the public static-analysis API.

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
    "EvidenceProvenance": "ai_pcb.models.evidence",
    "EvidenceSource": "ai_pcb.models.evidence",
    "IngestionReport": "ai_pcb.models.knowledge",
    "MasterSpec": "ai_pcb.models.spec",
    "Requirement": "ai_pcb.models.spec",
    "RequirementStatus": "ai_pcb.models.spec",
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
