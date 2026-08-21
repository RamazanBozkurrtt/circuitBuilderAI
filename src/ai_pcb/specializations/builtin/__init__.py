from ai_pcb.specializations.builtin.anc import AUDIO_ANC
from ai_pcb.specializations.builtin.audio import AUDIO
from ai_pcb.specializations.builtin.generic import GENERIC
from ai_pcb.specializations.builtin.high_speed_digital import HIGH_SPEED_DIGITAL
from ai_pcb.specializations.builtin.mixed_signal import MIXED_SIGNAL
from ai_pcb.specializations.builtin.power_electronics import POWER_ELECTRONICS
from ai_pcb.specializations.builtin.rf import RF
from ai_pcb.specializations.registry import SpecializationRegistry


def builtin_registry() -> SpecializationRegistry:
    return SpecializationRegistry(
        [
            GENERIC,
            MIXED_SIGNAL,
            AUDIO,
            AUDIO_ANC,
            HIGH_SPEED_DIGITAL,
            POWER_ELECTRONICS,
            RF,
        ]
    )


__all__ = [
    "AUDIO",
    "AUDIO_ANC",
    "GENERIC",
    "HIGH_SPEED_DIGITAL",
    "MIXED_SIGNAL",
    "POWER_ELECTRONICS",
    "RF",
    "builtin_registry",
]
