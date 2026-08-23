from __future__ import annotations

import math


def tdm_bit_clock_hz(sample_rate_hz: int, slots: int, slot_width_bits: int) -> int:
    if sample_rate_hz <= 0 or slots <= 0 or slot_width_bits <= 0:
        raise ValueError("TDM clock inputs must be positive")
    return sample_rate_hz * slots * slot_width_bits


def adp5054_feedback_top_ohms(
    output_voltage_v: float,
    bottom_resistance_ohm: float,
    *,
    reference_voltage_v: float = 0.8,
) -> float:
    if output_voltage_v <= reference_voltage_v:
        raise ValueError("output voltage must exceed the feedback reference")
    if bottom_resistance_ohm <= 0 or reference_voltage_v <= 0:
        raise ValueError("feedback parameters must be positive")
    return bottom_resistance_ohm * (output_voltage_v / reference_voltage_v - 1.0)


def adp5054_inductor_h(
    input_voltage_v: float,
    output_voltage_v: float,
    output_current_a: float,
    switching_frequency_hz: float,
    *,
    ripple_fraction: float = 0.35,
) -> float:
    if not 0 < output_voltage_v < input_voltage_v:
        raise ValueError("buck output voltage must lie between zero and input voltage")
    if output_current_a <= 0 or switching_frequency_hz <= 0:
        raise ValueError("buck current and switching frequency must be positive")
    if not 0 < ripple_fraction < 1:
        raise ValueError("ripple fraction must lie between zero and one")
    duty_cycle = output_voltage_v / input_voltage_v
    ripple_current_a = ripple_fraction * output_current_a
    return (
        (input_voltage_v - output_voltage_v)
        * duty_cycle
        / (ripple_current_a * switching_frequency_hz)
    )


def differential_high_pass_hz(resistance_ohm: float, capacitance_f: float) -> float:
    if resistance_ohm <= 0 or capacitance_f <= 0:
        raise ValueError("filter resistance and capacitance must be positive")
    return 1.0 / (2.0 * math.pi * resistance_ohm * capacitance_f)
