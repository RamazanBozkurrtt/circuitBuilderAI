# Phase 3.1 — Trusted manufacturer evidence and component closure

Phase 3.1 stops at architecture and major-component evaluation. It does not implement schematic
generation, KiCad automation, simulation, layout, or any Phase 4 capability.

## Acquisition result

The trusted corpus contains 13 current official manufacturer documents. Every authoritative copy
was acquired over HTTPS from an allowlisted `analog.com` or `ti.com` host, checked again after every
redirect, verified as a non-empty machine-readable PDF, identity-checked, hashed, and stored under a
content-addressed immutable name. The acquisition catalog preserves 19 total acquisition records,
including six earlier identity-unverified attempts in `knowledge/quarantine`; later curation did not
overwrite or promote those attempts silently.

| Manufacturer | Document | Type / revision | SHA-256 |
|---|---|---|---|
| Analog Devices | ADSP-21562/3/5/6/7/9 data sheet | DATASHEET, Rev. D | `0c908438ea8f71ccd559f44db26e7715fcd93dbf1d962c36e9a790e09efca85e` |
| Analog Devices | ADSP-2156x processor hardware reference | HARDWARE_REFERENCE | `96545b862402a7fd803d3aa69d42e7bc81f9b966309702f114de7ff7f4680867` |
| Analog Devices | EE-408 FIR/IIR accelerators | APPLICATION_NOTE, Rev. 2 | `95aa576936cdc2ade620bdbbd8299c9d9dc1dd1d33aa95de72d5b6478310df0d` |
| Analog Devices | EE-414 processor power estimation | APPLICATION_NOTE, Rev. 2 | `6d309560a7e412206e4df91ba0c9c51a4c9020ad7ab61b192841269c7d58ae92` |
| Analog Devices | EE-470 power sequencing | APPLICATION_NOTE, Rev. 1 | `99f1ef29705ec864f259cba3ad6f4562d4034f8241f3b2b8a30aaeefde40c061` |
| Analog Devices | EE-418 DMC board-design guidance | APPLICATION_NOTE, Rev. 2 | `5cf5847980dfb32e53723ed765f951ad7d26026b70e98bc0f8347d6b555c92df` |
| Analog Devices | ADSP-2156x silicon anomaly list | ERRATA | `84b9653c85367a246898e06bcf11d766a51d092811350ce3c5973db7b2d26a58` |
| Texas Instruments | PCM3168A | DATASHEET, Rev. A | `959ffa69e2f9656f766739aad0759be2e0c5509f26768d4b702925e3f9d68f93` |
| Analog Devices | AD1938 | DATASHEET, Rev. E | `45957be7b198d70bd6998324be0d0d84114c0d99907dc415711c4e28feaab5f3` |
| Analog Devices | ADAU1978 | DATASHEET, Rev. B | `5b80650206aba0345f6acb32d50cd5c3515575e3647846c55d3c497ce260f838` |
| Texas Instruments | TAS6424-Q1 | DATASHEET, Rev. B | `4cbfe2ed1be614928d9331e77c96462f67b9bd2937af82550bc90fcfb526404e` |
| Texas Instruments | SLOA242 inductor selection | APPLICATION_NOTE, Rev. A | `dee93b9cf35b75c0f3b2df98132ac655db5859e56fe9e209b22b5b4bbed4abc1` |
| Texas Instruments | SLAA701 LC-filter design | APPLICATION_NOTE, Rev. B | `c0b700ff064306630ae5d8995f7371880df06970bedd4cf43d8c825e8de5e040` |

No acquisition is pending. Dense indexing is deliberately narrower: the five candidate datasheets
are fully ingested and indexed with acquisition provenance. The 2,453-page processor hardware
reference and supporting notes are acquired but deferred from full dense indexing until the index
supports resumable per-document batches. A real-corpus run exposed an unsafe all-chunks-at-once
embedding call; it was replaced with bounded batches and covered by regression testing.

## Retrieval regression

Synthetic and real metrics are separate. The two-case synthetic fixture remains Recall@1/3/5 =
`1.0000` and MRR = `1.0000` in its isolated Phase 2 index. The real set has 31 fixed, manually
curated page locations across DSP, codec/ADC/DAC, and Class-D documents:

| Corpus | Queries | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---:|---:|---:|---:|---:|
| Synthetic isolated fixture | 2 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| Real manufacturer datasheets | 31 | 0.2581 | 0.4516 | 0.5161 | 0.3586 |

The real run records 15 misses: 12 hybrid-ranking issues, two cross-page-context issues, and one
table-location failure. Detailed page ranks show that deeper register/performance sections often
out-rank the curated first-page summaries, while the expected summary remains below Recall@5. The
expected pages were not moved to improve the result. No speculative ranking rewrite was made; the
only retrieval infrastructure change is the bounded embedding fix demonstrated necessary by the
real corpus.

## Architecture result

The evidence-aware rerun selects **Multichannel codec + DSP** as the provisional topology. The
**Separate ADC + DSP + DAC** topology remains a viable alternative, but its DAC is not evidenced in
the current corpus. The **DSP with integrated converters** topology is rejected because no trusted
candidate evidence establishes four synchronized input and four output converter channels in the
processor.

The codec topology itself is not evidence-verified as a final decision. PCM3168A and AD1938 both
meet the known channel-count requirement, but sample rate, microphone technology/interface,
converter choice, clock implementation, and final latency trade-offs remain unresolved.

## Component candidates

| Category | Candidate | Evidence status | Phase 3.1 status | Key reason |
|---|---|---|---|---|
| DSP | Analog Devices ADSP-21569 | EVIDENCE_VERIFIED | PROVISIONALLY_SELECTED / PROPOSED | Architecture-compatible; final FxLMS workload is unresolved |
| Codec | TI PCM3168A | EVIDENCE_VERIFIED | CANDIDATE | 6 ADC / 8 DAC channels; unresolved design variables prevent selection |
| Codec | Analog Devices AD1938 | EVIDENCE_VERIFIED | CANDIDATE | 4 ADC / 8 DAC channels; unresolved clock/latency trade-offs prevent selection |
| ADC | Analog Devices ADAU1978 | EVIDENCE_VERIFIED | CANDIDATE | Four-channel ADC supports a separate-converter alternative; no DAC is closed |
| Class-D | TI TAS6424-Q1 | EVIDENCE_VERIFIED | CANDIDATE / BLOCKED_BY_SPEAKER_LOAD | Four channels, but project load, power, and input supply are UNKNOWN |
| DAC | none | EVIDENCE_REQUIRED | BLOCKED | No trusted standalone DAC candidate in current corpus |
| Clocking | none | EVIDENCE_REQUIRED | BLOCKED | Clock topology and jitter requirements unresolved |
| Power management | none | EVIDENCE_REQUIRED | BLOCKED | Input supply and rail/current requirements unresolved |

No component candidate is rejected on an unsupported inference. Every evaluated candidate remains
`EVIDENCE_REQUIRED` for final viability because at least one hard project criterion is UNKNOWN. The
TAS6424-Q1 power figures are retained with their supply, load, and 10% THD+N conditions; they are not
treated as the project speaker requirement.

## Evidence-backed facts

- ADSP-21569: 800/1000 MHz speed grades, 640 kB L1 SRAM, 1024 kB L2 SRAM, full SPORT/S/PDIF/ASRC
  resources, FIR/IIR hardware accelerators, and precision clock generators.
- PCM3168A: six ADC and eight DAC channels; 24-bit conversion; ADC 8–96 kHz and DAC 8–192 kHz;
  documented serial formats, clocks, SNR/THD+N, and ADC/DAC group-delay formulas.
- AD1938: four ADC and eight DAC channels; 24-bit, 8–192 kHz; documented serial formats,
  performance, and ADC/DAC group-delay formulas.
- ADAU1978: four ADC channels; 24-bit, 8–192 kHz; documented serial formats, dynamic range, and
  decimation-filter group delay.
- TAS6424-Q1: four BTL channels; documented 2-ohm/4-ohm conditional power points; up-to-2.1 MHz
  switching; digital audio formats; noise, efficiency, protection, and thermal-warning conditions.

Each fact is a typed catalog entry tied to an acquisition ID, exact SHA-256, page, checked source
text, and promoted evidence record. A mismatched hash, missing page text, or non-TRUSTED acquisition
fails closed.

## DSP / FxLMS status

Status: **LIKELY_CAPABLE_PENDING_WORKLOAD**, not validated. Manufacturer evidence establishes an
audio-oriented SHARC+ architecture, memory, interfaces, clock resources, and FIR/IIR acceleration.
It does not establish the final ANC operation count.

Two explicitly labeled `DESIGN_EXPLORATION` scenarios are retained: 48 kHz/256 taps and 96 kHz/512
taps, each illustrating four reference, four error, and four output paths. Their formula is preserved
as:

`operations/sample = Npaths x (control-filter work + coefficient-update work + secondary-path-filter work)`

`operations/second = operations/sample x sample_rate`

Secondary-path length, MIMO coupling, buffering, numeric format, memory layout, implementation cost,
and required headroom remain UNKNOWN, so neither scenario is evidence-verified for workload fit.

## Latency status

Total latency remains **UNKNOWN** because no codec, sample rate, buffering policy, DSP schedule, or
amplifier/acoustic path is selected. Known candidate formulas are retained without converting them
to false precision:

- PCM3168A ADC: `27/fS` single-speed; DAC: `28/fS` single/dual and `19/fS` quad.
- AD1938 ADC: `22.9844/fS` (479 us typical at 48 kHz); DAC: `25/fS`, `11/fS`, or `8/fS` by mode.
- ADAU1978 ADC: `22.9844/fS` at 8–96 kHz and 35 us at 192 kHz.

Microphone-interface, serial transport, buffering, DSP-processing, and amplifier-path terms remain
explicit UNKNOWN. Unknown is never summed as zero.

## Blockers before schematic design

- Speaker impedance and per-channel power.
- Input supply voltage and board power budget.
- Microphone technology, electrical interface, and signal level.
- Final sample rate and bit depth.
- Final codec versus separate-converter choice and compatible clock tree.
- FxLMS topology, adaptive and secondary-path filter lengths, operation count, memory allocation,
  measured execution time, and required headroom.
- Numeric latency target and all unresolved latency contributors.
- Standalone DAC, clocking, and power-management evidence if the corresponding architecture remains
  in consideration.
- PCB dimensions, layer count, environmental requirements, and programming/control interfaces.

Schematic generation remains blocked. Phase 4 has not begun.

## Deferred capabilities

- Resumable/incremental dense indexing for very large manuals.
- OCR for the explicitly reported low-text pages.
- Deterministic workload benchmarking and ANC/FxLMS validation.
- Converter clock-tree validation and complete latency summation after requirements close.
- All schematic, ERC, SPICE, PCB, DRC, and manufacturing-output work.
