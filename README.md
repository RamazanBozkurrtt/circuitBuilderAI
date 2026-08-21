# CircuitAI Phase 1

CircuitAI is a local, fail-closed foundation for an AI-assisted PCB engineering
workflow. Phase 1 provides typed engineering state, provenance, validation,
bounded workflow routing, persistence, a structured Ollama boundary, and a typed
tool allowlist. It does **not** design or verify electronics.

## Requirements and setup

- Python 3.12+
- An Ollama installation is optional; unit tests mock the transport.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` to override configuration. `OLLAMA_MODEL` has no
default because selecting a model is an explicit operator decision.

## CLI

```bash
python -m ai_pcb.cli init example
python -m ai_pcb.cli validate-spec example
python -m ai_pcb.cli run example
python -m ai_pcb.cli show-state example
```

`init` creates all required MASTER_SPEC sections with empty requirement maps. It
does not insert ANC or electrical requirements. Empty sections and critical
unresolved requirements produce critical `UNKNOWN` validation results and block
the workflow. A Phase 1 `run` also blocks at `architecture`, which is deliberately
unavailable rather than reported as a fake pass.

Project data is stored as:

```text
projects/<project-name>/
    master_spec.yaml
    state/
        current.json
        iteration_001.json
    evidence/
    outputs/
```

Historical snapshots use exclusive creation and cannot be overwritten through
the repository API. `current.json` and YAML writes use same-directory temporary
files followed by atomic replacement.

## Quality checks

```bash
python -m pytest
python -m ruff check .
python -m mypy
```

Tests marked `integration` are the only tests permitted to require external
services. They are skipped unless explicitly configured.

## Phase 1 boundary

Deferred capabilities include architecture synthesis, component selection,
datasheet/PDF parsing, schematic generation, KiCad automation, ERC/DRC, PCB
layout, ngspice, manufacturing output generation, and ANC-specific design or
performance verification. Their workflow nodes exist for routing but report
critical `UNKNOWN`/unavailable until later phases provide deterministic
implementations.

