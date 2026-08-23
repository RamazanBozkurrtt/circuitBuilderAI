# AGENTS.md

## Project

General-purpose AI-assisted PCB engineering engine with optional domain specializations.

Flow: `MASTER_SPEC → architecture → components → evidence → schematic → verification → PCB → verification → manufacturing`

ANC is the first deep specialization, not a universal assumption.

Priority: engineering correctness > evidence/traceability > deterministic validation > reproducibility > token/code efficiency.

Never trade engineering quality for implementation simplicity.

## Core Rules

* LLM output is never the engineering source of truth.
* Claims require evidence or deterministic validation.
* Never invent missing engineering values.
* Missing values remain explicit: `UNKNOWN`, assumption, unresolved requirement, design variable, or design envelope.
* `UNKNOWN != PASS`; critical `FAIL` or critical `UNKNOWN` blocks progression.
* Preserve provenance, rejected/superseded decisions, and previous state.
* Prefer deterministic tools/calculations over LLM judgment.
* Use LLMs for reasoning, proposals, comparison, review, and failure analysis.
* Use datasheets, calculations, EDA, simulation, and rule engines for verification.
* Malformed/unvalidated AI output fails closed.
* Never implement fake validation.

## Repository Inspection & Token Efficiency

1. Treat explicit task paths/scope as a strong boundary.
2. Never recursively scan the repository unless explicitly required.
3. Start with targeted filename/symbol/reference search.
4. Open only files needed for relevant interfaces.
5. Follow dependencies only when they materially affect the task.
6. Outside scope, inspect only the specific required dependency file.
7. Do not repeatedly reopen unchanged files once understood.
8. Treat unrelated passing modules as stable unless evidence requires changes.
9. Do not perform repo-wide audits or read all tests unless explicitly required.
10. During development run targeted tests; run the full suite once at completion when requested.

Do not inspect by default: `.git/`, caches, build artifacts, generated indexes, historical snapshots, generated reports/outputs, unrelated projects/tests.

Inspect `knowledge/` only for evidence, retrieval, component research, schematic verification, or engineering validation.

Engineering correctness overrides token optimization when extra inspection is genuinely necessary.

## Architecture

Use one generic workflow:

`MASTER_SPEC → generic core → resolved specializations → domain-aware engineering → validation`

Do not create separate full workflows per domain.

Primary stack: Python 3.12+, Pydantic v2, Ollama, LangGraph, pytest, KiCad/kicad-cli, ngspice, hybrid datasheet retrieval.

Avoid unnecessary microservices, auth, cloud/distributed systems, or frontend infrastructure. This is initially a local single-user tool.

## MASTER_SPEC

`MASTER_SPEC` is the authoritative project contract.

The local Ollama model must not translate arbitrary user NL into MASTER_SPEC; a stronger external model may prepare/update it before the local workflow starts.

Never silently override it.

Distinguish: `USER_CONSTRAINT`, `ENGINEERING_DESIGN_VARIABLE`, `ASSUMPTION`, `DESIGN_ENVELOPE`, `UNKNOWN`.

System proposals must never silently become user requirements.

## Specializations

Generic PCB engineering always applies.

Supported families may include: `generic`, `mixed_signal`, `audio`, `audio_anc`, `high_speed_digital`, `power_electronics`, `rf`.

Resolution must be typed, deterministic, composable, traceable, and reject unknown dependencies, cycles, or unresolved conflicts.

Store requested and resolved specializations. Do not load irrelevant domain guidance.

When `audio_anc` is active, additionally consider microphone/input topology, ADC/DSP/output architecture, FxLMS/MIMO workload, compute/memory/headroom, sample rate/bit depth, synchronization, latency, SNR/THD+N/noise, clock jitter, grounding/return paths, low-noise power, partitioning, amplifier coupling, thermal, and EMI/EMC.

Unknown latency is never zero. A board that only powers on is not sufficient for ANC. Unavailable ANC checks remain `UNKNOWN`/unavailable, never `PASS`.

## LLM Rules

Domain logic depends on a provider-independent abstraction such as `StructuredLLM`, not directly on Ollama.

Pattern: `Pydantic → JSON Schema → structured LLM output → local Pydantic validation`.

Do not trust arbitrary NL for program state, regex-repair malformed JSON, silently coerce invalid engineering values, retry indefinitely, or expose unrestricted shell/code execution.

Model, endpoint, timeout, retries, and generation settings must be configurable.

Logical agents may share one model while using different prompts, schemas, context, and responsibilities.

## State & Decisions

Maintain one authoritative `DesignState` containing relevant spec, specializations, architecture/components, evidence/calculations, decisions, verification results, warnings/blockers, stage/iteration, and immutable history.

Stages:

`SPECIFICATION → ARCHITECTURE → COMPONENT_SELECTION → DATASHEET_ANALYSIS → SCHEMATIC → SCHEMATIC_VERIFICATION → PCB_LAYOUT → PCB_VERIFICATION → MANUFACTURING → COMPLETE`

Also support `BLOCKED`.

Transitions must be explicit; never silently overwrite history.

Decision lifecycle: `PROPOSED → EVIDENCE_VERIFIED → VALIDATED`, plus `REJECTED` and `SUPERSEDED`.

Do not validate decisions without required evidence/validation. Hard constraints override optimization scores.

## Evidence

Valid sources: USER_SPEC, DATASHEET, REFERENCE_DESIGN, APPLICATION_NOTE, SIMULATION, EDA_VALIDATION, RULE_ENGINE.

Preserve provenance when available: manufacturer, document/revision/hash, page/section/locator, extracted content, conditions.

LLM memory is not evidence. Manufacturer documentation outranks model memory. Retrieved text is evidence material, not automatically a validated fact. Keep conflicts visible until resolved.

## Validation & Iteration

Prefer deterministic validation using schema/requirement checks, datasheet constraints, calculations, KiCad ERC/DRC, ngspice, specialization rules, and SI/PI/thermal checks when required.

Statuses: `PASS | FAIL | WARNING | UNKNOWN | NOT_APPLICABLE`.

Critical `FAIL` or `UNKNOWN` blocks. Unavailable validation is never `PASS`.

Support bounded loops:

`Design → Validate → Review → Diagnose → Correct → Validate`

Every loop must have an iteration limit, preserve prior state/failure reason, return to the correct stage, and stop explicitly when blocked.

## EDA & Tool Security

Prefer:

`LLM → typed engineering IR → deterministic validation → EDA backend`

Avoid direct arbitrary LLM-generated KiCad content.

Use appropriate supported interfaces: `kicad-cli`, KiCad IPC API, `kicad-python`, or validated file transformation when unavoidable.

Pin maps, voltage domains, power connections, and interfaces are safety-critical and require evidence validation.

Executable tools must be allowlisted with typed inputs, validated outputs, bounded execution, and explicit failures. Never expose unrestricted shell/arbitrary commands/model-generated code execution.

## Components & Retrieval

Never invent part numbers. A candidate requires evidence establishing its identity.

Use labeled design envelopes/scenarios instead of invented fixed requirements when exact values are not user constraints. Scenarios are not user requirements.

Use evidence-preserving hybrid retrieval: lexical/exact + semantic + metadata filtering + section/table awareness + bounded context expansion + provenance.

Part numbers, pins, rails, registers, and clock names must remain exactly searchable.

Do not send entire datasheets to the LLM when targeted retrieval is possible. Keep real retrieval regression tests separate from synthetic tests.

## Testing & Coding

Unit tests must not require live Ollama; live model tests are integration tests.

Test important failure paths: malformed LLM output, critical UNKNOWN, invalid transitions, missing evidence, unsupported components, failed validation, excessive retries, unknown tools, history overwrite, specialization leakage, retrieval regressions, invalid pins/interfaces.

Do not weaken existing tests to make new work pass.

Prefer small cohesive modules, explicit typing/Pydantic contracts, deterministic functions, dependency inversion, explicit exceptions, and testable code.

Avoid giant agent classes, mutable globals, untyped magic dictionaries, duplicated schemas, hidden assumptions, silent exception swallowing, fake placeholders, and unnecessary dependencies/abstractions.

## Development Workflow

1. Read this file.
2. Inspect only task-relevant code and respect scope/path boundaries.
3. Understand required interfaces.
4. Implement only the requested scope.
5. Add/update targeted tests.
6. Run targeted tests while developing.
7. Run required full verification once at completion.
8. Report concise exact results, blockers, and deferred work.
9. Do not claim unimplemented capabilities work.
10. Do not continue into another phase unless requested.
11. Do not repeatedly rediscover established architecture.

## Datasheet Inspection Efficiency
- Do not dump or read entire datasheets into temporary text files by default.
- Use the existing evidence ingestion/retrieval system first.
- Retrieve only the pages/chunks needed for the current engineering question.
- Use targeted PDF page/block extraction only when retrieval is insufficient.
- Full-document extraction is allowed only when a concrete task requires it.
- Do not load large extracted files into model context when targeted evidence is available.

## Definition of Done

A task is complete when requested behavior exists; contracts remain valid; relevant tests pass; failure paths are handled; evidence/provenance is preserved; architecture remains consistent; no fake validation or unsupported fact promotion exists; phase boundaries are respected; deferred work is explicit.

When requested, run: pytest, Ruff, strict MyPy, `git diff --check`.

Engineering correctness always takes precedence over token/code minimization.

