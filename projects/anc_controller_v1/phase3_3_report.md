# Phase 3.3 — Architecture Closure & Phase 4 Readiness

## Final signal-path architecture

Four differential analog microphone channels → matched low-noise analog front ends →
ADAU1978 four-channel ADC → 96 kHz, 24-bit TDM4 → ADSP-21569 FxLMS processing →
96 kHz, 24-bit TDM4 → TAS6424-Q1 digital-input Class-D amplifier → four speaker outputs.

The selected path contains no DAC. ADAU1978 and TAS6424-Q1 use four 32-bit TDM slots,
with 24-bit samples, 12.288 MHz BCLK, and 96 kHz FSYNC. The signal path is digitally and
electrically coherent at every major boundary.

## Major provisional components

- ADC: ADAU1978.
- DSP: ADSP-21569.
- Output stage: TAS6424-Q1, conditional on the documented output envelope below.
- Low-voltage PMIC: ADP5054.
- Microphones: differential analog MEMS technology envelope; exact part remains a controlled
  acoustic/user-dependent selection.
- Clock source: low-jitter 24.576 MHz, 3.3 V oscillator envelope; exact oscillator and the
  3.3-to-1.8 V DSP clock translator are schematic-stage selections.

## Components removed or replaced

- AD1938 is removed from the selected signal path. Its DAC outputs are analog and cannot feed
  TAS6424-Q1; using only its ADC half retains an unused DAC subsystem with no evidenced latency
  or complexity advantage over ADAU1978.
- PCM3168A is not selected for the same unnecessary-DAC reason.
- A codec/DAC plus analog-input Class-D topology is rejected for this revision because it adds a
  DAC, an analog routing/gain stage, and a new amplifier selection without an evidenced advantage.
- TAS6424-Q1 is retained provisionally because it provides the required four synchronized digital
  inputs and removes the DAC. It may be oversized if the eventual speaker requirement is far below
  its documented operating points; that does not create an interface or Phase 4 constraint violation.

## Microphone architecture

Provisionally selected interface: four AC-coupled differential analog MEMS channels. Each channel
uses a matched low-noise differential AFE into one ADAU1978 input. The evidenced ADC envelope is
2 V rms differential full scale, 1.5 V input common mode, and 28.6 kΩ differential input resistance.
AFE gain, bias, coupling/high-pass values, noise target, anti-RF network, and overload margin remain
UNKNOWN until microphone sensitivity, acoustic overload point, environment, and placement are
supplied. PDM is not selected because a four-channel PDM capture/decimation path is not evidenced
for the selected DSP; electret microphones add avoidable bias and AFE complexity.

## Clock tree

- Root: 24.576 MHz low-jitter oscillator at 256 × fS.
- Direct 3.3 V MCLK sinks: ADAU1978 and TAS6424-Q1.
- DSP clock sink: ADSP-21569 SYS_CLKIN0 through a low-additive-jitter 3.3-to-1.8 V translator.
- Audio master: ADSP-21569 PCG/SPORT.
- TDM BCLK: 12.288 MHz, 128 × fS, PCG CLKDIV = 2 from the 24.576 MHz source.
- TDM FSYNC/LRCLK: 96 kHz, PCG FSDIV = 256 from the same source.
- DSP CGU: DF = 0, MSEL = 80 gives 1.96608 GHz PLLCLK; CSEL = 2 gives
  983.04 MHz CCLK; SYSSEL = 4 gives 491.52 MHz SYSCLK; S0SEL = 4 gives
  122.88 MHz SCLK0.
- Synchronization: one root clock, no ASRC; ADC and amplifier are TDM clock slaves.
- Reset order: hold DSP reset until rails and SYS_CLKIN0 are stable; release ADAU1978 after its
  documented rail/clock and PLL-lock interval; unmute TAS6424-Q1 only after valid clocks and setup.

MCLK, BCLK, and FSYNC are jitter-sensitive and must be isolated from Class-D and regulator switching
nodes during schematic/layout verification.

## Power tree

- Regulated external input envelope: 4.5–15.5 V, provisionally 14.4 V nominal. Raw automotive
  transients are outside this envelope.
- Protected input branch: TAS6424-Q1 PVDD/VBAT directly; 10 A connector/fuse design allowance.
- ADP5054 channel 3: 3.3 V / 2.5 A provisioned for DSP I/O, ADAU1978 AVDD/IOVDD,
  TAS6424-Q1 VDD, clock/control, and a locally filtered microphone/AFE branch.
- ADP5054 channel 4: 1.8 V / 2.5 A provisioned for DSP VDD_REF/VDD_ANA and clock translation,
  with local low-noise filtering.
- ADP5054 channel 1: 1.0 V / 1.5 A provisional DSP core rail, including 30% provisioning over
  the documented 1.157 A typical full-activity condition.
- ADP5054 channel 2 remains available for schematic-stage allocation; no DDR rail is required if
  external DDR is omitted.
- Sequencing uses individual enable/soft-start controls, maintains DSP rail-delta limits, supervises
  rails and clock before reset release, and releases amplifier mute last.

The documented active subtotal is 1.267 W for DSP core plus ADC and amplifier logic under their
stated conditions; DSP I/O/analog domains, microphones/AFE, control, clocking, flash, and regulator
losses remain explicit unknowns. A 120 W board-input design envelope covers the documented
four-channel 25 W amplifier stress point plus digital loads; it is not a user power requirement.
At the documented 86% four-channel 25 W condition, amplifier loss is about 16.3 W and requires
exposed-pad/copper thermal verification.

## FxLMS status

**LIKELY_CAPABLE.** With the documented four-MAC FIR accelerator at a provisional 983.04 MHz
core clock and only 50% of theoretical MAC issue capacity credited:

- 48 kHz, 256 control taps, 128 secondary taps, 4 paths: 122.88 MMAC/s, 16 KiB,
  93.75% credited headroom.
- 96 kHz, 512 control taps, 256 secondary taps, 4 paths: 491.52 MMAC/s, 32 KiB,
  75% credited headroom.
- 96 kHz, 512 control taps, 256 secondary taps, fully coupled 4×4/16 paths:
  1.96608 GMAC/s, 128 KiB, 0% credited headroom.

The 4×4 case exactly consumes the conservative allowance, so final mapped firmware requires a later
hardware benchmark. Physical runtime measurement is not required before schematic design.

## Latency status

The documented known minimum contribution is **364.421 µs** at 96 kHz: ADAU1978 ADC group
delay 239.421 µs plus TAS6424-Q1 input-to-output delay 125 µs. No DAC latency term exists.
Microphone/AFE delay, serial framing/transport, buffering, DSP execution, and acoustic propagation
remain UNKNOWN, so total end-to-end latency remains UNKNOWN rather than silently passing.
The main risks are firmware buffering/execution and the final acoustic/AFE implementation.

## Remaining blockers

None for entering Phase 4. Carry-forward verification unknowns are the exact microphone and AFE
values, exact speaker/load demand, clock oscillator/translator parts, final rail losses and passives,
DSP buffering/runtime, and thermal performance. These can be resolved or fail closed during
schematic and subsequent verification without changing the coherent architecture.

## Phase 4 readiness

**READY_FOR_PHASE_4.** Signal path, microphone topology, DSP justification, digital interfaces,
clock tree, provisional power tree, and output envelope are closed with no known violated hard
constraint. This status authorizes schematic design next; no schematic or KiCad work was performed.

## Holdout retrieval result

Added a 10-query unseen Phase 3.3 holdout set. Result: Recall@1 0.20, Recall@3 0.90,
Recall@5 1.00, MRR 0.52, with no Recall@5 failures. The tuned 31-query result remains separately
reported at Recall@5 1.00 and MRR 0.8102.

## Test results

- Full pytest: 99 passed, 1 skipped (live Ollama not requested), 1 third-party deprecation warning.
- Ruff: passed.
- Strict MyPy: passed for 70 source files.
- Git diff/status: inspected; Phase 3.2 user work was preserved and Phase 3.3 changes are uncommitted.
