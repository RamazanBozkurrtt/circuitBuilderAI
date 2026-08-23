# Phase 3.2 - Retrieval hardening and design-variable closure

## Retrieval metrics before / after

The 31 real expected document/page locations were not changed.

| Evaluation | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---:|---:|---:|---:|
| Real manufacturer datasheets - before | 0.2581 | 0.4516 | 0.5161 | 0.3586 |
| Real manufacturer datasheets - after | 0.6774 | 0.9355 | 1.0000 | 0.8102 |
| Synthetic isolated fixture - after | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

## Fixes made

- Deterministic typed query-intent classification for exact identifiers, electrical
  specifications, interfaces/clocks, performance, timing/latency, layout/thermal, and general
  semantic queries.
- Deterministic query decomposition, engineering-symbol normalization, and exact identifier and
  numeric/unit coverage boosts.
- Query-type-aware lexical/dense reciprocal-rank weighting and section-aware/table-aware local
  reranking.
- Page-level evidence aggregation and diversification so split tables or register fragments do not
  consume the result window, with bounded adjacent-page relevance propagation.
- Regression coverage for classification, decomposition, overview routing, table/symbol handling,
  page diversification, and the unchanged synthetic retrieval behavior.

## Architecture result

`multichannel codec + DSP` remains the provisional winner. It closes both converter directions
with one evidenced device and avoids the unresolved standalone DAC in the separate-converter path.
The integrated-converter DSP path remains rejected because no trusted evidence establishes the
required synchronized four ADC and four DAC channels.

## Selected / provisional components

- ADSP-21569: provisionally selected DSP, lifecycle `PROPOSED`.
- AD1938: provisionally selected 4-ADC/8-DAC codec at the engineering-selected 96 kHz, 24-bit
  operating point, lifecycle `PROPOSED`.
- PCM3168A: retained codec alternative; its documented 96 kHz converter filter delay is higher.
- TAS6424-Q1: not finalized; retained behind an evidenced 2/4-ohm, 4.5-26.4 V PVDD, conditional
  power envelope.
- ADAU1978: retained for the separate-ADC alternative, which remains incomplete without an
  evidenced DAC.
- Power management, standalone clocking, and standalone DAC: no evidenced selection.

## Unresolved user constraints

- Actual speaker impedance and required power per channel; safe device envelopes exist but do not
  rewrite the user constraint.
- External input supply, control interface, external connectivity, PCB dimensions, and operating
  environment.

## Resolved engineering variables

- 96 kHz sample rate and 24-bit conversion.
- Multichannel codec + DSP converter architecture with AD1938 and ADSP-21569 provisional models.
- IEEE 1149.1 JTAG programming/debug interface.
- Typed design envelopes for FxLMS filter length/topology, DSP-master codec clock direction, PVDD
  alternatives, and four/six-layer PCB exploration. Exact clock dividers, full power tree, and final
  stackup remain open.

## FxLMS status

`LIKELY_CAPABLE_PENDING_WORKLOAD`.

- 48 kHz, 256 control taps, 128 secondary-path taps, four paths: 122.88 MMAC/s and 16 KiB scenario
  storage.
- 96 kHz, 512 control taps, 256 secondary-path taps, four paths: 491.52 MMAC/s and 32 KiB.
- 96 kHz, 512 control taps, 256 secondary-path taps, 16-path 4x4 stress case: 1.96608 GMAC/s and
  128 KiB.

All counts preserve their formula and assumptions. Buffering, instruction overhead, accelerator
mapping, numeric implementation, and measured execution headroom remain UNKNOWN. No scenario is
claimed as evidence-verified workload fit.

## Latency status

Total latency is `UNKNOWN`; unknown contributors are not zero. At 96 kHz, supported manufacturer
filter terms give 239.421 us ADC plus 114.583 us DAC for AD1938, or 354.004 us documented converter
delay. PCM3168A's comparable documented filter delay is 572.917 us. The ADAU1978 separate path is
not totalable because the DAC is UNKNOWN. Microphone, transport, buffering, DSP execution, and
amplifier/acoustic contributors remain UNKNOWN.

## Phase 4 readiness

`NOT_READY_FOR_PHASE_4`.

Blockers:

- No evidenced microphone technology/electrical-interface/signal-level front-end envelope.
- Whole-board power rails, sequencing, and current budgets are not closed.
- Exact converter/DSP clock dividers and jitter plan remain provisional.
- FxLMS execution headroom is unmeasured for all defined scenarios.

## Exact verification results

- Full pytest: `98 passed, 1 skipped, 1 warning` (99 collected); the skipped test is the live Ollama
  integration test because live Ollama was not requested.
- Ruff: `All checks passed!`
- Strict MyPy: `Success: no issues found in 70 source files`
- `git diff --check`: exit code 0; only Git line-ending conversion warnings were emitted.
- Synthetic retrieval evaluation: 2 cases, Recall@1/3/5 `1.0000`, MRR `1.0000`.
- Real retrieval evaluation: 31 cases, Recall@1 `0.6774`, Recall@3 `0.9355`, Recall@5 `1.0000`,
  MRR `0.8102`, zero failures.
- Phase 3 component reevaluation: completed; architecture `multichannel codec + DSP`; readiness
  `NOT_READY_FOR_PHASE_4`.

Phase 4, schematic generation, KiCad, ERC/DRC, routing, and manufacturing were not started.
