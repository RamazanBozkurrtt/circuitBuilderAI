from __future__ import annotations

from collections.abc import Sequence

from ai_pcb.specializations.models import ResolvedSpecializationContext
from ai_pcb.specializations.registry import SpecializationRegistry


class SpecializationResolver:
    def __init__(self, registry: SpecializationRegistry) -> None:
        self.registry = registry

    def resolve(self, requested: Sequence[str]) -> ResolvedSpecializationContext:
        return self.registry.resolve(requested)
