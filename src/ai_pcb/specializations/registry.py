from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence

from ai_pcb.specializations.models import (
    AggregatedCapabilityRequirement,
    DesignSpecialization,
    EngineeringCapability,
    ResolvedSpecialization,
    ResolvedSpecializationContext,
)


class SpecializationError(ValueError):
    pass


class UnknownSpecializationError(SpecializationError):
    pass


class DuplicateSpecializationError(SpecializationError):
    pass


class SpecializationDependencyCycleError(SpecializationError):
    pass


class SpecializationConflictError(SpecializationError):
    pass


class SpecializationRegistry:
    """Explicit registry and deterministic dependency resolver."""

    def __init__(self, specializations: Iterable[DesignSpecialization] = ()) -> None:
        self._definitions: dict[str, DesignSpecialization] = {}
        for specialization in specializations:
            self.register(specialization)

    def register(self, specialization: DesignSpecialization) -> None:
        if specialization.id in self._definitions:
            raise DuplicateSpecializationError(
                f"specialization already registered: {specialization.id}"
            )
        self._definitions[specialization.id] = specialization

    def get(self, specialization_id: str) -> DesignSpecialization:
        try:
            return self._definitions[specialization_id]
        except KeyError as exc:
            raise UnknownSpecializationError(
                f"unknown specialization: {specialization_id}"
            ) from exc

    def all(self) -> tuple[DesignSpecialization, ...]:
        return tuple(self._definitions.values())

    def resolve(self, requested: Sequence[str]) -> ResolvedSpecializationContext:
        normalized = _ordered_unique(requested or ["generic"])

        resolved: list[DesignSpecialization] = []
        complete: set[str] = set()
        visiting: list[str] = []

        def visit(specialization_id: str) -> None:
            if specialization_id in complete:
                return
            if specialization_id in visiting:
                start = visiting.index(specialization_id)
                cycle = [*visiting[start:], specialization_id]
                raise SpecializationDependencyCycleError(
                    f"specialization dependency cycle: {' -> '.join(cycle)}"
                )
            definition = self.get(specialization_id)
            visiting.append(specialization_id)
            for dependency in definition.extends:
                visit(dependency)
            visiting.pop()
            complete.add(specialization_id)
            resolved.append(definition)

        visit("generic")
        for specialization_id in normalized:
            visit(specialization_id)
        self._detect_conflicts(resolved)
        return _compose_context(normalized, resolved)

    @staticmethod
    def _detect_conflicts(resolved: Sequence[DesignSpecialization]) -> None:
        active = {definition.id for definition in resolved}
        conflicts: set[tuple[str, str]] = set()
        for definition in resolved:
            for conflict in definition.conflicts:
                if conflict in active:
                    left, right = sorted((definition.id, conflict))
                    conflicts.add((left, right))
        if conflicts:
            rendered = ", ".join(
                f"{left} conflicts with {right}" for left, right in sorted(conflicts)
            )
            raise SpecializationConflictError(rendered)


def specialization_reference(definition: DesignSpecialization) -> ResolvedSpecialization:
    canonical = definition.model_dump_json(exclude_none=False)
    return ResolvedSpecialization(
        id=definition.id,
        version=definition.version,
        definition_fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _compose_context(
    requested: list[str], resolved: list[DesignSpecialization]
) -> ResolvedSpecializationContext:
    capability_order: list[EngineeringCapability] = []
    capability_data: dict[EngineeringCapability, tuple[bool, list[str], list[str], list[str]]] = {}
    for definition in resolved:
        for required, requirements in (
            (True, definition.required_capabilities),
            (False, definition.optional_capabilities),
        ):
            for requirement in requirements:
                capability = requirement.capability
                if capability not in capability_data:
                    capability_order.append(capability)
                    capability_data[capability] = (required, [], [], [])
                was_required, stages, declared_by, rationales = capability_data[capability]
                stages.extend(
                    stage for stage in requirement.applicable_stages if stage not in stages
                )
                if definition.id not in declared_by:
                    declared_by.append(definition.id)
                if requirement.rationale not in rationales:
                    rationales.append(requirement.rationale)
                capability_data[capability] = (
                    was_required or required,
                    stages,
                    declared_by,
                    rationales,
                )
    capabilities = [
        AggregatedCapabilityRequirement(
            capability=capability,
            required=capability_data[capability][0],
            applicable_stages=capability_data[capability][1],
            declared_by=capability_data[capability][2],
            rationales=capability_data[capability][3],
        )
        for capability in capability_order
    ]
    return ResolvedSpecializationContext(
        requested=requested,
        resolved=resolved,
        requirement_domains=list(
            dict.fromkeys(
                domain for definition in resolved for domain in definition.requirement_domains
            )
        ),
        validation_domains=list(
            dict.fromkeys(
                domain for definition in resolved for domain in definition.validation_domains
            )
        ),
        capabilities=capabilities,
        engineering_guidance=[
            item for definition in resolved for item in definition.engineering_guidance
        ],
        architecture_blocks=[
            item for definition in resolved for item in definition.architecture_blocks
        ],
        component_categories=[
            item for definition in resolved for item in definition.component_categories
        ],
        evaluation_criteria=[
            item for definition in resolved for item in definition.evaluation_criteria
        ],
        evidence_requirements=[
            item for definition in resolved for item in definition.evidence_requirements
        ],
        acceptance_criteria_extensions=[
            item for definition in resolved for item in definition.acceptance_criteria_extensions
        ],
        retrieval_hints=_ordered_unique(
            [hint for definition in resolved for hint in definition.metadata.retrieval_hints]
        ),
    )


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
