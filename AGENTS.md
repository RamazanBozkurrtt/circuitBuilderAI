# AGENTS.md

## Project

This repository contains a local AI-assisted PCB engineering system.

Primary long-term objective:

`MASTER_SPEC → architecture → component selection → evidence → schematic → verification → PCB layout → verification → iterative correction → manufacturing outputs`

The first real target design will be an Active Noise Cancellation controller PCB.

This system prioritizes engineering correctness and design quality over simplicity.

---

## Core Engineering Principles

1. LLM output is never the source of truth.
2. Engineering claims require evidence or deterministic validation.
3. Never invent missing engineering values.
4. Unknown values must remain explicitly UNKNOWN.
5. UNKNOWN must never silently become PASS.
6. Critical UNKNOWN values block progression.
7. All important engineering decisions must have provenance.
8. Prefer deterministic tools over LLM judgment whenever possible.
9. Use LLMs for reasoning, proposal generation, comparison and failure analysis.
10. Use EDA/simulation/rule engines for actual verification.
11. Preserve design history and rejected/superseded decisions.
12. Fail closed on malformed or unvalidated AI output.
13. Do not reduce engineering quality merely to simplify implementation.

---

## Architecture

Primary stack:

* Python 3.12+
* Ollama
* Pydantic v2
* LangGraph
* PyYAML
* pytest
* KiCad
* kicad-cli
* KiCad IPC API where appropriate
* ngspice
* Git

Future retrieval may use:

* structured datasheet parsing
* lexical search
* embeddings
* hybrid retrieval
* Qdrant

Do not introduce infrastructure unless it improves engineering quality, reliability, traceability or reproducibility.

Avoid unnecessary:

* microservices
* authentication
* frontend frameworks
* cloud infrastructure
* distributed systems

This is initially a local single-user engineering application.

---

## LLM Rules

Local inference is provided through Ollama.

Never allow domain code to depend directly on Ollama.

Use an abstraction such as:

`StructuredLLM`

LLM requests used by program logic must use typed structured output.

Preferred pattern:

`Pydantic model → model_json_schema() → Ollama structured output → local Pydantic validation`

Do not:

* regex-repair malformed JSON
* trust unvalidated natural language
* silently coerce invalid engineering values
* allow infinite retries
* give the LLM unrestricted shell access

Use deterministic generation settings where appropriate.

Model name and Ollama endpoint must be configuration values.

---

## Engineering State

Maintain one authoritative `DesignState`.

It should eventually contain:

* MASTER_SPEC
* architecture
* components
* evidence
* engineering decisions
* verification results
* warnings
* blockers
* workflow stage
* iteration
* immutable history

Important workflow stages:

* SPECIFICATION
* ARCHITECTURE
* COMPONENT_SELECTION
* DATASHEET_ANALYSIS
* SCHEMATIC
* SCHEMATIC_VERIFICATION
* PCB_LAYOUT
* PCB_VERIFICATION
* MANUFACTURING
* COMPLETE
* BLOCKED

State transitions must be explicit.

Persist state after major engineering stages.

Maintain a current snapshot plus immutable historical snapshots.

---

## MASTER_SPEC

`MASTER_SPEC` is the authoritative design requirement contract.

The user will NOT rely on the local model to translate arbitrary natural language into this contract.

A stronger external reasoning model may create or update MASTER_SPEC before the local engineering pipeline runs.

Never override MASTER_SPEC silently.

Missing information must use explicit typed unresolved states.

Engineering-sensitive defaults must not be invented.

---

## Evidence

Engineering facts should reference evidence.

Expected evidence sources include:

* USER_SPEC
* DATASHEET
* REFERENCE_DESIGN
* APPLICATION_NOTE
* SIMULATION
* EDA_VALIDATION
* RULE_ENGINE

Evidence should retain precise provenance when available:

* manufacturer
* document
* revision
* page
* section
* locator
* extracted content
* normalized fact
* confidence

A model's memory is not engineering evidence.

Datasheets and manufacturer documentation take precedence over LLM prior knowledge.

---

## Engineering Decisions

Important design choices must be represented explicitly.

Lifecycle:

`PROPOSED → EVIDENCE_VERIFIED → VALIDATED`

Possible terminal/non-current states:

* REJECTED
* SUPERSEDED

Do not mark a decision VALIDATED unless required validation/evidence exists.

Alternatives and risks should remain traceable.

---

## Validation

Validation must be deterministic whenever possible.

Expected validation sources eventually include:

* schema validation
* requirement rules
* datasheet constraints
* KiCad ERC
* KiCad DRC
* ngspice
* custom electrical rules
* audio/ANC-specific constraints
* signal integrity checks where required
* power integrity checks where required

Validation statuses:

* PASS
* FAIL
* WARNING
* UNKNOWN
* NOT_APPLICABLE

Severity should support:

* INFO
* LOW
* MEDIUM
* HIGH
* CRITICAL

Critical FAIL and critical UNKNOWN conditions must block progression.

Do not create fake validation.

Unimplemented validators must clearly report that they are unavailable rather than returning PASS.

---

## Iterative Design

The final architecture must support controlled loops such as:

`Design → Validate → Review → Diagnose → Correct → Validate`

All loops must be bounded.

Never create infinite autonomous loops.

The workflow must know why it returned to an earlier stage.

Corrections must preserve previous state/history.

---

## Agent Responsibilities

Logical roles may include:

* Architecture
* Component Selection
* Datasheet Analysis
* Schematic Design
* Electrical Review
* PCB Layout
* PCB Review
* ANC Performance Review
* Failure Analysis
* Manufacturing Review

These roles may share the same Ollama model.

Do not run unnecessary separate model instances.

Different roles should use different prompts, context and output schemas.

Agent separation exists for reasoning quality and verification independence, not for architectural decoration.

---

## ANC-Specific Quality Goals

The target PCB is intended for real-time Active Noise Cancellation.

Future validation must consider, where applicable:

* microphone channel count
* speaker/output channel count
* ADC performance
* DAC performance
* audio codec architecture
* DSP capability
* FxLMS/MIMO processing requirements
* sample rate
* bit depth
* total input-to-output latency
* converter latency
* DSP buffering latency
* channel synchronization
* SNR
* THD+N
* microphone input noise
* clock quality/jitter
* power supply noise
* grounding
* analog/digital partitioning
* amplifier noise
* thermal constraints
* EMI/EMC considerations

A PCB that merely powers on is not sufficient.

ANC performance requirements are first-class engineering requirements.

---

## KiCad / EDA Integration

Use the most appropriate supported interface for each operation.

Potential interfaces:

* `kicad-cli`
* KiCad IPC API
* `kicad-python`
* validated file generation/transformation when unavoidable

Do not assume one API supports every KiCad operation.

Abstract EDA operations behind typed interfaces.

The LLM must never directly execute arbitrary shell commands.

Use allowlisted tools with typed arguments.

---

## Tool Security

All tools must be registered explicitly.

Requirements:

* allowlisted tools only
* typed inputs
* validated outputs
* bounded execution
* clear failures
* no unrestricted shell tool
* no arbitrary code execution originating from model output

Unknown tool requests must be rejected.

---

## Testing

Engineering infrastructure requires tests.

Unit tests must not require a running Ollama instance.

Live Ollama tests must be marked integration tests.

Test important failure paths, especially:

* malformed structured AI output
* missing critical requirements
* UNKNOWN critical values
* invalid state transitions
* missing evidence
* invalid decisions
* failed validation
* excessive retry/iteration
* unknown tools
* state snapshot immutability
* prohibited arbitrary execution

Do not only test happy paths.

---

## Coding Guidelines

Prefer:

* small cohesive modules
* explicit types
* Pydantic contracts
* dependency inversion around external systems
* deterministic functions
* meaningful domain names
* clear exceptions
* testable code

Avoid:

* giant agent classes
* hidden mutable global state
* magic dictionaries where typed models fit
* premature abstraction
* duplicated schemas
* silent exception swallowing
* placeholder code pretending to work

Do not add dependencies without a concrete reason.

---

## Repository Layout

Preferred high-level layout:

```text
src/ai_pcb/
    models/
    llm/
    workflow/
    evidence/
    validation/
    tools/
    persistence/

tests/

projects/

knowledge/
    datasheets/
    reference_designs/
    app_notes/
```

The exact structure may evolve if there is a concrete engineering reason.

---

## Development Workflow

For each implementation task:

1. Inspect existing code first.
2. Preserve working architecture unless change is justified.
3. Implement the requested scope only.
4. Add/update tests.
5. Run relevant tests.
6. Run the full suite when practical.
7. Report exact results.
8. Report deferred or mocked functionality explicitly.
9. Do not claim unimplemented engineering capability works.
10. Do not proceed into a later project phase unless requested.

---

## Definition of Done

A task is complete only when:

* requested behavior exists
* types/contracts are valid
* relevant tests exist
* tests pass
* failure paths are handled
* architecture remains consistent
* no fake engineering validation was introduced
* deferred functionality is documented

Engineering correctness takes precedence over minimizing code size.
